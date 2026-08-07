"""D4: score the production card pipeline against TI 2025's real Swiss outcome.

A DIAGNOSTIC, not a gate. Spec section II ("D4") registered that before this file
existed and before any score was computed: one event is one sample, so a high
score here would not establish forecast value and a low one would not refute it.
Nothing in this module promotes, demotes or alters the shipping card.

What it does, under a `start_time < training_cutoff` filter with ONE documented
exception. The filter governs everything derived from match rows here: the
calibration refit, the Glicko fit and roster resolution all receive pre-cutoff
rows only. It does NOT govern `config/ti2026_rules.yaml`, whose `duration_model`
block was fitted over 41,082 maps -- effectively the whole store, including at
least 24,124 maps after the cutoff. The simulator draws map durations from those
parameters and durations feed the sixth tiebreak criterion, so post-cutoff
information reaches the simulation through that one channel. The committed
sensitivity sweep bounds the effect at about 0.0027 on a category marginal
against a Monte Carlo noise floor of about 0.0094, and reports `resolvable:
false` on every row -- but it varies only `log_sigma` and never `log_mean`, so
that bound is partial. This paragraph exists because the docstring previously
claimed a strict filter without the exception, which is not a claim the code
supports:

1. Re-derives TI 2025's observed Swiss outcome from the store and asserts it
   matches the frozen `config/ti2025_backtest.yaml`.
2. Re-measures the Glicko calibration slope from pre-cutoff maps ONLY, and
   separately measures the production slope fresh over the FULL store (never
   a hardcoded literal): re-using a stale literal for either would either leak
   the event's own maps into the correction applied to it, or silently drift
   from what `cli_card.py` actually ships once the store is re-ingested.
3. Fits Glicko on pre-cutoff maps, resolves the 16 teams' rosters as of the
   cutoff, applies the slope, and builds a card through the SAME functions
   `cli_card` uses -- imported, not reimplemented, so this measures the shipping
   pipeline rather than a lookalike.
4. Reports the score, the random baseline, the score's percentile in the model's
   own predictive distribution, and the per-slot hit/miss table -- the four
   things the registration named in advance.
5. Runs four additional, committed and seeded producers that were previously
   computed in throwaway inline commands and never checked in: a simulation-
   count sweep, a random capacity-respecting control, a naive strength-ladder
   comparator, and rank-correlation/displacement diagnostics between the
   predicted and observed category order. None of these feed back into the
   card built in steps 1-4; they are read-only diagnostics about it.

One payload dict is built from these measurements and is the ONLY source for
the JSON, Markdown and CSV outputs -- no report literal restates a number the
payload does not itself carry.
"""

import argparse
import csv
import json
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

from scipy.stats import spearmanr

from ti26.cli_card import apply_correction, derive_glicko_calibration_slope
from ti26.data.store import load_rows, open_store
from ti26.montecarlo import card_score_distribution, category_marginals, monte_carlo_stderr
from ti26.observed import SwissOutcome, derive_outcome, load_backtest_truth, score_card
from ti26.optimize import naive_strength_ladder, solve_card
from ti26.ratings import load_gate_config
from ti26.ratings.glicko import GlickoModel
from ti26.roster import RosterIndex, load_aliases
from ti26.rules import Rules, load_rules
from ti26.teams import load_teams, resolve_rosters, team_strengths
from ti26.types import Category


def _parse_positive_ints(raw: str) -> list[int]:
    """Parse a comma-separated list of ints; refuse an empty list or a <=0 value.

    Both a CLI typo (a trailing comma, an empty string) and a non-positive sim
    count or seed would otherwise fail deep inside `random.Random` or the
    simulation loop with an opaque error far from the actual mistake.
    """
    parts = [p.strip() for p in raw.split(",")]
    if any(not p for p in parts):
        raise ValueError(f"expected a non-empty comma-separated list of ints, got {raw!r}")
    values = [int(p) for p in parts]
    if any(v <= 0 for v in values):
        raise ValueError(f"all values must be positive, got {values}")
    return values


def percentile_of(scores: dict[int, int], observed: int) -> tuple[float, float]:
    """Return (share strictly below, share at or below) `observed`, as percents.

    Both bounds are reported because the score distribution is discrete and
    lumpy: with 17 possible integer scores a single value can hold several
    percent of the mass, and quoting one side alone would overstate precision.
    """
    total = sum(scores.values())
    below = sum(n for s, n in scores.items() if s < observed)
    at = scores.get(observed, 0)
    return 100.0 * below / total, 100.0 * (below + at) / total


