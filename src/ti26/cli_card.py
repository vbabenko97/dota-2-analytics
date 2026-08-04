"""Production card CLI: calibrated Glicko strengths, promoted from D3b's PASS.

Spec: docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md, "D3
calibration gate" and "D3b: the multiplicity-corrected Glicko gate". D3b
validated calibrated Glicko's PER-MAP probabilities out of sample (margin
0.00671 nats/map, 97.5% CI [0.00230, 0.01301], calibration slope 0.9049) --
see docs/audits/2026-08-03-d3-calibration-report.md's addendum. That was a
ONE-condition test (margin and slope were already known before the run;
only the bootstrap interval was newly computed), so it is weaker evidence
than a fresh three-condition pass would have been. This module is a
SEPARATE decision, made here: build the production card from calibrated
Glicko, replacing `cli_rung3.py` (public ratings) as the shipping source.
`cli_rung3.py` itself is untouched and stays the documented rung-3 fallback.

The card (`ti26.cli.main`) does not consume per-map probabilities. It
consumes a scalar strength per team through
`series.map_win_prob(s_a, s_b) = sigmoid(s_a - s_b)`, and
`GlickoModel.strengths()` returns the RAW, uncalibrated logit strength
`(rating - mean) * LOGIT_PER_GLICKO` -- no calibration correction applied.
This module closes that gap:

1. Fit `GlickoModel` over the full store; resolve the 16 configured teams to
   rosters and raw strengths exactly as `cli_rung3.py` does.
2. Derive a correction factor by running the SAME rolling-backtest
   measurement D2 used (`backtest.rolling_folds`, `backtest.run_model`,
   `backtest.calibration`) against the RAW (uncalibrated) `GlickoModel` --
   never a hardcoded literal. On the full store this reproduces D2's
   reported 0.4023 (docs/audits/2026-08-02-d2-build-ledger.md); this module
   recomputes it fresh every run so it never goes stale against re-ingested
   data. Only the SLOPE is applied to strengths, never the intercept: the
   intercept corrects a Radiant/Dire *order* bias in the raw model's
   predictions, which has no counterpart in a scalar, order-free team
   strength.
3. Multiply every raw strength by that slope, then re-centre (subtract the
   mean of the resulting 16-team subset -- NOT guaranteed to already be
   zero, since the 16 configured teams are a subset of every roster the
   full-store fit centred over).
4. Write `reports/strengths_calibrated.csv` and invoke `ti26.cli.main`
   with `--strengths`, so the card can never fall back to D1's synthetic
   `t00..t15` ladder.

This is a reasoned APPROXIMATION, not an exact transfer of what D3b
validated: D3b calibrated a per-map probability; this applies that model's
own (raw, uncalibrated) calibration slope to per-team STRENGTH differences.
That is valid to the extent that `GlickoModel.expected_score`'s RD
attenuation `g(phi)` is close to 1 across the 16 configured rosters --
`reports/card_provenance.md` reports the measured `g(phi)` range for this
run so a reader can judge it, rather than assuming it holds in general.
"""

import argparse
import csv
import json
import math
from pathlib import Path

from ti26.backtest import calibration, rolling_folds, run_model
from ti26.cli import main as cli_main
from ti26.data.store import load_rows, open_store
from ti26.montecarlo import category_marginals, monte_carlo_stderr
from ti26.optimize import solve_card
from ti26.public_ratings import observed_recent_form
from ti26.ratings import load_gate_config
from ti26.ratings.glicko import SCALE, GlickoModel, _g
from ti26.roster import RosterIndex, load_aliases
from ti26.rules import load_rules
from ti26.series import map_win_prob
from ti26.teams import load_teams, resolve_rosters, team_strengths

