# Closing report: making the TI 2026 forecast reproducible

**This is not the lock report.** The card below is the current card, regenerated
from the pinned 2026-08-02 snapshot. The near-lock regeneration runs close to the
2026-08-13 deadline against fresh data, following
[the runbook](../ti26/near-lock-runbook.md); rosters and ratings are still moving,
and doing it now would mean doing it twice.

**Superseded in part on 2026-08-06 by a rating-model correction.** A defect in
the Glicko idle-inflation path charged one variance increment per period too
many. Correcting it moved every number the model produces and changed two of the
sixteen assignments. This document has been updated to the corrected bundle; the
section "The Glicko correction" below records what moved and what did not. The
2026-08-04 bundle it previously described remains in the repository as a
historical artifact and is discussed there.

Every number in this document is read from the run bundle named below, whose
manifest binds it to a source revision, an input snapshot and a set of configs.

## Run bundle

| field | value |
|---|---|
| run id | `7c0c5e97a9acadce5e42fe8032df440ff88358c2db5b6f7c80dcc97fb5e2d198` |
| path | `reports/runs/7c0c5e97a9acadce5e42fe8032df440ff88358c2db5b6f7c80dcc97fb5e2d198/` |
| source revision | `d62fb41f4b9158928a79df76cd92e6c86ff4b866` |
| snapshot | `20260802T165535Z`, 19 committed chunks, 41,140 rows |
| logical store digest | `8b3f2bb715d0f75e92f1e039594b06835f5f87d85639bdd86e7cb596f8dc8cf9` |
| outputs / inputs hashed | 19 / 7 |

Reproduce it:

```
.venv/bin/python -m ti26.cli_release --snapshot 20260802T165535Z --source-revision d62fb41f4b9158928a79df76cd92e6c86ff4b866
.venv/bin/python -m ti26.cli_provenance verify-run \
  --bundle reports/runs/7c0c5e97a9acadce5e42fe8032df440ff88358c2db5b6f7c80dcc97fb5e2d198 \
  --against-revision $(git rev-parse HEAD)
```

`--against-revision` is the check this project did not have while the defect was
live. Without it `verify-run` asks only whether a bundle still describes the bytes
it was built from, which stayed true throughout; it never asked whether the
current source still produces them, and for two days it did not.

## The card

From `card/recommended_card.json`. Keyed by configured team id, because that is
what the pipeline orders on; display names are what the owner submits.

| team id | team | category |
|---|---|---|
| 9572001 | Team Vision | 4-0 |
| 7119388 | Team Spirit | 4-1 |
| 9823272 | Team Yandex | 4-1 |
| 9467224 | Aurora Gaming | elim_win |
| 10136357 | Nigma Galaxy | elim_win |
| 9247354 | Team Falcons | elim_win |
| 2163 | Team Liquid | elim_win |
| 8255888 | BoomBoys | elim_win |
| 10182357 | Iron Wing | elim_loss |
| 10150538 | LGD Gaming | elim_loss |
| 2586976 | OG | elim_loss |
| 726228 | Vici Gaming | elim_loss |
| 8261500 | Xtreme Gaming | elim_loss |
| 9964962 | GamerLegion | 1-4 |
| 10149530 | HULIGANI | 1-4 |
| 5017210 | Team Resilience | 0-4 |

Optimizer marginal objective 4.5903 against a random baseline of 3.75. That number
is the sum of the model's own estimated category marginals under this assignment.
It is descriptive only. It is not the evaluation-simulation mean score, and it is
not evidence of skill.

**Two assignments moved, and the seed-stability claim is withdrawn.** Team Spirit
and BoomBoys swap `4-1` and `elim_win` relative to the 2026-08-04 card. The cause
is the Glicko correction, not fresh data; the section below states which.

The previous card reported all 16 teams stable across seeds 1, 2 and 3 at 250,000
simulations. The corrected model reports **6 of 16 unstable**, including both
extremes:

| team | seed 1 | seed 2 | seed 3 |
|---|---|---|---|
| Team Vision | 4-0 | 4-1 | 4-0 |
| Team Resilience | 0-4 | 1-4 | 1-4 |
| Team Spirit | 4-1 | 4-0 | elim_win |
| Team Falcons | elim_win | elim_win | 4-1 |
| GamerLegion | 1-4 | 0-4 | 1-4 |
| HULIGANI | 1-4 | 1-4 | 0-4 |

