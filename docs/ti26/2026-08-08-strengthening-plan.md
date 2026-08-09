# Strengthening plan, 2026-08-08

How to make this project predict better, ranked by expected gain per unit of
work.

**Maturity: production.** The owner's decision on 2026-08-08 is that TI 2026 is
the first application of an ongoing forecasting system, not the point of it. That
changes the ranking below substantially: work that only pays off across seasons
(deeper history, drift monitoring, retraining cadence) is in scope, where a
one-shot project would cut all of it.

**Relationship to existing documents.** The
[design spec](../superpowers/specs/2026-08-01-ti2026-forecast-design.md) already
follows the same 12-section ML design template and remains the system of record
for what the pipeline *is*. This document says what should change and why, and
is organised against those sections so the two can be read side by side. Every
weakness referenced by number lives in
[known weaknesses](2026-08-08-known-weaknesses.md).

Assumptions that are not established by the repository are tagged inline as
`[ASSUMPTION: ...]`.

---

# Part A — Before the compendium locks (12-13 August)

Four to five days.

**The original headline of this section was "nothing in Part A will make the
card more accurate", and it was overtaken within hours.** Valve published the
TI 2026 Group Stage Rules during 2026-08-08. They differ from TI 2025's in four
places, the engine was wrong on all four, and correcting them changes the card.

That is not a breach of pre-registration discipline, and the distinction
matters enough to state: pre-registration exists to stop a result being shopped
for. Updating an INPUT when the ground truth is published is the opposite
failure to guard against — an engine that knowingly models the wrong
tournament, held in place by a rule meant to prevent cheating.

So the ranking below changed. Rules reconciliation first, everything else after.

## A1. DONE — reconcile the engine against the published TI 2026 rules