def random_card_control(
    outcome: Mapping[int, SwissOutcome],
    capacities: Mapping[Category, int],
    *,
    samples: int,
    seed: int,
) -> dict:
    """Score `samples` random capacity-respecting card assignments against `outcome`.

    Builds ONE multiset -- each category repeated `capacities[category]` times
    -- and shuffles it. It must NOT sample category labels independently: that
    would let a single draw put, say, three teams at "4-0" (capacity 1), which
    is not a legal card and not the control the audit claimed was measured.
    """
    if samples <= 0:
        raise ValueError(f"samples must be positive, got {samples}")
    team_order = sorted(outcome)
    observed = [outcome[t].category for t in team_order]
    pool = [c for c in Category for _ in range(capacities[c])]
    if len(pool) != len(observed):
        raise ValueError(f"{len(pool)} capacity slots but {len(observed)} observed teams")

    rng = random.Random(seed)
    score_counts: Counter[int] = Counter()
    for _ in range(samples):
        draw = list(pool)
        rng.shuffle(draw)
        score = sum(1 for a, b in zip(draw, observed, strict=True) if a == b)
        score_counts[score] += 1
    total = sum(score * count for score, count in score_counts.items())
    return {
        "samples": samples,
        "seed": seed,
        "mean_score": total / samples,
        "score_counts": {str(score): count for score, count in sorted(score_counts.items())},
    }


def rank_diagnostics(
    card: Mapping[str, Category],
    observed: Mapping[str, Category],
    category_order: Sequence[Category],
) -> dict:
    """Spearman rank correlation plus an ordinal-displacement partition.

    `category_order` fixes the ordinal position of each category (index 0 is
    the strongest). Both `card` and `observed` must name exactly the same
    teams -- a card silently missing a team would drop out of the comparison
    rather than surface as a mismatch.

    Ties are unavoidable here (several teams always share `elim_win` /
    `elim_loss`), so the correlation is computed with scipy's average-rank
    Spearman rather than a naive rank that would need a tie-break of its own.
    """
    if set(card) != set(observed):
        missing = sorted(set(observed) - set(card))
        extra = sorted(set(card) - set(observed))
        raise ValueError(f"card and observed must name the same teams; missing {missing}, extra {extra}")

    position = {c: i for i, c in enumerate(category_order)}
    teams = sorted(card)
    predicted_ord = [position[card[t]] for t in teams]
    observed_ord = [position[observed[t]] for t in teams]

    rho = float(spearmanr(predicted_ord, observed_ord).statistic)

    exact: list[str] = []
    off_by_one: list[str] = []
    off_by_two_or_more: list[str] = []
    displacement: dict[str, int] = {}
    for team, p, o in zip(teams, predicted_ord, observed_ord, strict=True):
        d = abs(p - o)
        displacement[team] = d
        if d == 0:
            exact.append(team)
        elif d == 1:
            off_by_one.append(team)
        else:
            off_by_two_or_more.append(team)
    assert len(exact) + len(off_by_one) + len(off_by_two_or_more) == len(card)

    return {
        "spearman_rho": rho,
        "exact": exact,
        "off_by_one": off_by_one,
        "off_by_two_or_more": off_by_two_or_more,
        "displacement": displacement,
        "mean_absolute_displacement": sum(displacement.values()) / len(card),
    }


def run_sweep(
    n_sims_list: Sequence[int],
    seeds: Sequence[int],
    strengths: dict[str, float],
    rules: Rules,
    outcome: Mapping[int, SwissOutcome],
    names: dict[int, str],
    team_ids: Mapping[str, object] | None = None,
) -> list[dict]:
    """Full solve-and-score for every (n_sims, seed) pair in the sweep.

    Each entry records BOTH the optimizer's own marginal objective
    (descriptive, from the model's own probabilities) and the observed score
    against the real TI 2025 outcome -- two different quantities that an
    earlier, uncommitted version of this sweep conflated under one "model
    expected" label.
    """
    entries = []
    for n_sims in n_sims_list:
        for seed in seeds:
            marginals = category_marginals(
                strengths, rules, n_sims=n_sims, seed=seed, team_ids=team_ids
            )
            card, optimizer_marginal_objective = solve_card(
                marginals,
                rules.category_capacities,
                tie_tolerance=monte_carlo_stderr(0.5, n_sims),
                team_ids=team_ids,
            )
            observed_score, _table = score_card(card, outcome, names)
            entries.append(
                {
                    "n_sims": n_sims,
                    "seed": seed,
                    "optimizer_marginal_objective": optimizer_marginal_objective,
                    "observed_score": observed_score,
                    "card": {name: c.value for name, c in sorted(card.items())},
                }
            )
    return entries


