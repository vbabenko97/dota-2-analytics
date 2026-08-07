# D4-MW: the card backtest with a training window matched to production

**Registered 2026-08-07, before the deeper snapshot was fetched and before any
score was computed.** This document exists so that the result cannot be tuned
after the fact. Everything below is fixed here; nothing in it may be revised once
a number exists.

## Why re-run a test that already has an answer

D4 scored the pipeline at 1/16 against a 3.75 random baseline. That result stands
and is not withdrawn. But D4 trains on maps before 2025-09-04, and the pinned
snapshot only reaches back to 2025-02-08, so it had **16,958 maps over 6.8
months** where production has **41,140 over 17.7**. It tested the procedure on
41% of the data.

The gap is not cosmetic. The calibration slope refit on pre-cutoff data is
0.2016; on the full store it is 0.4051. The backtest model had to be squeezed
twice as hard to be honest about its own confidence, which is the seven-month
model saying it knows considerably less than the eighteen-month one.

This is a misconfiguration, not an unwelcome result. The distinguishing test is
that it can be stated without reference to the score: *the backtest trains on 41%
of production's data.* That sentence would be equally true if D4 had returned
12/16.

## What is fixed, in advance

**Training window.** 17.7 months before the TI 2025 cutoff, matching production's
window before TI 2026. NOT "as much history as the ingest returns" — maximising
the window after seeing results is the move this document exists to prevent. The
ingest therefore needs roughly 30 months from today; any surplus beyond the
matched window is discarded by the cutoff filter, not used.

**Everything else is D4's, unchanged:** `--card-sims 250000`, `--card-seed 1`,
`--eval-seed 90001`, `--min-train 500`, the same `config/ti2025_backtest.yaml`
truth file, the same `config/ti2026_rules.yaml`.

**One run.** No sweeping the window, no trying a second seed, no re-running after
a disappointing number.

**Both results published,** side by side, with the original 1/16 stated first.

**It is not D4.** It is a post-hoc re-specification with a stated reason. It
gates nothing, it cannot promote or demote the card, and it has no pass
threshold. D4's registration is not transferable to it: D4 was registered before
its own code existed, and this cannot be.

## What it can and cannot settle

It can settle whether the 1/16 is confounded by data poverty. If the matched
window scores materially higher, the original result says less about the pipeline
than it appeared to. If it scores the same, the question is closed.

It cannot fix design-time leakage — the architecture was chosen by people who had
already seen TI 2025 — and it cannot escape n=1, because TI 2025 is the only
event that has ever run this format. There is no second sample to be had at any
ingest depth.

It also cannot make the pipeline useful if it is not. The ladder comparison has
since shown that at the production seed the card IS a strength sort, so what a
higher score would credit is the rating work, not the simulation.

## Preconditions

- The deeper snapshot is committed before anything is generated from it, exactly
  as the pinned one was.
- Production stays on the pinned 18-month snapshot for the lock. The deep
  snapshot is for this measurement only; moving the shipping card onto it days
  before the deadline as a side effect of an experiment is not acceptable.
- `explorer_query` is the only network path used.

## Stop conditions

Stop and ask the owner if the ingest returns fewer than 17.7 months before the
TI 2025 cutoff, if the reconstructed TI 2025 outcome stops matching the frozen
truth file, or if the deeper store changes the observed Swiss records at all.
Any of those means the comparison is not the one specified here.
