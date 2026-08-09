# Known weaknesses, 2026-08-08

What is wrong with this project, ranked by how much it should change your
confidence in the shipping card. Written on the day the last pre-lock PR merged
(`ec1ea1b`), against snapshot `20260802T165535Z`.

Every number below names where it comes from. Numbers marked **[bundle]** are
read from a committed run bundle whose manifest binds them to a source revision
and a store digest. Numbers marked **[producer]** come from a producer in this
repository that you can re-run. Nothing here is asserted from memory; that is
the rule this project broke once already
([correction register](../audits/2026-08-04-correction-register.md)).

Regenerate the data section with:

```
.venv/bin/python -m ti26.cli_data_health \
  --store data/processed/release-20260802T165535Z.sqlite --out reports/data_health
```

**Companion document:** [strengthening plan](2026-08-08-strengthening-plan.md)
proposes what to do about all of this. This document only diagnoses.

---

## 1. The rating model does not beat a coin flip until it is shrunk

Rolling out-of-sample log loss over 26,830 scored maps, 192 tournament folds
**[bundle: `reports/runs/fa6ecd08.../d2/d2_gate.md`]**:

| model | log loss | vs constant 50/50 |
|---|---|---|
| constant | 0.69315 | floor |
| elo | 0.69446 | **+0.00131 worse** |
| glicko | 0.69802 | **+0.00487 worse** |
| ewma | 0.70655 | **+0.01340 worse** |

Every raw rating model loses to a coin flip. That is not a subtlety in the
project's own words — the D2 report prints `Floor cleared: NO` for all three.

The only configuration that clears the floor is Glicko **after** its strengths
are multiplied by a calibration slope of 0.4051, which clears by 0.00673
nats/map **[bundle: `d3b/d3b_gate.json`]**. That margin is the information
content of a flat 55.8% per-map edge.

**So the entire demonstrated predictive content of this project is one
shrinkage constant applied to a model that is otherwise worse than nothing.**
Everything downstream — the simulation, the optimiser, the card — is machinery
built on top of that 5.8 percentage points.

### 1a. The D3b PASS is narrower than it looks

D3b is a **one-condition** test. Its margin and calibration slope were already
known before it was registered; only the bootstrap interval was open
**[bundle: `d3b/d3b_gate.json`, `open_for_test` flags]**. And the slope clears
its band by 0.0057 (0.9057 against a floor of 0.9). The gate's own report says
this in as many words. It is a real PASS and it is thin.

---

## 2. The data cannot support the question being asked of it

This is the section that should worry you most, because unlike everything else
here it is not fixable by better modelling.

All figures **[producer: `ti26.cli_data_health`, `reports/data_health/`]**.

### 2a. The corpus contains exactly one event of the type being forecast

| tier | maps | share |
|---|---|---|
| professional | 22,198 | 54.0% |
| excluded | 18,798 | 45.7% |
| **premium** | **144** | **0.35%** |

Those 144 premium maps are **one league id: 18324 — TI 2025 itself**, played
2025-09-04 to 2025-09-14.

The model is being asked to forecast a premium-tier event. Its training corpus
holds one, and that one is also the only event we can backtest against. You
cannot both train on it and hold it out, and there is no second premium event
anywhere in the store to check generalisation against.

The 45.7% tagged `excluded` comes straight from OpenDota's `leagues.tier`
column. Nothing in this repository documents what that label means at the
source, and it has not been verified against OpenDota's documentation — treat
the interpretation as open. What is certain is the part that matters: those
rows are *not* labelled premium or professional by the data source, and the
model weights them exactly as heavily as it weights TI.

This is a train/serve population mismatch, and it is **invisible to every gate
in the project**: the rolling backtest folds are drawn from the same corpus, so
they inherit the same mix. A model can be immaculately validated out-of-sample
and still be validated on the wrong population.

### 2b. 15 of 16 current rosters have never played a premium map

