# Calibrated-card report — production card from calibrated Glicko (D3b promotion)

Branch: `d3-rung3-public-ratings`. Implementation + tests commit `c07b2b1`
(before the real run); this document and the generated `reports/` artifacts
follow as a separate, docs-only commit, per this project's convention of
never committing generated `reports/` output (`.gitignore:21`) but always
committing the audit record of a real run.

## What this is

`src/ti26/cli_card.py` is the new production card runner. D3b
(`docs/audits/2026-08-03-d3-calibration-report.md`'s addendum) validated
calibrated Glicko's *per-map probability* calibration, not the card's scalar
per-team strengths. The card (`ti26.cli.main`) consumes strengths through
`series.map_win_prob(s_a, s_b) = sigmoid(s_a - s_b)`, and
`GlickoModel.strengths()` returns the raw, uncalibrated logit strength with
no correction applied. This module closes that gap and promotes calibrated
Glicko to the shipping strength source, replacing `cli_rung3.py` (public
ratings), which is untouched and remains the documented rung-3 fallback.

## Gate lineage (historical record, not measured by this module)

| gate | verdict | detail |
|---|---|---|
| D2 forecast-value (Elo vs Glicko) | **FAIL** | margin -0.00383 nats/map, CI [-0.02055, 0.00614] includes 0 |
| D3 calibration (Elo, primary gated candidate) | **FAIL** (all 3 conditions) | margin 0.00191 < 0.003; CI [-0.00046, 0.00500] includes 0; slope 0.6569 outside [0.9, 1.1] |
| D3b (multiplicity-corrected Glicko) | **PASS** | margin 0.00671 (≥0.003); 97.5% CI [0.00230, 0.01301] (excludes 0); slope 0.9049 (inside [0.9, 1.1], clearing the lower bound by only 0.0049) |

D3b was a **one-condition test**: Glicko's margin and slope were already
measured and already passing before that run; only the 97.5% bootstrap
interval was newly computed. It is therefore weaker evidence than a fresh
three-condition pass would have been. Building a production card from
calibrated Glicko is a separate decision, made here — D3b's own report
explicitly built no card.

## Correction factor: derivation, not a literal

`cli_card.derive_glicko_calibration_slope` re-runs the identical rolling
rolling-backtest machinery `cli_d2` used (`backtest.rolling_folds`,
`backtest.run_model`, `backtest.calibration`) against the **raw, uncalibrated
`GlickoModel`** — never a hardcoded constant — every time the module runs.
This is deliberately the raw model's own slope, not D3b's 0.9049: the card
consumes `GlickoModel.strengths()`, the raw model's own output, so the
correction that applies to it is that model's own calibration slope. D3b's
0.9049 corrects an already-in-fold-calibrated model's residual miscalibration
— a different, already-partially-corrected quantity — and would be the
wrong number to apply here.

**Measured this run: slope 0.4023, intercept 0.0849** (41,140 maps, 191
tournament folds, `min_train=500`, `glicko_tau=0.5` from
`config/d2_gate.yaml`). This reproduces D2's originally reported 0.4023
(`docs/audits/2026-08-02-d2-build-ledger.md`) to four decimal places on this
unchanged store — strong internal confirmation that the re-derivation is
correct, not a coincidence dressed up as one. Only the slope is applied to
strengths; the intercept corrects a Radiant/Dire order bias in the raw
model's predictions, which has no counterpart in a scalar, order-free team
strength.

**Resulting spread change:** raw strength spread 1.8518 → calibrated 0.7450
(×0.4023). Best-vs-worst implied map win probability: raw 0.8643 →
calibrated 0.6781. (These differ somewhat from the task brief's illustrative
reference numbers — 2.2597→0.9091, 0.9055→0.7128 — because those were
computed against a slightly different in-session state; the *slope* itself,
the actual correction factor, matches to four decimal places, which is the
figure that matters.)

## Approximation caveat

D3b validated a per-map probability; this applies that model's calibration
slope to per-team **strength differences** instead — a reasoned
approximation, not an exact transfer. Justified here because
`GlickoModel.expected_score`'s RD attenuation `g(phi)`, measured over the 16
configured rosters' 120 pairwise combined RDs, spans **0.9450 to 0.9784** (RD
itself spans 47.0 to 78.7) — close enough to 1 that `GlickoModel.strengths()`
(which omits `g(phi)`) tracks the raw model's own `expected_score` closely.
This is an **empirical property of this specific 16-team field**, not a
general guarantee: a field with more widely dispersed RDs (e.g. several
qualifier teams with almost no history) would make this approximation
materially worse, and any re-run against a different roster mix must
re-check this range rather than assume it holds.