def render_markdown(payload: dict) -> str:
    """Render the D4 report from `payload` ONLY -- every number below is a
    lookup into it, never a value computed or restated independently."""
    lines = [
        "# D4: TI 2025 card backtest",
        "",
        "**D4 is a diagnostic. It cannot promote, demote or alter the shipping card.**",
        "",
        f"Status: {payload['status']}",
        "",
        "## Headline",
        "",
        f"- League: {payload['league_id']}",
        f"- Training maps (strict cutoff, before the event): {payload['training_maps']}",
        (
            f"- Observed score: {payload['observed_score']}/16 "
            f"(random baseline {payload['random_baseline']:.4f})"
        ),
        (
            "- Optimizer marginal objective (descriptive only, never evidence): "
            f"{payload['optimizer_marginal_objective']:.4f}"
        ),
        (
            "- Evaluation-simulation mean score: "
            f"{payload['evaluation_simulation_mean_score']:.4f}"
        ),
        (
            f"- Percentile in the model's own distribution: "
            f"{payload['percentile_strictly_below']:.1f}% strictly below, "
            f"{payload['percentile_at_or_below']:.1f}% at or below"
        ),
        (
            "- Calibration slope, refit pre-cutoff: "
            f"{payload['calibration_slope_refit_precutoff']:.4f}"
        ),
        (
            "- Calibration slope, production (measured fresh, full store): "
            f"{payload['calibration_slope_production_full_store']:.4f}"
        ),
        "",
        "## Sim-count sweep",
        "",
        "| n_sims | seed | optimizer marginal objective | observed score |",
        "|---|---|---|---|",
    ]
    for entry in payload["sweep"]["entries"]:
        lines.append(
            f"| {entry['n_sims']} | {entry['seed']} | "
            f"{entry['optimizer_marginal_objective']:.4f} | {entry['observed_score']} |"
        )
    lines += [
        "",
        "## Random-card control",
        "",
        (
            f"- Samples: {payload['random_control']['samples']} "
            f"(seed {payload['random_control']['seed']})"
        ),
        f"- Mean score: {payload['random_control']['mean_score']:.4f}",
        "",
        "## Naive strength ladder (no simulation, no optimiser)",
        "",
        f"- Score: {payload['naive_ladder']['score']}/16",
        "",
        "## Rank diagnostics",
        "",
        (
            "- Spearman rho (predicted vs observed category order): "
            f"{payload['rank_diagnostics']['spearman_rho']:.4f}"
        ),
        f"- Exact: {len(payload['rank_diagnostics']['exact'])}",
        f"- Off by one: {len(payload['rank_diagnostics']['off_by_one'])}",
        f"- Off by two or more: {len(payload['rank_diagnostics']['off_by_two_or_more'])}",
        (
            "- Mean absolute displacement: "
            f"{payload['rank_diagnostics']['mean_absolute_displacement']:.4f}"
        ),
        "",
        "## Per-slot table",
        "",
        "| team | predicted | observed | hit |",
        "|---|---|---|---|",
    ]
    for row in payload["per_slot"]:
        lines.append(f"| {row['team']} | {row['predicted']} | {row['observed']} | {int(row['hit'])} |")
    if payload["prior_driven_teams"]:
        lines += [
            "",
            "**WARNING prior-driven (unrated) rosters:** "
            + ", ".join(payload["prior_driven_teams"]),
        ]
    return "\n".join(lines) + "\n"


