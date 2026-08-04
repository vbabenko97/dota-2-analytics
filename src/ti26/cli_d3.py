"""D3: fit in-fold calibration, run the pre-registered calibration gate.

Spec: docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md, section
"D3 calibration gate". D2's forecast-value gate failed and no rating model
cleared the spec V floor (see docs/audits/2026-08-02-d2-build-ledger.md).
The measured diagnosis was miscalibration, not absent signal -- this module
applies the correction `backtest.calibration()` already computes and never
applied, and scores it against the gate registered before this code existed.
"""

import argparse
import csv
from pathlib import Path

from ti26.backtest import calibration, log_loss, rolling_folds, run_model
from ti26.calibrate import SLOPE_BAND, evaluate_d3_gate, run_calibrated_model
from ti26.data.store import load_rows, open_store
from ti26.ratings import load_gate_config
from ti26.ratings.elo import EloModel
from ti26.ratings.glicko import GlickoModel
from ti26.ratings.simple import ConstantModel
from ti26.roster import RosterIndex, load_aliases

# Distinct from 0 (success): a caller that only checks "did this fail" still
# sees failure, and the report always states the reason in full.
GATE_FAIL_EXIT = 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="D3: in-fold calibration and the pre-registered calibration gate"
    )
    parser.add_argument("--store", default="data/processed/d2.sqlite")
    # Same file as D2's gate: the margin, bootstrap draws/CI and seed are
    # pre-registered to match D2's exactly, so the two results are directly
    # comparable (spec). Reusing the one registered file rather than a
    # second transcription rules out drift between the two.
    parser.add_argument("--gate-config", default="config/d2_gate.yaml")
    parser.add_argument("--aliases", default="config/team_aliases.yaml")
    parser.add_argument("--min-train", type=int, default=500)
    parser.add_argument("--out", default="reports")
    args = parser.parse_args(argv)

    config = load_gate_config(args.gate_config)
    aliases = load_aliases(args.aliases)
    rows = load_rows(open_store(args.store))
    if not rows:
        raise SystemExit(f"{args.store} is empty; run `python -m ti26.cli_ingest` first")

    folds = rolling_folds(rows, min_train=args.min_train)
    if not folds:
        raise SystemExit(f"no tournament had {args.min_train}+ prior maps; lower --min-train")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # Constant floor: uncalibrated -- ConstantModel always predicts exactly
    # 0.5, so there is nothing for a calibration correction to fit.
    predictions_constant = run_model(rows, ConstantModel, folds)

    # Elo: the primary and ONLY gated candidate (registered 2026-08-03: it
    # had the lower uncalibrated out-of-sample log loss, and log loss is
    # this gate's own metric).
    predictions_elo, _fitted_elo = run_calibrated_model(
        rows, lambda: EloModel(k=config.elo_k), folds
    )
    slope_elo, intercept_elo = calibration(predictions_elo, rows)

    # Glicko: calibrated and reported as a DIAGNOSTIC only. Registered
    # 2026-08-03: putting two candidates through one gate roughly doubles
    # the false-pass probability, and choosing the winner after seeing
    # results is the multiple-comparisons version of moving the margin. Never
    # gated, never substituted if Elo fails.
    predictions_glicko, _fitted_glicko = run_calibrated_model(
        rows, lambda: GlickoModel(tau=config.glicko_tau, roster_index=RosterIndex(aliases)), folds
    )
    slope_glicko, intercept_glicko = calibration(predictions_glicko, rows)

    result = evaluate_d3_gate(
        predictions_constant, predictions_elo, rows, config, slope_elo, intercept_elo
    )

    metrics = {
        "constant": {
            "log_loss": log_loss(predictions_constant, rows),
            "calibration_slope": float("nan"),
            "calibration_intercept": float("nan"),
            "n_predictions": len(predictions_constant),
            "n_scored": sum(1 for p in predictions_constant if p.rated),
        },
        "elo_calibrated": {
            "log_loss": log_loss(predictions_elo, rows),
            "calibration_slope": slope_elo,
            "calibration_intercept": intercept_elo,
            "n_predictions": len(predictions_elo),
            "n_scored": sum(1 for p in predictions_elo if p.rated),
        },
        "glicko_calibrated_diagnostic": {
            "log_loss": log_loss(predictions_glicko, rows),
            "calibration_slope": slope_glicko,
            "calibration_intercept": intercept_glicko,
            "n_predictions": len(predictions_glicko),
            "n_scored": sum(1 for p in predictions_glicko if p.rated),
        },
    }

    with (out / "d3_metrics.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["model", *sorted(next(iter(metrics.values())))])
        for name, m in metrics.items():
            writer.writerow([name, *(m[k] for k in sorted(m))])

    verdict = "PASS" if result.passed else "FAIL"
    lines = [
        "# D3 calibration gate result",
        "",
        f"**Verdict: {verdict}**",
        "",
        (
            "Pre-registered 2026-08-02/03 in "
            "`docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md` "
            "§II \"D3 calibration gate\", before any calibration code existed:"
        ),
        "",
        "```",
        "mean(LL_constant - LL_calibrated) >= 0.003 nats/map",
        "AND paired cluster bootstrap 95% CI on that difference excludes 0",
        f"AND calibration slope of the calibrated model in [{SLOPE_BAND[0]}, {SLOPE_BAND[1]}]",
        "```",
        "",
        (
            "All three conditions, not any. Elo is the primary and only gated "
            "candidate (registered 2026-08-03); calibrated Glicko is reported below "
            "as a diagnostic and is never gated or substituted."
        ),
        "",
        "| condition | measured | required | result |",
        "|---|---|---|---|",
        (
            f"| margin: mean(LL_constant - LL_calibrated) | {result.margin:.5f} nats/map | "
            f">= {config.min_margin_nats} | {'PASS' if result.margin_passed else 'FAIL'} |"
        ),
        (
            f"| bootstrap {config.bootstrap_ci:.0%} CI excludes 0 | "
            f"[{result.ci_low:.5f}, {result.ci_high:.5f}] | excludes 0 | "
            f"{'PASS' if result.ci_passed else 'FAIL'} |"
        ),
        (
            f"| calibration slope | {result.calibration_slope:.4f} | "
            f"[{result.slope_band[0]}, {result.slope_band[1]}] | "
            f"{'PASS' if result.slope_passed else 'FAIL'} |"
        ),
        "",
        f"**Overall: {verdict}**",
        "",
        f"Interval method: {result.method}. Maps compared: {result.n_maps}.",
        "",
        (
            f"Excluded from scoring: {sum(result.excluded.values())} maps"
            + (
                " (" + ", ".join(f"{v} {k}" for k, v in sorted(result.excluded.items())) + ")"
                if result.excluded
                else " (none)"
            )
        ),
        "",
        f"Folds: {len(folds)} tournaments, {sum(f.n_test for f in folds)} out-of-sample maps.",
        "",
        "## Metrics",
        "",
        "| model | log loss | calibration slope | calibration intercept | n scored / n predictions |",
        "|---|---|---|---|---|",
    ]
    for name, m in metrics.items():
        lines.append(
            f"| {name} | {m['log_loss']:.5f} | {m['calibration_slope']:.4f} | "
            f"{m['calibration_intercept']:.4f} | {m['n_scored']} / {m['n_predictions']} |"
        )
    lines += [
        "",
        (
            "`elo_calibrated` is the gated candidate. `glicko_calibrated_diagnostic` is "
            "reported here only -- per spec (registered 2026-08-03), putting two "
            "candidates through one gate roughly doubles the false-pass probability, "
            "and choosing between them after seeing results is the multiple-comparisons "
            "version of moving the margin. It never gates and is never substituted if "
            "Elo fails."
        ),
        "",
        "## Consequence",
        "",
    ]
    if result.passed:
        lines.append("Proceed to D3 dynamic Bradley-Terry development (spec build plan).")
    else:
        lines += [
            "**D3 stops here.** Reasons: " + "; ".join(result.reasons) + ".",
            "",
            (
                "Per spec: **the rung-3 public-ratings card ships, and no custom "
                "Bradley-Terry model is built.** Two failed gates on the same data "
                "(D2's elo-vs-glicko forecast-value gate and this calibration gate) is "
                "evidence about the data, not a reason for a third attempt with a "
                "looser bar."
            ),
        ]
    (out / "d3_gate.md").write_text("\n".join(lines) + "\n")

    print(
        f"D3 gate: {verdict} (margin {result.margin:.5f}, CI [{result.ci_low:.5f}, "
        f"{result.ci_high:.5f}], slope {result.calibration_slope:.4f})"
    )
    return 0 if result.passed else GATE_FAIL_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
