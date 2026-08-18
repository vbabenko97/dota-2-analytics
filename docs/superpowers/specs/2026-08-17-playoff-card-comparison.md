# Playoff card comparison — registration

**Status: registered before the Compendium playoff lock and before any playoff
match, while the client shows the bracket as unlocked.**

The date is bound to that verifiable state rather than to a calendar assertion:
the owner's locked-client screenshot shows `THE INTERNATIONAL — LOCKS IN 2
DAYS` and `UB ROUND 1 — AUG 20`, with the group stage already `LOCKED 5/16`.

## The notarial record

**The commit dates in this repository are not evidence of when anything was
written.** `GIT_AUTHOR_DATE` and `GIT_COMMITTER_DATE` are author-controlled, so
a local commit — however early its timestamp reads — proves nothing about
preregistration on its own. An earlier claim in discussion that "the local
commit standing before the lock is the freeze" was wrong for audit purposes and
is withdrawn.

### Primary durable anchor

Two freezes, each with its own anchor. **The second is the one that covers the
card actually submitted**; the first covers the original five and the state of
the registration on 2026-08-17.

```
PR #28  merged_at         2026-08-17T08:21:38Z    (GitHub server timestamp)
PR #28  merge_commit_sha  1e5960e7162d80cdf5dd862bb341c437fb2263ef
frozen commit             3ebff935b4e45cb891ce97ee7ba1399ceb9a006b
                          verified: an ancestor of that merge commit

PR #31  merged_at         2026-08-18T06:19:08Z    (GitHub server timestamp)
PR #31  merge_commit_sha  f847d21141e077c3d939475a2631c1001a75c704
frozen commits            8c9145f  H-owner-final and the headline amendment
                          c03574c  the coin-flipped slots
                          verified: both ancestors of that merge commit
```

Both merges precede `UB ROUND 1 — AUG 20`, the first Main Event match, so every
card here was fixed before any outcome existed.

Unlike #28, PR #31's head was **not** moved after it was opened: its `head.sha`
is still `c03574c`, the commit it was opened on, so for that one the
`created_at` receipt and the merge receipt agree. The merge anchor remains the
one to cite, because it is the one that cannot be disturbed later.

The first playoff match is `UB ROUND 1 — AUG 20` per the locked client, so the
merge precedes every outcome these cards forecast. Because #28 was merged with
a **merge commit** rather than squashed or rebased, the frozen objects entered
`main`'s ancestry unchanged. That is what makes this anchor durable: the exact
commit is reachable from a server-timestamped merge, and no later branch
activity — or deletion of `feat/playoff-card-freeze` — can affect it.

### Supporting contemporaneous receipt

```
PR #28  created_at        2026-08-17T08:19:20Z
        headRefOid observed at creation: 3ebff935b4e45cb891ce97ee7ba1399ceb9a006b
