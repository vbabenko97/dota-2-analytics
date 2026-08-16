# TI 2026 playoff bracket prediction — registration

**Status: registered 2026-08-16, before any model number for this task exists.**

This document fixes what is being predicted, what counts as a hit, and what the
null is. It is written before the producer exists and before any bracket
probability has been computed, because a criterion chosen after seeing the
number is not a criterion.

The group-stage card scored 5/16 against a null mean of 3.75, which a random
card matches or beats 30.9% of the time. That result is recorded in
`data/ti2026_outcome.yaml` and is the reason this document is strict: the
project has now demonstrated it can ship something indistinguishable from luck,
and the next artifact should not be able to hide that.

## What is predicted

The Compendium playoff prediction is a **single pre-committed bracket**. All 14
match winners are named before the first Main Event match, and later picks are
constrained by earlier ones.

That the whole bracket is filled at once is **owner testimony**, not a Valve
publication. Valve's own announcement of 2026-08-12 (bound in evidence record
`066b04c68e286b86dd7dd20c5f7ea696ce26d05e2202b49da0ce4bd59ea7e2be`) confirms
the eight-team double-elimination Main Event and that bracket predictions
exist, but states neither the count of predictions nor the fill mechanic. The
2026-07-30 announcement mentions bracket predictions and gives only the Swiss
lock time. Provenance is therefore `owner_testimony_2026_08_16`, and it may
never be labelled `official`.

## The 14 slots

Field and Upper Bracket quarterfinal pairings, from the client bracket:

| slot | participants |
|---|---|
| UB QF1 | Iron Wing vs Team Spirit |
| UB QF2 | Team Vision vs BoomBoys |
| UB QF3 | Team Liquid vs Team Yandex |
| UB QF4 | Nigma Galaxy vs Team Falcons |

The remaining ten slots are UB SF1, UB SF2, UB Final, LB R1M1, LB R1M2, LB QF1,
LB QF2, LB SF, LB Final, Grand Final.

## Metric

**Score = the number of the 14 slots whose named winner equals the actual
winner of that slot.**

A pick naming a team that never reached the slot is a miss, not an error. The
submitted bracket must be internally coherent: a team may occupy a later slot
only if the same bracket advanced it there.

## The unresolved input: lower-bracket feed topology

Whether an Upper Bracket semifinal loser meets the Lower Bracket Round 1 winner
from its **own** half or the **opposite** half is not established. It is absent
from Valve's announcements, from the Liquipedia page (flagged in development),
and from every public derived source checked. One community implementation
shows cross-feed; that is corroboration, not verification, and a second public
tracker shows a bracket incompatible with the confirmed eight teams and four
pairings, so derived sources are demonstrably unreliable here.

This is **not** merely a benchmark parameter. The topology enters the
simulation, so it determines the winner distribution of LB QF1, LB QF2, LB SF,
LB Final and Grand Final — six of the fourteen picks.

## Nulls, both registered now

The null is a random player obliged to submit a coherent bracket in advance,
with every match a coin flip. It is not a per-match oracle: such a player does
not know who reaches a late slot, so its chance of matching at UB Final is 1/8
rather than 1/2.

Computed exactly, by enumerating all 2^14 coherent brackets and summing
Σ_t P(t wins slot)² per slot:

```
null(cross-feed)  = 15/4 = 3.7500 / 14
null(direct-feed) = 4    = 4.0000 / 14
```

Every slot but the two LB quarterfinals contributes 3.5 under both. Under
direct-feed each LB QF winner is uniform over four teams and contributes 1/4;
under cross-feed it is uniform over eight and contributes 1/8.

Exact tail of the cross-feed null, from full pairwise enumeration of 2^14 × 2^14
bracket pairs (mean reproduces 15/4 exactly):

| score | P(exactly) | P(at least) |
|---|---|---|
| 10 | 0.0075 | 0.0119 |
| 9 | 0.0164 | 0.0283 |
| 8 | 0.0323 | 0.0606 |
| 7 | 0.0572 | 0.1178 |
| 6 | 0.0916 | 0.2093 |
| 5 | 0.1311 | 0.3405 |
| 4 | 0.1632 | 0.5037 |
| 3 | 0.1764 | 0.6801 |

A separate, much stronger control is the **oracle coin**: a flipper shown the
two actual participants of each slot, scoring 7/14 in expectation. A
pre-committed random bracket reaches 7 only 11.8% of the time. Both are
reported; neither may be substituted for the other after the fact.

### Selection rule, fixed now

```
use the topology exhibited by the locked TI 2026 client bracket;
determine it before computing or inspecting our model score;
no post-score discretion.
```

Registering both values rather than deferring is deliberate. An unregistered
null is one that gets chosen after the score is known.

## Method