Team Resilience holds the `0-4` slot on one seed of the three and `1-4` on the
other two, so the shipping pick is the minority outcome among the seeds checked.
Nothing about the diagnostic changed. The earlier stability was an artifact of the
inflated strength spread.

This is not resolvable by simulating harder, and the temptation to try was
examined and rejected. The gap between the best and second-best full assignment
under these marginals is 0.000004, exactly one simulated tournament in 250,000,
against a sampling error on a single marginal of about 0.00073 -- 183 times
larger. Raising the count would also silently move the tie tolerance, which
`cli_card.py` derives from it, and
[the runbook](../ti26/near-lock-runbook.md) makes a tolerance-driven assignment
change an owner stop. Spec section IX had already set the acceptance threshold
that 250,000 meets and called anything beyond it "ritual, not method". The
instability is the model reporting that it cannot separate six of sixteen slots.

## Gate lineage

From `frozen_gate_results.json`, which the card report now reads instead of
quoting literals. All three scored the same 26,830 maps.

| gate | verdict | conditions |
|---|---|---|
| D2 | **FAIL** | margin −0.00356 against ≥0.003; 95% CI [−0.02037, 0.00649] does not exclude 0 |
| D3 | **FAIL** | margin 0.00191 against ≥0.003; CI [−0.00046, 0.00500] does not exclude 0; slope 0.6569 outside [0.9, 1.1] |
| D3b | **PASS** | margin 0.00673; 97.5% CI [0.00240, 0.01290] excludes 0; slope 0.9057 inside [0.9, 1.1] |

D3 is byte-identical to the 2026-08-04 run, and not by coincidence: it gates on
Elo, which never touches `GlickoModel`. Only its Glicko diagnostic row moved.

**These are recomputations, not re-registrations.** The corrected model has no
pre-registered D3b result and cannot be given one. D3b's standing came from an
ordering -- registered after Elo failed, before Glicko's interval was computed --
that cannot be recreated after the fact. What can be said is narrower and is all
that is claimed here: re-running each gate on corrected code, with its arguments,
thresholds and data unchanged, overturns no verdict, and D3b's fragile slope
condition clears its 0.9 bound by 0.0057 rather than 0.0049.

D3b's artifact records which condition was actually open: only the interval.
Margin and slope were already measured and already passing when it ran, so the
flags travel with the numbers instead of depending on prose. The slope clears its
lower bound by 0.0049.

## D4, still a diagnostic

From `d4/d4_card_backtest.json`. It promotes and demotes nothing.

Observed score **1/16** against the 3.75 random baseline, at the 0.72nd percentile
strictly below / 4.99th at-or-below of the model's own predictive distribution.
Optimizer marginal objective 4.1637; evaluation-simulation mean score 4.1601.
Calibration slope refit strictly before the cutoff 0.2016, against 0.4051 measured
over the full store.

The headline survives the Glicko correction unchanged: the observed score is still
1/16, the naive strength ladder with no simulation at all still scores 2/16, the
rank correlation is still 0.4781, and the displacement partition is still one team
exact, ten off by one, five off by two or more.

The sweep does not survive, and the previous version of this report was wrong to
say it "reproduced the published table exactly". It reproduced the table computed
under the defective model. Under the corrected model the scores are 4, 1, 3 at
2,000 sims; 4, 5, 2 at 20,000; 1, 2, 2 at 250,000. The direction the earlier
report drew from it — that scoring gets no better, and if anything worse, as the
optimisation gets more precise — is unchanged, but it was reported as an exact
reproduction and it was not.

## The Glicko correction

Found by an external audit of the reproducibility work, on 2026-08-06.

`GlickoModel` inflated a rating's deviation once per elapsed period and then
handed it to `update_rating`, which applies Glicko-2's own step-6 increment
`sqrt(phi^2 + sigma'^2)` on top. A roster active in consecutive periods therefore
took two variance increments where Glickman specifies one, and one returning after
k idle periods took k+1. The same mistake lived in three places: the rated roster,
every opponent captured into the pending period, and the prior an inheriting
roster is seeded from. The first fix corrected one of the three and its commit
message asserted the other two did not exist; a second audit caught that, and the
completion is a separate commit.

