<!-- ti26-run: 61c63f4aa32c573cdbc7e4abe48e08308801f1ff3cb8e5629a4ae446d5d22b6b manifest.json -->
# D4: TI 2025 card backtest

**D4 is a diagnostic. It cannot promote, demote or alter the shipping card.**

Status: DIAGNOSTIC -- not a gate; does not alter the shipping card

## Headline

- League: 18324
- Training maps (strict cutoff, before the event): 16958
- Observed score: 1/16 (random baseline 3.7500)
- Optimizer marginal objective (descriptive only, never evidence): 4.1637
- Evaluation-simulation mean score: 4.1601
- Percentile in the model's own distribution: 0.7% strictly below, 5.0% at or below
- Calibration slope, refit pre-cutoff: 0.2016
- Calibration slope, production (measured fresh, full store): 0.4051

## Sim-count sweep

| n_sims | seed | optimizer marginal objective | observed score |
|---|---|---|---|
| 2000 | 1 | 4.2250 | 4 |
| 2000 | 2 | 4.2300 | 1 |
| 2000 | 3 | 4.2360 | 3 |
| 20000 | 1 | 4.1591 | 4 |
| 20000 | 2 | 4.1814 | 5 |
| 20000 | 3 | 4.1670 | 2 |
| 250000 | 1 | 4.1637 | 1 |
| 250000 | 2 | 4.1673 | 2 |
| 250000 | 3 | 4.1622 | 2 |

## Random-card control

- Samples: 200000 (seed 1)
- Mean score: 3.7486

## Naive strength ladder (no simulation, no optimiser)

- Score: 2/16

## Rank diagnostics

- Spearman rho (predicted vs observed category order): 0.4781
- Exact: 1
- Off by one: 10
- Off by two or more: 5
- Mean absolute displacement: 1.2500

## Per-slot table

| team | predicted | observed | hit |
|---|---|---|---|
| Aurora Gaming | 0-4 | elim_loss | 0 |
| BOOM Esports | elim_loss | 1-4 | 0 |
| BoomBoys | elim_win | 4-1 | 0 |
| HEROIC | elim_loss | elim_win | 0 |
| Natus Vincere | elim_loss | 1-4 | 0 |
| Nigma Galaxy | elim_loss | elim_win | 0 |
| TEAM VISION | 4-1 | elim_win | 0 |
| Team Falcons | 4-0 | elim_win | 0 |
| Team Liquid | elim_win | elim_loss | 0 |
| Team Nemesis | elim_loss | 0-4 | 0 |
| Team Spirit | 4-1 | elim_loss | 0 |
| Team Tidebound | elim_win | 4-1 | 0 |
| Wildcard | 1-4 | elim_loss | 0 |
| Xtreme Gaming | elim_win | 4-0 | 0 |
| Yakult Brothers | 1-4 | elim_loss | 0 |
| Tundra Esports | elim_win | elim_win | 1 |
