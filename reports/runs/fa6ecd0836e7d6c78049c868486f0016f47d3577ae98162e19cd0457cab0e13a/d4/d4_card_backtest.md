<!-- ti26-run: fa6ecd0836e7d6c78049c868486f0016f47d3577ae98162e19cd0457cab0e13a manifest.json -->
# D4: TI 2025 card backtest

**D4 is a diagnostic. It cannot promote, demote or alter the shipping card.**

Status: DIAGNOSTIC -- not a gate; does not alter the shipping card

## Headline

- League: 18324
- Training maps (strict cutoff, before the event): 16958
- Observed score: 2/16 (random baseline 3.7500)
- Optimizer marginal objective (descriptive only, never evidence): 4.1574
- Evaluation-simulation mean score: 4.1525
- Percentile in the model's own distribution: 5.1% strictly below, 17.1% at or below
- Calibration slope, refit pre-cutoff: 0.2016
- Calibration slope, production (measured fresh, full store): 0.4051

## Sim-count sweep

| n_sims | seed | optimizer marginal objective | observed score |
|---|---|---|---|
| 2000 | 1 | 4.1910 | 5 |
| 2000 | 2 | 4.2010 | 2 |
| 2000 | 3 | 4.2030 | 2 |
| 20000 | 1 | 4.1776 | 2 |
| 20000 | 2 | 4.1781 | 2 |
| 20000 | 3 | 4.1785 | 3 |
| 250000 | 1 | 4.1574 | 2 |
| 250000 | 2 | 4.1601 | 2 |
| 250000 | 3 | 4.1635 | 2 |

## Random-card control

- Samples: 200000 (seed 1)
- Mean score: 3.7486

## Naive strength ladder (no simulation, no optimiser)

- Score: 2/16

## Rank diagnostics

- Spearman rho (predicted vs observed category order): 0.3997
- Exact: 2
- Off by one: 9
- Off by two or more: 5
- Mean absolute displacement: 1.2500

## Per-slot table

| team | predicted | observed | hit |
|---|---|---|---|
| BOOM Esports | elim_loss | 1-4 | 0 |
| BoomBoys | elim_win | 4-1 | 0 |
| HEROIC | elim_loss | elim_win | 0 |
| Natus Vincere | elim_loss | 1-4 | 0 |
| Nigma Galaxy | 0-4 | elim_win | 0 |
| TEAM VISION | 4-0 | elim_win | 0 |
| Team Falcons | 4-1 | elim_win | 0 |
| Team Liquid | elim_win | elim_loss | 0 |
| Team Nemesis | elim_loss | 0-4 | 0 |
| Team Spirit | 4-1 | elim_loss | 0 |
| Team Tidebound | elim_win | 4-1 | 0 |
| Wildcard | 1-4 | elim_loss | 0 |
| Xtreme Gaming | elim_win | 4-0 | 0 |
| Yakult Brothers | 1-4 | elim_loss | 0 |
| Aurora Gaming | elim_loss | elim_loss | 1 |
| Tundra Esports | elim_win | elim_win | 1 |
