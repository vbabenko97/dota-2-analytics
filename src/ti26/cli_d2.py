"""Fit ratings, run the rolling backtest, report the pre-registered verdict."""

import argparse
import csv
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from ti26.backtest import (
    accuracy,
    brier,
    calibration,
    evaluate_gate,
    log_loss,
    rolling_folds,
    run_model,
)
from ti26.cli import main as cli_main
from ti26.data.store import load_rows, open_store
from ti26.duration import fit_duration_model, rating_gaps, sensitivity_sweep
from ti26.gate_artifacts import gate_result_payload, write_gate_result
from ti26.ratings import load_gate_config
from ti26.ratings.elo import EloModel
from ti26.ratings.glicko import GlickoModel
from ti26.ratings.simple import ConstantModel, EwmaModel
from ti26.roster import RosterIndex, load_aliases
from ti26.rules import load_rules
from ti26.teams import (
    RosterStaleness,
    UnresolvedTeamError,
    check_roster_staleness,
    load_teams,
    resolve_rosters,
    team_strengths,
)

# Distinct from 0 (success) and from the plain `raise SystemExit(str)` paths
# elsewhere in this module (which exit 1): a caller that only checks "did
# this fail" still sees failure, but a caller that cares WHY can tell "no
# card was written from our fit" apart from every other error in this
# file. Shared by BOTH refusal reasons -- the spec V floor not clearing,
# and (spec X) the elo-vs-glicko gate failing under "auto" -- because both
# mean the same thing to a caller: nothing shipped, check rung 3.
NO_CARD_EXIT = 3

# Refitting on UNCHANGED data reproduces bit-identical floats, so any gap
# larger than this between `duration_fit` and the loaded rules config's
# duration_model means the config is stale relative to this run's data,
# not floating-point noise.
DURATION_STALENESS_TOLERANCE = 1e-6


