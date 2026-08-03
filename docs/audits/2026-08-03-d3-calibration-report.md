# D3 calibration report — the pre-registered gate FAILED

Branch: `d3-rung3-public-ratings`. Implementation commit `62e90a9` (before any
calibration was fitted or scored); gate-run commit follows this document.

## Outcome: the D3 calibration gate FAILED, on all three conditions

Measured on the same 41,140-map store D2 used (snapshot `20260802T165535Z`),
192 rolling tournament folds, 28,923 out-of-sample predictions, 26,830 scored
after excluding 2,093 `null_team` rows (identical population D2 scored):

| condition | measured | required | result |
|---|---|---|---|
| margin: mean(LL_constant − LL_calibrated) | 0.00191 nats/map | ≥ 0.003 | **FAIL** |
| paired cluster bootstrap 95% CI excludes 0 | [−0.00046, 0.00500] | excludes 0 | **FAIL** |
| calibration slope (calibrated Elo) | 0.6569 | [0.9, 1.1] | **FAIL** |

**Overall: FAIL.** All three conditions were required (spec: "All three
conditions, not any"); none of the three individually cleared its bar.

Full metrics (`reports/d3_metrics.csv`):

| model | log loss | calibration slope | calibration intercept |
|---|---|---|---|
| constant | 0.693147 (= ln 2, exact) | n/a | n/a |
| **elo (calibrated, gated)** | 0.691241 | 0.6569 | 0.0460 |
| glicko (calibrated, diagnostic only) | 0.686439 | 0.9049 | 0.0314 |

## Calibrated Glicko — reported, not gated

Per the two choices registered 2026-08-03 (spec, before this code was
written), Elo is the primary and only gated candidate; calibrated Glicko is
computed and reported as a diagnostic and is **not** substituted here even
though its own numbers are more favourable: its margin against constant
(0.693147 − 0.686439 = 0.006708 nats/map) clears 0.003, and its slope 0.9049
sits just inside the [0.9, 1.1] band. Per spec, choosing the winner after
seeing results is the multiple-comparisons version of moving the margin, so
this is reported for the record and not acted on. The gate result above is
Elo's alone.

## What the numbers say

The in-fold correction did move Elo's calibration meaningfully — D2 measured
Elo's raw (uncalibrated) out-of-sample slope at 0.4448; the in-fold-fitted
correction lifted it to 0.6569 out-of-sample. That is real, substantial
progress toward 1.0, and it came with a genuine (if small) log-loss
improvement over the constant floor (0.00191 nats/map, versus D2's Elo being
0.0013142 nats/map *worse* than the floor uncalibrated). But 0.6569 is still
well outside the pre-registered [0.9, 1.1] band, and the margin and CI both
missed their own pre-registered bars independently. This is not a
borderline, arguable result on any of the three conditions — margin needed to
more than triple, and the slope needed to move by another ~0.25 with the CI
simultaneously tightening past zero.

The single-recent-hold-out approximation (spec: "a single recent hold-out is
the cheap approximation of \[a nested rolling backtest], chosen deliberately
and recorded as an approximation") is one plausible reason the correction
under-shoots: 20% of each fold's training window is a noisier, coarser
estimate of the true recalibration than a fully nested rolling estimate would
give, and it is fit once per fold rather than adapting within the fold's own
tournament. That is a property of the registered method, not a defect found
in the implementation — D2's own review already ruled out fold-construction,
leakage, and population-mismatch as explanations for the underlying
uncalibrated result, and this run reused that same, unmodified backtest
machinery (`rolling_folds`, `assert_fold_integrity`, `assert_no_leakage`,
`paired_differences`, `paired_cluster_bootstrap`) end to end.

## Consequence (per spec, stated in `reports/d3_gate.md` itself)

**The rung-3 public-ratings card ships, and no custom Bradley-Terry model is
built.** Two failed gates on the same data (D2's elo-vs-glicko forecast-value
gate, and this calibration gate) is evidence about the data, not a reason for
a third attempt with a looser bar.

## Test summary

- New: 21 tests in `tests/test_calibrate.py`, 6 in `tests/test_cli_d3.py`
  (some marked `@pytest.mark.slow`; final verification ran unfiltered).
- Full suite: 657 passed, 0 failed (`.venv/bin/python -m pytest -q`,
  unfiltered, ~6.5 minutes).
- `ruff check .`: clean.

## Mutation proofs (scratch copy at `/tmp/d3mut`, tracked source untouched —
`git status` confirmed clean before and after)

1. **Slope band boundary** (`slope_band[0] <= slope <= slope_band[1]` →
   `<`/`<`): `test_d3_gate_slope_band_boundary_is_inclusive` failed at
   `slope=0.9` under the mutant (`assert False is True`), passed against real
   code.
2. **Margin comparison** (`margin >= config.min_margin_nats` → `>`):
   `test_d3_gate_margin_boundary_is_inclusive` failed at the exact threshold
   under the mutant. This test was itself rewritten mid-task: an earlier
   version tried to engineer the fixture to land on the literal `0.003`
   through an `exp`/`log` round-trip, which is not guaranteed to be
   bit-exact and in fact did not discriminate the mutant on the first try
   (false pass). Rewritten to read back the fixture's own actual margin and
   compare it against itself plus `math.nextafter`, which is
   floating-point-safe and does discriminate the mutant.
3. **Leakage guard** (`fit_in_fold_calibration(train, ...)` →
   `fit_in_fold_calibration([r for r in ordered if r.league_id ==
   fold.league_id], ...)`, i.e. fitting on the fold's tournament instead of
   its training hold-out):
   `test_calibration_is_fitted_on_the_training_holdout_not_the_test_tournament`
   failed under the mutant (fitted slope swung from +0.795 to −0.784, matching
   contamination by the tournament's inverted-outcome signal instead of the
   hold-out's well-calibrated one) and passed against real code. The
   structural freshness test also caught this same mutation as a side effect.

## Concerns

- **The single-recent-hold-out approximation is registered as an
  approximation, and this result cannot distinguish "the correction is
  under-powered" from "there is a ceiling on how well this data can be
  calibrated."** The spec itself flags this ("a nested rolling backtest
  inside every fold would be the fully correct estimator"); a fully nested
  version was out of scope here (not requested, and would be a deviation from
  what was registered), but a reader should not conclude from this FAIL that
  no calibration approach could work — only that this pre-registered one
  does not clear the bar on this data.
- **The CI direction check (`ci_passed`) mirrors D2's `evaluate_gate` exactly**,
  including its "entirely negative" branch, which is exercised by a dedicated
  test but did not fire on the real run (the real CI straddles zero rather
  than sitting entirely below it).
- **Test I was least certain about going in:** the margin-boundary test,
  precisely because of the floating-point round-trip issue described above —
  it is the one place in this task where a first-draft test passed for the
  wrong reason (it happened to land a hair on the correct side of the
  literal by luck) and had to be rewritten after noticing the mutant slipped
  through. Recorded here rather than silently fixed, per this project's own
  established practice of naming vacuous or near-miss tests explicitly.
- I did not find anything wrong with the gate as registered. The margin and
  bootstrap method matching D2's exactly is a deliberate, sound design
  choice (spec: "so the two results are directly comparable"), and the
  slope band is unchanged from this spec's own D3 target set before any
  numbers existed.