Consequences, in descending order of how much they matter:

- **Two assignments moved.** Spirit and BoomBoys swap, because BoomBoys carried
  the largest single correction in the field at −0.0337 logits and fell from third
  to fifth. This is a corrected computation, not fresh data.
- **The seed-stability claim is withdrawn**, as above. A tighter deviation makes
  each result move a rating less, so the corrected model separates teams more
  slowly: the raw spread over the 16 falls from 1.8518 to 1.7918.
- **No gate verdict is overturned**, as above.
- **The D4 sweep no longer reproduces** the committed table, as above.
- **Completing the fix changed no assignment.** The opponent-capture and
  inheritance instances moved the objective from 4.5905 to 4.5903 and nothing
  else, so they are real defects roughly two orders of magnitude smaller than the
  first.

Three tests now pin the convention, one per instance, each observed failing under
the exact mutation it names. All three need a gap of more than one period to
separate the two conventions; at a one-period gap they agree, which is why 819
passing tests never saw any of it.

**The 2026-08-04 bundle no longer verifies.** Retagging the tournament-format
provenance changed `config/ti2026_rules.yaml`, which that bundle declares as an
input, so `verify-run` now fails on it with an input hash mismatch. Nothing it
computed was affected — no code reads those tags — but content addressing does not
distinguish a comment from a coefficient, and it should not. The earlier bytes are
in Git history if the old bundle ever needs to be re-verified.

## Every audit finding

What happened to each superseded claim family is recorded in
[the correction register](2026-08-04-correction-register.md); this table covers
the numbered verdicts and lettered findings of
[the external audit](2026-08-04-external-audit-of-d0221dc.md), whose triage is
[here](2026-08-04-response-to-external-audit.md).

| # | finding | outcome | note |
|---|---|---|---|
| 1–3, 5–7, 12–13, 16 | substantive results confirmed by fresh execution | **confirmed, now bound** | all regenerated into the bundle |
| 4 | "one-condition test" contradicts D3b's three-way control flow | **narrowed** | the artifact records `open_for_test` per condition; the epistemic claim stands, the phrasing no longer invites a control-flow reading |
| 8 | sim-count sweep had no producer | **fixed** | seeded producer; reproduces the published table exactly |
| 9 | random-card control had no producer | **fixed, value moved** | seeded producer; differs in the 4th significant figure from the published value, different RNG stream, both agree with theory |
| 10 | naive strength ladder had no producer | **fixed** | reproduces 2/16 |
| 11 | rank-correlation statistics had no producer | **fixed, value moved** | displacement counts reproduce exactly (1 / 10 / 5); the correlation does not — see below |
| 14 | card depends on display names at exact ties | **fixed** | ordering keyed on configured team id; exact-tie regression tests; card unchanged |
| 15 | tie tolerance is not the standard error it is documented as | **narrowed, behaviour unchanged** | relabelled as a worst-case single-marginal magnitude heuristic, with an explicit statement of what it is not |
| 17 | human identity verification not code-checkable | **declined — not fixable in code** | the store holds no organisation names; the runbook makes it an account-set check with an owner stop |
| A | D4 had no tests | **fixed** | seven tests including the exact-cutoff end-to-end case |
| B | D3b tests pinned report self-consistency | **fixed** | sentinel gate result drives report fields and exit code |
| C | statistical-causality prose exceeded computation | **narrowed** | the diagnostic counts sign directions and now says it cannot attribute cause |
| D | thin-history Elo bias asserted, not measured | **narrowed** | described as the sample-size flag it is |
| E | `g(phi)` range does not prove probability tracking | **narrowed** | range still reported; the tracking inference is disclaimed |
| F | public-rating sensitivity test was vacuous | **fixed** | scripted marginals, known non-zero delta, both resolvability outcomes |
| G | card reports repeat frozen gate numbers | **fixed** | read from the frozen-gate artifact, or the report says lineage was not supplied |
| H | D4 overstates a post-hoc descriptive sweep | **narrowed** | sweep is a committed producer and its post-hoc status is recorded |
| I | two meanings of "model expected" | **fixed** | `optimizer_marginal_objective` and `evaluation_simulation_mean_score` everywhere |
| J | D4 hardcodes 0.4023 | **fixed** | measured fresh from the same rows every run |
| K | historic drift became forward guidance | **narrowed** | stated as one past observation used as a reference scale |
| L | "roughly doubles" / "roughly 30%" unsupported | **fixed by deletion** | neither quantity is computed anywhere; both removed |
| M | snapshot provenance unbound | **fixed** | snapshot committed; store rebuild matches the database the published numbers came from |

