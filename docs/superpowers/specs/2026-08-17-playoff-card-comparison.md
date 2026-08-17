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

```
PR #28  merged_at         2026-08-17T08:21:38Z    (GitHub server timestamp)
PR #28  merge_commit_sha  1e5960e7162d80cdf5dd862bb341c437fb2263ef
frozen commit             3ebff935b4e45cb891ce97ee7ba1399ceb9a006b
                          verified: an ancestor of that merge commit
```

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
headline:      A-model  vs  E-owner
attribution:   B, C, D  — may NOT be promoted to the headline afterwards
```

B, C and D are analytic constructions. Naming the headline in advance is the
whole point: after the outcomes, five cards offer five stories, and the
flattering one would be available to whichever side lost.

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
| D + both | 4.2002 | −0.1613 |
| E owner | 4.1356 | −0.2259 |

The decomposition is the useful part:

```
A -> D   -0.1613     the two root decisions
D -> E   -0.0646     all six remaining differences combined
```

**71% of the model-implied cost of the owner's card sits in the two root
decisions**, `Spirit -> Iron Wing` and `Yandex -> Liquid`. The cascade into six
further slots looks large in a diff and is nearly free in expectation. So the
disagreement really is about those two matches, despite the table.

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
