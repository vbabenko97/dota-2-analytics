# Data health

**DIAGNOSTIC -- no threshold, gates nothing, cannot alter the card**

Store: `data/processed/release-20260802T165535Z.sqlite`, 41140 maps over 539.9 days.

## Headline

- Maps at the forecast target's own tier (`premium`): **0.4%** of the corpus, from **1 distinct event(s)** (league ids: 18324).
- Maps on the newest patch (`7.41`): **16.9%** of the corpus.
- Current-roster volume across the field: **27 to 376 maps**, a 13.9x spread.
- Rating deviation across the field: **41.2 to 76.9**, a 1.86x spread.
- Teams under 50 maps on their current roster: **3**.
- Teams with zero `premium` maps on their current roster: **15**.

## Tier mix

| tier | maps | share |
|---|---|---|
| professional | 22198 | 54.0% |
| excluded | 18798 | 45.7% |
| premium | 144 | 0.4% |

## Patch mix (most recent first)

| patch | maps | share |
|---|---|---|
| 7.41 | 6958 | 16.9% |
| 7.40 | 7943 | 19.3% |
| 7.39 | 17867 | 43.4% |
| 7.38 | 7299 | 17.7% |
| 7.37 | 1073 | 2.6% |

## Recency

| window | maps | share of corpus |
|---|---|---|
| last 30 days | 418 | 1.0% |
| last 60 days | 1340 | 3.3% |
| last 90 days | 3809 | 9.3% |
| last 180 days | 10963 | 26.6% |
| last 365 days | 26994 | 65.6% |

## Rows the model declines to rate

- `null_team`: 2127 (5.2%)
- `bad_roster`: 0 (0.0%)

## The field, by current roster

Sorted by volume, thinnest first. `raw_strength` is pre-calibration and zero-centred over every roster in the store, not over these sixteen.

| team | roster maps | RD | raw strength | `premium` maps | days idle |
|---|---|---|---|---|---|
| OG | 27 | 67.8 | 2.139 | 0 | 0.2 |
| Nigma Galaxy | 30 | 73.9 | 2.300 | 0 | 0.2 |
| Team Resilience | 38 | 76.9 | 1.403 | 0 | 0.1 |
| Team Spirit | 63 | 57.7 | 2.636 | 0 | 17.1 |
| Team Yandex | 71 | 52.7 | 3.039 | 0 | 14.2 |
| Team Vision | 80 | 50.4 | 3.195 | 0 | 13.9 |
| GamerLegion | 82 | 52.6 | 1.574 | 0 | 0.1 |
| Vici Gaming | 99 | 48.1 | 1.807 | 0 | 1.2 |
| HULIGANI | 132 | 47.4 | 1.549 | 0 | 1.0 |
| Aurora Gaming | 144 | 46.0 | 2.519 | 0 | 18.1 |
| LGD Gaming | 164 | 42.9 | 2.187 | 0 | 1.0 |
| Xtreme Gaming | 233 | 44.1 | 1.900 | 0 | 0.8 |
| Iron Wing | 234 | 43.6 | 2.192 | 0 | 0.0 |
| Team Liquid | 255 | 44.8 | 2.351 | 0 | 0.8 |
| BoomBoys | 316 | 41.2 | 2.599 | 0 | 1.0 |
| Team Falcons | 376 | 44.3 | 2.627 | 29 | 0.0 |
