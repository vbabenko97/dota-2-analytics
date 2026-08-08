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
explanations, and this project has not distinguished them:

1. **Real.** Teams stop playing publicly before a major — they qualify, then
   bootcamp privately.
2. **Artefact.** The tail of any OpenDota snapshot is incomplete, because match
   ingestion and parsing lag behind play.

Both produce the same immediate problem — the period whose form matters most is
the period with the least data — but they call for opposite responses. If it is
real, the model should widen its uncertainty. If it is ingest lag, the snapshot
should simply be taken later, and treating it as a real slowdown would be
wrong. **Distinguishing them is one query** (compare map counts for a fixed
historical window across two snapshots taken weeks apart) and both snapshots
already exist in `data/raw/`.

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

## 3. The rules engine is contradicted where it matters most

**[producer: `ti26.cli_pairing_check`, run against `release-deep.sqlite`]**

### 3a. The elimination rule does not reproduce the one bracket we can check

```
engine_reproduces_the_real_bracket: false, false, false, false, false   (5 seeds)
real_bracket_distance:              8
best_reachable_distance:            10
pairs_shared_with_engine:           3 of 5
```

`config/ti2026_rules.yaml` asserts
`elimination_round.maximize_ranking_distance: true`. TI 2025's real elimination
bracket scored 8 when 10 was reachable, so it did not maximise. Our engine
produces the maximising bracket and shares 3 of 5 pairs with what actually
happened, on every seed.

This governs the `elim_win` and `elim_loss` categories — **10 of the 16 card
slots**.

### 3b. Swiss pairing is much healthier, but not clean

15 of 17 buckets agree across all 5 seeds; 16 of 17 real pairings sit at
minimum ranking distance. Both disagreements are Round 2, Group A, where the
ranking is most tie-dominated, and one of them sat at distance 8 — the
*maximum* — against a minimum-distance rule.

### 3c. The config's own justification for the pairing tag is stale

[`config/ti2026_rules.yaml:155`](../../config/ti2026_rules.yaml#L155) tags
`base_pairing_preference: refuted_immaterial`, justified by a comment saying
the real pairing is among the engine's candidates "in 4 of the 11 buckets".
That comment is commit `b05569d`, 2026-08-07 — written **before** the rules
engine was corrected on 2026-08-08 (`23beac3`, `f96fb0e`). Re-running the
producer today gives 15 of 17.

A load-bearing tag resting on a number its own producer no longer reproduces is
the exact failure mode the correction register exists to prevent, reappearing
in a config file rather than in an audit.

### 3d. Most of the format is still inherited assumption

`tiebreak_order`, `within_group`/`cross_group`, the elimination rule and soft
repeat avoidance are all tagged `owner_transcript_2025_inherited`. TI 2026
published no pairing rules as of 2026-08-08, and Valve changed a rule
mid-event in 2025 without announcing it. The compendium screenshot fixed
`n_teams`, `total_rounds`, `advance_at_wins` and `eliminate_at_losses`; it says
nothing about pairing.

Groups are also still unannounced, so the card currently averages over draws
rather than conditioning on the real one. The machinery to condition is in
place (`--groups`); the input does not exist yet.

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

---

## 5. Card-level skill is undetectable

**[bundle: `reports/d4_matched_window_corrected/`]**, training window matched to
production's 17.7 months:

- Pipeline: **4/16**
- Naive strength ladder (no simulation, no optimiser): **4/16**
- Random baseline: 3.75
- Percentile in the model's own distribution: 23.1%

n = 1 tournament. The simulation and assignment layers have never been shown to
beat `sorted()` on the one event available to score them against.

The only positive out-of-sample result is series-level
**[bundle: `reports/series_score/`]**: 36/58 = 62.1%, one-sided p = 0.0435. At
35/58 it would be p = 0.074 and would fail its own pre-registered threshold. Its
own report states that 58 series sharing a patch, venue, meta and field are not
58 independent draws.

### 5a. Calibration contradicts itself across levels

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

## 6. Dead machinery

**`duration_log_sigma` moves nothing.** Duration was removed from the tiebreak
order on 2026-08-08, but [`duration.py:196-210`](../../src/ti26/duration.py#L196)
still sweeps it and [`cli_d2.py:210`](../../src/ti26/cli_d2.py#L210) still
aborts the run if the fitted value drifts from config. Verified: sigma 0.05 vs
5.00 — a 100x change — moves the category marginals by a maximum absolute delta
of **0.0**. A staleness gate on a parameter with no path into the model can only
ever produce false alarms.

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
