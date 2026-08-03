# TI 2026 Swiss Stage Forecast — ML System Design

**Date:** 2026-08-01 (rev 2, incorporating GPT-5.6 Pro review)
**Problem summary:** Produce one prediction card assigning all 16 TI 2026 teams to six fixed Swiss-stage outcome categories, maximizing the expected number of correct assignments, before predictions lock at 2026-08-13 10:00 China Standard Time (04:00 CEST).
**Maturity:** POC. One-shot forecast with a hard deadline. All 12 sections retained, abbreviated. No production deployment follows.

**Scope tiers** (referenced throughout):
- **Tier 0** (~1 day): public ratings + exact Swiss simulator + Hungarian optimizer. No custom model.
- **Tier 1** (~4 days) — **this document**: Tier 0 plus own map-level Glicko/Bradley-Terry fit, roster-hash canonicalization, market-informed prior. Card ships at end of D4.
- **Tier 1+** (D5, +1 day): meta/hero-pool work (§VIII). The scouting report ships unconditionally; one gated scalar feature may regenerate the card.
- **Tier 2** (~11 days): schedule-scenario ensemble, robust card, full Codex differential audit. Entered only if the D2 forecast-value gate (§II) justifies it.

---

## Evidence status

Claims fall into four provenance tiers. Treating them as equally solid is the fastest way to build the wrong thing.

**A. Verified in this session (arithmetic, reproducible):**
- Given a 16-team Swiss where 4 wins advances and 4 losses eliminates, final category capacities are structurally forced to `[1, 2, 5, 5, 2, 1]` regardless of who wins. Every record group has even size at every round, so the split is deterministic. Derivation in §I.
- Random-assignment baseline: `Σ kc²/16 = (1+4+25+25+4+1)/16 = 3.75` expected correct entries.
- **Consistency check:** teams advancing = `1 (4-0) + 2 (4-1) + 5 (elimination winners) = 8`. This independently corroborates the capacity structure against tier B's separately-sourced "eight teams survive to the main event" — the 8 was not used to derive the capacities.
- `https://www.dota2.com/esports/ti15/tirules` and the Valve predictions news post are **JS-rendered**; plain HTTP fetch returns only the page title. Confirmed by two WebFetch calls returning no body content.
- **Duration is not a rare tiebreak.** Instrumented D1 runs: 4.79 duration lookups per ranking call, in 300/300 simulated tournaments; 23.9% of ranking instances across 500 tournaments. Structural, not a modelling artefact — see §XII.
- **OpenDota data availability, measured 2026-08-02** (queries and figures in §III): the `/explorer` SQL endpoint serves the full map-level schema including rosters, unkeyed; 41,627 maps over 18 months with 100% roster coverage; unkeyed REST cap is 3,000/day; recent monthly volume has fallen to ~1–15% of its 2025 level; league `tier` labels are unmaintained for 2026.

**B. Reported verified by GPT-5.6 Pro against official Valve pages (2026-08-01), with citations this session could not open. Corroborated by the tier-A consistency check. Pending D1 confirmation:**
- 16 teams; five-round Swiss group stage on August 13–16; five elimination matches; eight teams surviving to the main event.
- Standings tiebreak order: matches won → matches lost → total matches won by previous opponents → game-win percentage → opponents' average game-win percentage → average game duration (shorter better) → coin toss.
- Organizer-set Round 1 groups and matches; Rounds 2–3 within initial groups; Round 4 across groups; maximum ranking distance for Round 5 matches where the loser is eliminated.
- Sequential opponent selection by the five 3-2 teams from the five 2-3 teams.
- Prediction lock: 2026-08-13 10:00 China Standard Time = **04:00 CEST**. Event is in Shanghai, which resolves the CST ambiguity to UTC+8 rather than US Central.

**C. Sourced from [gpt-pro-output.md](../../../gpt-pro-output.md), not independently verified:**
- Roster aliases (Iron Wing / Team Vision / BoomBoys / HULIGANI).

**D. Unknown:**
- Whether categories carry unequal point values. This changes the optimizer objective directly (§XII) and is a D1 item.

D1 performs browser verification as a **regression check and archival snapshot**, not as a project blocker. Tier B is strong enough to build against.

---

## I. Problem Definition

Valve's TI compendium asks for a complete assignment of 16 teams to six categories. The card is submitted once and locked; there is no revision after play begins.

Category capacities, derived from the format:

```
R1: 16 teams        → 1-0:8   0-1:8
R2:                 → 2-0:4   1-1:8   0-2:4
R3:                 → 3-0:2   2-1:6   1-2:6   0-3:2
R4:                 → 4-0:1   3-1:4   2-2:6   1-3:4   0-4:1
R5: 4-0 and 0-4 are done (advanced / eliminated)
    3-1 (4) → 2×4-1 + 2×3-2
    2-2 (6) → 3×3-2 + 3×2-3
    1-3 (4) → 2×2-3 + 2×1-4

Final: 4-0:1  4-1:2  3-2:5  2-3:5  1-4:2  0-4:1   = 16
Advancing: 1 + 2 + 5 elimination winners = 8       ✓ matches official count
```

The 3-2 and 2-3 teams then play five elimination matches, producing 5 winners and 5 losers. The six card categories are therefore `4-0`, `4-1`, `Elim winner`, `Elim loser`, `1-4`, `0-4` with capacities `[1, 2, 5, 5, 2, 1]`.