def render_csv_rows(payload: dict) -> list[list[str]]:
    """Per-slot CSV rows, sourced from `payload["per_slot"]` only."""
    out = [["team", "predicted", "observed", "hit"]]
    for row in payload["per_slot"]:
        out.append([row["team"], row["predicted"], row["observed"], str(int(row["hit"]))])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", default="config/ti2025_backtest.yaml")
    parser.add_argument("--aliases", default="config/team_aliases.yaml")
    parser.add_argument("--rules", default="config/ti2026_rules.yaml")
    parser.add_argument("--store", default="data/processed/d2.sqlite")
    parser.add_argument("--gate-config", default="config/d2_gate.yaml")
    parser.add_argument("--min-train", type=int, default=500)
    parser.add_argument(
        "--train-from",
        type=int,
        default=None,
        help=(
            "lower bound on training rows, as epoch seconds. Unset reproduces "
            "D4's original behaviour, where the store's own start is the "
            "effective bound. Set it to match production's window length: on a "
            "deeper snapshot the cutoff alone would give the backtest MORE "
            "history than production has, which flatters the score"
        ),
    )
    parser.add_argument("--card-sims", type=int, default=250_000)
    parser.add_argument("--card-seed", type=int, default=1)
    parser.add_argument(
        "--eval-seed",
        type=int,
        default=90_001,
        help=(
            "Seed for the outcomes the card is SCORED against. Deliberately "
            "independent of --card-seed: the card was solved to maximise "
            "expected score over the card-seed draws, so re-using them would "
            "credit it for noise it was fitted to."
        ),
    )
    parser.add_argument(
        "--sweep-sims",
        default="2000,20000,250000",
        help="comma-separated n_sims values for the sim-count sweep diagnostic",
    )
    parser.add_argument(
        "--sweep-seeds",
        default="1,2,3",
        help="comma-separated seeds for the sim-count sweep diagnostic",
    )
    parser.add_argument(
        "--random-samples",
        type=int,
        default=200_000,
        help="number of random capacity-respecting card draws for the random control",
    )
    parser.add_argument("--random-seed", type=int, default=1)
    parser.add_argument("--out", default="reports")
    args = parser.parse_args(argv)

    sweep_sims = _parse_positive_ints(args.sweep_sims)
    sweep_seeds = _parse_positive_ints(args.sweep_seeds)

    truth = load_backtest_truth(args.truth)
    rules = load_rules(args.rules)
    aliases = load_aliases(args.aliases)
    gate_config = load_gate_config(args.gate_config)

    all_rows = load_rows(open_store(args.store))
    if not all_rows:
        raise SystemExit(f"{args.store} is empty; run `python -m ti26.cli_ingest` first")

    # --- 1. The observed outcome, re-derived and cross-checked ---------------
    # Deliberately sees ALL rows, including the event's own: it reconstructs
    # the observed result, which is not a training input.
    outcome = derive_outcome(all_rows, truth)

    # --- 2. The strict cutoff. Everything below sees only these rows ---------
    # `--train-from` is the LOWER bound, and it exists because the cutoff alone
    # is not a window. On the pinned 18-month snapshot the store's own start is
    # the effective lower bound and the backtest sees 6.8 months where
    # production gets 17.7. On a deeper snapshot the same code would hand the
    # backtest a LONGER window than production, which flatters the result by
    # exactly the mechanism it was meant to correct. Set it and the span is
    # matched deliberately; leave it unset and the behaviour is D4's original.
    train = [r for r in all_rows if r.start_time < truth.training_cutoff]
    if args.train_from is not None:
        train = [r for r in train if r.start_time >= args.train_from]
    if not train:
        raise SystemExit("no maps in the training window")
    if max(r.start_time for r in train) >= truth.training_cutoff:
        raise SystemExit("training rows include a map at or after the cutoff")
    if args.train_from is not None and min(r.start_time for r in train) < args.train_from:
        raise SystemExit("training rows precede --train-from")
    train_span_days = (max(r.start_time for r in train) - min(r.start_time for r in train)) / 86400

    # --- 3. The production comparator, measured fresh over the FULL store ----
    # This is cli_card.py's own production slope, computed exactly the way it
    # computes it -- never a hardcoded literal that could drift once the store
    # is re-ingested.
    slope_full_store, _intercept_full_store = derive_glicko_calibration_slope(
        all_rows, aliases, gate_config.glicko_tau, args.min_train
    )

    # --- 4. Refit the correction on pre-cutoff data only ----------------------
    slope, _intercept = derive_glicko_calibration_slope(
        train, aliases, gate_config.glicko_tau, args.min_train
    )

    # --- 5. The card, through cli_card's own path ----------------------------
    model = GlickoModel(tau=gate_config.glicko_tau, roster_index=RosterIndex(aliases))
    for row in train:
        model.update(row)
    model.flush()
    fitted = model.strengths()

    teams = load_teams(args.truth)
    resolved = resolve_rosters(train, teams, aliases)
    raw_strengths, prior_driven = team_strengths(resolved, fitted)
    strengths = apply_correction(raw_strengths, slope)

    # Same identity keying as the shipping card: this measures that pipeline,
    # so it must not order teams by a key the pipeline does not use.
    team_ids = {entry.name: str(entry.team_id) for entry in teams}
    marginals = category_marginals(
        strengths, rules, n_sims=args.card_sims, seed=args.card_seed, team_ids=team_ids
    )
    card, optimizer_marginal_objective = solve_card(
        marginals,
        rules.category_capacities,
        tie_tolerance=monte_carlo_stderr(0.5, args.card_sims),
        team_ids=team_ids,
    )

    # --- 6. Score plus the three companions the registration demanded -------
    score, table = score_card(card, outcome, truth.names)
    baseline = sum(c * c for c in rules.category_capacities.values()) / len(teams)
    dist = card_score_distribution(
        card, strengths, rules, n_sims=args.card_sims, seed=args.eval_seed, team_ids=team_ids
    )
    below, at_or_below = percentile_of(dist, score)
    sim_mean = sum(s * n for s, n in dist.items()) / sum(dist.values())

    # --- 7. The four committed producers added after seeing the first score --
    sweep_entries = run_sweep(
        sweep_sims, sweep_seeds, strengths, rules, outcome, truth.names, team_ids=team_ids
    )
    random_control = random_card_control(
        outcome, rules.category_capacities, samples=args.random_samples, seed=args.random_seed
    )
    naive_card = naive_strength_ladder(strengths, rules.category_capacities, team_ids=team_ids)
    naive_score, _naive_table = score_card(naive_card, outcome, truth.names)
    observed_categories = {truth.names[team_id]: obs.category for team_id, obs in outcome.items()}
    rank_stats = rank_diagnostics(card, observed_categories, list(Category))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "DIAGNOSTIC -- not a gate; does not alter the shipping card",
        "league_id": truth.league_id,
        "training_maps": len(train),
        # Reported so the window can be CHECKED against production's rather
        # than assumed to match: 41% of production's maps was the defect that
        # made a matched-window re-run necessary in the first place.
        "training_from": args.train_from,
        "training_window_days": round(train_span_days, 1),
        "observed_score": score,
        "random_baseline": baseline,
        "optimizer_marginal_objective": optimizer_marginal_objective,
        "evaluation_simulation_mean_score": sim_mean,
        "percentile_strictly_below": below,
        "percentile_at_or_below": at_or_below,
        "calibration_slope_refit_precutoff": slope,
        "calibration_slope_production_full_store": slope_full_store,
        "prior_driven_teams": prior_driven,
        "n_sims": args.card_sims,
        "card_seed": args.card_seed,
        "eval_seed": args.eval_seed,
        "score_distribution": {str(k): v for k, v in sorted(dist.items())},
        "card": {name: c.value for name, c in sorted(card.items())},
        "per_slot": [
            {"team": n, "predicted": p.value, "observed": o.value, "hit": h}
            for n, p, o, h in table
        ],
        "sweep": {"n_sims": sweep_sims, "seeds": sweep_seeds, "entries": sweep_entries},
        "random_control": random_control,
        "naive_ladder": {
            "card": {name: c.value for name, c in sorted(naive_card.items())},
            "score": naive_score,
        },
        "rank_diagnostics": rank_stats,
    }
    (out / "d4_card_backtest.json").write_text(json.dumps(payload, indent=2) + "\n")
    (out / "d4_card_backtest.md").write_text(render_markdown(payload))

    with (out / "d4_per_slot.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        for csv_row in render_csv_rows(payload):
            writer.writerow(csv_row)

    hits = sum(1 for r in table if r[3])
    print(f"d4: DIAGNOSTIC (not a gate). trained on {len(train)} maps before cutoff")
    print(
        f"d4: refit calibration slope {slope:.4f} "
        f"(production, full store: {slope_full_store:.4f})"
    )
    print(
        f"d4: observed score {score}/16 | random baseline {baseline:.2f} | "
        f"optimizer marginal objective {optimizer_marginal_objective:.4f} | "
        f"evaluation-simulation mean score {sim_mean:.4f}"
    )
    print(f"d4: percentile {below:.1f}% strictly below, {at_or_below:.1f}% at or below")
    print(f"d4: {hits} hits, {len(table) - hits} misses")
    print(
        f"d4: random-card control mean score {random_control['mean_score']:.4f} "
        f"over {random_control['samples']} samples (seed {random_control['seed']})"
    )
    print(f"d4: naive strength ladder score {naive_score}/16")
    print(f"d4: rank correlation (predicted vs observed category order) {rank_stats['spearman_rho']:.4f}")
    if prior_driven:
        print(f"d4: WARNING prior-driven (unrated) rosters: {prior_driven}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
