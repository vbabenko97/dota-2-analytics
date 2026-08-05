# Closing report: making the TI 2026 forecast reproducible

**This is not the lock report.** The card below is the current card, regenerated
from the pinned 2026-08-02 snapshot. The near-lock regeneration runs close to the
2026-08-13 deadline against fresh data, following
[the runbook](../ti26/near-lock-runbook.md); rosters and ratings are still moving,
and doing it now would mean doing it twice.

Every number in this document is read from the run bundle named below, whose
manifest binds it to a source revision, an input snapshot and a set of configs.

## Run bundle

| field | value |
|---|---|
| run id | `c118831c6f96242071b758fcc7948f9b9ee7e82c44f7ae11e9bb173c74a978ea` |
| path | `reports/runs/c118831c6f96242071b758fcc7948f9b9ee7e82c44f7ae11e9bb173c74a978ea/` |
| source revision | `247aba5f01a905f8e6226d9bdd4a3408ec3d247f` |
| snapshot | `20260802T165535Z`, 19 committed chunks, 41,140 rows |
| logical store digest | `8b3f2bb715d0f75e92f1e039594b06835f5f87d85639bdd86e7cb596f8dc8cf9` |
| outputs / inputs hashed | 19 / 7 |

Reproduce it:

```
.venv/bin/python -m ti26.cli_release --snapshot 20260802T165535Z --source-revision 247aba5f01a905f8e6226d9bdd4a3408ec3d247f
.venv/bin/python -m ti26.cli_provenance verify-run --bundle reports/runs/<run-id>
```

## The card

From `card/recommended_card.json`. Keyed by configured team id, because that is
what the pipeline orders on; display names are what the owner submits.

| team id | team | category |
|---|---|---|
| 9572001 | Team Vision | 4-0 |
| 8255888 | BoomBoys | 4-1 |
| 9823272 | Team Yandex | 4-1 |
| 9467224 | Aurora Gaming | elim_win |
| 10136357 | Nigma Galaxy | elim_win |
| 9247354 | Team Falcons | elim_win |
| 2163 | Team Liquid | elim_win |
| 7119388 | Team Spirit | elim_win |
| 10182357 | Iron Wing | elim_loss |
| 10150538 | LGD Gaming | elim_loss |
| 2586976 | OG | elim_loss |
| 726228 | Vici Gaming | elim_loss |
| 8261500 | Xtreme Gaming | elim_loss |
| 9964962 | GamerLegion | 1-4 |
| 10149530 | HULIGANI | 1-4 |
| 5017210 | Team Resilience | 0-4 |

Optimizer marginal objective 4.629 against a random baseline of 3.75. That number
is the sum of the model's own estimated category marginals under this assignment.
It is descriptive only. It is not the evaluation-simulation mean score, and it is
not evidence of skill.

**Unchanged from the previously published card.** All 16 assignments and the
objective are identical. The identity and tie-tolerance corrections below were
reproducibility fixes; running the production command before and after each of
them produced byte-identical assignments, because float Glicko strengths do not
tie exactly.

## Gate lineage

From `frozen_gate_results.json`, which the card report now reads instead of
quoting literals. All three scored the same 26,830 maps.

| gate | verdict | conditions |
|---|---|---|
| D2 | **FAIL** | margin −0.00383 against ≥0.003; 95% CI [−0.02055, 0.00614] does not exclude 0 |
| D3 | **FAIL** | margin 0.00191 against ≥0.003; CI [−0.00046, 0.00500] does not exclude 0; slope 0.6569 outside [0.9, 1.1] |
| D3b | **PASS** | margin 0.00671; 97.5% CI [0.00230, 0.01301] excludes 0; slope 0.9049 inside [0.9, 1.1] |

D3b's artifact records which condition was actually open: only the interval.
Margin and slope were already measured and already passing when it ran, so the
flags travel with the numbers instead of depending on prose. The slope clears its
lower bound by 0.0049.

## D4, still a diagnostic

From `d4/d4_card_backtest.json`. It promotes and demotes nothing.

Observed score **1/16** against the 3.75 random baseline, at the 0.7th percentile
strictly below / 5.0th at-or-below of the model's own predictive distribution.
Optimizer marginal objective 4.1675; evaluation-simulation mean score 4.1634.
Calibration slope refit strictly before the cutoff 0.2009, against 0.4023 measured
over the full store.

The sweep reproduced the published table exactly — scores of 5, 3, 3 at 2,000
sims; 3, 2, 2 at 20,000; 1, 2, 1 at 250,000 — while the objective barely moves.
The naive strength ladder, with no simulation at all, scored 2/16.

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
- **Every claim about a future TI 2026 result.** Nothing here forecasts anything;
  it makes an existing forecast checkable.

## What may be claimed for this card

It is a deterministic, manifest-bound output of the calibrated-Glicko pipeline on
a committed input: anyone with this repository can rebuild the store, regenerate
the card, and verify that every published number came from those exact bytes. That
is the entire claim, and it is a claim about reproducibility, not accuracy. The
evidence for the card's forecasting value is weak and points one way. The D2
forecast-value gate failed and no rating model beat a constant 50/50 floor. D3's
Elo gate failed all three of its pre-registered conditions. D3b passed, but as a
one-condition test clearing its slope band by 0.0049, which is weaker than a fresh
three-condition pass. The only card-level out-of-sample test available scored 1/16
against a random baseline of 3.75, and scored worse the more precisely it
optimised — while a naive strength ladder with no simulation scored better. One
event is one sample and a random card reaches 1/16 about 5% of the time, so this
does not establish that the pipeline is worse than chance; it removes the last
reason to believe it is better. Making a misspecified optimum reproducible does
not make it right, and nothing in this work was intended to.