**Problem:** [weakness §3](2026-08-08-known-weaknesses.md#3-the-rules-engine-modelled-the-wrong-year-and-the-format-changed).
Valve's TI 2026 Group Stage Rules were fetched on 2026-08-08 and archived
verbatim in [the fetched rules doc](2026-08-08-ti2026-rules-fetched.md). The
engine differed in four places, all of them introduced that morning by aligning
to a transcript of TI 2025's rules while 2026's were still unpublished:

1. ranking criteria 3 and 4 transposed;
2. Average Game Duration missing as criterion 6;
3. Round 5's max-distance-when-loser-eliminated modification deleted;
4. the elimination round modelled as distance maximisation rather than as the
   sequential choice the 2026 rules describe.

All four are corrected, with the provenance tags now naming the fetch and its
date. `pair_elimination` is retained for `cli_pairing_check`, which validates
against TI 2025 and therefore needs TI 2025's rule.

**This supersedes the previous A1**, which proposed DELETING the duration
machinery as dead code. It was measurably inert only because it had been
removed from the tiebreak hours earlier; TI 2026 lists it as criterion 6. Had
that item been executed it would have hard-coded the defect.

**What survives of the old A1:** `cli_d2` warns when the fitted duration
parameters drift from config, the runbook never mentions it, and a fresh
snapshot on lock day will probably trip it. That is now a runbook line, not a
deletion.

**Done when:** the card regenerates under the corrected rules and the runbook
explains the duration warning.

## A2. DONE — the stale pairing justification in config now cites an artifact

**Problem:** [weakness §3d](2026-08-08-known-weaknesses.md#3d-fixed--the-configs-own-justification-for-the-pairing-tag-was-stale).
`base_pairing_preference: refuted_immaterial` was justified by a bare count
written on 2026-08-07, before three separate engine corrections.

**Done:** the producer's output is committed at
[`reports/pairing_check/pairing_check.json`](../../reports/pairing_check/pairing_check.json)
and the comment cites it, stating no count of its own.

**The tag did NOT become `corroborated_immaterial`, and this entry's reasoning
for expecting that was wrong.** It rested on the producer reporting a
comfortable majority of buckets agreeing. That headline counts buckets in which
every legal matching scores the same ranking distance — where the preference
cannot be wrong and agreement is not evidence. On the buckets where the
criterion actually decides something, agreement is close to a coin flip, and the
original `refuted` verdict survives.

The producer now emits both denominators (`summary.where_distance_discriminates`)
so the inflated one cannot be read by accident, which is the same defect as A3's
in a different field.

## A3. DONE — `cli_pairing_check` no longer misrepresents its own result

**Problem:** [weakness §3b](2026-08-08-known-weaknesses.md#3b-the-ti-2025-diagnostic-and-why-its-verdict-field-misleads).

`cli_pairing_check` emitted

```
engine_reproduces_the_real_bracket: false
pairs_shared_with_engine: <count>
```

with no indication of two things a reader needs. Part of the discrepancy has a
known, documented, external cause — the unannounced two-series-per-day
constraint of 6 September, which forced HEROIC onto Yakult. And the check
measures **TI 2025's** elimination rule, which TI 2026 has replaced entirely, so
a `false` here says nothing at all about the
shipping engine.

This entry has been through two wrong versions, both caused by reading that
`false` without either piece of context: first "the rule is refuted", then
"measure the reachable minimum before deciding whether to flip it". A producer
emitting a true number that reliably causes a false inference is the same class
of problem as an unbound number and deserves the same treatment.

**Done:** the output carries a `known_deviations` entry naming the constraint,
the teams it moved and the document that sources it; a `rule_year` block naming
which tournament's rule each check models; and, per seed, the pairs that differ
in each direction plus a computed `distance_shortfall`.

**One thing came out differently from the plan.** This entry proposed that
`known_deviations` state the constraint's distance cost. It does not, because
that cost was measured under a ranking that has since been corrected and it
moved. The deviation is named and sourced; every number beside it is computed by
the run.

**And the fix uncovered a live defect.** The producer had not run at all since
`106c409` on 2026-08-08: restoring Average Game Duration as the sixth ranking
criterion put back a criterion whose duration source in this producer had been
deleted with it, so it raised `DurationUnavailableError` on the TI 2025 store,
where three teams tie through five criteria. It is not a release producer and no
test built a bracket with a surviving tie, so nothing noticed. Fixed, with a
test that builds one.

That is also why §3b's and the format-rules document's figures moved: every
pairing-check number published before 2026-08-09 came from the engine state
between `23beac3` and `106c409`.

## A4. Run the near-lock runbook

[`docs/ti26/near-lock-runbook.md`](near-lock-runbook.md), all ten steps,
including step 3's field re-confirmation against a source outside
`explorer_query` regardless of the 2026-08-07 result. Fresh snapshot, full
regeneration, verify the bundle.

**Effort:** ~2 hours including ingest.

## A5. DONE — the recent-data collapse is real, not ingest lag

**Problem:** [weakness §2d](2026-08-08-known-weaknesses.md#2d-the-freshest-evidence-is-the-thinnest).
The corpus holds 76 maps/day overall and 14/day across the last 30. That is
either a real pre-major slowdown or the incomplete tail every snapshot has, and
the two call for opposite responses.

**Answered by `cli_snapshot_lag`**, which counts the same calendar window across
the two committed snapshots rather than each snapshot's own recent window —
`cli_data_health` cannot do this, because its recency windows are measured from
each store's own last map, so running it twice compares two different windows.

Of 421 maps in the tail, 3 were absent from the older snapshot, all of them on
its single final day of coverage. The tail rate on the newer snapshot is 14.0
maps/day against 76.2 over the whole window, a ratio of 0.18, and 0 maps were
dropped between the two. Lag is real, confined to about one day, and far too
small to explain the gap.

**Consequences, both now in the runbook:** taking the lock-day snapshot later
buys roughly one day of completeness, so step 1 should not be delayed for it;
and the thin recent evidence is a fact the forecast carries rather than a defect
to be snapshotted away. The runbook also re-runs the comparison against the new
snapshot and stops on any non-zero `dropped_maps`.

**Bound on the claim:** the two snapshots are 5.1 days apart, which is the
longest backfill this comparison can observe. The producer emits that as
`observation_horizon_days` rather than leaving it implicit.

## A6. Condition on the group draw the moment it is published

Already built (`--groups`). Add the flag to the release invocation, nothing
else. If groups are never published, the card ships averaging over draws, which
is correct and is recorded as `group_draw: null` in the payload.

**Effort:** minutes.

## A7. DONE — emit the standalone diagnostics into the release bundle

`cli_data_health` and `cli_external_cards` ran standalone until 2026-08-09. Both
are now `cli_release` producers, so the corpus's tier mix, patch mix, recency and
per-team volume — and the external-card ceiling result — land inside the
manifest-bound bundle. The card now ships alongside a statement of what it was
trained on and of how much a card score can prove.

**This moves the run id**, since the id derives from the descriptor and the
descriptor contains the producer list. That is correct: a bundle containing
different outputs is a different bundle.

**Two things changed beyond the list itself**, both consequences of it growing:

- The must-succeed check named the card and D4 explicitly, so anything added
  afterwards could fail in silence. It now names the *gates* — whose non-zero
  exit is a registered verdict — and treats every other producer as
  must-succeed. A producer added later is protected by default.
- The frozen-gate re-run found the card by list index. The index still happened
  to be right, which is exactly why it was worth removing: it is found by name
  now, and a test moves the card to prove it.

## Explicitly NOT before the lock

- **Any change to `strengths()`,** including the uncertainty propagation in B1.
  It changes every number the card is built from and would need D3b re-run and
  re-registered. Four days is not enough to do that honestly.
- **Any new rating candidate.** Each one tightens the multiplicity correction on
  every gate (see B0).
- **Re-running any gate that has already returned a verdict.**

---

# Part B — The roadmap

Ranked by expected gain per unit of work. Section numbers map to the design
template so this can be reviewed against the standard checklist.

## B0. First, a constraint that shapes everything below

*(§II Metrics and Losses, §IV Validation Schema)*

D3b already applied a Bonferroni correction over two candidates (Elo, Glicko),
tightening its interval to 97.5%. **Every new rating candidate added below
tightens that correction further.** A roadmap that proposes five new models
proposes a per-comparison alpha of 0.01 and a bar most of them will fail on
noise alone.

The response is not to abandon multiplicity control. It is to **stop treating
model selection as the unit of evidence** and hold out data instead: with more
than one premium event (B1), candidates can be compared on a held-out event
rather than on a corrected interval over the same corpus. That is why B1 is
first and why nothing else should jump it.

## B1. Ingest deep history — the unlock

*(§III Dataset)*

**Attacks:** [§2a](2026-08-08-known-weaknesses.md#2a-the-corpus-contains-exactly-one-event-of-the-type-being-forecast) (one premium event), §2h (17.7-month horizon), §3a (one bracket to infer rules from).

The store begins 2025-02-08 because that is what was ingested, not because
anything older is unavailable. Extending backwards through TI 2023, TI 2024 and
the intervening majors would take the premium-tier event count from **1 to
roughly 3-4** `[ASSUMPTION: TI 2023 and TI 2024 are tagged premium in
OpenDota's leagues table, as TI 2025 is — checkable with one explorer query
before committing to the ingest]`.

That single change unlocks:

- **Real validation at the target tier.** Train on earlier TIs, evaluate on the
  latest. The current project cannot do this at all.
- **Rule inference from multiple brackets** rather than the single TI 2025
  bracket that §3a rests on.
- **A meaningful card-level backtest.** D4's n = 1 becomes n = 3-4. Still small,
  but it is the difference between an anecdote and a trend.
- **The multiplicity escape in B0.**

**Cost:** ingest time and OpenDota rate limits; roughly 30 additional months of
`explorer_query` month-windows. Storage is trivial (the current 17.7 months is
17 MB).

**Risks:** older patches are *less* representative of current Dota, so this
helps rule inference and tier coverage more than it helps rating accuracy. Guard
by keeping the production training window a tunable, and reporting results at
both windows rather than silently adopting the longer one.

**Done when:** `cli_data_health` reports `target_tier_events >= 3`, and a
held-out-event evaluation exists.

## B2. Test a tier-filtered corpus as a gated candidate

*(§III Dataset, §V Baseline Solution)*

**Attacks:** [§2a](2026-08-08-known-weaknesses.md#2a-the-corpus-contains-exactly-one-event-of-the-type-being-forecast) (45.7% of rows are OpenDota-`excluded`).

Cheapest high-value experiment available, because the machinery already exists:
the D2/D3b rolling-backtest harness is built to compare candidates, so this is a
data filter and a gate registration, not new modelling.

Three variants worth testing: drop `excluded` entirely; down-weight it; or fit a
tier effect. `[ASSUMPTION: excluded-tier results are noisier per map rather than
systematically biased — if instead they inflate ratings for teams that farm weak
opposition, down-weighting will beat dropping, because dropping also removes the
common opponents that link rating pools together.]`

Confirm first what `excluded` actually denotes in OpenDota's `leagues` table.
This repository has never checked, and the weakness document is deliberately
agnostic about it. A filter built on a guessed label meaning is not a
data-quality improvement.

That last point is the real risk and deserves stating: dropping 45.7% of the
corpus can **disconnect the comparison graph**. Two teams that never meet
directly are only comparable through shared opponents, and low-tier matches
supply many of those links. Measure graph connectivity before and after, not
just log loss.

**Done when:** a registered gate compares the filtered candidate against current
Glicko on held-out data, with connectivity reported alongside.

**Effort:** ~1 day.

## B3. Model the series, not just the map

*(§II Metrics and Losses, §VIII Features)*

**Attacks:** [§5b](2026-08-08-known-weaknesses.md#5b-calibration-contradicts-itself-across-levels) (map says overconfident, series says underconfident).

[`series.py`](../../src/ti26/series.py) converts map probability to series
probability with `math.comb` under independence. Maps within a series are not
independent — drafts adapt, sides alternate, momentum is real — and the
independence assumption is a plausible source of the calibration contradiction:
it *compresses* series probabilities toward 0.5 relative to truth, which is
exactly the direction a series slope of 2.12 indicates.

Testing this is cheap and does not require a new rating model: fit a single
free parameter (a series-level over-dispersion, or map correlation rho) on
pre-TI data and check whether the series calibration slope moves toward 1.0.
One parameter, one pre-registered gate.

**Done when:** the TI-series calibration slope's CI contains 1.0 and is narrower
than the current [0.699, 3.534].

**Effort:** ~1-2 days.

**Promoted since the first draft of this document.** The external-card
diagnostic ([§5a](2026-08-08-known-weaknesses.md#5a-what-an-expert-scored-and-why-it-reframes-the-whole-section))
showed that a random card matches the best published expert card 31% of the
time, and that 7 of 16 is the threshold for even a marginal result. A sixteen-slot
card is therefore not a measuring instrument, for us or anyone. Series scoring
has 58 observations to the card's 16 and is the only place a signal has appeared,
so **series-level work should be treated as the project's primary metric track
and the card score demoted to a reported headline.** That is a stronger argument
for B3 than the calibration contradiction it was originally justified by.

## B4. Propagate rating uncertainty into the simulation

*(§VII Training Pipeline, §VIII Features)*

**Attacks:** [§2c](2026-08-08-known-weaknesses.md#2c-evidence-per-team-varies-139x-and-the-model-discards-that-fact) (RD computed, then discarded).

Glicko's entire purpose is tracking per-team uncertainty; `strengths()` throws
it away and the simulation treats a 27-map roster exactly like a 376-map one.
Fix: draw each team's strength from its posterior once per simulated
tournament, rather than using the mean 250,000 times.

Expected effect: thin-evidence teams (OG, Nigma, Resilience — RD 67.8 to 76.9)
get wider category distributions, which is correct. Whether it *raises expected
card score* is a separate question and should not be assumed — a flatter
marginal can lower the optimiser's objective while being better calibrated.
**Register the calibration criterion, not the score criterion**, or this becomes
a search for a higher number.

**Risk:** this changes every strength the card is built from, so it needs the
full D3b treatment. Do it early in a cycle, never near a lock.

**Effort:** ~2-3 days including re-validation.

## B5. Treat a patch change like idleness

*(§VIII Features)*

**Attacks:** [§2e](2026-08-08-known-weaknesses.md#2e-83-of-the-corpus-describes-a-game-that-no-longer-exists) (five patches pooled, `patch` ingested and unread).

The elegant cheap version: a patch boundary raises every roster's RD, exactly as
an idle period does. It reuses machinery already in `GlickoModel._inflate`,
needs one parameter, and encodes the true statement "after a patch we know less
about everyone" without pretending to know *how* the patch changed things.

The expensive version — per-patch effects or hero-aware adjustment — belongs in
B6.

`[ASSUMPTION: TI 2026 will be played on a patch released close to the event,
as is customary. If so, no model trained on this corpus will have seen it, and
the RD bump is the only honest response available.]`

**Effort:** ~1 day.

## B6. Draft and hero features

*(§VIII Features)*

**Attacks:** [§2f](2026-08-08-known-weaknesses.md#2f-ingested-and-unused) (hero arrays sitting in the store, unread).

Highest ceiling, highest cost, and deliberately last. Hero data is the most
informative observable in Dota, and the design spec already contemplates it
(D5, `reports/meta_scouting.md`).

It is last because a feature model stacked on a rating base that is worse than a
coin flip until shrunk (§1) compounds two error sources instead of fixing
either. Fix the base first. When it is fixed, the store already holds the data,
so nothing here is blocked on ingest.

**Effort:** weeks.

## B7. Monitoring and operations

*(§XI Monitoring, §X Integration)*

The gap the checklist would flag hardest: this project has excellent *provenance*
and no *monitoring*. Everything is verified at build time; nothing watches for
decay between runs.

- **Data health on every release.** A6 makes this automatic. Add thresholds:
  alert when the target tier's share drops, when a configured roster's map count
  falls below the thin threshold, when the newest patch's share of the corpus
  falls below a floor.
- **Drift-triggered re-validation.** D3b's slope clears its band by 0.0057. That
  is close enough that a re-ingest could move it out. Re-run the gate on every
  material corpus change and treat a band exit as a stop, not a warning.
- **Roster staleness as a first-class alarm.** `check_roster_staleness` exists;
  its output should gate a release rather than inform a human reading a report.
- **Post-event scoring.** For an ongoing system this is the most valuable habit
  available: after every event, score the forecast that was actually published,
  append it to a permanent record, and never edit past entries. Ten events of
  honest scoring is worth more than any modelling change in this document.

**Effort:** ~2-3 days, then continuous.

---

# Implementation plan

| Phase | Items | Depends on | Calendar |
|---|---|---|---|
| Pre-lock | A1-A7 | nothing | by 12-13 Aug 2026 |
| Post-TI, first | B1 (deep ingest), B7 (post-event scoring of the TI 2026 card) | TI 2026 concluding | ~2 weeks after the event |
| Second | B2 (tier filter), B3 (series model) | B1 for held-out validation | ~1 month |
| Third | B4 (uncertainty), B5 (patch RD) | B2/B3 settled, so candidates are not compared against a moving base | ~2 months |
| Later | B6 (draft features) | a rating base that clears the floor unshrunk | open |

**Resources:** single developer, local execution. Compute is not a constraint —
the heaviest current step is 250,000 simulations plus a 10,000-draw bootstrap,
both minutes on one machine. `[ASSUMPTION: this stays a single-maintainer
project; if it does not, the pre-registration discipline needs a written
protocol for who may register a gate.]`

**Dependencies outside our control:** OpenDota's API availability and rate
limits; whether Valve publishes TI 2026's pairing rules; whether TI 2023/2024
are tagged premium in the leagues table (gates B1's main benefit).

## Risks and mitigations

| Risk | Consequence | Mitigation |
|---|---|---|
| Deep ingest changes historical rows, breaking bundle reproduction | Published numbers stop verifying | Never re-ingest into an existing snapshot id; new snapshot, new run id, old bundles untouched |
| Tier filtering disconnects the comparison graph | Ratings become incomparable across pools; log loss may still look fine | Measure connectivity explicitly (B2), not just the scoring rule |
| Each new candidate tightens multiplicity | Real improvements fail their gate on noise | Held-out-event evaluation via B1 instead of more corrected intervals |
| Uncertainty propagation lowers the optimiser objective | Tempting to revert a correct change because a number went down | Register the calibration criterion in advance (B4), never the score |
| Improvements land near a lock | Regression under deadline pressure | Model changes only at the start of a cycle; Part A's exclusion list is the standing rule |
| Post-event scoring is skipped after a bad result | The record becomes a highlight reel, and the one honest signal this system has is lost | Score before reading the result; commit the producer before the event |

---

# Scope notes

Recorded because a reviewer working from a standard ML design checklist will
look for each of these, and "absent" and "not applicable" are different answers.

**Serving and inference: not applicable.** There is no API, no latency budget,
no online traffic. The artifact is a card produced once per event plus the
bundle that proves its lineage. Compute is minutes on one laptop. If that ever
changes — a public forecast page, say — this section stops being a note and
becomes a design problem.

**A/B testing: not applicable, and cannot become applicable.** There is one
compendium submission per event and no control arm. This is why the pre-lock
registration discipline carries the weight that an experiment would carry
elsewhere, and why B7's append-only post-event record is the closest available
substitute.

**Fallback strategy: exists, documented, and now REHEARSED.** If the fitted
model cannot ship — roster resolution failure, unusable snapshot, a producer
that cannot run — the registered fallback is rung 3: OpenDota's public
`team_rating` table piped into the same simulator via `cli_rung3`, with a
`team,strength` CSV and `python -m ti26.cli --strengths <file>`.

Rehearsed end to end on 2026-08-09, which changed four things:

- **A failing gate is not a trigger, and the old wording implied it was.** D2 and
  D3 already fail; that is recorded evidence and the card ships from calibrated
  Glicko regardless. `cli_d2` refuses to silently substitute a different model,
  which is a different guarantee from "a failed gate sends you to rung 3".
- **Rung 3 needs the network, through the same seam as the ingest, and the store
  too** — for the Elo anchor and the observed-form diagnostic. Both of the
  conditions that would send you here can therefore also disable it. It now
  fails with the command that finishes the card from the ratings it already
  fetched, instead of a traceback from two modules away.
- **The rung-3 card is a different forecast, not a degraded rendering of the
  same one.** At identical sim count and seed it moved half the assignments.
- **Its objective is higher, and that is not evidence it is better** — the
  objective is computed under its own marginals, so confidence raises it whether
  or not accuracy does. `cli_provenance card-diff` now carries that warning in
  its own output, because the comparison is one step and the trap is obvious
  only after it is pointed out.

The procedure is steps 9b and 9c of the [runbook](near-lock-runbook.md). The
rehearsal's outputs are not committed and its figures are labelled as one-off
observations rather than reproducible evidence: rung 3 reads a live table, so it
cannot be replayed offline, which is why the correction register withdrew
rung-3 numbers from project prose in the first place.

**One thing the rehearsal verified rather than broke.** The network-free last
resort — the card generator fed a `team,strength` CSV — reproduced the shipping
card exactly from the same strengths at the same sim count and seed, assignments
and objective alike. The generator is sound; the only open question in that path
is where the strengths come from. It also showed sim count is not a free
parameter: the same strengths at 2,000 sims instead of 250,000 moved four slots.

**Data privacy.** The store holds player `account_id`s, which are public
OpenDota identifiers but are still person-linked. No names, no contact
information, nothing derived about individuals beyond match participation. If
this project ever publishes per-player output rather than per-team, that
judgement needs revisiting.

**Backup and recovery.** Raw snapshots are committed to the repository, so the
store is rebuildable from Git alone and needs no separate backup. This is a
deliberate property, not an accident: `cli_ingest` reconstructs the SQLite store
from `data/raw/<snapshot-id>/` with no network access.

**Error analysis loop.** The per-slot and per-bucket analysis lives in the
weakness document and in the diagnostics that produce it. What is missing is a
*loop*: nothing routes a finding into a registered follow-up. B7's post-event
record is the intended mechanism.

---

# What success looks like

Concretely, so this document can be marked wrong later:

1. `cli_data_health` reports **3 or more** distinct premium events (today: 1).
2. A rating model clears the spec-V constant floor **without** calibration
   shrinkage (today: none do).
3. The TI-series calibration slope's 95% CI contains 1.0 and is narrower than
   [0.699, 3.534].
4. Card-level backtest beats the naive strength ladder on a held-out event
   (today: 4/16 vs 4/16, tied).
5. A permanent, append-only record of published forecasts and their scores
   exists, with at least three entries.

Item 2 is the one that matters. Until a model beats a coin flip on its own,
everything else in this repository is scaffolding around a 55.8% edge.

**A criterion deliberately NOT on this list: a card score.** Not "beat 4/16",
not "beat the expert's 5/16", not any single-event card target. The external-card
diagnostic showed a random card reaching 5/16 about 31% of the time and 7/16
being the threshold for even a marginal result, so a card-score target would be
a coin-flip dressed as a goal — hit it and learn nothing, miss it and learn
nothing. Item 4 survives only because it is a *paired* comparison against the
ladder on the same event, which cancels most of the shared luck, and even that
needs several events before it means much.