## What remains unverified

- **D3b's registration timing.** Git chronology supports that margin and slope
  were measured before the D3b code existed. No independently timestamped
  preregistration artifact exists and none can be created now.
- **The rank correlation's published value.** The committed producer uses Spearman
  with average tied ranks, which this data requires — five teams always share
  `elim_win`. It gives 0.4781. The published +0.375 came from an ad-hoc
  calculation whose tie convention was never recorded; the external auditor
  reproduced it only by independently making the same unstated choice. Which
  convention was originally intended is not recoverable.
- **Historical before/after counts** for the display-name and tie-tolerance
  changes. No retained input/output pair; withdrawn rather than restated.
- **Real-world team identity.** That a given OpenDota `team_id` is the
  organisation the owner submits under a given name is not decidable from the
  store, which holds no organisation names. Five configured teams already show
  account sets under a different `team_id`; the near-lock check is an account-set
  comparison with an owner stop, not a name match.
- **Rung-3 public ratings.** `cli_rung3` reads a live table with no snapshot here,
  so none of its historical numbers can be replayed offline.
- **The tournament format itself.** The Swiss structure, win and loss thresholds,
  series length, tiebreak sequence and round-one seeding reach this repository
  secondhand, through citations the originating session could not open, from a
  JavaScript-rendered page that returned no body. No archived copy is committed.
  Every published marginal depends on these values. They are now tagged
  `reported_official` rather than `official`, which is what is actually known;
  confirming them needs sources outside `explorer_query` and is an owner task.
- **Why the real bracket paired as it did.** The engine's rule is now known not
  to reproduce TI 2025, and known not to matter, but no alternative rule fits
  either. Part of the disagreement may be the ranking rather than the pairing:
  after one or two rounds that ranking is mostly ties resolved by coin toss,
  plus a real-world initial seeding neither the model nor the check possesses.
  The check fails in rounds 4 and 5 too, where that explanation is weakest.
- **The corrected model's out-of-period behaviour at scale.** The three fixed
  instances are pinned by unit tests against a Glicko-2 reference. Nothing here
  independently re-derives the full-store fit against a second implementation.
- **Every claim about a future TI 2026 result.** Nothing here forecasts anything;
  it makes an existing forecast checkable.

## D4 was confounded by data poverty, and the corrected number is 4/16

Registered in advance at
[the matched-window spec](../ti26/2026-08-07-d4-matched-window-spec.md), run once,
both numbers published as that spec required.

D4 trains on maps before 2025-09-04, and the pinned snapshot only reaches back to
2025-02-08, so it saw **16,958 maps over 6.8 months where production has 41,140
over 17.7**. It tested the procedure on 41% of the data. A 30-month snapshot and
a `--train-from` bound give a genuinely matched window: **44,097 maps over 17.7
months**, against production's 41,140 over 17.7.

| | D4, as registered | D4-MW, matched window |
|---|---|---|
| training maps / months | 16,958 / 6.8 | 44,097 / 17.7 |
| **observed score** | **1 / 16** | **4 / 16** |
| naive strength ladder | 2 / 16 | 4 / 16 |
| random baseline | 3.75 | 3.75 |
| percentile in the model's own distribution | 0.7% / 5.0% | 23.2% / 42.8% |
| calibration slope, refit pre-cutoff | 0.2016 | 0.4352 |
| sim-count sweep, observed scores | 5,3,3 / 3,2,2 / 1,2,1 | 4,4,3 / 4,4,4 / 4,4,4 |

**The 1/16 was substantially an artifact of a seven-month training window.** The
registered result stands as what it was, and it is not withdrawn, but it should
not be quoted as the pipeline's out-of-sample performance without this beside it.
Statements elsewhere that leaned on 1/16 as evidence of the pipeline being worse
than chance were resting on a confounded number.

Two things the correction does NOT rescue.