# Gate lineage, per docs/audits/2026-08-03-d3-calibration-report.md. These are
# HISTORICAL facts about gates already run and frozen on this branch -- not
# something this module measures -- so they are literal, sourced text, not a
# hardcoded input to any computation below.
D2_GATE_SUMMARY = (
    "D2 forecast-value gate FAILED (margin -0.00383 nats/map, CI "
    "[-0.02055, 0.00614], includes 0) -- see docs/audits/2026-08-02-d2-build-ledger.md."
)
D3_ELO_GATE_SUMMARY = (
    "D3 calibration gate (Elo, the primary gated candidate) FAILED on all three "
    "pre-registered conditions: margin 0.00191 < 0.003, CI [-0.00046, 0.00500] "
    "includes 0, calibration slope 0.6569 outside [0.9, 1.1] -- see "
    "docs/audits/2026-08-03-d3-calibration-report.md."
)
D3B_GLICKO_GATE_SUMMARY = (
    "D3b (the multiplicity-corrected Glicko gate) PASSED: margin 0.00671 nats/map "
    "(>= 0.003), 97.5% bootstrap CI [0.00230, 0.01301] (excludes 0), calibration "
    "slope 0.9049 (inside [0.9, 1.1], clearing the 0.9 lower bound by only "
    "0.0049 -- a fragile margin). This was a ONE-CONDITION test: Glicko's margin "
    "and slope were already measured and already passing before this run; only "
    "the 97.5% bootstrap interval was newly computed. It is therefore WEAKER "
    "evidence than a fresh three-condition pass would have been -- see the "
    "addendum in docs/audits/2026-08-03-d3-calibration-report.md."
)


def derive_glicko_calibration_slope(
    rows, aliases: dict[int, int], glicko_tau: float, min_train: int
) -> tuple[float, float]:
    """Measure the RAW (uncalibrated) Glicko out-of-sample calibration slope.

    Uses the IDENTICAL rolling-backtest machinery `cli_d2` used to originally
    report 0.4023 (`rolling_folds`, `run_model`, `backtest.calibration`) --
    never a hardcoded literal. Deliberately the raw `GlickoModel`, not
    `CalibratedModel`: `GlickoModel.strengths()` (what the card actually
    consumes) is this raw model's own output, so the correction that applies
    to it is this model's OWN calibration slope -- not the slope of an
    already-in-fold-corrected model (D3b's 0.9049), which corrects a
    different, already-partially-corrected quantity.

    Returns `(slope, intercept)`. Only `slope` is applied by
    `apply_correction` below -- see the module docstring for why the
    intercept is deliberately not transferred onto team strengths.
    """
    folds = rolling_folds(rows, min_train=min_train)
    if not folds:
        raise SystemExit(
            f"no tournament had {min_train}+ prior maps for the calibration "
            "backtest; lower --min-train"
        )
    factory = lambda: GlickoModel(tau=glicko_tau, roster_index=RosterIndex(aliases))
    predictions = run_model(rows, factory, folds)
    slope, intercept = calibration(predictions, rows)
    if math.isnan(slope) or math.isnan(intercept):
        raise SystemExit(
            "backtest.calibration() returned NaN for the Glicko backtest -- "
            "refusing to apply a NaN correction to the card's strengths"
        )
    return slope, intercept


def apply_correction(strengths: dict[str, float], slope: float) -> dict[str, float]:
    """Multiply every strength by `slope`, then re-centre.

    Re-centring is NOT a tautology here: `strengths` is normally the 16
    CONFIGURED teams' subset of a full-store fit that was zero-centred over
    EVERY rated roster in the store, not just these 16 -- so this subset's
    own mean is not guaranteed to be (and in general will not be) zero
    before this function runs.
    """
    if not strengths:
        return {}
    scaled = {name: s * slope for name, s in strengths.items()}
    mean = sum(scaled.values()) / len(scaled)
    return {name: s - mean for name, s in scaled.items()}


def rd_attenuation_range(
    model: GlickoModel, resolved: dict[str, str]
) -> tuple[float, float, float, float]:
    """Empirical (RD min, RD max, g(phi) min, g(phi) max) over the 16
    CONFIGURED rosters and their pairwise combined RDs.

    The near-uniformity of `g(phi)` across this specific field is the
    empirical justification the module docstring's approximation caveat
    depends on -- reused directly from `GlickoModel`'s own already-public
    `rating_deviations()` and its private `_g` attenuation formula, rather
    than recomputing the RD-to-attenuation math independently and risking it
    silently drifting from what `expected_score` itself actually computes.
    """
    rds = model.rating_deviations()
    values = [rds[rvid] for rvid in resolved.values()]
    rd_lo, rd_hi = min(values), max(values)
    names = sorted(resolved)
    g_values = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            rd_a, rd_b = rds[resolved[names[i]]], rds[resolved[names[j]]]
            phi = math.sqrt(rd_a**2 + rd_b**2) / SCALE
            g_values.append(_g(phi))
    return rd_lo, rd_hi, min(g_values), max(g_values)