The space of coherent brackets is exactly 2^14 = 16384, because each match is a
binary choice given the earlier ones. It is enumerated in full, so the pick set
maximising expected hits is found **exactly**. No greedy heuristic is used and
none is needed; per-slot `argmax P(win)` is not necessarily coherent and is not
the objective.

Per-slot win probabilities come from simulating the bracket with the project's
existing rating and series machinery. Series are Bo3, except the Grand Final,
which is Bo5. No new modelling layer is introduced.

## What may not happen

**No new signal is promoted because it would have helped in the group stage.**
`observed_recent_form` is a diagnostic and stays one. It pointed the right way
on Team Resilience, whose 0-4 pick was the shipped card's worst call. Promoting
it now would be a criterion chosen after seeing the number, and would make this
result meaningless in exactly the way the group card's was not.

**No hero, draft or pool modelling.** The store carries hero columns and no
model reads them. The eight teams have roughly a dozen event maps each; fitting
draft behaviour on that is overfitting, and the correction register exists
because this project has made that class of mistake before.

**The prediction ships even if it is unimpressive.** Expected score is bounded
by how separated these eight teams actually are. The shipped card's own
provenance reports a calibrated best-versus-worst map win probability of 0.6739
across the full sixteen-team field; the surviving eight are closer together
than that. A result near the null is a result, and gets reported as one.

## Protocol deviation: the store was not preregistered

This section records a gap in the registration above, found after the first
model run. It is written as history, not as a rule that existed beforehand.

The spec fixed the metric, both nulls and the method, but **never fixed which
store the strengths come from**. The choice was made de facto by running the
producer on the post-group-stage store first. That is not preregistration, and
back-dating it into a rule — "use the most recent store" — would be exactly the
criterion-after-the-number this document exists to prevent.

```
primary_store:
    data/processed/ti2026-postgroup.sqlite
    sha256 be01fd916b89484fa24e90a8913941519825e391fab12eecbefd4a59e704b7ad
    40076 rows, latest map 2026-08-16T10:24:26Z
    selected by the first playoff-model run, before any store comparison
    selection rule NOT preregistered: protocol deviation

store_sensitivity:
    comparator data/processed/release-20260802T165535Z.sqlite
    result: 14/14 picks unchanged under cross-feed
            14/14 picks unchanged under direct-feed

interpretation:
    the recommendation is robust to this one store perturbation.
    That is a sensitivity result. It is NOT evidence of predictive accuracy,
    and it does not retire the deviation above.
```

The digest and latest-map timestamp are frozen here because the store is
gitignored: without them, "postgroup.sqlite" names a different file every time
anyone re-ingests.

## Expected lift, both topologies

Neither may be quoted alone while the topology is unverified:

| topology | expected | null | lift |
|---|---|---|---|
| cross-feed | 4.3615 | 3.7500 | **+0.6115** |
| direct-feed | 4.5802 | 4.0000 | **+0.5802** |

The unresolved edge is deployment-critical for two specific picks and almost
irrelevant to the aggregate: it moves the lift by 0.03 of a slot.

## What the rating response does and does not show

Comparing calibrated strengths across the two stores mixes two effects, because
the rolling-backtest slope also moved (0.4051 to 0.3596) and `apply_correction`
recentres. Measured on raw Glicko instead, over the five teams whose Swiss
result gives an unambiguous expected direction:

| team | Swiss | raw change |
|---|---|---|
| Nigma Galaxy | 4-1 | +0.2338 |
| Team Liquid | 4-1 | +0.1189 |
| Team Yandex | 2-3 | −0.3533 |
| BoomBoys | 2-3 | −0.1715 |
| Team Vision | 4-0 | **−0.0029** |

Four of five move as expected. **Team Vision does not**: it went 4-0 and its raw
rating is flat. It only gains under a common slope, which recentres, so that
gain is relative to the field rather than absolute. The 3-2 teams are excluded
because their direction is not determined by the result.

An earlier draft of this analysis claimed all eight moved consistently. That was
wrong, and wrong in the flattering direction.

## What the DatDota comparison is and is not

It is a **weak ordering sanity check only**. It is not a probability-level
check, and the two are not in the same information state:

- Our pre-TI store fixes ratings at 2026-08-02; DatDota's snapshot #12 states
  ratings as of 2026-08-10.
- Our run is conditioned on the **actual** eight-team field and the actual
  quarterfinal pairings. DatDota #12 still simulates the elimination round, so
  five of its playoff places are unresolved and thirteen teams carry non-zero
  title probability.

Comparing 32.2% against our champion probability would therefore compare two
different questions. `1W` and `Iron Wing` are the same organisation and are not
a discrepancy.

## Blocking condition

Compute the optimal slate under **both** topologies and compare.

- If the 14 picks are identical, the unresolved edge does not block the
  artifact and remains a provenance note on which null applies.
- If any pick differs, the artifact **may not ship** without verifying the
  topology from the locked client bracket.
