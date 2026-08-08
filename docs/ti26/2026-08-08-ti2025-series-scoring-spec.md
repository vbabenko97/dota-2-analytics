# S1: series-level scoring on TI 2025, Swiss stage and playoffs

**Registered 2026-08-08, before the producer existed and before any score was
computed.** Everything below is fixed here. Nothing in it may be revised once a
number exists.

## The question

Every out-of-sample result this project has is card-level: D4 scores one
assignment of sixteen teams to six buckets, which collapses the model's entire
output into a single integer between 0 and 16. That is one observation.

The same event contains **58 series with known winners**, all starting on or
after 2025-09-04, which is D4's own training cutoff. A model trained strictly
before that cutoff has never seen any of them. They have never been scored.

This asks the narrower and more answerable question: **do the calibrated
strengths predict who wins a series between two TI-level teams?**

## Why not the playoffs alone

The request that prompted this was to check the approach on the TI 2025
playoffs. Those are 14 series. Computed before writing this document, from the
binomial:

| population | needed to beat a coin flip, one-sided p<0.05 | power if the model is truly 65% |
|---|---|---|
| 14 playoff series | 11 of 14 (79%) | 22% |
| 58 TI 2025 series | 36 of 58 (62%) | 73% |

At n=14 even a genuinely 70%-accurate model reaches significance only 36% of the
time, so a null result would carry almost no information and a positive one would
mostly be luck. The playoffs are also the hardest population available -- eight
elite teams, closely matched -- so accuracy there sits near 50% almost regardless
of model quality.

**The headline is therefore all 58 series.** The 14 playoff series are reported
as a pre-registered subgroup, named here in advance so it cannot be selected
after the fact, and its weakness is stated wherever it is quoted.

## What is fixed, in advance

**Training window.** `data/processed/release-deep.sqlite` with
`--train-from 1710295805`, giving the same 17.7-month window matched to
production that D4-MW uses. Not "as much history as the store holds": that is the
misconfiguration D4-MW exists to correct, and repeating it here would flatter
this result by the same mechanism.

**Cutoff.** `truth.training_cutoff` from `config/ti2025_backtest.yaml`, unchanged.
Training rows are strictly before it. The producer must fail if any training row
falls at or after the cutoff, and if any row precedes `--train-from`.

**Calibration.** The slope refit on pre-cutoff rows only, exactly as `cli_d4`
step 4 computes it. The full-store slope must not be used: it is fitted on data
that includes the series being scored.

**Orientation.** For each series, the probability is computed for the
lexicographically smaller `team_id`, and the outcome is whether that team won.
Predicting for the model's own favourite would make Brier and log-loss depend on
a choice the model makes, which is not what they measure.

**Series length** is read from the data, not assumed: 57 Bo3 and one Bo5 grand
final. `series_win_prob` is Bo3-only today and must be generalised rather than
approximated.

**Metrics, all four, all reported whatever they say:**

- accuracy, defined as the model's favourite winning
- Brier score
- log loss
- calibration slope, from a logistic refit of outcome on the predicted logit

**Baseline** is a constant 0.5 predictor, on every metric. A calibration slope of
1.0 is perfect; below 1.0 is overconfidence, which is the specific failure the
design spec named -- "a model that says 65% when the truth is 80%" -- and the
population where it would show up most.

**Exclusions.** A series in which either team has no fitted strength is excluded
and the count reported. Exclusions must be reported even if zero.

**Subgroups, fixed here:** all 58; the 44 Swiss series; the 14 playoff series.
No others.

**One run.** No sweeping the window, no second seed, no re-running after a
disappointing number.

**It gates nothing.** No pass threshold, no promotion or demotion of the card.
It cannot alter the shipping card and is not a substitute for D2, D3 or D3b.

## What it can and cannot settle

It can settle whether the ratings carry series-level signal against a coin flip,
with roughly 73% power at a true accuracy of 65%. It is the largest genuinely
held-out sample this project has ever scored at the level the card depends on.

It cannot escape being one event. All 58 series share a patch, a venue, a
meta and a field, so they are not 58 independent draws from the population of
future matches, and the effective sample is smaller than 58 by an amount this
document cannot quantify.

It cannot escape design-time leakage: the architecture was chosen by people who
had already seen TI 2025.

It says nothing about the card. Series-level skill and card-level skill are
different quantities, and D4 already shows the card can score badly while the
ratings are doing something.

## Stop conditions

Stop and ask the owner if the reconstructed series count is not 58, if the Swiss
and playoff split is not 44 and 14, if the training window is not 17.7 months, or
if more than two series are excluded for missing strengths. Any of those means
the population is not the one specified here.