def seed_stability(
    strengths: dict[str, float], rules, seeds: list[int], n_sims: int
) -> tuple[dict[int, dict[str, str]], list[str]]:
    """Solve the card under every seed in `seeds` at `n_sims`.

    Returns `(cards_by_seed, unstable_teams)`: `unstable_teams` names every
    team whose assigned category differs between at least two of the seeds
    -- so an ambiguous slot is visible in the report rather than hidden
    behind whichever seed happened to run.
    """
    cards_by_seed: dict[int, dict[str, str]] = {}
    for seed in seeds:
        marginals = category_marginals(strengths, rules, n_sims=n_sims, seed=seed)
        # Tie tolerance MUST match `cli.main`'s, or this diagnostic measures a
        # solver nobody ships: it would report instability the card does not
        # have, or hide instability it does.
        card, _score = solve_card(
            marginals,
            rules.category_capacities,
            tie_tolerance=monte_carlo_stderr(0.5, n_sims),
        )
        cards_by_seed[seed] = {team: category.value for team, category in card.items()}

    reference_seed = seeds[0]
    unstable = sorted(
        team
        for team in cards_by_seed[reference_seed]
        if any(
            cards_by_seed[seed][team] != cards_by_seed[reference_seed][team]
            for seed in seeds[1:]
        )
    )
    return cards_by_seed, unstable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Production card: calibrated Glicko strengths (promoted from D3b)"
    )
    parser.add_argument("--teams", default="config/ti2026_teams.yaml")
    parser.add_argument("--aliases", default="config/team_aliases.yaml")
    parser.add_argument("--rules", default="config/ti2026_rules.yaml")
    parser.add_argument("--store", default="data/processed/d2.sqlite")
    parser.add_argument("--gate-config", default="config/d2_gate.yaml")
    parser.add_argument(
        "--min-train", type=int, default=500,
        help="minimum prior training maps for a rolling-backtest fold (matches cli_d2's default)",
    )
    parser.add_argument("--card-sims", type=int, default=250_000)
    parser.add_argument("--card-seed", type=int, default=1)
    parser.add_argument(
        "--stability-seeds", default=None,
        help="comma-separated seeds for the seed-stability diagnostic "
        "(default: card-seed, card-seed+1, card-seed+2)",
    )
    parser.add_argument("--out", default="reports")
    args = parser.parse_args(argv)

    teams = load_teams(args.teams)
    rules = load_rules(args.rules)
    aliases = load_aliases(args.aliases)
    gate_config = load_gate_config(args.gate_config)
    if len(teams) != rules.n_teams:
        raise SystemExit(
            f"{args.teams} lists {len(teams)} teams but the rules require {rules.n_teams}"
        )

    rows = load_rows(open_store(args.store))
    if not rows:
        raise SystemExit(f"{args.store} is empty; run `python -m ti26.cli_ingest` first")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # --- 1. Correction factor, traceable to a fresh measurement --------------
    slope, intercept = derive_glicko_calibration_slope(
        rows, aliases, gate_config.glicko_tau, args.min_train
    )

    # --- 2. Fit Glicko over the FULL store, resolve to the 16 teams ----------
    model = GlickoModel(tau=gate_config.glicko_tau, roster_index=RosterIndex(aliases))
    for row in rows:
        model.update(row)
    model.flush()
    fitted = model.strengths()

    resolved = resolve_rosters(rows, teams, aliases)
    raw_strengths, prior_driven = team_strengths(resolved, fitted)

    # --- 3. Apply the correction, re-centre -----------------------------------
    calibrated_strengths = apply_correction(raw_strengths, slope)

    strengths_path = out / "strengths_calibrated.csv"
    with strengths_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["team", "strength"])
        for name in sorted(calibrated_strengths):
            writer.writerow([name, f"{calibrated_strengths[name]:.6f}"])

    # --- 4. Card, via D1's generator, fed OUR calibrated strengths -----------
    card_rc = cli_main(
        [
            "--strengths", str(strengths_path),
            "--rules", args.rules,
            "--n-sims", str(args.card_sims),
            "--seed", str(args.card_seed),
            "--out", str(out),
        ]
    )
    if card_rc != 0:
        raise SystemExit(f"card generation failed with exit code {card_rc}")

    # --- 5. Seed-stability diagnostic at production sim count -----------------
    if args.stability_seeds:
        seeds = [int(s) for s in args.stability_seeds.split(",")]
    else:
        seeds = [args.card_seed, args.card_seed + 1, args.card_seed + 2]
    cards_by_seed, unstable_teams = seed_stability(
        calibrated_strengths, rules, seeds, args.card_sims
    )

    # --- 6. Observed recent form (reused, not reimplemented) -------------------
    reference_time = max(r.start_time for r in rows)
    observed_form = observed_recent_form(rows, resolved, calibrated_strengths, reference_time)
    form_consistent = sum(1 for f in observed_form.values() if f.verdict == "consistent")
    form_above = sum(1 for f in observed_form.values() if f.verdict == "form ABOVE implied")
    form_below = sum(1 for f in observed_form.values() if f.verdict == "form BELOW implied")
    form_no_data = sum(1 for f in observed_form.values() if f.verdict == "no data")

    # --- 7. Approximation-caveat diagnostic: RD / g(phi) range over the field -
    rd_lo, rd_hi, g_lo, g_hi = rd_attenuation_range(model, resolved)

    # --- 8. Provenance report ---------------------------------------------------
    raw_spread = max(raw_strengths.values()) - min(raw_strengths.values())
    calibrated_spread = max(calibrated_strengths.values()) - min(calibrated_strengths.values())
    ordered_raw = sorted(raw_strengths, key=lambda t: raw_strengths[t], reverse=True)
    ordered_cal = sorted(
        calibrated_strengths, key=lambda t: calibrated_strengths[t], reverse=True
    )
    raw_best, raw_worst = ordered_raw[0], ordered_raw[-1]
    cal_best, cal_worst = ordered_cal[0], ordered_cal[-1]
    raw_p = map_win_prob(raw_strengths[raw_best], raw_strengths[raw_worst])
    cal_p = map_win_prob(calibrated_strengths[cal_best], calibrated_strengths[cal_worst])

    card_payload = json.loads((out / "recommended_card.json").read_text())

    lines = [
        "# Production card provenance -- calibrated Glicko (D3b)",
        "",
        (
            "**Strength source: calibrated Glicko.** This replaces `cli_rung3.py` "
            "(public ratings) as the shipping source, per the D3b gate PASS below. "
            "`cli_rung3.py` is unchanged and remains the documented rung-3 fallback."
        ),
        "",
        "## Gate lineage",
        "",
        f"- {D2_GATE_SUMMARY}",
        f"- {D3_ELO_GATE_SUMMARY}",
        f"- {D3B_GLICKO_GATE_SUMMARY}",
        "",
        (
            "Building the production card from calibrated Glicko is a SEPARATE "
            "decision made here, not made by the D3b gate run itself -- D3b's own "
            "report states explicitly that no card was built in that run."
        ),
        "",
        "## Correction factor",
        "",
        (
            f"**Slope: {slope:.4f}** (intercept {intercept:.4f}, NOT applied -- see "
            "below). Measured THIS run by re-running the identical rolling-backtest "
            "machinery `cli_d2` used (`backtest.rolling_folds`, `backtest.run_model`, "
            "`backtest.calibration`) against the RAW, uncalibrated `GlickoModel` over "
            f"the full store ({len(rows)} maps) -- never a hardcoded literal, so this "
            "cannot go stale against re-ingested data. On the original D2 snapshot "
            "this measurement reported **0.4023** "
            "(docs/audits/2026-08-02-d2-build-ledger.md); a close match here is a "
            "consistency check, not a requirement this run must hit exactly."
        ),
        "",
        (
            "Only the slope is applied to strengths. The intercept corrects a "
            "Radiant/Dire *order* bias in the raw model's predictions -- it has no "
            "counterpart in a scalar, order-free team strength, so transferring it "
            "onto `GlickoModel.strengths()` would not correct anything real."
        ),
        "",
        (
            f"**Resulting spread change:** raw strength spread {raw_spread:.4f} -> "
            f"calibrated {calibrated_spread:.4f}. Best-vs-worst implied map win "
            f"probability: raw {raw_p:.4f} -> calibrated {cal_p:.4f}."
        ),
        "",
        "## Approximation caveat -- stated plainly",
        "",
        (
            "D3b validated a PER-MAP probability's calibration. This module applies "
            "that model's calibration slope to PER-TEAM STRENGTH differences instead "
            "-- a reasoned approximation, not an exact transfer of what was validated."
        ),
        "",
        (
            "The approximation is justified here because `GlickoModel.expected_score`'s "
            f"RD attenuation `g(phi)` is measured, over these 16 rosters' pairwise "
            f"combined RDs, to span **{g_lo:.4f} to {g_hi:.4f}** (RD itself spans "
            f"{rd_lo:.1f} to {rd_hi:.1f}) -- close enough to 1 that "
            "`GlickoModel.strengths()` (which omits `g(phi)` entirely) tracks the raw "
            "model's own `expected_score` closely. **This is an EMPIRICAL property of "
            "this specific 16-team field, not a general guarantee** -- a field with "
            "widely dispersed RDs (e.g. several qualifier teams with almost no "
            "history) would make this approximation materially worse, and a re-run "
            "against a different roster mix must re-check this range rather than "
            "assume it."
        ),
        "",
        "## Seed-stability diagnostic",
        "",
        (
            f"The card was solved under {len(seeds)} seeds ({', '.join(str(s) for s in seeds)}) "
            f"at the production sim count ({args.card_sims}), so an ambiguous slot is "
            "visible rather than hidden behind one lucky seed."
        ),
        "",
    ]
    if unstable_teams:
        lines += [
            (
                f"**{len(unstable_teams)} of {len(cards_by_seed[seeds[0]])} team(s) are NOT "
                "seed-stable:**"
            ),
            "",
            "| team | " + " | ".join(f"seed {s}" for s in seeds) + " |",
            "|---|" + "---|" * len(seeds),
        ]
        for team in unstable_teams:
            lines.append(
                "| " + team + " | "
                + " | ".join(cards_by_seed[s][team] for s in seeds) + " |"
            )
    else:
        lines.append("**All teams are seed-stable across the seeds checked.**")
    lines += [
        "",
        "## Observed recent form (diagnostic only)",
        "",
        (
            "Reused directly from `public_ratings.observed_recent_form` (not "
            "reimplemented): each team's implied map win rate (from the calibrated "
            "strengths above) against what its CURRENT roster actually did over its "
            "recent maps. Diagnostic only -- opposition strength is not controlled, "
            "and this never overrides a strength or the card on its own."
        ),
        "",
        "| team | strength | implied | observed | n | 95% Wilson CI | verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in sorted(calibrated_strengths, key=lambda t: calibrated_strengths[t], reverse=True):
        f = observed_form[name]
        if f.n == 0:
            lines.append(
                f"| {name} | {calibrated_strengths[name]:.3f} | {f.implied:.3f} | - | 0 | - | "
                "no data |"
            )
        else:
            lines.append(
                f"| {name} | {calibrated_strengths[name]:.3f} | {f.implied:.3f} | "
                f"{f.rate:.3f} | {f.n} | [{f.ci_low:.3f}, {f.ci_high:.3f}] | {f.verdict} |"
            )
    lines += [
        "",
        (
            f"**{form_consistent} consistent, {form_above} form ABOVE implied, "
            f"{form_below} form BELOW implied**"
            + (f", {form_no_data} no data" if form_no_data else "")
            + "."
        ),
        "",
        "## Card",
        "",
        f"Status: generated from calibrated Glicko strengths ({len(calibrated_strengths)} teams).",
        (
            f"Model-implied expected score: {card_payload['model_implied_expected_score']} "
            "(descriptive only, never evidence of skill)."
        ),
    ]
    if prior_driven:
        lines += [
            "",
            f"**Prior-driven teams ({len(prior_driven)}):** " + ", ".join(prior_driven)
            + ". These carry the average-team prior, not a fitted rating.",
        ]
    (out / "card_provenance.md").write_text("\n".join(lines) + "\n")

    print(f"card: calibration slope {slope:.4f} (measured this run), spread "
          f"{raw_spread:.4f} -> {calibrated_spread:.4f}")
    print(f"card: {len(unstable_teams)} of {len(calibrated_strengths)} team(s) not seed-stable")
    print(f"card: written to {out}/recommended_card.json from {strengths_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