**Stakeholder:** the author, a single user submitting one card. No downstream consumer.

**Cost of a wrong prediction:** near zero in real terms — compendium points. The genuine cost is wasted build time and, in the failure case that matters, missing the lock deadline entirely.

**Why existing solutions fall short:** public forecasts (Noxville's Glicko + Monte Carlo, betting markets) estimate *tournament winner* or *match* probabilities. Neither publishes the joint distribution over these six specific Swiss categories, and neither solves the constrained assignment. The simulator and optimizer are the parts nobody else has built for this card.

**Known risks:** deadline missed; over-dispersed simulator producing a card indistinguishable from random; a rules-engine bug in pairing or tiebreak logic that shifts assignments systematically.

---

## II. Metrics and Losses

**Objective (business KPI):** expected number of correct category assignments, out of 16.

**External baseline:** 3.75 (random card chosen independently of the outcome). This is a property of the capacity vector, not of any model.

**Model metric (offline):** per-map log loss on rolling out-of-sample pro matches, with Brier score and calibration slope/intercept as secondary. Accuracy is reported but never used for selection — it is not a proper scoring rule and rewards threshold-crossing rather than honest probabilities.

**Loss:** binary cross-entropy on map outcomes. Links to the KPI through the simulator: calibrated map probabilities → calibrated series scores and tiebreakers → calibrated category marginals `P[team, category]` → the assignment that maximizes `Σ x·P`.

**Trade-off that actually binds:** discrimination in the middle of the table versus at the extremes. The two 5-capacity slots carry `50/60 = 83%` of the random baseline's expected score, and they contain the teams the model separates worst. Effort spent sharpening the 4-0 pick is close to wasted.

### The optimizer objective is descriptive, never evidence

`Σ x·P` is computed from the model's *own* estimated probabilities. A model that assigns 0.8 to sixteen incorrect assignments reports an objective near 12.8 — that demonstrates access to multiplication, not forecasting skill. **The optimizer objective is never used as evidence of model quality.**

Where reported, it carries the qualifier: *model-implied expected score under the assumption that its category probabilities are calibrated.*

### D2 gates — two separate checks

**Engineering gate (blocking).** By end of D2 the pipeline produces a legal card from any strength vector, and the `as_of` leakage assertion passes.

**Forecast-value gate (decides whether D3–D4 happen).** Proceed with custom Bradley-Terry development only if roster-aware Glicko beats Elo by the pre-registered paired out-of-sample log-loss margin below, while remaining adequately calibrated.

**Pre-registered, 2026-08-02, before any backtest was run:**

```
mean(LL_elo − LL_glicko) ≥ 0.003 nats/map
AND paired bootstrap 95% CI on that difference excludes 0
```

Both conditions, not either. With ~40k maps the significance test alone would pass on differences far too small to move a card, and an effect size alone can be sampling noise. The margin is registered here, in the spec, with a date — moving it after seeing a result voids the gate.

**Diagnostic, not a gate:** whether the custom model materially changes at least one card slot relative to the public-rating fallback. A difference establishes that the custom model *matters*, not that it is *better*. If the log-loss gate fails and this diagnostic passes, investigate — but ship the fallback. A card that differs without demonstrated out-of-sample skill is noise with extra steps.

### D3 calibration gate

**Pre-registered, 2026-08-02, before any calibration was fitted or scored.**

The D2 gate above failed, and worse: *no* rating model beat the rung-1 constant floor (elo +0.0013142, glicko +0.0051449, ewma +0.0133990 nats/map worse than a coin flip — see `docs/audits/2026-08-02-d2-build-ledger.md`). The measured diagnosis is miscalibration, not absent signal: accuracy exceeded 50% for all three models (elo 0.5363, glicko 0.5439) while calibration slopes sat at 0.2126 / 0.4448 / 0.4023 against a target of 1.0, i.e. the predicted logits are roughly 2.2× too wide. `backtest.calibration()` already computes the correcting slope and intercept on every run and nothing applies them.

Applying that correction and re-running the D2 gate would be post-hoc: the D2 gate was registered against uncalibrated models, and re-using it after seeing which way the models failed is exactly what pre-registration exists to prevent. So D3 gets its own gate, registered here first:

```
mean(LL_constant − LL_calibrated) ≥ 0.003 nats/map
AND paired cluster bootstrap 95% CI on that difference excludes 0
AND calibration slope of the calibrated model ∈ [0.9, 1.1]
```

All three conditions, not any. The margin and the bootstrap match D2's gate exactly — same value, same clustered method over tournaments then series, so the two results are directly comparable. The slope band is the target this spec's own build plan already set for D3, and it is included because a model can clear a log-loss floor while remaining badly calibrated, and calibration quality is the entire claim under test.

The calibration must be fitted **inside each backtest fold**, from that fold's training data only. Fitting it on the full history and then scoring the folds would leak the test outcomes into the correction and produce a number that cannot fail.

**If this gate fails:** ship the rung-3 public-rating card (§X), and do not proceed to a custom Bradley-Terry model. Two failed gates on the same data is evidence about the data, not a reason for a third attempt with a looser bar.

---

## III. Dataset

| Source | Content | Notes |
|---|---|---|
| **OpenDota `/explorer`** (primary) | map-level results **and rosters**, 18 months, in ~19 monthly SQL queries | Public Postgres-backed SQL endpoint. No API key. Measured 2026-08-02: a full month (3,011 maps, 1.0 MB) returns in 0.44 s with no row cap |
| OpenDota REST | spot checks, `picks_bans` backfill for D5 | Live headers measured 2026-08-02: `x-rate-limit-remaining-minute: 59`, `x-rate-limit-remaining-day: 2998` — the unkeyed daily cap is **3,000**, not the 2,000 previously recorded here |
| Liquipedia | roster history, tournament brackets, alias resolution | Only where explorer rosters are insufficient. Requires descriptive User-Agent |
| Betting markets | outright odds as external ranking prior; H2H odds post-schedule | See §VIII |

**STRATZ is no longer on the critical path.** It was specified to supply rosters, league tiers, and durations. The explorer returns all three, unkeyed, in one query. Keeping a keyed dependency for data we already have would add a credential and a failure mode for nothing.

**Ingestion is not the bottleneck it was designed around.** The original plan implied ~19,000 per-match REST calls to obtain rosters — six days against a 3,000/day cap, which would not fit inside D2. Measured alternative:

```sql
select m.match_id, m.start_time, m.duration, m.radiant_win, m.leagueid, l.tier,
       m.radiant_team_id, m.dire_team_id, m.series_id, m.series_type, mp.patch,
       array_agg(pm.account_id order by pm.player_slot) as accounts,
       array_agg(pm.hero_id    order by pm.player_slot) as heroes
from matches m
join match_patch    mp on mp.match_id = m.match_id
join player_matches pm on pm.match_id = m.match_id
left join leagues    l on l.leagueid  = m.leagueid
where m.start_time >= :month_start and m.start_time < :month_end
group by 1,2,3,4,5,6,7,8,9,10,11
```

Chunk by month to stay well under any timeout. Total ≈ 41,600 maps, ≈ 19 MB, under a minute.

**Measured data-quality facts (2026-08-02), superseding assumptions:**

- **Roster coverage is complete.** 41,627 of 41,627 maps over 18 months have player rows. Roster hashing needs no fallback path.
- **Recent pro volume has collapsed.** Monthly counts hold ~2,200–3,000 through 2026-05, then 1,113 (Jun), 435 (Jul), 44 (Aug 1–2). A 90-day half-life window contains roughly 1,600 maps *in total*, of which TI contenders are a fraction. The §VI "few tier-1 maps → overconfident rating" corner case is therefore the **default condition, not an edge case** — uncertainty inflation must be on by default, and the report must name which teams are prior-driven.
- **League tier metadata rots.** `tier in ('premium','professional')` selects 2,152/3,011 maps in 2025-09 but 455/2,480 in 2026-05. Recent leagues are unlabeled, not downgraded.
- **≈6.7% of maps carry a null team ID** (203/3,011 in the sampled month). Handle explicitly; never drop silently.

**League scope decision:** fit on **all** ingested maps, carrying `tier` and `league_id` as covariates/weights rather than filtering. A tier filter would discard ~80% of 2026 maps for a metadata-maintenance reason unrelated to match quality, putting the filter in direct conflict with recency weighting.

**Unit of observation:** one map (not one series). Game-win percentage and average duration are official tiebreakers, so a series-only simulator cannot reproduce standings.

**Fields per map:** `match_id, series_id, league_id, start_time, patch, radiant_team_id, dire_team_id, radiant_players[5], dire_players[5], winner, duration, lan_or_online, best_of, forfeit_flag, standin_flags, picks_bans, player_hero_ids`.

`picks_bans` and `player_hero_ids` are captured on D2 even though the features consuming them are deferred to D5 (§VIII). They arrive in the same match-details payload the core model already pulls, so marginal ingest cost is zero — whereas refetching 18 months of matches through rate-limited APIs later costs about a day. Asymmetric enough to capture unconditionally.

**Entity resolution:** statistical identity follows the roster, not the organization.

```
display_team_id      # organization name, for presentation only
roster_version_id    # hash(sorted(player_account_ids))
```

New rosters initialize from a weighted blend of the predecessor team's rating, retained players' recent ratings, and a regional prior — weighted by roster continuity. Without this, a re-branded org appears as a team with no history and receives the global prior, which is badly wrong for a roster that has played together for a year.

**Known quality issues:** forfeits and stand-ins contaminate results (flag and downweight, do not silently drop); patch labels must be read per-map, not inferred from tournament dates, because concurrent events do not switch patches simultaneously; online and LAN results are not exchangeable.

**Historical depth:** 18 months with time decay rather than a hard cutoff. [ASSUMPTION: 90-day half-life as the starting value — see §VII on why this is not tuned aggressively]

---

## IV. Validation Schema

Random train/test splitting is invalid. It lets future matches inform past predictions, which produces excellent metrics and useless forecasts.

**Rolling event cutoffs:**
1. Pick a historical tournament.
2. Set the data cutoff to 24h before its first match.
3. Reconstruct rosters exactly as they existed at that cutoff.
4. Fit on earlier matches only.
5. Predict every map in the tournament.
6. Advance.

**Leakage test (automated, blocking):** assert no training row has `start_time > as_of`. This is the single reproducibility check worth automating; it catches the failure mode that silently inflates every other metric.

### TI 2025 replay is rules validation, not category calibration

One tournament yields one 4-0 observation, one 0-4, two in each of 4-1 and 1-4, and five in each middle category. Category calibration cannot be assessed from that, and a vague "the simulation looks plausible" gate is trivially satisfiable after seeing the answer.

**Rules validation (hard pass/fail):**
- The engine exactly reproduces all known TI 2025 pairings and final records when fed the actual match results.

**Posterior predictive checks (weak, honest plausibility only).** Under pre-event strengths, the observed TI 2025 summary statistics should not be extreme:
- number of favorite series wins;
- number of 2-0 series;
- strength ranks of the 4-0 and 0-4 teams;
- aggregate record by pre-event strength quintile.

**Failure here is diagnostic, not a license to tune simulator variance against this single event.** Forecast validation proper comes from map- and series-level rolling backtests across many historical tournaments, including ones whose formats differ.

**Re-validation:** on each re-run as new results land (1win Essence II, Games of the Future, schedule reveal). Model specification freezes after D4; later runs update parameters, not structure.

---

## V. Baseline Solution

Ordered floor-to-ceiling. Each must be beaten on rolling out-of-sample log loss to justify the next.

1. **Constant:** every map 50/50. Log loss = 0.693.
2. **Random card:** 3.75 expected correct. External baseline for card scoring.
3. **Exponentially weighted recent map win rate.** No opponent adjustment.
4. **Elo**, map-level. The comparator for the D2 forecast-value gate.
5. **Glicko-2**, roster-aware, map-level. The rating deviation is the reason to prefer it over Elo here — qualifier teams and freshly assembled rosters genuinely are uncertain, and pretending otherwise distorts the tails, which is exactly where the 4-0 and 0-4 slots live.
6. **Public external ratings** (Noxville, datdota) as the fallback strength source and sanity anchor. If our top-4 ordering diverges wildly from theirs, debug before trusting.

---

## VI. Error Analysis

**Residuals:** calibration plots per rating-gap decile. The failure mode to hunt is over-dispersion at large gaps — a model that says 65% when the truth is 80% will produce category marginals flattened toward 1/16 and a card barely better than random.

**Corner cases with named handling:**

| Case | Risk | Handling |
|---|---|---|
| Newly formed roster (qualifier teams) | Prior dominates; arbitrary | Inflate rating deviation; report which teams are prior-driven |
| Re-branded org (Iron Wing, Team Vision, BoomBoys, HULIGANI) | History lost, team looks new | Alias table + roster-hash continuity |
| Forfeits / stand-ins | Fake results move ratings | Flag columns, downweight |
| Team with few tier-1 maps | Overconfident rating | Uncertainty inflation |
| Patch transition | Stale hero-context assumptions | Per-map patch label; see §VIII |

### Three distinct variance sources, and why the series shock defaults to zero

- **Parameter uncertainty** — uncertainty about a team's true persistent strength. Sampled once per simulated tournament.
- **Series state** — temporary variation shared across maps of one series: form, strategic matchup, draft adaptation, illness.
- **Map randomness** — conditional Bernoulli noise once strength and series state are fixed.

Parameter uncertainty and series state produce the *same* within-series correlation signature, so the aggregate 2-0 versus 2-1 ratio cannot identify them separately. Calibrating a series shock against that ratio alone would be fitting a free parameter to a statistic that does not constrain it.

**Default: conditional map independence within a series.** Tier 0 and the initial Tier 1 card assume no series shock. A Bo3 already contains ample variance, and parameter uncertainty alone induces some within-series correlation.

**Identification, if the shock is added at all.** Compare, controlling for pre-series predicted probability `p` and side:

```
P(win map 2 | won map 1, p)   vs   P(win map 2 | lost map 1, p)
```

The gap measures within-series dependence directly. A shared series shock is added only if rolling historical residual analysis shows material dependence after those controls, and its variance is fixed from that analysis before any TI simulation.

---

## VII. Training Pipeline

Python. `uv` for dependency management. No experiment-tracking service — a CSV of run metadata is proportionate to a five-day POC.

**Reproducibility — kept:** explicit seeds on every random operation; immutable timestamped raw snapshots (`data/raw` never overwritten); the `as_of` leakage assertion.

**Reproducibility — deliberately cut:** CI instruction-drift checks, config-SHA in every report, five lifecycle hook types, five subagent definitions. These cost roughly a day and a half and buy zero forecast accuracy on a one-shot personal prediction. This is a departure from [gpt-pro-output.md](../../../gpt-pro-output.md) §8 and it is intentional.

**Hyperparameters are set, not searched.** Paired per-map log-loss differences between two similar rating configurations are resolvable on a few thousand pro maps. Selecting the best of a twenty-configuration grid is not — that is winner's curse, and the expected out-of-sample gain lands well below the in-sample gain that motivated the choice. Budget: two or three candidate half-lives, one paired comparison, one hour. Not two days.

---

## VIII. Features

**Core model inputs.** Dynamic Bradley-Terry on the logit scale:

```
logit P(A beats B on a map) = s_A(t) - s_B(t) + βᵀX
```

`X` holds a deliberately short list: LAN vs online, roster continuity, region, recent inactivity, patch.

### Market integration — no outright inversion

Inverting outright championship odds through the simulator to a strength vector is an ill-posed inverse problem, not one operation. Championship odds bundle playoff performance, seeding, and bracket effects; many strength vectors produce nearly identical title probabilities; bookmaker margins and cross-market inconsistencies survive de-vigging; and optimization is unstable for long-shots. It would also require a credible playoff model that this project's objective does not otherwise need. **Removed from Tier 1.**

```
Pre-schedule outright markets are used as an external ranking and sensitivity
prior, not inverted into a uniquely identified strength vector. Optionally fit
one scalar affine mapping from de-vigged log odds to the existing strength
ordering, without claiming the result is bookmaker-implied Swiss strength.

Primary market integration begins after Round 1 matchups publish:
- de-vig H2H series prices;
- convert series probabilities to map-level strength differences under the
  same Bo3 model;
- shrink toward the statistical model;
- report sensitivity to the shrinkage weight.
```

The shrinkage form is unchanged:

```
s_final = w · s_market + (1 - w) · s_model      # logit scale
```

`w` is **not fitted** — backtesting it needs a historical odds archive not obtainable in the time available, and a weight fitted on one event is fake precision. Report the card across `w ∈ {0, 0.25, 0.5, 0.75, 1}`. `w = 0.5` is acceptable as the centre of a sensitivity analysis, but is **not** claimed as an evidence-backed default.

The sweep is the deliverable, not the weight. A card stable across `w` means the market/model distinction did not matter here. A card that flips has identified exactly which teams the model disagrees with the market about.

### Meta / hero-pool work (D5) — one guaranteed artifact, one optional experiment

```
D5: build hero-strength + player-affinity tables
     ├─→ reports/meta_scouting.md      ships unconditionally
     ├─→ manual_adjustments.yaml       bounded human judgment
     └─→ one gated scalar feature      regenerates card only on a passing test
```

#### Guaranteed artifact — `reports/meta_scouting.md`

Deliberately minimal so it cannot fail to ship:

1. **Hero contest rates** (pick+ban %), for current and broad patch windows.
2. **Player-hero sample counts** — 80 TI players against top-contested heroes, last 12 months of pro play.
3. **Pool breadth** per player.
4. **Low-sample warnings**, prominent.

Built entirely from the pro-match corpus ingested on D2. **No external scraping.** Dotabuff's hero pages are public-match data by default, and pub meta diverges sharply from drafted Bo3 pro meta — a tier list built from pubs would mislead about TI. [ASSUMPTION: Dota2ProTracker is a closer-population external cross-check if one is wanted — current state and queryability unverified]

**Lead with contest rate, not win rate.** Strong heroes get banned, so they accumulate few games and their win rate looks unremarkable — selection contaminates the metric Dotabuff presents first. Ban rate is the pro scene's revealed opinion of hero strength, closer to a market price than a performance statistic.

**Report pool presence confidently, pool win rate cautiously.** Whether a player has demonstrated a hero in pro play over 12 months is near-binary and reliable. Whether they are *good* on it is a win rate on single-digit n. That distinction is most of what separates a useful scouting document from a misleading one.

**Report both patch windows, do not collapse.** 7.41e is days old, so a pro-only tier list restricted to it has almost no sample. Show it alongside the broader 7.41 window with explicit game counts and let the disagreement be visible.

#### Optional experiment — one scalar first

The full three-feature programme (role mapping across roster changes, hero-strength regression, player-by-hero matrices, patch-transition event construction, post-ban pool approximation, historical adaptation, leakage-safe backtest across 6–12 events, plus the report) does not fit in one day. The likely outcome of attempting it is not failure but a plausible-looking implementation whose edge cases were never inspected.

**Order, strictly:**

| Priority | Feature | Definition | Rationale |
|---|---|---|---|
| 1 | `patch_adaptation` | win-rate delta in the 3 weeks after a patch vs trailing baseline, averaged over many historical patches | cleanest causal story; does not depend on forecasting the current TI draft distribution; survives TI-specific meta divergence because adaptability is a trait, not a fit to one meta |
| 2 | `pool_breadth` | entropy / unique-hero count per player over last N maps | the draft is adversarial. Three elite meta heroes get banned — that value shows up as ban pressure, not wins. Fifteen serviceable heroes cannot be banned out |
| 3 | `meta_fit` | overlap of the team's decayed pick distribution with rating-adjusted patch hero strength, over the expected post-ban pool | **deferred** unless 1 and 2 are implemented early and tested. Weakest: measures fit to a pre-TI meta that TI partly invalidates |

**Why the feature can add anything at all.** Outside a patch transition it is redundant — a team exploiting the current meta has been winning, and time-decayed ratings already encode that. Its entire claim to incremental value is the window between a patch landing and ratings catching up. 7.41e landed days ago and TI is ~12 days out, so this forecast sits inside that window.

**Hero strength must be rating-adjusted, not raw win rate.** Fit over all pro maps on the patch:

```
logit P(radiant win) ~ Σ hero_indicators + (s_radiant − s_dire)
```

Hero coefficients then read as strength net of team quality — the correct fix for circularity. Leave-one-out exclusion of a team's own maps is noisy over 16 teams and only partially works.

Measure at player level and aggregate to roster, since rosters change — which is why the original observation was about players rather than teams.

**Pre-registered acceptance test:**

> Meta features improve out-of-sample paired log loss **on matches played within 21 days of a major patch.**

Test on every tier-1 tournament in the last 18 months starting shortly after a patch — likely 6–12 events, though the count is a guess and should be checked before building. Fit with and without on pre-cutoff data only; paired comparison restricted to those matches, since the feature makes no claim outside the window. If the event count is too small to resolve the comparison, stop rather than run an underpowered test and read the result anyway.

**Hard exclusion: no draft-conditional modeling.** TI drafts are unobservable before they happen, so a draft→outcome model requires a draft→draft model, doubling error for no gain.

### Manual adjustments — bounded, not banned

Real information lives outside match data: stand-ins, visas, illness, coach changes. Discarding it is a modeling choice, not rigor.

Mechanism: `manual_adjustments.yaml` with `(team, delta, reason, source_url, timestamp)`, committed **before** the optimizer runs and printed in the final report.

**Cap: ±0.10 logit by default.** ±0.25 is reserved for severe, sourced events such as a confirmed stand-in, and must be justified in the reason field.

The bound is stated in units the reader can feel, because "bounded" adjustments are routinely given bounds wide enough to drive a truck through:

| Delta | Map prob (from 50%) | Bo3 prob (independent maps) |
|---|---|---|
| ±0.10 | 52.5% | 53.8% (+3.8pp) |
| ±0.25 | 56.2% | 59.3% (**+9.3pp**) |

---

## IX. Measuring and Reporting

**Offline results:** rolling backtest log loss and Brier vs each §V baseline; calibration slope and intercept; the TI 2025 rules replay and posterior predictive checks (§IV).

**Acceptance thresholds:**
- Calibration slope ∈ [0.9, 1.1], intercept ≈ 0.
- Beats Elo on paired out-of-sample log loss by the pre-registered margin.
- Monte Carlo standard error below 0.001 on the largest category probability. At 250k simulations the worst-case single-probability standard error is ≈0.1pp; running a million because the number is comforting is ritual, not method.

**Simulator invariants — hold in 100% of runs:**
- Category counts exactly `[1,2,5,5,2,1]`; each team in exactly one category.
- No self-pairings.
- **No repeated opponent occurs when a legal non-repeat perfect matching exists.** The official rule avoids repeats *where possible*, not absolutely. Property tests must construct cases where a repeat is forced and assert the engine takes it rather than failing.
- Rounds 2–3 within initial groups; Round 4 cross-group.
- **Equal-strength symmetry, with finite-sample tolerance:** for equal-strength teams and symmetric schedule generation, every team's estimated category probability lies within a predeclared Monte Carlo tolerance of `kc/16`. Additionally test label-permutation invariance using the same random streams — an exact `kc/16` assertion is true only in expectation and only if schedule generation, pairing tie resolution, elimination choice, and team labels are all exchangeable.

**Reporting:** `final_report.md` with the card, category probability table, the `w` sweep, backtest metrics, and the manual-adjustment register. Audience is the author.

**A/B Testing:** Deferred until production.

---

## X. Integration

"Integration" means a human pasting 16 team names into a web form before the lock.

**Deliverables:** `category_probabilities.csv`, `recommended_card.json`, `schedule_sensitivity.csv`, `final_report.md`, `reports/meta_scouting.md` (§VIII).

**Fallback ladder**, in order, if a component fails:
1. Full pipeline: own ratings, market-shrunk once H2H odds exist.
2. Own ratings unblended.
3. Public ratings (Noxville) piped straight into the simulator. This is the rung for a D2 ingestion failure, and the default if the forecast-value gate fails.
4. Hand-ordered strength vector into the simulator.

Every rung produces a valid card. The simulator is the component that must not fail — which is why it is built first, on synthetic ratings, before any data exists.

**Correction, 2026-08-02 (D3 rung-3 build).** Rung 3 fired: the D2 forecast-value gate failed and, separately, no rating model cleared the spec V floor (see `docs/audits/2026-08-02-d2-build-ledger.md`). Rung 3's named source, "Noxville, datdota", is UNREACHABLE from this environment — HTTP 403 to every access path tried, including the Internet Archive's own crawler, and Noxville's public dataset dead since 2020-12-29 (full survey: `docs/audits/2026-08-02-rung3-source-research.md`). Built instead from OpenDota's own `team_rating` table, via the existing `explorer_query` seam — no new network path. The scale conversion from that table's raw `rating` column to a logit (`math.log(10) / 400`, matching this repo's own Elo convention) is tagged **`inferred`**: OpenDota documents no divisor for this specific table, and unlike Elo/Glicko a public rating snapshot cannot be backtested to check it. See `reports/rung3_provenance.md` for the per-team ratings, the scale-sensitivity sweep with its noise floor, and the Elo-ordering sanity anchor.