Only Team Falcons carries premium-tier maps on the roster it will field
(29 of them). The other fifteen have zero, because premium means TI 2025 and
those rosters have since changed.

### 2c. Evidence per team varies 13.9x, and the model discards that fact

| team | roster maps | RD | days idle |
|---|---|---|---|
| OG | 27 | 67.8 | 0.2 |
| Nigma Galaxy | 30 | 73.9 | 0.2 |
| Team Resilience | 38 | 76.9 | 0.1 |
| Team Spirit | 63 | 57.7 | 17.1 |
| Team Yandex | 71 | 52.7 | 14.2 |
| Team Vision | 80 | 50.4 | 13.9 |
| ... | ... | ... | ... |
| BoomBoys | 316 | 41.2 | 1.0 |
| Team Falcons | 376 | 44.3 | 0.0 |

Full table in `reports/data_health/data_health.md`. Counted by roster hash, not
by organisation — the current five, not the badge.

Glicko exists precisely to track this: RD spans 41.2 to 76.9, a 1.86x spread in
uncertainty, and the model knows it. Then
[`glicko.py:281-296`](../../src/ti26/ratings/glicko.py#L281) returns
`(rating - mean) * LOGIT_PER_GLICKO` and **RD is dropped on the floor**. A
27-map roster and a 376-map roster enter the 250,000 simulations as equally
confident point estimates.

The card's own provenance report is honest that `strengths()` omits the RD
attenuation term `g(phi)`, and bounds it over this field at 0.9472–0.9826
**[bundle: `card/card_provenance.md`]**. That bound is real but it is a bound on
one term in the win-probability function, not on the loss from treating unequal
evidence as equal when propagating a team through five rounds of a bracket.

### 2d. The freshest evidence is the thinnest

| window | maps | share of corpus |
|---|---|---|
| last 30 days | 418 | 1.0% |
| last 60 days | 1,340 | 3.3% |
| last 90 days | 3,809 | 9.3% |
| last 180 days | 10,963 | 26.6% |

The corpus averages 76 maps/day overall and 14/day across the last 30. Two
explanations, which call for opposite responses:

1. **Real.** Teams stop playing publicly before a major — they qualify, then
   bootcamp privately. The response is to widen uncertainty on recent form.
2. **Artefact.** The tail of any OpenDota snapshot is incomplete, because match
   ingestion and parsing lag behind play. The response is to snapshot later and
   to stop reading the final days as evidence.

**Measured on 2026-08-09, and it is the first.** `cli_snapshot_lag` counts the
same calendar window across the two committed snapshots, five days apart
([`reports/snapshot_lag/`](../../reports/snapshot_lag/snapshot_lag.md)):

| quantity | value |
|---|---|
| tail maps present in the newer snapshot but not the older | 3 of 421 (0.7%) |
| tail rate, newer snapshot | 14.0 maps/day |
| whole-window rate, newer snapshot | 76.2 maps/day |
| ratio | 0.18 |
| maps dropped between snapshots | 0 |

All three backfilled maps fall on the single last day of the older snapshot's
coverage; every earlier day is identical in both. So lag exists, is confined to
roughly the final day, and is nowhere near large enough to explain a rate 82%
below the corpus average. **The slowdown is real, and the response is the first
one.**

**What this cannot see.** The two snapshots are 5.1 days apart, so a row
arriving later than that is scored here as no lag at all. The measurement bounds
backfill within five days; it says nothing about a longer one. That number is
emitted as `observation_horizon_days` rather than left implicit.

Two consequences follow, both now in the runbook: taking the lock-day snapshot
later buys almost nothing, and the thin recent evidence is a fact about the
world that the model has to carry rather than a defect to be snapshotted away.

Note this is a corpus-wide effect, not a per-team one: most of the sixteen
played within two days of the snapshot (§2c). Glicko's answer to idleness is RD
inflation, which per §2c is discarded before the simulation sees it.

### 2e. 83% of the corpus describes a game that no longer exists

| patch | maps | share |
|---|---|---|
| 7.41 | 6,958 | 16.9% |
| 7.40 | 7,943 | 19.3% |
| 7.39 | 17,867 | 43.4% |
| 7.38 | 7,299 | 17.7% |
| 7.37 | 1,073 | 2.6% |

`MapRow` carries `patch`, and no rating model reads it
([`glicko.py:226-267`](../../src/ti26/ratings/glicko.py#L226) uses only
`radiant_accounts`, `dire_accounts` and `radiant_win`). Five patches are pooled
as if Dota were stationary across eighteen months. If Valve ships a patch for
TI 2026 — which is the norm — the event will be played on a version with zero
maps in the corpus.

### 2f. Ingested and unused

`MapRow` also carries `duration`, `tier`, `series_type` and both teams' full
`heroes` arrays. The rating models consume none of them. Draft information — the
single most informative observable in a Dota match — is sitting in the store,
unread.

### 2g. 5.2% of rows are unrateable

2,127 maps carry `null_team` **[producer]**. The model declines to rate them and
the gates score only the population it was willing to train on. That is the
correct call, and it means the reported gate margins describe a filtered
population, not the corpus.

### 2h. Horizon and staleness

The store spans 2025-02-08 to 2026-08-02 — **17.7 months**. Organisations with
decade-long histories (OG, Liquid, LGD) get no credit for any of it. And the
shipping snapshot is 6 days old as of writing; the near-lock runbook exists to
fix that on the day.

---

## 3. The rules engine modelled the wrong year, and the format changed

**Superseded twice in one day.** This section first said the elimination rule
was contradicted by TI 2025, then that it was corroborated by it. Both were
answering the wrong question: **TI 2026 does not use TI 2025's rules.** Valve
published the 2026 Group Stage Rules during 2026-08-08 and they were fetched
and archived the same evening
([verbatim](2026-08-08-ti2026-rules-fetched.md)).

Four differences, and the engine was wrong on all four for about eleven hours:

| # | TI 2026 | TI 2025 | engine, 09:33-20:00 |
|---|---|---|---|
| 1 | criterion 3 is opponents' match wins, 4 is % games won | reversed | TI 2025's |
| 2 | criterion 6 is **Average Game Duration**, 7 criteria | no duration, 6 criteria | TI 2025's |
| 3 | Round 5 **maximizes distance where the loser is eliminated** | no R5 modification | TI 2025's |
| 4 | Elimination Round: best 3-2 team **chooses** its opponent | distance is maximized | TI 2025's |

**The engine held all four correctly before 2026-08-08**, from the design
spec's original values. Commit `23beac3` replaced them with a better-sourced
transcript of the wrong year's rules, on the reasonable assumption that the
format carried over. It did not.

The lesson is not "check your sources" — the transcript was accurate and
correctly applied. It is that **a well-evidenced value from an adjacent context
beats an unsourced one on every axis except being right.** Provenance tags
record where a value came from; they cannot record that it describes a
different tournament.

Now corrected, with the tags naming the fetch and its date
(`valve_rules_page_2026_08_08`).

### 3a. What is still uncertain about the elimination round, and what it costs

The rules fix the ORDER in which 3-2 teams choose and say **nothing about the
basis**. That is not a gap this project can close by reading more carefully; it
is genuinely unspecified, and it governs 10 of 16 card slots.

`elimination_choice_policy` is therefore tagged
`unspecified_by_published_rules`, and all three candidates were measured rather
than assumed **[producer: `ti26.cli_schedule_sensitivity`,
`reports/schedule_sensitivity_2026/`, 250,000 sims, seeds 1/2/3]**:

| policy | max marginal delta vs configured | assignments changed | objective |
|---|---|---|---|
| rational (configured) | 0.00000 | 0 | 4.5903 |
| noisy | 0.00418 | **0** | 4.5795 |
| random | 0.00371 | **0** | 4.5860 |

Reseeding the *same* policy, for comparison: max delta 0.00310, and **4
assignments changed**.

**No policy changes a single card slot, and the seed changes four.** The
assumption that looked like it drove ten slots drives none of them, and the
thing that does drive them is Monte Carlo noise — which is §4's problem, not
this one's.

`rational` stays configured. That is a deliberate departure from the "when it
does not matter, assume least" rule that would have selected `random`: uniform
choice is not a weaker assumption, it is a different and less plausible one.
Valve gave the best 3-2 team a choice precisely because it is worth something,
and professionals playing for seven figures will not exercise it by coin flip.
`noisy` would model that best of the three but carries a free temperature
parameter, and buying an unregistered parameter for a measured benefit of zero
is the wrong trade.

### 3b. The TI 2025 diagnostic, and why its verdict field misleads

**[producer: `ti26.cli_pairing_check`, run against `release-deep.sqlite`]**

This entry was written backwards in the first draft of this document and is
kept, because the way it misleads is worth preserving.

The producer reports:

```
engine_reproduces_the_real_bracket: false, false, false, false, false   (5 seeds)
real_bracket_distance:              8
best_reachable_distance:            10
pairs_shared_with_engine:           3 of 5
```

That measures the engine against **TI 2025's** elimination rule, which is what
`pair_elimination` still implements and what `cli_pairing_check` needs, since
TI 2025 is the event being checked. It says nothing about TI 2026's rule, which
is a sequential choice.

Read alone, the `false` is damning: it looks as though maximum ranking distance
is refuted by the only event that ran it. **That reading is wrong**, and
[the format-rules document](2026-08-08-published-format-rules.md#ti-2025s-elimination-round-did-not-follow-the-published-rule)
already said so:

- The maximise rule **is** published. It sits in the TI 2025 text's
  **Elimination Round** section, below the Swiss Pairing Rules section that ends
  at Round 5. A screenshot of the Swiss pairing rules alone does not contain it,
  and does contain the *opposite* general rule (minimise), which is what makes
  this so easy to get backwards.
- The 8-versus-10 gap has a **documented cause outside the rules**. Teams were
  notified on 6 September of a previously non-existent constraint — no more than
  two series per day — that was never publicly announced. It forced HEROIC onto
  Yakult; the rule-following pairing was HEROIC vs Spirit and Falcons vs Yakult.
  That single swap is exactly the difference between 8 and 10 and accounts for
  precisely the two pairs the engine does not share.

**So the published rule reproduces the event to within one swap, and the swap is
an unannounced mid-event rule change.** The engine is corroborated, not
contradicted.

The real weakness is the one underneath: **the organiser demonstrably changes
the rules mid-event without announcing them, and did so at the only event we can
check.** One unannounced constraint moved 2 of 5 elimination pairs. That is not
forecastable, not a model defect, and not fixable — but it is a floor on how
accurate the elimination categories can ever be, and those are 10 of the 16 card
slots.

And it is the same hazard as the section above, on a shorter timescale: rules
that change during an event, and rules published mid-preparation, are both the
organiser moving the target after you have aimed.

The producer's own field name is a trap: `engine_reproduces_the_real_bracket:
false` is literally true and reads as "the rule is wrong". It should carry the
known deviation alongside it.

### 3c. Swiss pairing is much healthier, but not clean

15 of 17 buckets agree across all 5 seeds; 16 of 17 real pairings sit at
minimum ranking distance. Both disagreements are Round 2, Group A, where the
ranking is most tie-dominated, and one of them sat at distance 8 — the
*maximum* — against a minimum-distance rule.

### 3d. The config's own justification for the pairing tag is stale

[`config/ti2026_rules.yaml:155`](../../config/ti2026_rules.yaml#L155) tags
`base_pairing_preference: refuted_immaterial`, justified by a comment saying
the real pairing is among the engine's candidates "in 4 of the 11 buckets".
That comment is commit `b05569d`, 2026-08-07 — written **before** the rules
engine was corrected on 2026-08-08 (`23beac3`, `f96fb0e`). Re-running the
producer today gives 15 of 17.

A load-bearing tag resting on a number its own producer no longer reproduces is
the exact failure mode the correction register exists to prevent, reappearing
in a config file rather than in an audit.

### 3e. What remains unsourced, now that the rules are published

Most of what this section used to list is resolved: `tiebreak_order`, the
group-round assignments, the Round 5 modification and soft repeat avoidance all
now come from Valve's own page. Three things do not.

- **The elimination choice basis**, per §3a. Genuinely unspecified, and it
  drives 10 of 16 slots.
- **The page can change under us.** It gained its entire pairing section during
  2026-08-08, hours after the owner checked and found none. No test here can
  detect that — tests never reach the network — so the tag carries the fetch
  date and the near-lock runbook must re-fetch rather than trust this archive.
- **The groups are still unannounced**, so the card averages over draws rather
  than conditioning on the real one. `--groups` accepts both the split and
  exact Round 1 pairings, which the rules say the organiser sets; the input
  does not exist yet.

---

## 4. The card's two interesting slots are a coin flip

The shipped assignment gives Team Spirit `4-0` and Team Vision `4-1`. The swap
scores **0.003776** lower on the optimiser's own objective
**[bundle: `card/category_probabilities.csv`]**:

```
shipped (Spirit 4-0, Vision 4-1): 0.332004
swap    (Vision 4-0, Spirit 4-1): 0.328228
```

The pipeline's entire edge over a random card is 0.8479 slots
(4.5979 − 3.75) **[bundle: `card/recommended_card.json`]**. So this decision
turns on **0.45% of the total edge**, and the seed-stability diagnostic
confirms it: 4 of 16 teams are not seed-stable, and Spirit and Vision are two
of them **[bundle: `card/card_provenance.md`]**.

Those same two slots are the *only* places the card differs from sorting teams
by strength. So the pipeline's whole visible contribution is concentrated
entirely in its least stable decision.

### 4a. And under the corrected TI 2026 rules, that contribution is zero

Regenerating on the fetched rules (§3) moves **exactly those two slots, and
nothing else** — Spirit and Vision swap back:

```
objective   4.5979 -> 4.5903
Team Spirit   4-0  ->  4-1
Team Vision   4-1  ->  4-0
```

Which makes the corrected card **identical to the naive strength sort on all 16
slots**. It previously differed on 2.

So the simulation and the optimiser now add nothing at all to `sorted()` on this
field — and the two slots where they appeared to add something were an artifact
of modelling last year's elimination round. The pipeline's only visible
contribution over a sort was a bug.

That is not an argument for deleting the pipeline: on a different field, or once
the group draw is known, it could separate from the sort for real reasons, and
§5 shows a single card cannot measure which of them is better anyway. But it
does mean **nothing in the current shipping card requires any of the simulation
machinery to produce**, and any claim that the pipeline earns its complexity has
to come from somewhere other than this card.

---

## 5. A sixteen-slot card cannot measure skill — for anyone

**[bundle: `reports/d4_matched_window_corrected/`]**, training window matched to
production's 17.7 months:

- Pipeline: **4/16**
- Naive strength ladder (no simulation, no optimiser): **4/16**
- Random baseline: 3.75
- Percentile in the model's own distribution: 23.1%

n = 1 tournament. The simulation and assignment layers have never been shown to
beat `sorted()` on the one event available to score them against.

### 5a. What an expert scored, and why it reframes the whole section

**[producer: `ti26.cli_external_cards`, `reports/external_cards/`]**

Every benchmark above is internal — the pipeline against itself, against a
strength sort, against noise. None of them answers the prior question: **is this
task measurable at all?** An expert card does, because it is the strongest
realistic attempt available, and Noxville published two before TI 2025 with a
Glicko-2 model and domain knowledge this project does not have.

| card | published | score | P(random card scores at least this) |
|---|---|---|---|
| final, night before the event | 2025-09-08 | **5/16** | 0.3090 |
| first, twelve days out | 2025-08-22 | **4/16** | 0.5402 |

The null here is computed exactly rather than sampled: a random card is a
uniformly random arrangement of the capacities, so the hit distribution has a
closed form. Its mean is forced to Σc²/n = **3.75**, which is the same random
baseline quoted everywhere else in this project — the computation reproduces it
as an identity rather than an estimate.

**A random card matches or beats the expert's final card 31% of the time.** You
need **7/16** to reach p ≈ 0.05 and **8/16** to be clear of it. Nobody was close:
not this pipeline at 4/16, not the strength sort at 4/16, not the best public
analyst at 5/16.

So the honest reading of this section is not "our pipeline is weak". It is that
**one sixteen-slot card carries almost no information about forecasting skill**,
and a single event's card score cannot distinguish a good model from a lucky
one in either direction. The pipeline's failure to beat `sorted()` on one event
is a statement about the measurement, not only about the pipeline.

That has a direct consequence for what this project should optimise: the
series-level scoring below has 58 data points to the card's 16 slots, and it is
the only place a real signal has shown up.

The only positive out-of-sample result is series-level
**[bundle: `reports/series_score/`]**: 36/58 = 62.1%, one-sided p = 0.0435. At
35/58 it would be p = 0.074 and would fail its own pre-registered threshold. Its
own report states that 58 series sharing a patch, venue, meta and field are not
58 independent draws.

### 5b. Calibration contradicts itself across levels

- Per-map, 44k maps: overconfident, needs shrinking to 0.435.
- Per-series, TI 2025: slope **2.1165**, 95% CI [0.699, 3.534] — *under*confident.

Both are in the repo. If the series slope is anywhere near real, production
shrink is too aggressive and the card is systematically flattened toward the
middle categories. n = 58 cannot settle it.

Corroborating: the form diagnostic reads **5 teams "form ABOVE implied", 0
"BELOW"** **[bundle: `card/card_provenance.md`]**. Zero on one side is not what
noise around a well-scaled model looks like — though note the field is a
selected sample (teams qualify for TI by overperforming), so this is suggestive,
not decisive.

---

## 6. WITHDRAWN — "dead machinery"

This section claimed `duration_log_sigma` moved nothing and that the duration
machinery should be deleted. The measurement was correct and the conclusion was
exactly backwards.

Duration moved nothing **because it had been removed from the tiebreak order
that morning**. It is criterion 6 in TI 2026's published ranking — "Average
Game Duration (Shorter is Better)" — so the right response was to put it back,
which is done. A test now pins that a surviving tie consults duration rather
than falling through to the coin toss.

Kept rather than deleted because the failure is instructive: the measurement
was sound, reproducible and irrelevant. *"This parameter does not affect the
output"* was a fact about the code, and it was read as a fact about the
tournament. The strengthening plan's A1, which proposed ripping the rest of it
out, would have hard-coded the error.

The one real observation survives in weaker form: `cli_d2` warns loudly when
the fitted duration parameters drift from config, the runbook does not mention
it, and a fresh snapshot on lock day will very likely trip it. That is now
worth a runbook line rather than a deletion.

---

## What is NOT a weakness

Stated so the list above is read as calibration rather than as despair.

- **Reproducibility.** Content-addressed run bundles, SHA-256 manifests binding
  every output to a source revision, store digest and config digest. Numbers can
  be regenerated from committed bytes. This is better than most production ML.
- **Pre-registration.** Gates were registered before their code existed, and
  the register records what happened when results were disappointing — including
  the ones that failed.
- **Leakage discipline.** The backtest cuts folds 24h before each tournament's
  first match; `assert_fold_integrity` and `assert_no_leakage` are enforced.
  The series-scoring and D4 producers both use strict pre-cutoff training.
- **Identity.** Ratings follow the roster, not the organisation. This is the
  correct choice and most public Dota models get it wrong.
- **Honesty of the reports.** Every finding in sections 1, 4 and 5 above was
  read off a report *this project generated about itself*. The instrumentation
  works; the model is what is weak.
