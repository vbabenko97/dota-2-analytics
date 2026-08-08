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

Four to five days. The honest headline first:

> **Nothing in Part A will make the card more accurate.** No model change can be
> made, validated and regenerated safely in four days without breaking the
> pre-registration discipline that is this project's main asset. Part A is about
> making sure the run does not break and the record is not wrong.

Ranked by risk of the thing going wrong on the day.

## A1. Remove the dead duration machinery and its lock-day false alarm

**Problem:** [weakness §6](2026-08-08-known-weaknesses.md#6-dead-machinery).
Duration was removed from the tiebreak on 2026-08-08 and now provably moves
nothing: sigma 0.05 vs 5.00 — a 100x change — shifts the category marginals by a
maximum absolute delta of 0.0.

**Why it is first:** the near-lock run ingests a *fresh* snapshot, which refits
duration, which will very likely trip the staleness comparison at
[`cli_d2.py:209-221`](../../src/ti26/cli_d2.py#L209). That prints:

> `WARNING: ... Any card built this run used the STALE config values -- update
> the rules config from duration_fit.json and re-run before trusting it.`

The check **warns rather than aborts** — the code comment says hard-failing was
deliberately avoided so it would not break the documented build sequence — so
this does not block the run. What it does is worse in a different way: on lock
day the operator sees an unexplained warning stating the card cannot be trusted
and instructing a config sync plus a full re-run, for a parameter that cannot
affect the output. The near-lock runbook does not mention duration anywhere, so
there is nothing to tell them to ignore it.

**Fix:** delete `duration_model` from the rules dataclass, the staleness check,
and `duration.py`'s sensitivity sweep. If deletion is too broad for the
remaining time, the minimum viable fix is a runbook line saying the warning is
expected and harmless — but that leaves a staleness gate on a dead parameter,
which will mislead the next person instead.

**Done when:** `pytest` unfiltered passes with the duration tests removed or
rewritten, and `cli_release` completes on the pinned snapshot with no duration
warning.

**Effort:** ~1 hour.

## A2. Correct the stale pairing justification in config

**Problem:** [weakness §3c](2026-08-08-known-weaknesses.md#3c-the-configs-own-justification-for-the-pairing-tag-is-stale).
`base_pairing_preference: refuted_immaterial` is justified by a "4 of 11
buckets" measurement predating the 2026-08-08 engine corrections. Current value
is 15 of 17.

**Fix:** re-run `cli_pairing_check`, commit its output as an artifact, and
rewrite the comment to cite the artifact rather than restate a number. The tag
itself probably becomes `corroborated_immaterial` — the rule now agrees with
reality far more often than "refuted" implies, and
`cli_schedule_sensitivity` separately showed it does not move the card.

**Done when:** the comment cites a committed artifact and no bare number.

**Effort:** ~30 minutes.

## A3. Stop `cli_pairing_check` from misrepresenting its own result

**Problem:** [weakness §3a](2026-08-08-known-weaknesses.md#3a-the-elimination-round-the-engine-is-right-and-its-raw-output-says-otherwise).

**Do not change the elimination rule.** It is published TI 2025 text, it sits in
the Elimination Round section below the Swiss pairing rules, and the engine
reproduces the real bracket to within one swap — a swap fully explained by the
unannounced two-series-per-day constraint of 6 September. This entry previously
proposed measuring the reachable minimum before deciding; that was written from
a misreading of the producer's output and is withdrawn. The question is settled
and the answer is in
[the format-rules document](2026-08-08-published-format-rules.md#ti-2025s-elimination-round-did-not-follow-the-published-rule).

**The actual defect is the report, not the rule.** `cli_pairing_check` emits

```
engine_reproduces_the_real_bracket: false
pairs_shared_with_engine: 3 of 5
```

with no indication that the discrepancy is a known, documented, external
constraint. Anyone reading the raw JSON — including the author of this document,
who did — concludes the rule is refuted. That is a producer emitting a true
number that reliably causes a false inference, which is the same class of
problem as an unbound number and deserves the same treatment.

**Fix:** carry the known deviation in the output. A `known_deviations` field
naming the 6 September constraint, the pairs it moved (HEROIC/Yakult in place of
HEROIC/Spirit and Falcons/Yakult), and its distance cost (10 → 8), so the
verdict field is never read alone. Cite the format-rules document from the
producer's docstring.

**Done when:** the JSON explains its own `false`, and a reader who has never
seen the format-rules document cannot draw the wrong conclusion from it.

**Effort:** ~1 hour.

## A4. Run the near-lock runbook

[`docs/ti26/near-lock-runbook.md`](near-lock-runbook.md), all ten steps,
including step 3's field re-confirmation against a source outside
`explorer_query` regardless of the 2026-08-07 result. Fresh snapshot, full
regeneration, verify the bundle.

**Effort:** ~2 hours including ingest.

## A5. Settle whether the recent-data collapse is real or ingest lag

**Problem:** [weakness §2d](2026-08-08-known-weaknesses.md#2d-the-freshest-evidence-is-the-thinnest).
The corpus holds 76 maps/day overall and 13.9/day across the last 30. That is
either a real pre-major slowdown or the incomplete tail every snapshot has, and
the two call for opposite responses.

**Fix:** both `data/raw/20260802T165535Z` and `data/raw/20260807T182355Z` are
already committed. Rebuild each and compare map counts over an identical
historical window. If the older snapshot reports fewer maps for the same window
than the newer one, the gap is ingest lag and the answer is simply to snapshot
later on lock day. If the counts match, the slowdown is real.

**Why it earns a slot:** it changes the lock-day procedure, it costs one
comparison, and it is the difference between "take the snapshot as late as
possible" and "widen uncertainty on recent form".

**Effort:** ~30 minutes.

## A6. Condition on the group draw the moment it is published

Already built (`--groups`). Add the flag to the release invocation, nothing
else. If groups are never published, the card ships averaging over draws, which
is correct and is recorded as `group_draw: null` in the payload.

**Effort:** minutes.

## A7. Emit data health into the release bundle

`cli_data_health` currently runs standalone. Adding it to `cli_release`'s
producer list puts the corpus's tier mix, patch mix, recency and per-team
volume into the manifest-bound bundle, so the card ships alongside a statement
of what it was trained on.

**Effort:** ~30 minutes.

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

**Attacks:** [§5a](2026-08-08-known-weaknesses.md#5a-calibration-contradicts-itself-across-levels) (map says overconfident, series says underconfident).

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

**Fallback strategy: exists and is documented.** If the fitted model cannot ship
— gate failure, roster resolution failure, unusable snapshot — the registered
fallback is rung 3: OpenDota's public `team_rating` table piped into the same
simulator via `cli_rung3`, with a `team,strength` CSV and
`python -m ti26.cli --strengths <file>`. `cli_d2` already refuses to
silently substitute a different model on a failed gate. The gap is that this
path is exercised by tests but has never been run end-to-end under time
pressure; **rehearsing it once, before the lock, is worth an hour** and is not
in Part A only because it competes with A1-A5 for the same days.

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