---

## XI. Monitoring

Monitoring here means watching for the schedule reveal and for late results, not model drift in production.

**Schedule watcher — escalating cadence, cheapest method first:**

```
Aug 1–8:            every 12 hours
Aug 9–11:           every 3 hours
Aug 12 until lock:  hourly
```

Try a lightweight fetch or search endpoint first; Playwright is the fallback for JS-rendered content, not the foundation of a page diff. Polling only from Aug 9 risks missing an early publication, and daily polling now is nearly free.

- **Late results:** re-ingest after 1win Essence II and Games of the Future conclude (~Aug 5).
- **Data quality:** re-run the `as_of` leakage assertion and the simulator invariants on every re-run. Non-negotiable, blocking.
- **Sanity:** compare the top-4 ordering against public ratings and market odds each run. A wild divergence is a bug signal, not an edge signal.

**Schedule-sensitivity experiment (D4, 30 minutes).** [gpt-pro-output.md](../../../gpt-pro-output.md) §2 proposes four schedule families plus an adversarial search. Swiss self-corrects, so the prior here is that round-1 pairing barely moves final-category probabilities except at the 4-0 and 0-4 extremes. Test it: run uniform-legal vs seed-banded, measure `max|ΔP_{i,c}|`. Below ~2pp, delete the robust card and the adversarial search.

