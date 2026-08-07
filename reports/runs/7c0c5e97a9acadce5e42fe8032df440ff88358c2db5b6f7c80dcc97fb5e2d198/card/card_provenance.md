<!-- ti26-run: 7c0c5e97a9acadce5e42fe8032df440ff88358c2db5b6f7c80dcc97fb5e2d198 manifest.json -->
# Production card provenance -- calibrated Glicko (D3b)

**Strength source: calibrated Glicko.** This replaces `cli_rung3.py` (public ratings) as the shipping source, per the D3b gate PASS below. `cli_rung3.py` is unchanged and remains the documented rung-3 fallback.

## Gate lineage

- **D2 FAIL** (ci [-0.02037, 0.00649], must exclude 0.0: FAIL; margin -0.00356 against 0.003: FAIL). Maps compared: 26830, interval method: cluster bootstrap over 191 tournaments. Registered: docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md section II, D2 forecast-value gate.
- **D3 FAIL** (ci [-0.00046, 0.00500], must exclude 0.0: FAIL; margin 0.00191 against 0.003: FAIL; slope 0.65690 against band [0.9, 1.1]: FAIL). Maps compared: 26830, interval method: cluster bootstrap over 191 tournaments. Registered: docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md section II, D3 calibration gate (Elo, sole gated candidate).
- **D3B PASS** (ci [0.00240, 0.01290], must exclude 0.0: PASS; margin 0.00673 against 0.003: PASS; slope 0.90571 against band [0.9, 1.1]: PASS). Maps compared: 26830, interval method: cluster bootstrap over 191 tournaments. Registered: docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md section II, D3b multiplicity-corrected Glicko gate.

Read from `reports/runs/7c0c5e97a9acadce5e42fe8032df440ff88358c2db5b6f7c80dcc97fb5e2d198/frozen_gate_results.json` (frozen-gate artifact, source revision `d62fb41f4b9158928a79df76cd92e6c86ff4b866`). Every value above is that artifact's; this module restates none of them from memory.

Building the production card from calibrated Glicko is a SEPARATE decision made here, not made by the D3b gate run itself -- D3b's own report states explicitly that no card was built in that run.

## Correction factor

**Slope: 0.4051** (intercept 0.0849, NOT applied -- see below). Measured THIS run by re-running the identical rolling-backtest machinery `cli_d2` used (`backtest.rolling_folds`, `backtest.run_model`, `backtest.calibration`) against the RAW, uncalibrated `GlickoModel` over the full store (41140 maps) -- never a hardcoded literal, so this cannot go stale against re-ingested data. On the original D2 snapshot this measurement reported **0.4023** (docs/audits/2026-08-02-d2-build-ledger.md); a close match here is a consistency check, not a requirement this run must hit exactly.

Only the slope is applied to strengths. The intercept corrects a Radiant/Dire *order* bias in the raw model's predictions -- it has no counterpart in a scalar, order-free team strength, so transferring it onto `GlickoModel.strengths()` would not correct anything real.

**Resulting spread change:** raw strength spread 1.7918 -> calibrated 0.7258. Best-vs-worst implied map win probability: raw 0.8572 -> calibrated 0.6739.

## Approximation caveat -- stated plainly

D3b validated a PER-MAP probability's calibration. This module applies that model's calibration slope to PER-TEAM STRENGTH differences instead -- a reasoned approximation, not an exact transfer of what was validated.

What is measured: `GlickoModel.expected_score`'s RD attenuation `g(phi)`, over these 16 rosters' pairwise combined RDs, spans **0.9472 to 0.9826** (RD itself spans 41.2 to 76.9). `GlickoModel.strengths()` omits `g(phi)` entirely, so the narrower that range sits around 1, the less the omission can do.

What is NOT measured: this range is not the error the approximation makes. The quantity that would settle it -- the discrepancy between the pairwise probabilities implied by these scalar strengths and the ones `expected_score` returns -- is not computed by this run, so no claim is made here about how closely the two track. **The range is also an empirical property of this specific 16-team field, not a general guarantee**: a field with widely dispersed RDs (several qualifier teams with almost no history, say) would widen it, and a re-run against a different roster mix must re-read this number rather than assume it.

## Seed-stability diagnostic

The card was solved under 3 seeds (1, 2, 3) at the production sim count (250000), so an ambiguous slot is visible rather than hidden behind one lucky seed.

**6 of 16 team(s) are NOT seed-stable:**

| team | seed 1 | seed 2 | seed 3 |
|---|---|---|---|
| GamerLegion | 1-4 | 0-4 | 1-4 |
| HULIGANI | 1-4 | 1-4 | 0-4 |
| Team Falcons | elim_win | elim_win | 4-1 |
| Team Resilience | 0-4 | 1-4 | 1-4 |
| Team Spirit | 4-1 | 4-0 | elim_win |
| Team Vision | 4-0 | 4-1 | 4-0 |

## Observed recent form (diagnostic only)

Reused directly from `public_ratings.observed_recent_form` (not reimplemented): each team's implied map win rate (from the calibrated strengths above) against what its CURRENT roster actually did over its recent maps. Diagnostic only -- opposition strength is not controlled, and this never overrides a strength or the card on its own.

| team | strength | implied | observed | n | 95% Wilson CI | verdict |
|---|---|---|---|---|---|---|
| Team Vision | 0.382 | 0.600 | 0.762 | 80 | [0.659, 0.842] | form ABOVE implied |
| Team Yandex | 0.319 | 0.584 | 0.762 | 42 | [0.615, 0.865] | form ABOVE implied |
| Team Spirit | 0.156 | 0.541 | 0.651 | 63 | [0.528, 0.757] | consistent |
| Team Falcons | 0.152 | 0.540 | 0.719 | 57 | [0.592, 0.819] | form ABOVE implied |
| BoomBoys | 0.141 | 0.537 | 0.639 | 72 | [0.524, 0.740] | consistent |
| Aurora Gaming | 0.109 | 0.529 | 0.586 | 70 | [0.469, 0.694] | consistent |
| Team Liquid | 0.041 | 0.511 | 0.532 | 62 | [0.410, 0.651] | consistent |
| Nigma Galaxy | 0.020 | 0.505 | 0.567 | 30 | [0.392, 0.726] | consistent |
| Iron Wing | -0.024 | 0.494 | 0.437 | 71 | [0.327, 0.552] | consistent |
| LGD Gaming | -0.026 | 0.493 | 0.621 | 66 | [0.501, 0.729] | form ABOVE implied |
| OG | -0.045 | 0.488 | 0.630 | 27 | [0.442, 0.785] | consistent |
| Xtreme Gaming | -0.142 | 0.463 | 0.423 | 52 | [0.299, 0.558] | consistent |
| Vici Gaming | -0.180 | 0.453 | 0.525 | 61 | [0.402, 0.645] | consistent |
| GamerLegion | -0.274 | 0.428 | 0.467 | 45 | [0.329, 0.609] | consistent |
| HULIGANI | -0.284 | 0.425 | 0.487 | 39 | [0.339, 0.638] | consistent |
| Team Resilience | -0.344 | 0.410 | 0.714 | 14 | [0.454, 0.883] | form ABOVE implied |

**11 consistent, 5 form ABOVE implied, 0 form BELOW implied**.

## Card

Status: generated from calibrated Glicko strengths (16 teams).
Optimizer marginal objective: 4.5903 -- the sum of the model's own estimated category marginals under this assignment. Descriptive only, never evidence of skill. It is NOT the evaluation-simulation mean score, which scores this card against independently seeded simulated outcomes and is a different quantity.
