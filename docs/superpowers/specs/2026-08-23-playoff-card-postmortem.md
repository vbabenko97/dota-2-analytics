# TI 2026 playoff card postmortem — registration

Registered 2026-08-23. The producer named here, `cli_playoff_postmortem`, does
**not exist yet**: this document is written first, and no number it describes has
been computed. That ordering is the only protection this measurement has, and it
is a weaker one than the playoff cards themselves enjoy.

## What is already known, and why that matters

The outcome is public. Card `A-model` scored **11/14** and its frozen
model-implied expectation is **4.3615**
([`data/ti2026_playoff_cards.yaml`](../../../data/ti2026_playoff_cards.yaml),
[the comparison registration](2026-08-17-playoff-card-comparison.md)).

So this is **not** preregistration. It is a post-outcome diagnostic whose method
is fixed before its numbers exist — the same standing as
[the group card postmortem](2026-08-16-group-card-postmortem.md), and the same
limit. The direction of the divergence is known, which is precisely why no
one-sided tail and no threshold is registered below: choosing either now, with
11 in hand, would be the criterion-after-the-number failure the project exists
to prevent. Both tails and the full distribution are registered instead, so
there is nothing left to choose.

## Status

**DIAGNOSTIC.** It gates nothing. It cannot promote, demote, reorder or alter
any card, and it may not be converted into a gate. It cannot change the model,
the ratings, the store, or any frozen artifact. Every card it scores was frozen
and merge-anchored before the first Main Event match; nothing here reaches back.

## The question, stated so it cannot drift

Given the model's own frozen pre-event probability distribution over playoff
outcomes, how probable was a hit count at least as high as the one the card
actually achieved?

That is a question about **internal consistency**, not about skill. It asks
whether the outcome fell where the model's own distribution said it plausibly
could. A model that is misspecified is a poor judge of its own error, so a
surprising answer indicts the distribution as readily as it flatters the pick.

## What this is NOT, registered before the numbers exist

The skill question against a null is **already answered and already published**:
`P(random coherent bracket >= 11) = 0.004517`, enumerated against the realised
bracket in [`cli_playoff_score`](../../../src/ti26/cli_playoff_score.py) and
recorded in the comparison registration.

`P_model(S >= 11)` is a **different quantity against a different reference** —
the model's own distribution, not the coin's. Reporting the two as though they
were two pieces of evidence would count one event twice. They are one event
viewed from two angles, and the registration says so in advance.

## Inputs, all frozen or recomputed and checked

```
cards       data/ti2026_playoff_cards.yaml            picks, roles, frozen E[hits]
outcome     data/ti2026_playoff_outcome.yaml          the realised 14 winners
topology    cross-feed, read from the cards file      never hardcoded
store       data/processed/ti2026-postgroup.sqlite    the store that reproduces
                                                      all eight frozen literals
teams       config/ti2026_teams.yaml
aliases     config/team_aliases.yaml
gate config config/d2_gate.yaml                       glicko_tau only
```

The strengths are not stored as an artifact, so they are refitted by the same
path `cli_playoff_cards` uses — `derive_glicko_calibration_slope`, `GlickoModel`
over all rows, `resolve_rosters`, `team_strengths`, `apply_correction`. The
producer must therefore prove it reconstructed the same distribution the cards
were frozen under.

### Precondition: the mean must reproduce the frozen literal

For every card, the mean of the hit-count distribution the producer builds
equals that card's frozen `model_implied_expected`, because
`E[S] = Σ_slot P(slot pick correct)` is exactly the sum those literals record.

```
|E_model[S] - model_implied_expected| <= 0.00005     (TOLERANCE, as in cli_playoff_cards)
```

**On failure the producer exits non-zero and reports nothing.** There is no
fallback and no recomputation with different arguments. A distribution whose
mean does not reproduce the frozen literal is not the pre-event distribution,
and every tail derived from it would be describing a different model.

### No seed, and why this one has none to register

The group card postmortem had to register `eval_seed = 90001`, pin an RNG
identity, and force the eval seed to differ from the card seed. **None of that
applies here, and the reason is structural rather than a relaxation.**

The playoff outcome space is 2\*\*14 = 16384 leaves. `slot_distributions` already
enumerates all of them, carrying structure and probability on the same walk, so
every quantity below is **exact**. There are no draws, no Monte Carlo standard
error, no BitGenerator, and no stream-stability question. `numpy` is not on this
path.

The in-sample concern the seed separation existed to address is still real and
is handled differently: card A is the **argmax** of `E[S]` over all 16384
coherent brackets, so its expectation is the highest any card can have and its
distribution is the most favourable available. Verified rather than assumed
before registering this — `bracket.best_bracket` over the store above returns
exactly A's fourteen picks, and its value is A's frozen literal.

That is a fact about the card's construction, not noise it was fitted to: an
exact optimum over a full outcome space has no sampling noise to overfit, which
is why no held-out seed is needed. It still means A's distribution is not
exchangeable with the other seven cards', and the producer records A as an
in-sample optimum next to its numbers on every run.

## What is computed

### 1. Hit-count distribution, exactly, for all eight frozen cards