---

## XII. Serving and Inference

**Requirements:** one batch run, minutes not milliseconds, single machine. 250k–500k simulations. No latency or throughput constraint worth naming.

**Architecture:**

```
ingest → roster canonicalization → ratings fit → market shrinkage
       → Swiss simulator (maps → series → standings → pairings → elimination)
       → P[team, category] → Hungarian assignment → card
```

**Optimizer.** Expand the six categories into 16 individual slots and solve the assignment maximizing `Σ x_{i,c} · P_{i,c}` subject to `Σ_c x_{i,c} = 1` and `Σ_i x_{i,c} = k_c`, via the Hungarian algorithm. Greedily taking the argmax team per category is wrong — it duplicates teams and violates capacities.

If categories carry unequal point values, multiply `P_{i,c}` by the category weight before solving. Verify on D1.

**Lazy duration evaluation — and a corrected claim about how often it fires.**

Average game duration is the sixth tiebreak criterion. Lazy evaluation is still correct: compute it only for ties surviving the first five criteria, and skip it entirely where no plausible duration could change a pairing or an elimination-choice order.

```
Duration is evaluated lazily. The simulator computes it only for standings
ties surviving the first five criteria, memoised per team and extended as
maps accumulate.
```

**The rationale originally given for that design was wrong, and the D1 build measured it.** This section previously asserted that ties reaching criterion 6 are "rare" and that duration therefore has "almost no influence on the card". Instrumented runs say otherwise: across 300 simulated tournaments, **every single run consulted the duration resolver, at an average of 4.79 lookups per ranking call — roughly 30% of the 16 teams, in every round from 2 onward.** Independently reproduced by a reviewer.

