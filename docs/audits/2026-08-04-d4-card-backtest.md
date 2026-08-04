# D4: the TI 2025 card backtest — a negative result

**Date:** 2026-08-04
**Status:** DIAGNOSTIC, registered as such before it ran. It does not alter the shipping card.
**Registration:** `9ceb28e`, spec §II "D4" — committed before `observed.py` or `cli_d4.py` existed and before any score was computed.

## Headline

On the one held-out event this project can test, **the card pipeline scored 1/16 against a random baseline of 3.75**, and scored *worse the harder it optimised*.

| | score /16 |
|---|---|
| Production settings (250k sims, seed 1) | **1** |
| Production settings, seeds 1/2/3 | 1, 2, 1 (mean 1.33) |
| Naive strength ladder, no simulation at all | 2 |
| Random assignment (200k samples, measured) | mean **3.7504** |
| The model's own expectation for its card | 4.1675 |

## What was tested

TI 2025's Swiss stage (OpenDota `league_id` 18324): 16 teams, 108 maps, 44 Bo3 series, 2025-09-04→07, separated from the playoffs by a 3-day gap.

Everything was refit under a strict `start_time < 2025-09-04` cutoff — 16,958 maps, 207 days of history. That includes the calibration slope: re-using production's 0.4023 (measured over the full store) would have leaked the event's own maps into the correction applied to it.

**The refit slope came out at 0.2009**, half the production value. Under 207 days of history the raw model is roughly 5× too confident rather than 2.5×. The pre-cutoff conditions were materially worse than TI 2026's, which is a reason to discount this result — but not a reason to dismiss it, since the direction of the error is the same.

The observed outcome was re-derived from the store and cross-checked against the frozen `config/ti2025_backtest.yaml` on every record, advancement flag and category; `derive_outcome` raises on any disagreement. Both checks agree on all 16 teams. No roster was prior-driven, so this is not a missing-data artifact.

## The finding that matters more than the score

| n_sims | scores (seeds 1,2,3) | mean | model's own expectation |
|---|---|---|---|
| 2,000 | 5, 3, 3 | 3.67 | ~4.24 |
| 20,000 | 3, 2, 2 | 2.33 | ~4.17 |
| 250,000 | 1, 2, 1 | 1.33 | ~4.17 |

The model considers all nine of these cards equally good. Against reality they get monotonically worse as the Monte Carlo resolution rises. That is the signature of a **misspecified model**: optimising more precisely against a wrong objective carries you further from the truth, and the optimiser cannot know it because its own expected score barely moves.

This also reframes the determinism work done earlier the same day (`67198ee`, `cf85c14`). Those fixes were correct — the card should not depend on display names or on differences below Monte Carlo resolution — but they bought *reproducibility*, not accuracy. Making a misspecified optimum stable does not make it right.

## Where the misses came from

Ordering correlation between predicted and observed category rank: **+0.375**. There was real signal. It was not enough.

- off by 0 categories: **1** team
- off by exactly 1: **10** teams
- off by 2 or more: **5** teams
- mean absolute category distance: **1.25**

Exact-match scoring pays nothing for adjacent, so a card that is broadly right and locally wrong scores near zero. Every extreme was wrong in both directions: predicted 4-0 was Team Falcons (actually 4-2); the actual 4-0 was Xtreme Gaming (predicted `elim_win`). Predicted 0-4 was Aurora Gaming (actually 3-3, eliminated); the actual 0-4 was Team Nemesis (predicted `elim_loss`). The single hit was Tundra Esports at `elim_win`.

The worst single miss was Team Spirit: predicted 4-1, finished 2-4.

## Controls

**Random cards, measured rather than assumed.** 200,000 random capacity-respecting assignments scored against the same outcome: mean 3.7504, sd 1.641, against the theoretical Σk²/16 = 3.75. The agreement to four significant figures is the check that the scoring code is correct — it was the first thing suspected when 1/16 appeared, and it is not the explanation.

For calibration of how unusual 1/16 is: a *random* card scores ≤1 on this outcome 7.50% of the time, and ≤2 22.84% of the time. So the pipeline's score is not astronomically improbable even for a coin flip; the gap between 1.33 and 3.75 is roughly 1.5 sd of the random distribution.

**Naive strength ladder** — assign categories straight down the strength order, no simulation, no optimiser: **2/16**. It beat the fully-optimised card. So the Monte Carlo layer is not the sole culprit; the underlying strengths were themselves too weakly ordered for this event.

## What this does and does not establish

**Does not:** establish that the pipeline is worse than random. One event is one sample, the registration said so before the number existed, and the random control shows a single score of 1 is within reach of chance.

**Does:** remove the last remaining reason to believe the card has demonstrated forecast value. The evidence chain is now uniformly weak in the same direction — D2's forecast-value gate failed, no rating model beat the constant floor, D3's Elo gate failed all three conditions, D3b passed only as a one-condition test clearing its slope band by 0.0049, and the sole card-level test available came back below random. Nothing in that chain is individually fatal. Nothing in it is positive either.

**Leakage that remains, restated.** The cutoff kept this event's outcomes out of the training data. It did not keep them out of the method: Glicko-over-Elo, τ, and the gate thresholds were all chosen using rolling backtests whose folds include September 2025. If anything that biases this test *optimistically*, which makes the negative result harder to explain away.

## Deviations from the registration, disclosed

The registration named four outputs: score, baseline, percentile, per-slot table. All four are in `reports/d4_card_backtest.json`.

The sim-count sweep and the two controls were **added after seeing the first score**, prompted by a low-sim smoke run that scored 5/16 where the production run scored 1/16. They are diagnostics about the diagnostic — they do not change the target, the cutoff, or the scoring rule, all of which were frozen in `9ceb28e`. Recorded here rather than presented as pre-planned.

## Consequence

Per the registration, none for the shipping card: it remains the one D3b selected. What changes is what can honestly be claimed for it. The card's own 4.63 expected score was already labelled descriptive-only in every report; this is the first measurement showing what that label is worth.
