# D4: TI 2025 card backtest

**D4 is a diagnostic. It cannot promote, demote or alter the shipping card.**

Status: DIAGNOSTIC -- not a gate; does not alter the shipping card

## Headline

- League: 18324
- Training maps (strict cutoff, before the event): 44097
- Observed score: 4/16 (random baseline 3.7500)
- Optimizer marginal objective (descriptive only, never evidence): 4.9161
- Evaluation-simulation mean score: 4.9230
- Percentile in the model's own distribution: 23.1% strictly below, 43.0% at or below
- Calibration slope, refit pre-cutoff: 0.4352
- Calibration slope, production (measured fresh, full store): 0.5145

## Sim-count sweep

| n_sims | seed | optimizer marginal objective | observed score |
|---|---|---|---|
| 2000 | 1 | 4.8825 | 4 |
| 2000 | 2 | 5.0085 | 4 |
| 2000 | 3 | 4.9065 | 4 |
| 20000 | 1 | 4.9066 | 4 |
| 20000 | 2 | 4.9267 | 4 |
| 20000 | 3 | 4.9233 | 4 |
| 250000 | 1 | 4.9161 | 4 |
| 250000 | 2 | 4.9234 | 4 |
| 250000 | 3 | 4.9257 | 4 |

## Random-card control

- Samples: 200000 (seed 1)
- Mean score: 3.7486

## Naive strength ladder (no simulation, no optimiser)

- Score: 4/16

## Rank diagnostics

- Spearman rho (predicted vs observed category order): 0.5478
- Exact: 4
- Off by one: 9
- Off by two or more: 3
- Mean absolute displacement: 1.0000

## Per-slot table

| team | predicted | observed | hit |
|---|---|---|---|
| BoomBoys | elim_win | 4-1 | 0 |
| HEROIC | elim_loss | elim_win | 0 |
| Natus Vincere | elim_loss | 1-4 | 0 |
| Nigma Galaxy | elim_loss | elim_win | 0 |
| TEAM VISION | 4-1 | elim_win | 0 |
| Team Falcons | 4-1 | elim_win | 0 |
| Team Liquid | elim_win | elim_loss | 0 |
| Team Nemesis | 1-4 | 0-4 | 0 |
| Team Spirit | 4-0 | elim_loss | 0 |
| Team Tidebound | elim_win | 4-1 | 0 |
| Wildcard | 0-4 | elim_loss | 0 |
| Xtreme Gaming | elim_win | 4-0 | 0 |
| Aurora Gaming | elim_loss | elim_loss | 1 |
| BOOM Esports | 1-4 | 1-4 | 1 |
| Tundra Esports | elim_win | elim_win | 1 |
| Yakult Brothers | elim_loss | elim_loss | 1 |