The cause is structural, not a modelling artefact. Criteria 1–5 are coarse integers and small-denominator rationals computed over four or five games. In a 16-team bracket that resolution simply cannot separate the field, so near-ties are the norm. **Real TI standings have the same property**, which means Valve's published order genuinely reaches the duration criterion often.

Three consequences:

1. **The duration model is load-bearing, not decorative.** It is currently a placeholder log-normal carrying `arbitrary` provenance in `ti2026_rules.yaml` — our invention, not a Valve statement. It is steering ~30% of every ranking, and ranking drives pairing distance and elimination pick order.
2. **Durations persist within a tournament.** Samples are memoised per team and extended as maps accumulate, so a team that draws short durations early keeps that ranking edge in later ties. That is more realistic than an independent per-round coin toss — fast teams do keep playing fast — but the strength of the persistence is set by an invented `log_sigma`.
3. **D2 must fit the duration model from real data.** `duration` is already in the D2 raw schema (§III), so the data is arriving regardless. Fit the distribution, conditioned at minimum on rating gap, and re-run. If fitting proves impractical, run a sensitivity check across plausible `log_sigma` values and report how much the card moves.

This does not bias the forecast in an obvious direction — teams are exchangeable a priori, so an invented tiebreak behaves like a persistent random one. But it does mean a meaningful share of simulated standings is decided by a fabricated parameter, and that must not be reported as skill-driven.