**4/16 is not a good score.** It is barely above the 3.75 random baseline, and it
sits at the 23rd percentile of the model's OWN predictive distribution -- the
model expected 4.92 and got 4. Scoring below your own expectation is not evidence
of skill.

**The naive strength ladder also scores 4/16.** With adequate data the pipeline
draws level with a sort rather than beating it, which is the same finding the
ladder comparison reports on the 2026 field.

One earlier claim does not survive and is withdrawn: that the pipeline "scored
worse the more precisely it optimised". That pattern came from the sweep under
the seven-month window. Under the matched window the sweep is flat at 4 across
every simulation count.

Unchanged: n=1, permanently, because TI 2025 is the only event that has ever run
this format; and design-time leakage, because the architecture was chosen by
people who had already seen TI 2025.

## What the simulation contributes

Three diagnostics run after the Glicko correction, all committed producers, all
gating nothing.

**The bracket rules are corroborated; the pairing rule is not.**
`ti26.cli_pairing_check` reconstructs TI 2025 -- the only event that has ever run
this format -- and reproduces the structure exactly: equal-record pairing across
all 44 series, two groups of eight, rounds 1-3 within group, round 4 entirely
cross-group, five Swiss rounds then a five-series elimination round pairing 3-2
against 2-3. The within-bucket pairing preference does not reproduce: the real
pairing is among the engine's candidates in 4 of the 11 buckets where the rule
had a choice, and the real bracket follows neither this rule nor its opposite.

**And the pairing rule does not matter.** `ti26.cli_schedule_sensitivity`
compares changing the rule against changing the simulation seed. Signal-to-noise
is 1.08. Discarding the ranking-distance criterion entirely moves marginals less
than re-seeding does and changes no assignment, so the failure above is harmless
and the criterion is decorative.

**The card is a strength sort.** `ti26.cli_ladder_check` compares the shipped
card with the naive alternative -- sort by calibrated strength, cut the ranking
into the capacities, no simulation and no optimiser. At the production seed all
sixteen assignments are identical and the objective gap is exactly 0.0. At seeds
2 and 3 twelve of sixteen agree, and the four that differ are not the same four,
so the departures are sampling noise rather than information. The optimiser's
advantage is at most 0.0041 on the model's own objective, against a claimed edge
over random of 4.59 - 3.75 = 0.84.

None of this touches the rating work that produces the strengths. It bounds what
the simulation and assignment layers CONTRIBUTE, and the bound is approximately
zero. Both methods read the same strengths, so agreement is expected wherever the
strength ordering is decisive -- that is the point, not a caveat against it.

The card report now states this itself, so a reader does not have to run a
separate tool to learn that the simulation changed nothing.

## What may be claimed for this card

It is a deterministic, manifest-bound output of the calibrated-Glicko pipeline on
a committed input: anyone with this repository can rebuild the store, regenerate
the card, and verify that every published number came from those exact bytes. That
is the entire claim, and it is a claim about reproducibility, not accuracy.

**And it is a claim about less machinery than it appears to be.** At the shipping
seed the card is the strength sort, so what is really being submitted is a ranking
of sixteen teams cut into six buckets. The simulation, the pairing rules and the
assignment solver are all reproducible, all correct as far as they have been
tested, and all contributing nothing to the answer. A card that equals the sort
can be submitted without any dependence on a random seed, which also disposes of
the six seed-unstable slots -- they are only unstable in a pipeline whose output
does not differ from the sort anyway.

The
evidence for the card's forecasting value is weak and points one way. The D2
forecast-value gate failed and no rating model beat a constant 50/50 floor. D3's
Elo gate failed all three of its pre-registered conditions. D3b passed, but as a
one-condition test clearing its slope band by 0.0049, which is weaker than a fresh
three-condition pass. The only card-level out-of-sample test available scored 1/16
against a random baseline of 3.75 on a seven-month training window, and 4/16 once
the window was matched to production's eighteen — barely above the baseline, at
the 23rd percentile of the model's own expectation, and exactly level with a
naive strength ladder that runs no simulation at all. One event is one sample, so
none of this establishes the pipeline is worse than chance; it removes the reason
to believe it is better. Making a misspecified optimum reproducible does
not make it right, and nothing in this work was intended to.