All eight, named in advance so none can be selected afterwards: `A-model`,
`B-override-iron-wing`, `C-override-liquid`, `D-override-both`, `E-owner`,
`F-gpt-5-6-xhigh`, `G-gemini-3-1-pro`, `H-owner-final`.

```
P_model(S = k)  for every k in 0..14        the full table, always printed
E_model[S]      checked against the frozen literal
SD_model[S]
P_model(S < s)  |
P_model(S = s)  |  s = that card's realised score
P_model(S > s)  |
```

The full table is printed for every card so no single tail can be quoted without
its distribution visible beside it. All three point/tail terms are reported
separately: for a discrete `S`, `P(S <= s)` and `P(S >= s)` are **not**
complements, and treating one as the other's complement is a real error rather
than a rounding one. Cumulative tails are derived from the table, never measured
separately.

### 2. Per-slot proper scores against the coin reference

The hit count discards the probabilities and keeps only the argmax. This scores
the probabilities themselves. Conventions frozen here because more than one
exists:

```
multiclass Brier, unscaled:  BS = mean_slot  sum_team (p - y)^2
multiclass log loss, nats:   LL = -mean_slot ln(p_realised winner)
BSS = 1 - BS_model / BS_reference
dLL = LL_reference - LL_model              (positive favours the model)
```

Identical to the conventions registered for the group card, and for the same
reason: `backtest.brier` in this repository is the **binary** `mean((p - y)^2)`,
exactly half the sum form above. The two are on different scales and must never
be compared. A ratio skill score is published for Brier; for log loss a
difference is published, because a ratio of negative log-likelihoods has no
natural zero. Log loss is reported in nats and returns `inf` rather than
clipping, per [`proper_scores`](../../../src/ti26/proper_scores.py).

#### Reference forecast

The coin's own slot marginals: `slot_distributions` with every series at 0.5.
These are uniform over the teams that can reach each slot — a fact
`cli_playoff_score` asserts on every run, and the same fact that makes the
registered null 3.75 equal to the outcome-conditional mean.

The reference is therefore **structural and outcome-independent**: it depends
only on the bracket topology and the seeding, not on who won. It is a
deterministic constant and the producer emits it, rather than this document
freezing a literal it would have to compute today. A test asserts the reference
is unchanged when the outcome is changed — if it moves, it was never a
reference.

#### What scoring marginals does and does not test

The model states a distribution per slot. Proper scoring rules evaluate the
forecasts actually stated, so this tests **the 14 slot marginals** and says
nothing about the joint distribution over brackets — the same caveat the group
card's `16x6` matrix of identical rows carries.

The 14 slots are **dependent**. They are not 14 independent observations and no
standard error over slots may be reported as though they were. This is one
event, and the mean over slots is a summary of one event.

## Interpretation, fixed in advance

```
hit-count distribution   internal consistency only
proper-score comparison  realized OOS comparison on ONE event
neither, alone or together, establishes predictive skill
```

A small `P_model(S >= 11)` admits at least two readings that **one event cannot
separate**:

1. the model was underconfident — its slot probabilities were closer to 0.5 than
   the truth, so it understated a card it had actually got right;
2. the outcome was a favourable draw from a correctly-specified distribution.

Registering this now, before the number exists, means neither reading may later
be presented as the finding. If the value is small, the honest report names both
and prefers neither.

The reverse is registered with equal force. A `P_model(S >= 11)` near the middle
of the distribution would establish only that the model was internally
consistent on this one card — not that it has skill, and not that the coin
comparison means less than it says.

Permitted and forbidden, explicitly:

```
permitted:  "the model's own frozen distribution assigned probability p to a
             hit count at least as high as the one card X achieved"
permitted:  the same statement for the proper scores, naming the reference
forbidden:  reading P_model as a p-value against a no-skill null
            (the coin null already answers that, at 0.004517)
forbidden:  adding P_model and the coin tail as two pieces of evidence
forbidden:  "the model is well calibrated" / "the model is miscalibrated"
            from one event
forbidden:  any change to the model, the ratings, or a frozen card
forbidden:  a threshold on any quantity here, since the outcome is known
```

## The pair with the group card, and its limit

The group card expected **4.5879** and realised **5**. The playoff card expected
**4.3615** and realised **11**. Registered in advance: the pair is interesting
and the pair is **not** two independent measurements.

Same model, same store, overlapping teams, and the group stage's results are
inputs to the playoff strengths. Fourteen dependent slots on one event, and
sixteen on another, can look internally consistent on one and not the other from
sampling alone. No composite statistic over the two is registered and none may
be constructed afterwards.

## Delivery

This document merges **before** the producer is written, per the project's
register-before-you-measure rule. The producer, its tests — each naming the
mutation it kills — and its output land in a separate PR afterwards.

## Standing conclusion this does not disturb

The description of card A stands unchanged: **preregistered model slate that
scored 11/14 on one event, above a 3.75 coin null, with predictive skill not
demonstrated out of sample.** Its `model_implied_expected` remains model-implied
edge and never measured edge. Nothing in this document licenses upgrading that
sentence, and its purpose is partly to make the upgrade harder.