def floor_check(metrics: dict[str, dict], floor_name: str = "constant") -> dict[str, dict]:
    """Spec V: every rating model must beat the constant 50/50 floor.

    Compares each model's out-of-sample log loss against `floor_name`'s on
    the identical prediction population. A model "clears" the floor only
    if its log loss is STRICTLY lower -- a tie is not a beat, and the floor
    model can never clear its own bar. Returns, per model name, its log
    loss, the signed difference from the floor (positive = worse), and
    whether it cleared.
    """
    floor_loss = metrics[floor_name]["log_loss"]
    return {
        name: {
            "log_loss": m["log_loss"],
            "diff": m["log_loss"] - floor_loss,
            "cleared": name != floor_name and m["log_loss"] < floor_loss,
        }
        for name, m in metrics.items()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D2: fit ratings and evaluate the gate")
    parser.add_argument("--store", default="data/processed/d2.sqlite")
    parser.add_argument("--gate-config", default="config/d2_gate.yaml")
    parser.add_argument("--rules", default="config/ti2026_rules.yaml")
    parser.add_argument("--aliases", default="config/team_aliases.yaml")
    parser.add_argument("--teams", default="config/ti2026_teams.yaml")
    parser.add_argument("--min-train", type=int, default=500)
    parser.add_argument("--final-model", choices=["auto", "elo", "glicko"], default="auto")
    parser.add_argument("--card-sims", type=int, default=250_000)
    parser.add_argument("--card-seed", type=int, default=1)
    parser.add_argument("--skip-card", action="store_true",
                        help="stop after the gate; use when the team list is not yet known")
    parser.add_argument("--out", default="reports")
    args = parser.parse_args(argv)

    config = load_gate_config(args.gate_config)
    rules = load_rules(args.rules)
    aliases = load_aliases(args.aliases)
    rows = load_rows(open_store(args.store))
    if not rows:
        raise SystemExit(f"{args.store} is empty; run `python -m ti26.cli_ingest` first")

    folds = rolling_folds(rows, min_train=args.min_train)
    if not folds:
        raise SystemExit(f"no tournament had {args.min_train}+ prior maps; lower --min-train")

    # The SAME factories are used for the backtest and for the final fit, so a
    # collaborator missing here is missing in both -- never in only one.
    models = {
        "constant": lambda: ConstantModel(),
        "ewma": lambda: EwmaModel(half_life_maps=config.ewma_half_life_maps),
        "elo": lambda: EloModel(k=config.elo_k),
        "glicko": lambda: GlickoModel(
            tau=config.glicko_tau, roster_index=RosterIndex(aliases)
        ),
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    predictions, metrics = {}, {}
    for name, factory in models.items():
        predictions[name] = run_model(rows, factory, folds)
        slope, intercept = calibration(predictions[name], rows)
        metrics[name] = {
            "log_loss": log_loss(predictions[name], rows),
            "brier": brier(predictions[name], rows),
            "accuracy": accuracy(predictions[name], rows),
            "calibration_slope": slope,
            "calibration_intercept": intercept,
            # Two different denominators, labeled so neither is mistaken for
            # the other: `n_predictions` is every out-of-sample row (rated
            # or not), `n_scored` is the population log_loss/brier/accuracy
            # above are actually computed over (`rated=True` only). They sit
            # in the same row as the floor-gate log-loss values, so an
            # ambiguous single count would invite dividing by the wrong one.
            "n_predictions": len(predictions[name]),
            "n_scored": sum(1 for p in predictions[name] if p.rated),
        }

    with (out / "backtest_metrics.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["model", *sorted(next(iter(metrics.values())))])
        for name in models:
            writer.writerow([name, *(metrics[name][k] for k in sorted(metrics[name]))])

    # Spec V: each rating model must beat the constant floor on rolling
    # out-of-sample log loss to be trusted as a strength source, independent
    # of whether Glicko beats Elo below. Computed on the SAME metrics as the
    # table above, so it can never disagree with what the report prints.
    floor = floor_check(metrics)

    result = evaluate_gate(predictions["elo"], predictions["glicko"], rows, config)

    # --- Final fit on everything, then the card -------------------------------
    selected = args.final_model
    gate_forced_rung3 = False
    if selected == "auto":
        if result.passed:
            selected = "glicko"
        else:
            # Spec X is explicit: public ratings are "the default if the
            # forecast-value gate fails" -- rung 3, not a quiet fallback to
            # Elo (rung 2). This must hold regardless of whether Elo would
            # separately clear the spec V floor below: a failed gate is not
            # allowed to land on rung 2. `selected` still names Elo (used
            # below only as the diagnostic input to the sensitivity sweep,
            # same as a floor refusal), but no card is written from it.
            selected = "elo"
            gate_forced_rung3 = True

    final = models[selected]()
    for row in rows:
        final.update(row)
    if hasattr(final, "flush"):
        final.flush()
    fitted = final.strengths()

    # Rating gap per map from a SEPARATE Elo pass, predict-then-update, so the
    # duration fit is conditioned on gap without ever seeing a map's own result.
    gaps = rating_gaps(rows, EloModel(k=config.elo_k))
    duration_fit = fit_duration_model(rows, gaps=gaps)
    (out / "duration_fit.json").write_text(
        json.dumps(
            {
                "log_mean": duration_fit.log_mean,
                "log_sigma": duration_fit.log_sigma,
                "gap_coefficient": duration_fit.gap_coefficient,
                "gap_se": duration_fit.gap_se,
                "gap_effect_material": duration_fit.material,
                "n": duration_fit.n,
                "placeholder_log_mean": 7.65,
                "placeholder_log_sigma": 0.25,
                "note": "spec XII: this parameter steers ~30% of every ranking",
            },
            indent=2,
        )
        + "\n"
    )

    # The card (built below via `cli_main --rules args.rules`) reads its
    # duration parameters from the STATIC config file on disk, not from
    # `duration_fit` above -- `cli.main` calls `load_rules(args.rules)`
    # itself and has no way to receive the freshly-fitted values from this
    # run. Syncing `config/ti2026_rules.yaml` is a separate, manual step
    # (this build's Step 11); nothing in this file writes it automatically.
    # A silent re-ingest that refits different values without that manual
    # sync would ship a card built on stale duration parameters. Made loud
    # rather than threaded through automatically: the documented workflow
    # deliberately runs the card once on the outgoing config (Step 10)
    # BEFORE the config is updated from this exact fit (Step 11), so a
    # mismatch is sometimes expected mid-workflow, not always a bug --
    # hard-failing here would break that documented sequence.
    duration_stale = (
        abs(duration_fit.log_mean - rules.duration_log_mean) > DURATION_STALENESS_TOLERANCE
        or abs(duration_fit.log_sigma - rules.duration_log_sigma) > DURATION_STALENESS_TOLERANCE
    )
    if duration_stale:
        print(
            f"WARNING: {args.rules}'s duration_model (log_mean="
            f"{rules.duration_log_mean:.4f}, log_sigma={rules.duration_log_sigma:.4f}) does "
            f"NOT match this run's freshly-fitted values (log_mean={duration_fit.log_mean:.4f}, "
            f"log_sigma={duration_fit.log_sigma:.4f}). Any card built this run used the STALE "
            "config values -- update the rules config from duration_fit.json and re-run "
            "before trusting it."
        )

    card_status = "skipped (--skip-card)"
    sweep: list[dict] = []
    sweep_strengths_note = ""
    prior_driven: list[str] = []
    card_refused = False
    staleness: list[RosterStaleness] = []
    if not args.skip_card:
        teams = load_teams(args.teams)
        if len(teams) != rules.n_teams:
            raise SystemExit(
                f"{args.teams} lists {len(teams)} teams but the rules require "
                f"{rules.n_teams}; populate it or pass --skip-card"
            )

        # Time-critical (TI 2026 Swiss locks 2026-08-13): detect a configured
        # team whose org has moved to a new, unaliased team_id since the
        # configured id's last map -- run on every invocation, not gated on
        # the floor verdict, since this affects the sweep's diagnostic
        # strengths too. WARN, never hard-fail: several already-confirmed
        # duplicate team_id registrations (Xtreme Gaming, HULIGANI, Team
        # Resilience) produce the IDENTICAL signature as a genuine migration
        # (same roster, later map, different unaliased id) and this store
        # has no way to tell them apart from account/team_id data alone --
        # hard-failing would block a correct run on those every time.
        staleness = check_roster_staleness(rows, teams, aliases)
        migrations = [c for c in staleness if c.migrated_to is not None]
        if migrations:
            names = ", ".join(f"{c.name} (team_id={c.team_id} -> {c.migrated_to})" for c in migrations)
            print(
                f"WARNING: {len(migrations)} configured team(s) may have migrated to an "
                f"unaliased team_id -- check before the card ships: {names}"
            )

        card_refused = gate_forced_rung3 or not floor[selected]["cleared"]
        if card_refused:
            # Two independent reasons converge on the same refusal: spec V
            # (a model that loses to a coin flip is not a strength source)
            # and spec X (a failed elo-vs-glicko gate goes straight to rung
            # 3, never rung 2). No card is written either way, and no OTHER
            # model is silently substituted -- the user picked (or "auto"
            # picked) `selected`, and refusing beats second-guessing that
            # choice. `strengths.csv` is withheld too: it is the card's
            # direct input, and writing it invites running the card
            # manually from a disqualified or gate-failed model.
            if gate_forced_rung3:
                card_status = (
                    "REFUSED: the elo-vs-glicko gate failed under --final-model auto, so "
                    "per spec X rung 3 no card ships from our fit -- regardless of "
                    f"whether {selected} would separately clear the spec V floor (here: "
                    f"{'cleared' if floor[selected]['cleared'] else 'not cleared'}; see "
                    "the Floor check table)"
                )
            else:
                card_status = (
                    f"REFUSED: {selected} log loss {floor[selected]['log_loss']:.5f} does not "
                    f"beat the constant floor {floor['constant']['log_loss']:.5f} (spec V "
                    "rung 1); no card written from our fit"
                )
            # The duration sensitivity sweep still runs: spec XII requires
            # reporting the simulator's sensitivity to the duration
            # parameter regardless of which strength source ships. This
            # does NOT write the fitted parameter into `ti2026_rules.yaml`
            # -- that sync is a separate, manual step (see the staleness
            # check above) -- it only reports how much a card would move if
            # `log_sigma` changed. The sweep measures the SIMULATOR's
            # sensitivity, not the quality of the strengths behind it --
            # Task 7 measured this statistic close to invariant to which
            # strengths it is given -- so the disqualified fit is a valid,
            # explicitly-labeled diagnostic input, kept in memory only
            # (never written to `strengths.csv`).
            try:
                resolved = resolve_rosters(rows, teams, aliases)
                sweep_strengths, _ = team_strengths(resolved, fitted)
                sweep_strengths_note = (
                    f"diagnostic only, not endorsed: disqualified {selected} strengths "
                    f"({len(sweep_strengths)} teams)"
                )
            except UnresolvedTeamError as exc:
                sweep_strengths = {t.name: 0.0 for t in teams}
                sweep_strengths_note = (
                    f"diagnostic only: tied strengths (roster resolution failed for an "
                    f"unrelated reason: {exc})"
                )
        else:
            resolved = resolve_rosters(rows, teams, aliases)
            strengths, prior_driven = team_strengths(resolved, fitted)
            sweep_strengths = strengths
            sweep_strengths_note = f"fitted {selected} strengths ({len(strengths)} teams)"

            # team_id travels with the strength so the card generator orders
            # teams by configured identity rather than by display name.
            team_ids = {entry.name: str(entry.team_id) for entry in teams}
            strengths_path = out / "strengths.csv"
            with strengths_path.open("w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(
                    ["team", "team_id", "strength", "roster_version_id", "prior_driven"]
                )
                for name in sorted(strengths):
                    writer.writerow(
                        [
                            name,
                            team_ids[name],
                            f"{strengths[name]:.6f}",
                            resolved[name],
                            name in prior_driven,
                        ]
                    )

            # The card comes from the D1 generator, fed OUR fitted strengths --
            # not from its synthetic fallback ladder.
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
            card_status = f"generated from {selected} strengths ({len(strengths)} teams)"

        # Spec XII: report how much the card depends on the duration parameter,
        # regardless of whether a card actually shipped this run.
        sweep = sensitivity_sweep(
            sweep_strengths,
            replace(rules, duration_log_sigma=duration_fit.log_sigma),
            [duration_fit.log_sigma, duration_fit.log_sigma * 0.5,
             duration_fit.log_sigma * 1.5, 0.25],
            n_sims=max(20_000, args.card_sims // 10),
            seed=args.card_seed,
        )
        (out / "duration_sensitivity.json").write_text(json.dumps(sweep, indent=2) + "\n")

    verdict = "PASS" if result.passed else "FAIL"
    lines = [
        "# D2 gate result",
        "",
        f"**Verdict: {verdict}**",
        "",
        "Pre-registered 2026-08-02 in `config/d2_gate.yaml`, before any backtest ran:",
        "",
        f"- required margin: `mean(LL_elo - LL_glicko) >= {config.min_margin_nats}` nats/map",
        f"- required significance: paired bootstrap {config.bootstrap_ci:.0%} CI excludes 0",
        "",
        (
            f"Observed margin: **{result.margin:.5f}** nats/map, "
            f"CI [{result.ci_low:.5f}, {result.ci_high:.5f}]"
        ),
        "",
        f"Interval method: {result.method}. Maps compared: {result.n_maps}.",
        "",
        (
            f"Excluded from scoring: {sum(result.excluded.values())} maps "
            + (
                "(" + ", ".join(f"{v} {k}" for k, v in sorted(result.excluded.items())) + ")"
                if result.excluded
                else "(none)"
            )
            + f". {sum(f.n_test for f in folds)} out-of-sample maps total minus "
            f"{sum(result.excluded.values())} excluded is {result.n_maps} compared -- the "
            "model itself declined to rate these rows (`null_team`/`bad_roster`), so the "
            "gate scores only the population it was willing to train on, per spec IV."
        ),
        "",
        (
            "The interval is a **cluster** bootstrap, not an iid one over maps: maps "
            "inside a series share teams, day, patch and momentum, and treating them "
            "as independent would understate the interval and let this gate pass on noise."
        ),
        "",
        f"Folds: {len(folds)} tournaments, {sum(f.n_test for f in folds)} out-of-sample maps.",
        "",
        "## Backtest metrics",
        "",
        "| model | log loss | Brier | accuracy | cal. slope | cal. intercept |",
        "|---|---|---|---|---|---|",
    ]
    for name in models:
        m = metrics[name]
        lines.append(
            f"| {name} | {m['log_loss']:.5f} | {m['brier']:.5f} | {m['accuracy']:.4f} | "
            f"{m['calibration_slope']:.3f} | {m['calibration_intercept']:.3f} |"
        )
    lines += [
        "",
        (
            "Accuracy is reported but never used for selection (spec II): it is not a proper "
            "scoring rule."
        ),
        "",
        "## Floor check (spec V)",
        "",
        (
            "Spec V: each rating model must beat the constant 50/50 floor on rolling "
            "out-of-sample log loss to be trusted as a strength source. Checked here "
            "independently of the Elo-vs-Glicko significance gate above -- a model can "
            "lose that comparison and still clear the floor, or win it and still lose to "
            "a coin flip."
        ),
        "",
        "| model | log loss | vs floor | cleared |",
        "|---|---|---|---|",
    ]
    for name in models:
        f = floor[name]
        cleared_cell = "-- (floor)" if name == "constant" else ("yes" if f["cleared"] else "**NO**")
        diff_cell = "--" if name == "constant" else f"{f['diff']:+.5f}"
        lines.append(f"| {name} | {f['log_loss']:.5f} | {diff_cell} | {cleared_cell} |")
    lines += [
        "",
        (
            f"**Selected model for the card: {selected}. Floor cleared: "
            f"{'YES' if floor[selected]['cleared'] else 'NO'}.**"
        ),
    ]
    if card_refused:
        reason = (
            "the elo-vs-glicko gate failed under `--final-model auto` (spec X: rung 3 is "
            "the default on a failed gate, never a quiet fallback to rung 2)"
            if gate_forced_rung3
            else f"{selected} does not beat the constant floor (spec V rung 1)"
        )
        lines += [
            "",
            (
                f"**No card ships from our fit.** {reason}, so no card is written and no "
                "other model is silently substituted in its place. Spec X rung 3: use "
                "public ratings (Noxville/datdota) instead -- write a `team,strength` CSV "
                "and run `python -m ti26.cli --strengths <file>`."
            ),
        ]
    lines += [
        "",
        "## Consequence",
        "",
        (
            "Proceed to D3 dynamic Bradley-Terry development."
            if result.passed
            else "**Do not proceed to D3.** Reasons: " + "; ".join(result.reasons)
        ),
        "",
        "## Duration model (spec XII)",
        "",
        (
            f"Fitted from {duration_fit.n} real map durations, conditioned on pre-match "
            f"rating gap: `log_mean={duration_fit.log_mean:.4f}`, "
            f"`log_sigma={duration_fit.log_sigma:.4f}`, "
            f"`gap_coefficient={duration_fit.gap_coefficient:.4f}` "
            f"(SE {duration_fit.gap_se:.4f}, material={duration_fit.material}). "
            "The placeholder was 7.65 / 0.25 with provenance `arbitrary`."
        ),
        "",
        (
            f"**Config staleness check:** `{args.rules}` currently has "
            f"`log_mean={rules.duration_log_mean:.4f}`, `log_sigma={rules.duration_log_sigma:.4f}`. "
            + (
                "**This does NOT match the fit above -- any card built this run (or manually, "
                "from this config) used STALE duration parameters.** Update the rules config "
                "from `duration_fit.json` and re-run before trusting a card."
                if duration_stale
                else "Matches the fit above; a card built this run used these current values."
            )
        ),
        "",
        "## Card",
        "",
        f"Status: {card_status}.",
    ]
    if not args.skip_card and prior_driven:
        lines += [
            "",
            f"**Prior-driven teams ({len(prior_driven)}):** " + ", ".join(prior_driven)
            + ". These carry the average-team prior, not a fitted rating.",
        ]
    if staleness:
        migrations = [c for c in staleness if c.migrated_to is not None]
        lines += [
            "",
            "## Roster staleness (spec III)",
            "",
            (
                "Two independent checks per configured team: does the SAME roster appear "
                "later under a different, unaliased team_id (a possible migration -- this "
                "is exactly how the Tundra Esports/1win entry went stale until a human "
                "fact-check caught it), and how long since this roster's last map relative "
                "to the store's own most recent map. A migration hit does not by itself mean "
                "the entry is wrong: several configured teams are already-confirmed "
                "duplicate team_id registrations for the SAME org (Xtreme Gaming, HULIGANI, "
                "Team Resilience -- see `ti2026_teams.yaml`'s ledger) and produce this "
                "identical signature. This check WARNS rather than hard-failing `cli_d2` "
                "for exactly that reason: a hard fail would block a correct run on those "
                "every time. Every hit below needs a human cross-check against what is "
                "already documented before being treated as new news."
            ),
            "",
            "| team | team_id | last map | stale (days) | possible migration |",
            "|---|---|---|---|---|",
        ]
        for c in sorted(staleness, key=lambda c: c.name):
            last_date = datetime.fromtimestamp(c.last_map_at, UTC).date()
            if c.migrated_to is not None:
                migrated_date = datetime.fromtimestamp(c.migrated_at, UTC).date()
                migration_cell = (
                    f"**team_id={c.migrated_to} on {migrated_date} "
                    f"({c.migrated_overlap}/5 accounts)**"
                )
            else:
                migration_cell = "--"
            lines.append(
                f"| {c.name} | {c.team_id} | {last_date} | {c.stale_days:.1f} | "
                f"{migration_cell} |"
            )
        if migrations:
            names = ", ".join(f"{c.name} (team_id={c.team_id} -> {c.migrated_to})" for c in migrations)
            lines += [
                "",
                (
                    f"**{len(migrations)} configured team(s) show a possible migration: "
                    f"{names}.** Check each against `ti2026_teams.yaml`'s ledger before "
                    "the card ships."
                ),
            ]
        else:
            lines += ["", "No migrations detected against any configured team this run."]
    if sweep:
        lines += [
            "",
            "## Duration sensitivity",
            "",
            (
                f"Strengths used for this sweep: {sweep_strengths_note}. The sweep measures "
                "the SIMULATOR's sensitivity to the duration parameter, not the quality of "
                "these strengths -- it runs regardless of the floor verdict above."
            ),
            "",
            "| log_sigma | max abs delta vs fitted |",
            "|---|---|",
        ] + [
            f"| {s['log_sigma']:.4f} | {s['max_abs_delta']:.5f} |" for s in sweep
        ] + [
            "",
            (
                "Largest movement in any single category probability when the duration "
                "parameter is varied. Spec §XII requires this parameter's influence to be "
                "reported rather than assumed away. The table above is that report; this "
                "run measures the movement, not the share of any ranking the parameter "
                "accounts for."
            ),
        ]
    (out / "d2_gate.md").write_text("\n".join(lines) + "\n")

    exit_code = NO_CARD_EXIT if card_refused else 0
    write_gate_result(
        out / "d2_gate.json",
        gate_result_payload(
            gate="d2",
            verdict=verdict,
            # D2's registered refusal exit is NO_CARD_EXIT, which is non-zero
            # for a failing gate; the artifact records what this process
            # actually returned rather than a normalised stand-in.
            exit_code=exit_code,
            registration=(
                "docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md "
                "section II, D2 forecast-value gate"
            ),
            conditions={
                "margin": {
                    "value": result.margin,
                    "threshold": config.min_margin_nats,
                    "passed": result.margin_passed,
                },
                "ci": {
                    "value": [result.ci_low, result.ci_high],
                    "excludes": 0.0,
                    "passed": result.ci_passed,
                },
            },
            method=result.method,
            n_maps=result.n_maps,
            excluded=result.excluded,
            config={
                "bootstrap_ci": config.bootstrap_ci,
                "bootstrap_draws": config.bootstrap_draws,
                "min_train": args.min_train,
                "seed": config.seed,
            },
        ),
    )

    print(f"gate: {verdict} (margin {result.margin:.5f}, CI [{result.ci_low:.5f}, "
          f"{result.ci_high:.5f}], {result.method})")
    print(f"floor: {selected} cleared={floor[selected]['cleared']}")
    print(f"card: {card_status}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
