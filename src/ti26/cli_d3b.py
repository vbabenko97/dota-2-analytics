"""D3b: the multiplicity-corrected Glicko gate.

Spec: docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md, section
"D3b: the multiplicity-corrected Glicko gate". Registered 2026-08-03, AFTER
the Elo gate (D3) failed on all three conditions and BEFORE Glicko's
bootstrap interval was computed.

This is a ONE-condition test, not three. Calibrated Glicko's margin
(0.00671) and calibration slope (0.9049) were already measured -- computed
alongside Elo's diagnostic in the D3 run -- and already pass. The only open
quantity is Glicko's paired cluster bootstrap interval, which this module
computes for real via `backtest.paired_differences` /
`backtest.paired_cluster_bootstrap` (through `calibrate.evaluate_d3_gate` --
no second bootstrap is written).

Because two candidates were actually computed (Elo, Glicko), the interval
pays for that multiplicity: Bonferroni over 2 comparisons gives a 97.5%
two-sided interval instead of the Elo gate's 95%, deliberately STRICTER.
`config/d2_gate.yaml`'s `bootstrap_ci: 0.95` is NOT edited -- D2's own gate
result must stay reproducible from that file untouched -- the 97.5% level is
applied only to an in-memory copy of the loaded config.
"""

import argparse
from dataclasses import replace
from pathlib import Path

from ti26.backtest import calibration, rolling_folds, run_model
from ti26.calibrate import SLOPE_BAND, evaluate_d3_gate, run_calibrated_model
from ti26.data.store import load_rows, open_store
from ti26.gate_artifacts import gate_result_payload, write_gate_result
from ti26.ratings import load_gate_config
from ti26.ratings.glicko import GlickoModel
from ti26.ratings.simple import ConstantModel
from ti26.roster import RosterIndex, load_aliases

# Bonferroni: family-wise alpha 0.05 over the 2 candidates actually computed
# (Elo, Glicko) gives per-comparison alpha 0.025, hence a 97.5% two-sided
# interval -- stricter than the Elo gate's 95%, which is why this does not
# fall foul of the "no looser bar on a third attempt" prohibition.
D3B_BOOTSTRAP_CI = 0.975