**Correction, 2026-08-02 (Task 7 measurement).** Consequence 1 above conflated two separate claims: that the resolver is consulted often (true, measured above) and that the `log_sigma` parameter *moves the card* (asserted, not measured). `duration.sensitivity_sweep` now checks the second claim against its own resampling noise rather than assuming it, and the measured answer is that it does not, at least not resolvably. Its noise-floor control — two runs of the *same* baseline sigma under different seeds, tied strengths, `n_sims=20000` — produced a max-abs-delta of 0.0107, while every sigma-varying comparison tried (0.05 → 1.20, tied strengths: 0.0050–0.0093 across seeds 5–7; the same sweep with strengths spread `(i − 7.5) × 0.35`: 0.0061–0.0070) fell at or below that same noise floor. Mechanism: `DurationResolver` draws i.i.d. per-team lognormal noise, so rescaling `log_sigma` rescales all 16 exchangeable teams' noise equally and leaves the ranking distribution close to invariant; varying sigma also desynchronises the RNG stream between runs, so the shared `seed` buys almost no common-random-numbers variance reduction to help separate signal from noise. **Conclusion: `log_mean` still matters — it sets the resolver's centre, and the resolver is consulted on ~30% of rankings regardless. `log_sigma` is low-risk: the resolver's high consultation rate does not translate into this parameter measurably steering where standings land.** `sensitivity_sweep` reports a `noise_floor` and a per-entry `resolvable` flag so this is checked mechanically on every run rather than asserted once and assumed forever.

