# TI 2026 group card postmortem — registration

**Status: registered 2026-08-16, before the producer exists and before any
number in it has been computed.**

The shipped group card scored 5/16. The registered capacity-constrained null
gives `P(random coherent card scores at least 5) = 0.3090`, so the result did
not demonstrate skill — and did not reject the model in favour of the null
either. 69.1% of random cards score below 5.

This document registers the diagnostics that make that sentence sharper, and
fixes in advance what they are and are not allowed to establish. It is written
first because every number below depends on a seed, a formula convention and a
reference forecast, and each of those could be chosen after the fact to flatter
the result.

## Status

**DIAGNOSTIC.** It gates nothing. It cannot promote, demote or alter any card,
shipped or pending. It is not a gate, must not be converted into one, and its
output may not be cited as grounds to change the playoff slate. The group card
it scores was submitted days before this document existed.

## Why the model-implied numbers do not exist yet

The shipped card
(`reports/card_ti2026_rules/recommended_card.json`) carries
`optimizer_marginal_objective = 4.5903`. Its own note says what that is not:

> is NOT the evaluation-simulation mean score, which is estimated by scoring
> this card against independently seeded simulated outcomes

The card was chosen to maximise that sum over those specific draws, so it is an
in-sample objective. `E_model[S]` for TI 2026 has never been computed. This
document registers its computation.

`reports/recommended_card.json` — no `card_ti2026_rules/` — is a **different
card** from a different configuration (BoomBoys `4-1`, not `elim_win`) and
carries `model_implied_expected_score = 4.629`. That number describes that
card, not the shipped one, and may not be quoted for the shipped card.

## Inputs, all frozen

The producer reads no store and fits nothing. Every input is a committed or
pinned artifact:

```
card        reports/card_ti2026_rules/recommended_card.json
marginals   reports/card_ti2026_rules/category_probabilities.csv
strengths   reports/card_ti2026_rules/strengths_calibrated.csv
rules       config/ti2026_rules.yaml
outcome     data/ti2026_outcome.yaml
```

The simulation configuration is reproduced from the shipped card's own
metadata and not re-chosen: `groups = null`, `round_one_supplied = false`,
`elimination_choice_policy = "rational"`, `n_sims = 250000`. Supplying the
group draw would answer a different question than the one the shipped card
answered.

## Registered before running

```
eval_seed  = 90001
n_sims     = 250000
card_seed  = 1          (the shipped card's own seed; recorded, not re-used)

the eval seed and the card seed MUST differ, and the producer fails if they
do not: scoring a card against the draws it was fitted to rewards it for the
noise it was fitted to, and inflates every number below.
```

`eval_seed = 90001` is not invented here. It is the seed `cli_d4` already used
against card seed 1, chosen long before TI 2026 was played and not by anyone
who had seen this result.

### RNG identity

`montecarlo.card_score_distribution` reseeds per replicate with
`random.Random(seed * 1_000_003 + i)` — the CPython standard library Mersenne
Twister, whose stream for a given integer seed is a documented compatibility
guarantee. **numpy is not on this path at all** (it appears only in
`optimize`, `duration` and `backtest`), so there is no `BitGenerator` to pin
and no `default_rng` stream-stability question to answer. The producer records
the RNG identity and the Python version in its output, following the
convention `cli_release` already uses for numpy/scipy/yaml versions.

## What is computed

### 1. Model-score distribution — an internal-consistency diagnostic

```
E_model[S]        with Monte Carlo standard error
P_model(S < 5)
P_model(S = 5)
P_model(S > 5)
```

All three tails are reported separately. For a discrete distribution
`P(S <= 5)` and `P(S >= 5)` are **not** complements, and quoting one as if it
were the other's complement is a real error, not a rounding one. Cumulative
tails are derived from these three, never measured separately.

Every probability carries its own Monte Carlo standard error, not just the
mean. At 250000 simulations the worst case (`p = 0.5`) is `0.001`, so a
reader can see immediately how little of any number here is seed noise.

**This family is a diagnostic of internal consistency only.** It asks how
surprising 5 is to the model that produced the card, using that model's own
probabilities. If the model is misspecified, its own distribution is a poor
judge of its own error. It is not a measurement of skill and may not be
reported as one.

### 2. Realized proper-score comparison against the registered reference

Not "skill measurement". The name is the claim.

```
multiclass Brier, unscaled:  BS = mean_i sum_k (p_ik - y_ik)^2
multiclass log loss, nats:   LL = -mean_i ln(p_i,actual)
BSS = 1 - BS_model / BS_reference
dLL = LL_reference - LL_model          (positive favours the model)
```

The Brier convention is frozen here because more than one exists.
`backtest.brier` in this repository is the **binary** `mean((p - y)^2)`, which
for a two-class problem is exactly **half** the sum form above. The two
numbers are on different scales and must never be compared with each other.
A ratio skill score is published for Brier; for log loss a difference is
published instead, because a ratio of negative log-likelihoods has no natural
zero.

### Reference forecast

```
q = capacity / 16 = [4-0, 4-1, elim_win, elim_loss, 1-4, 0-4] / 16
                  = [1, 2, 5, 5, 2, 1] / 16
```

This is the **team-level marginal induced by the preregistered
capacity-constrained null**, and that is the exact claim. It is not the same
distribution as that null. The null assigns categories under capacity
constraints, so different teams' outcomes are dependent; a 16x6 matrix of
identical `q` rows carries only each team's marginal forecast and says nothing
about the joint. Proper scoring rules evaluate the forecasts actually stated,
so scoring these marginals tests the marginals and not the card's joint
distribution.

What the reference does reproduce exactly is the null's expected hit count:

```
16 * sum(q^2) = (1 + 4 + 25 + 25 + 4 + 1) / 16 = 3.75
```

Because the realised outcome fills the same capacities, both reference scores
are deterministic constants, fixed here before the run and used as test
oracles:

```
Brier_ref   = 0.765625
LogLoss_ref = 1.593403231828482
```

## Interpretation, fixed in advance

```
model-score distribution   internal consistency only
proper-score comparison    realized OOS comparison on ONE event
neither, alone or together, establishes predictive skill
```

A better realized Brier than the reference on TI 2026 licenses exactly one
sentence — "the model achieved a better realized Brier score than the
reference on TI 2026" — and not "predictive skill demonstrated". Skill is a
property of expected repeated out-of-sample behaviour; propriety of a scoring
rule is itself defined in expectation, and one event still contains variance.
A cumulative skill claim waits for several frozen out-of-sample events.

The reverse is registered with equal force: a worse realized score on this one
event does not establish that the model lacks skill, and may not be used to
retire it.

## Standing conclusion this does not disturb

The playoff slate is not changed by anything in this document. Its picks were
computed before these numbers existed, and rewriting them after seeing a
postmortem is the criterion-after-the-number failure the project exists to
prevent. The correct description of that slate is **preregistered model slate;
predictive skill not yet demonstrated out of sample** — and its `+0.6115` /
`+0.5802` lifts are **model-implied edge**, never measured edge.