GATE_FAIL_EXIT = 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="D3b: the multiplicity-corrected Glicko gate (a one-condition test)"
    )
    parser.add_argument("--store", default="data/processed/d2.sqlite")
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

    # Same construction as the D3 (Elo) run: identical rows, folds and model
    # factory, so this scores the same population the Elo gate did -- required
    # for the two intervals to be directly comparable. The size of that
    # population is reported by this run as `n_maps`, not asserted here.
    predictions_constant = run_model(rows, ConstantModel, folds)
    predictions_glicko, _fitted = run_calibrated_model(
        rows, lambda: GlickoModel(tau=config.glicko_tau, roster_index=RosterIndex(aliases)), folds
    )
    slope, intercept = calibration(predictions_glicko, rows)

    # The YAML file on disk keeps bootstrap_ci: 0.95 -- only this in-memory
    # copy is corrected to 97.5%.
    config_975 = replace(config, bootstrap_ci=D3B_BOOTSTRAP_CI)
    result = evaluate_d3_gate(
        predictions_constant, predictions_glicko, rows, config_975, slope, intercept,
        slope_band=SLOPE_BAND,
    )

    verdict = "PASS" if result.passed else "FAIL"
    slope_margin = result.calibration_slope - SLOPE_BAND[0]
    lines = [
        "# D3b calibration gate result -- the multiplicity-corrected Glicko gate",
        "",
        f"**Verdict: {verdict}**",
        "",
        (
            "Registered 2026-08-03 in "
            "`docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md` §II "
            "\"D3b: the multiplicity-corrected Glicko gate\", after the Elo gate (D3) "
            "failed on all three conditions and BEFORE Glicko's bootstrap interval was "
            "computed."
        ),
        "",
        (
            "**This is a ONE-condition test, not three.** Calibrated Glicko's margin "
            "and calibration slope were already measured -- computed alongside Elo's "
            "diagnostic in the D3 run -- and already pass. They are restated below for "
            "the record, not re-tested; the interval is the only quantity that was open "
            "when this gate was registered, and it is the actual test."
        ),
        "",
        "## Already measured (not under test here)",
        "",
        "| condition | value | required | result |",
        "|---|---|---|---|",
        (
            f"| margin: mean(LL_constant - LL_glicko_calibrated) | {result.margin:.5f} "
            f"nats/map | >= {config.min_margin_nats} | "
            f"{'PASS' if result.margin_passed else 'FAIL'} (already known) |"
        ),
        (
            f"| calibration slope | {result.calibration_slope:.4f} | "
            f"[{SLOPE_BAND[0]}, {SLOPE_BAND[1]}] | "
            f"{'PASS' if result.slope_passed else 'FAIL'} (already known) |"
        ),
        "",
        (
            f"**The slope's margin of compliance is fragile: {result.calibration_slope:.4f} "
            f"clears the {SLOPE_BAND[0]} lower bound by only {slope_margin:.4f}.** This is "
            "stated plainly rather than shown as a bare PASS, so a reader can judge it "
            "rather than trust it."
        ),
        "",
        "## The actual test: the paired cluster bootstrap interval, at 97.5% not 95%",
        "",
        (
            "Bonferroni for the two candidates actually computed (Elo, Glicko): "
            "family-wise alpha 0.05 over 2 comparisons gives per-comparison alpha "
            "0.025, hence a 97.5% two-sided interval -- STRICTER than the Elo gate's "
            "95%, not looser, so this does not fall foul of the prohibition on a third "
            "attempt with a looser bar."
        ),
        "",
        "| condition | measured | required | result |",
        "|---|---|---|---|",
        (
            f"| paired cluster bootstrap 97.5% CI excludes 0 | "
            f"[{result.ci_low:.5f}, {result.ci_high:.5f}] | excludes 0 | "
            f"{'PASS' if result.ci_passed else 'FAIL'} |"
        ),
        "",
        f"**Overall D3b verdict: {verdict}**",
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
        "## Consequence",
        "",
    ]
    if result.passed:
        lines += [
            (
                "**Calibrated Glicko is a backtested strength source: the card can be "
                "built from it instead of rung 3's unverifiable public-rating divisor.** "
                "But this rests on a ONE-condition test whose other two conditions "
                "(margin, slope) were already known before this run -- it is weaker "
                "evidence than the Elo gate would have been had Elo itself passed all "
                "three conditions fresh. Building a card from Glicko is a separate "
                "decision, not made in this run."
            ),
        ]
    else:
        lines += [
            "**The rung-3 public-ratings card ships. D3 is over. There is no D3c.**",
        ]
    (out / "d3b_gate.md").write_text("\n".join(lines) + "\n")

    exit_code = 0 if result.passed else GATE_FAIL_EXIT
    write_gate_result(
        out / "d3b_gate.json",
        gate_result_payload(
            gate="d3b",
            verdict=verdict,
            exit_code=exit_code,
            registration=(
                "docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md "
                "section II, D3b multiplicity-corrected Glicko gate"
            ),
            conditions={
                "margin": {
                    "value": result.margin,
                    "threshold": config.min_margin_nats,
                    "passed": result.margin_passed,
                    "open_for_test": False,
                },
                # The interval is the only quantity that was open when this
                # gate was registered; margin and slope were already measured.
                "ci": {
                    "value": [result.ci_low, result.ci_high],
                    "excludes": 0.0,
                    "passed": result.ci_passed,
                    "open_for_test": True,
                },
                "slope": {
                    "value": result.calibration_slope,
                    "band": list(result.slope_band),
                    "passed": result.slope_passed,
                    "open_for_test": False,
                },
            },
            method=result.method,
            n_maps=result.n_maps,
            excluded=result.excluded,
            config={
                "bootstrap_ci": config_975.bootstrap_ci,
                "bootstrap_draws": config_975.bootstrap_draws,
                "min_train": args.min_train,
                "seed": config_975.seed,
                "slope_band": list(SLOPE_BAND),
            },
        ),
    )

    print(
        f"D3b gate: {verdict} (97.5% CI [{result.ci_low:.5f}, {result.ci_high:.5f}], "
        f"margin {result.margin:.5f} already known, slope {result.calibration_slope:.4f} "
        "already known)"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