**Pairing implementation.** Record groups hold at most 8 teams, so enumerate all legal perfect matchings by brute force and select lexicographically: group and record constraints → fewest repeat opponents → minimum ranking distance → maximum ranking distance for Round 5 matches where the loser is eliminated → random among exact ties. Transparent and testable; burying this in an optimization library trades auditability for nothing.

**Rules provenance tagging.** Valve specifies priorities, but some tie-resolution details remain implicit. Every branch in the rules engine records its status:

```
official          — stated in the published rules
logically forced  — the only outcome consistent with the official rules
inferred          — a reading of ambiguous official text
arbitrary         — unconstrained; chosen exchangeably (e.g. random among exact ties)
empirical         — estimated from observed data; see the fit report for n and CI
```

Provenance matters more than pretending every branch has textual authority. `inferred` and `arbitrary` branches are the first place to look when the differential test disagrees.

**Elimination opponent choice.** The five 3-2 teams select sequentially from the five 2-3 teams. Run three assumptions and report sensitivity: rational (pick highest win probability), noisy-rational (softmax), random. Do not assume professional teams will choose what the code considers optimal.

**Optimization** (inference-level: batching, quantization, caching — distinct from the assignment optimizer above)**:** Deferred until production.

---

## Build plan

| | Work | Gate |
|---|---|---|
| **D1** (Aug 1–2) | Browser-verify rules and point values → `ti2026_rules.yaml` + archival snapshot (regression check, not blocker). Swiss engine + tiebreakers + Hungarian optimizer on **synthetic** ratings. Property tests incl. forced-repeat and MC-tolerance cases. | Card generator works end-to-end from any strength vector; all §IX invariants hold |
| **D2** (Aug 3) | Ingestion via OpenDota `/explorer`: 18mo maps + rosters, immutable monthly snapshots. Roster-hash canonicalization, alias table. Elo and Glicko-2 baselines. Rolling backtest harness. **Fit the duration model from real data** (§XII). | **Engineering:** leakage test passes, legal card produced from fitted ratings. **Forecast-value:** `mean(LL_elo − LL_glicko) ≥ 0.003` nats/map AND paired bootstrap 95% CI excludes 0 — else ship the public-rating fallback and stop |
| **D3** (Aug 4) | Dynamic BT + time decay. Rolling backtest vs Elo/Glicko. Calibration. Outright odds as ranking prior. `w` sweep scaffolding. | Calibration slope ∈ [0.9, 1.1]; beats Elo on paired log loss |
| **D4** (Aug 5) | Within-series dependence analysis (§VI) — add a series shock only if supported. Schedule-sensitivity experiment. Full run. **Card ships.** Reports. | TI 2025 pairings reproduced exactly from actual results; PPC summary stats not extreme |
| **D5** (Aug 6) | Meta work (§VIII). Hero contest rates + player sample counts + pool breadth → `reports/meta_scouting.md` (**ships unconditionally**). Then `patch_adaptation` only, backtested. | Report readable with sample counts stated. Pre-registered test on post-patch matches. **Card regenerates only on pass** |
| **D6–11** | Slack. Re-run on new results. H2H market integration on schedule reveal. Remaining Tier 2 add-ons only if D2 justified them. | |

