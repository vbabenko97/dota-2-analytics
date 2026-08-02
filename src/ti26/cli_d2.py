"""Fit ratings, run the rolling backtest, report the pre-registered verdict."""

import argparse
import csv
import json
from dataclasses import replace
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
from ti26.ratings import load_gate_config
from ti26.ratings.elo import EloModel
from ti26.ratings.glicko import GlickoModel
from ti26.ratings.simple import ConstantModel, EwmaModel
from ti26.roster import RosterIndex, load_aliases
from ti26.rules import load_rules
from ti26.teams import load_teams, resolve_rosters, team_strengths


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
            "n_predictions": len(predictions[name]),
        }

    with (out / "backtest_metrics.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["model", *sorted(next(iter(metrics.values())))])
        for name in models:
            writer.writerow([name, *(metrics[name][k] for k in sorted(metrics[name]))])

    result = evaluate_gate(predictions["elo"], predictions["glicko"], rows, config)

    # --- Final fit on everything, then the card -------------------------------
    selected = args.final_model
    if selected == "auto":
        selected = "glicko" if result.passed else "elo"

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

    card_status = "skipped (--skip-card)"
    sweep: list[dict] = []
    prior_driven: list[str] = []
    if not args.skip_card:
        teams = load_teams(args.teams)
        if len(teams) != rules.n_teams:
            raise SystemExit(
                f"{args.teams} lists {len(teams)} teams but the rules require "
                f"{rules.n_teams}; populate it or pass --skip-card"
            )
        resolved = resolve_rosters(rows, teams, aliases)
        strengths, prior_driven = team_strengths(resolved, fitted)

        strengths_path = out / "strengths.csv"
        with strengths_path.open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["team", "strength", "roster_version_id", "prior_driven"])
            for name in sorted(strengths):
                writer.writerow(
                    [name, f"{strengths[name]:.6f}", resolved[name], name in prior_driven]
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

        # Spec XII: report how much the card depends on the duration parameter.
        sweep = sensitivity_sweep(
            strengths,
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
        "## Consequence",
        "",
        (
            "Proceed to D3 dynamic Bradley-Terry development."
            if result.passed
            else "**Do not proceed to D3.** Ship the public-rating fallback (spec X, rung 3). "
            "Reasons: " + "; ".join(result.reasons)
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
        "## Card",
        "",
        (
            f"Status: {card_status}. Final model: **{selected}** "
            f"({'gate passed' if result.passed else 'gate failed — Elo is the shipped fit'})."
        ),
    ]
    if not args.skip_card and prior_driven:
        lines += [
            "",
            f"**Prior-driven teams ({len(prior_driven)}):** " + ", ".join(prior_driven)
            + ". These carry the average-team prior, not a fitted rating.",
        ]
    if not result.passed:
        lines += [
            "",
            (
                "Spec §X rung 3 makes public ratings the default when this gate fails. "
                "To ship that instead, write a `team,strength` CSV and run "
                "`python -m ti26.cli --strengths <file>`."
            ),
        ]
    if sweep:
        lines += [
            "",
            "## Duration sensitivity",
            "",
            "| log_sigma | max abs delta vs fitted |",
            "|---|---|",
        ] + [
            f"| {s['log_sigma']:.4f} | {s['max_abs_delta']:.5f} |" for s in sweep
        ] + [
            "",
            (
                "Largest movement in any single category probability when the duration "
                "parameter is varied. Spec §XII: this parameter is consulted on roughly "
                "30% of every ranking, so its influence is reported rather than assumed away."
            ),
        ]
    (out / "d2_gate.md").write_text("\n".join(lines) + "\n")

    print(f"gate: {verdict} (margin {result.margin:.5f}, CI [{result.ci_low:.5f}, "
          f"{result.ci_high:.5f}], {result.method})")
    print(f"card: {card_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
