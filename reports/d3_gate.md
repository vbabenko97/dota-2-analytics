# D3 calibration gate result

**Verdict: FAIL**

Pre-registered 2026-08-02/03 in `docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md` §II "D3 calibration gate", before any calibration code existed:

```
mean(LL_constant - LL_calibrated) >= 0.003 nats/map
AND paired cluster bootstrap 95% CI on that difference excludes 0
AND calibration slope of the calibrated model in [0.9, 1.1]
```

All three conditions, not any. Elo is the primary and only gated candidate (registered 2026-08-03); calibrated Glicko is reported below as a diagnostic and is never gated or substituted.

| condition | measured | required | result |
|---|---|---|---|
| margin: mean(LL_constant - LL_calibrated) | 0.00191 nats/map | >= 0.003 | FAIL |
| bootstrap 95% CI excludes 0 | [-0.00046, 0.00500] | excludes 0 | FAIL |
| calibration slope | 0.6569 | [0.9, 1.1] | FAIL |

**Overall: FAIL**

Interval method: cluster bootstrap over 191 tournaments. Maps compared: 26830.

Excluded from scoring: 2093 maps (2093 null_team)

Folds: 192 tournaments, 28923 out-of-sample maps.

## Metrics

| model | log loss | calibration slope | calibration intercept | n scored / n predictions |
|---|---|---|---|---|
| constant | 0.69315 | nan | nan | 26830 / 28923 |
| elo_calibrated | 0.69124 | 0.6569 | 0.0460 | 26830 / 28923 |
| glicko_calibrated_diagnostic | 0.68644 | 0.9049 | 0.0314 | 26830 / 28923 |

`elo_calibrated` is the gated candidate. `glicko_calibrated_diagnostic` is reported here only -- per spec (registered 2026-08-03), putting two candidates through one gate roughly doubles the false-pass probability, and choosing between them after seeing results is the multiple-comparisons version of moving the margin. It never gates and is never substituted if Elo fails.

## Consequence

**D3 stops here.** Reasons: margin 0.00191 < pre-registered 0.003 nats/map; bootstrap 95% CI [-0.00046, 0.00500] includes 0; calibration slope 0.6569 outside pre-registered [0.9, 1.1].

Per spec: **the rung-3 public-ratings card ships, and no custom Bradley-Terry model is built.** Two failed gates on the same data (D2's elo-vs-glicko forecast-value gate and this calibration gate) is evidence about the data, not a reason for a third attempt with a looser bar.