Five build days and six slack days, against a hard deadline at 2026-08-13 04:00 CEST. [gpt-pro-output.md](../../../gpt-pro-output.md) §9 loads all eleven days with the final run on Aug 12 — any slip misses the lock.

**Build order is inverted relative to that plan, deliberately.** The rules engine is the highest-risk component (its bugs are deterministic and large, unlike model error, which is a rounding error next to Bo3 variance) and it needs zero data. Building it first yields a working end-to-end card generator on D2 with a fallback that always produces an answer.

---

## Cut list

Dropped from [gpt-pro-output.md](../../../gpt-pro-output.md) under Tier 1 scope:

- Adversarial schedule search and the robust card — pending the §XI sensitivity experiment.
- Two-model ensemble as specified. Glicko-2 and dynamic Bradley-Terry are both logit-scale paired-comparison fits on identical data; blending them buys close to nothing. Diversity comes from the *information source*, not the fitting algorithm.
- Outright-odds inversion through the simulator (§VIII) — ill-posed and off the critical path.
- Two days of hyperparameter grid search (§VII).
- CI instruction-drift check, five hook types, five subagent definitions, config-SHA-in-every-report.
- The Codex audit worktree, **except** for an independent implementation of the deterministic rules core plus differential testing. That test must cover **deliberately constructed cases — exact ties at every tiebreak level, forced repeat pairings, Round 5 maximum-ranking-distance matches, and sequential elimination choices — not only random tournaments**, which rarely hit ties. This is the one place two implementations genuinely disagree; on Glicko they will agree and tell you nothing.

## Not used: Claude Science

The `claude-science-prompting` skill authors prompts for scientific research workflows — literature review, citation fidelity, controlled-access data, biosafety and clinical gates, manuscript provenance. This project has none of those. Its transferable elements (provenance requirements, a reviewer with concrete checks, evaluation cases) are already covered by §IV, §IX, and the superpowers TDD / verification skills. Its own checklist item 10 — "no longer than needed for the scientific risk" — argues against including it.

Narrow exception: if `final_report.md` should read like a methods paper with a reproducibility appendix and calibrated uncertainty statements, it is a reasonable template for that single artifact.