## Seed-stability diagnostic

Solved under 3 seeds (1, 2, 3) at the production sim count (250,000).
**2 of 16 teams are not seed-stable — Team Vision and BoomBoys swap between
`4-0` and `4-1`** (seed 1: Team Vision `4-0`/BoomBoys `4-1`; seeds 2–3:
reversed). Every other slot is stable across all three seeds. This is a
single ambiguous boundary (the top slot), not independent noise scattered
across the card.

## The 16-team card (seed 1, 250k sims)

| category | teams |
|---|---|
| 4-0 | Team Vision |
| 4-1 | BoomBoys, Team Yandex |
| elim_win | Aurora Gaming, Nigma Galaxy, Team Falcons, Team Liquid, Team Spirit |
| elim_loss | 1win, LGD Gaming, OG, Vici Gaming, Xtreme Gaming |
| 1-4 | GamerLegion, HULIGANI |
| 0-4 | Team Resilience |

**Model-implied expected score: 4.6321** (descriptive only, per spec II —
computed from the model's own probabilities, never evidence of forecast
skill). Random baseline: 3.75.

## Observed recent form (diagnostic only, carried over from `cli_rung3`)

Reused directly from `public_ratings.observed_recent_form` (not
reimplemented). **11 consistent, 5 form ABOVE implied, 0 form BELOW
implied.** All five "above" deviations (Team Vision, Team Yandex, Team
Falcons, LGD Gaming, Team Resilience) point the same direction — none below
— which is at least consistent with genuine recent over-performance rather
than pure noise, but opposition strength is not controlled for in this
diagnostic (see `reports/card_provenance.md`), so it is reported, not acted
on.

## Test summary

- New: 13 tests in `tests/test_cli_card.py` — 3 pure-function unit tests
  (`apply_correction`, including a non-tautological re-centring check over a
  deliberately non-zero-mean subset), 1 direct `seed_stability` unit test
  using an exact strength tie (deterministic, not flaky), 2 refusal-path
  tests, and 7 end-to-end tests against a 20-roster synthetic store (16
  configured + 4 unconfigured "filler" rosters, the latter deliberately
  biased so the 16-team subset's raw mean is non-zero — otherwise
  re-centring would be a tautology).
- Full suite: 676 passed, 0 failed, unfiltered
  (`.venv/bin/python -m pytest -q`, ~6 minutes). `ruff check .`: clean.
- Mutation proofs (scratch copy at `/tmp/cardmut`, tracked source untouched —
  confirmed via `git status` before and after): omitting the correction
  (slope treated as 1.0) fails 2 tests; omitting re-centring fails 3 tests
  (including the dedicated non-tautological re-centring test); dropping one
  team from the 16-row CSV fails 5 tests (including the dedicated row-count
  test, independent of `ti26.cli`'s own downstream 16-strengths check).

## Concerns

- The approximation (per-map calibration slope applied to per-team
  strengths) rests on the measured `g(phi)` range being close to 1 for
  *this* field. That holds here but is not guaranteed to hold for a
  differently-composed field (e.g. more qualifier teams with thin history);
  the report states the measured range explicitly so this is checkable, not
  assumed, on every future re-run.
- The seed-stability check used only 3 seeds (the task's stated minimum).
  With more seeds, more boundary pairs might show ambiguity beyond the
  Team Vision/BoomBoys top slot found here — `--stability-seeds` accepts an
  arbitrary comma list for a deeper check.
- D3b's own PASS is comparatively weak evidence (one-condition test, slope
  clearing its band by only 0.0049) — this module's report states that
  plainly rather than treating "D3b PASS" as a strong endorsement.