```

This is recorded as **supporting evidence only, and it is weaker than it looks**.
`ae9907b` — this section itself — was pushed after the pull request was opened,
so the PR's `head.sha` now reads `ae9907b124ecb4dba098020839113c2cb8197ed1`.
Current PR metadata therefore does **not** show that the head at creation was
`3ebff93`, and the events that would connect them expire. `created_at` alone
must not be cited as binding the pull request to the frozen commit; the merge
anchor above is what carries the claim.

### Not claimed

The commits are **not signed** — signing is not configured in this repository.
Signing establishes authorship, which is a different question from time and not
the one this preregistration needs.

`feat/playoff-card-freeze` was never rebased, so the SHAs above are the original
objects rather than replayed copies.

Five brackets are frozen in `data/ti2026_playoff_cards.yaml`. This document
fixes what they are for, which comparison is the headline, and what the result
may and may not be used to claim.

## Why this exists

The model's slate and the owner's own bracket disagree at 8 of 14 slots. Both
are defensible and the evidence between them is genuinely thin: the pick they
turn on is 0.5291, and overriding it costs 0.1070 expected hits.

Freezing only one of them would settle the disagreement by fiat. Freezing both
before the outcomes makes it measurable — not settled, but measurable, on one
event.

## The headline is designated now

```
headline:      A-model  vs  H-owner-final
attribution:   B, C, D, E  — analytic constructions and the superseded owner card
external:      F, G        — supplemental entrants
```

Only A and H are the headline. **None of the others may be promoted afterwards,
however well one happens to score.** Naming it in advance is the whole point:
after the outcomes, eight cards offer eight stories, and the flattering one
would be available to whichever side lost.

### Amendment: the headline moved from E to H, before any match

Registered as A vs E on 2026-08-17. On 2026-08-18 — still before the first
Main Event match — the owner revised six slots and submitted a different
bracket. E was frozen as the card actually submitted, and that had stopped
being true.

This is an amendment to a registered designation and is recorded as one. It is
**not** a criterion chosen after seeing a number: no playoff match has been
played, so nothing about the outcomes was known when it was made. What would
have been forbidden is re-designating after results, and what would have been
worse is leaving the headline pointed at a card the owner never submitted.

E is kept frozen, demoted to attribution, and still scored. Deleting a forecast
because it was later revised is how a record becomes flattering. That the
"frozen" human card moved within a day is itself a result about the stability
of judgemental forecasts, and it survives only if E survives.

The revision was worth **+0.0683** on the model's own account (E 4.1356, H
4.2039), and moved the owner from 6/14 to 7/14 agreement with the model.

### The submitted card is partly randomised

Two of the fourteen slots were decided by a **coin flip**, both named by the
owner: `LB SF` and `LB Final`. A coin-flipped slot carries no human judgement,
so scoring H as a pure judgemental forecast would credit or blame a person for
a randomiser this experiment introduced itself.

**The list is a lower bound, not a census.** The owner first described the card
as made "not without using a coin in some matches" and later named these two.
An earlier flip is neither confirmed nor excluded — `UB QF4` is the obvious
candidate, sitting at a model probability of 0.5032 and being the one slot
where H disagrees with all seven other cards. `coin_flipped_slots_complete:
false` records that, and scoring must respect it.

What makes these two worth keeping is that **a stated human estimate existed
before the coin was thrown, and the coin overrode it**:

| slot | matchup | reviewer | model | coin gave |
|---|---|---|---|---|
| LB SF | BoomBoys vs Falcons | BB **0.58** | BB 0.4824 | Falcons |
| LB Final | Liquid vs Falcons | Liquid **0.58** | Liquid 0.4882 | Falcons |
| Grand Final | Vision vs Falcons | Vision 0.66 | Vision 0.6056 | *no coin* |

On both flipped slots the reviewer favoured the other team and the model
weakly favoured the side the coin produced. That is chance, not vindication —
two flips decide nothing — but it is exactly the kind of detail that becomes
invisible if only the final picks are stored.

The reviewer's three estimates are **conditional series probabilities** —
`P(A beats B | that series is played)`, and the series exists only along H's
path. Each is stored beside the directly comparable conditional from this
project's own strengths, never beside a slot marginal. Quoting `0.58` against
a marginal would repeat the DatDota title-probability error.

### The stated probabilities and the submitted card disagree

`P_owner(Iron Wing > Spirit) = 0.55` favours Iron Wing. H picks Team Spirit.
Either the number went stale within a day or that slot was one of the coin
flips. Recorded in `contradicted_by_submitted_card` rather than reconciled:
adjusting the probability to match the pick would erase the only evidence here
that a stated forecast and a submitted action came apart.

One more thing fell out of it: H shares its two root decisions with the
**reviewer's** stated position, not the owner's own. The owner's final card
agrees with the reviewer's probabilities and contradicts the owner's.

## The two external entrants

`F-gpt-5-6-xhigh` and `G-gemini-3-1-pro` are brackets extracted from
LLM-authored analyses supplied by the owner. Both are coherent 14-slot
brackets and both are scored by the same registered metric. The raw documents
are frozen in `predictions-from-llms/` and bound to the cards by SHA-256, so
the transcription can be checked against the bytes it came from and the source
cannot be edited afterwards to agree with the result.

Four limits, all recorded in the data file:

1. **They are not topology evidence.** Both produced cross-feed brackets and
   one states outright that it simulated "the standard eight-team
   double-elimination feed". That is an assumption about the standard bracket,
   not an observation of the locked client. The fields are `topology_used:
   cross-feed` and `topology_evidence: none`. The topology still rests entirely
   on the owner's client screenshot.
2. **They are not independent measurements.** Both read the same post-Swiss
   public narrative, which is precisely the recency signal this project's model
   underweights. Counting model + owner + reviewer + F + G as five votes on
   Liquid over Yandex would be counting one signal five times — the same error
   already rejected for the DatDota comparison.
3. **F's percentages are conditional, not marginals.** The source calls its
   later rounds conditional modal projections: "70.8%" means *if that matchup
   occurs*. Placing it beside this project's per-slot marginal of 0.2112 would
   compare two different questions.
4. **The prose is not an evidence corpus.** G's text contradicts itself — it
   states the Main Event is eight teams and then places the LB Round 1 loser
   at "13th-16th place", impossible in a field of eight. Its 14 picks are
   unaffected, which is exactly why the card is frozen and the explanation is
   not. (Checked and passing: G's stated Swiss records for all eight teams
   match `data/ti2026_outcome.yaml` exactly.)

`model_implied_expected` for F and G is **this project's model's estimate of
those cards**, not their authors' own expected accuracy.

One incidental note worth keeping: F describes its method as a
recency-weighted Elo with an approximately 60-day half-life. That is the same
time-decay hypothesis this project has deferred to a future registration, so F
is one unvalidated realisation of it — interesting, and not evidence that the
half-life is right.

## This is not an experiment

It is a **prospective out-of-sample comparison of pre-frozen decision
policies**. There is no randomisation, card E was formed after seeing the
model's per-slot probabilities, and B/C/D were constructed analytically rather
than chosen by anyone. Calling it a natural experiment would dress it in a lab
coat it has not earned.

## Metric

The 14-slot hit count already registered in
[the playoff bracket spec](2026-08-16-ti2026-playoff-bracket-prediction.md),
unchanged, applied identically to every card. The registered null under the
confirmed cross-feed topology is **3.75 / 14**.

Card E needs no subjective probabilities to be scored. The hit count is
defined on picks.

## Model-implied expected hits, and the attribution that matters

| card | model-implied E[hits] | vs A |
|---|---|---|
| A model | 4.3615 | — |
| B + Iron Wing | 4.2820 | −0.0795 |
| C + Liquid | 4.2545 | −0.1070 |
| **H owner, submitted** | **4.2039** | **−0.1576** |
| D + both | 4.2002 | −0.1613 |
| F gpt-5-6-xhigh | 4.1886 | −0.1729 |
| E owner, superseded | 4.1356 | −0.2259 |
| G gemini-3-1-pro | 4.0707 | −0.2908 |

The decomposition is the useful part. For the **submitted** card the
intermediate is C, not D: H keeps Team Spirit at UB QF1 and overrides UB QF3
(Liquid) and UB QF4 (Nigma), so D isolates a pair of roots the owner has since
abandoned and quoting it would attribute H's cost to a decision it no longer
contains.

```
A -> C   -0.1070     the Liquid override alone
C -> H   -0.0506     the Nigma override and everything downstream
A -> H   -0.1576
```

**68% of the submitted card's model-implied cost sits in the Liquid override.**
Everything else together is worth less than half of it, so the disagreement is
still essentially about one match.

For the superseded card E the corresponding split was `A -> D -0.1613`,
`D -> E -0.0646`, i.e. 71% in its two root decisions.

Every number here is model-implied and descriptive. None of it is evidence
about which card will score better.

## What D is not

D is the model's optimum given both root decisions. It is **not** the owner's
card. The model, even after losing Yandex at UB QF3, still routes Yandex deep
through the lower bracket; the owner's card removes Yandex from every branch.
That is a third, separate judgement, and it is why E is frozen as itself rather
than reconstructed from two flips.

## Subjective probabilities — a separate, smaller question

Two blocks, kept apart on purpose, both now stated before any playoff match.
They are different people's judgements and must never be merged to fill a field
that looks empty.

| match | model | reviewer | owner |
|---|---|---|---|
| Liquid > Yandex | 0.4709 | 0.53 | **0.60** |
| Iron Wing > Spirit | 0.4742 | 0.48 | **0.55** |

A three-way spread on the same two matches, all frozen in advance. The owner is
`+0.1291` and `+0.0758` from the model; the reviewer is `+0.0591` and `+0.0058`,
i.e. effectively agreeing with the model on the second match.

Both are judgmental forecasts made after the model's numbers were visible.
They are out of sample with respect to the outcomes and **not independent of
the model**, and that provenance is recorded with the numbers so it cannot
quietly inflate later.

### What each pair does and does not identify

Taken as picks, the reviewer's are Liquid and Spirit — **one** root override —
which is uniquely frozen card `C-override-liquid`.

The owner's are Liquid and Iron Wing — **both** root overrides — which is
**not** unique: cards D and E share both roots and are separated only by six
downstream slots these two numbers say nothing about. The file therefore
records `implied_root_decisions` and `consistent_with_cards: [D, E]` rather
than a single `implied_card`, and notes separately that E is the card actually
submitted.

Neither pair covers a whole bracket. That would need a stated probability for
every matchup a card forecasts. Card E is scored on the 14-slot hit count and
needs none of them.

Two binary outcomes cannot establish calibration and will not be scored as
though they could. Their value is that three positions were written down before
the matches instead of remembered afterwards.

## Interpretation, fixed in advance

One tournament cannot establish that either policy has skill. Fourteen
dependent slots on one event is a small sample, and the two cards agree on six
of them, so the comparison effectively turns on eight.

```
permitted:  "card X scored N/14 and card Y scored M/14 on TI 2026"
permitted:  attribution of the difference to specific root decisions via B/C/D
forbidden:  "the eye test beats the model"  (or the reverse) from this alone
forbidden:  promoting B, C or D to the headline after the outcomes
forbidden:  changing any frozen card
```

The question this is a first data point toward — whether watching matches
carries signal the rating model lacks — needs several events. This is event
one, and it is registered as such.

## Standing constraint

None of this alters the model. `observed_recent_form` remains a diagnostic.
Time decay and tier weighting are live, testable hypotheses for a future
registration, to be selected on out-of-sample log loss over the rolling
backtest and never on whether they move a particular pick.

An earlier claim in discussion — that no reasonable decay could shift a
strength by the 0.0776 logits this pick turns on — was an impossibility
assertion made without measurement, and is withdrawn.
