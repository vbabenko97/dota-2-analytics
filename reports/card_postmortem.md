# TI 2026 group card postmortem

**DIAGNOSTIC -- gates nothing, alters no card. The card it scores was already
submitted, and nothing here may be used to change the pending playoff slate.**

Card: `reports/card_ti2026_rules/recommended_card.json`, observed score **5/16**.
Evaluation: 250000 simulations at eval seed **90001**, card seed 1 (they must differ, and the producer refuses if they do not).
RNG: `random.Random(seed * 1_000_003 + i)` per replicate -- CPython 3.13.5 Mersenne Twister. numpy is not on this path.

## What the model expected of itself

`E_model[S]` = **4.5879** +/- 0.0037 (MC standard error), against the registered random-card mean of 3.75.

| tail | P | MC SE |
|---|---|---|
| `P_model(S < 5)` | 0.5015 | 0.0010 |
| `P_model(S = 5)` | 0.2006 | 0.0008 |
| `P_model(S > 5)` | 0.2979 | 0.0009 |

Derived: `P_model(S <= 5)` = 0.7021, `P_model(S >= 5)` = 0.4985. These are **not** complements.

This family is an INTERNAL CONSISTENCY diagnostic. It asks how surprising 5 is to the model that produced the card, using that model's own probabilities. If the model is misspecified its own distribution is a poor judge of its own error, so this measures no skill and must not be reported as if it did.

## Realized proper-score comparison against the registered reference

Reference `q = capacity / 16` -- the team-level MARGINAL induced by the preregistered capacity-constrained null, not that null's joint distribution. It reproduces the null's expected hit count exactly: **3.7500**.

| score | model | reference | comparison |
|---|---|---|---|
| multiclass Brier (unscaled) | 0.709012 | 0.765625 | BSS **+0.0739** |
| multiclass log loss (nats) | 1.402089 | 1.593403 | dLL **+0.1913** |

Brier here is the unscaled sum form `mean_i sum_k (p_ik - y_ik)^2`. `backtest.brier` is the BINARY `mean((p - y)^2)`, exactly half this for two classes; the two are on different scales and may not be compared.

A positive BSS licenses one sentence -- the model achieved a better realized Brier score than the reference on TI 2026 -- and not 'predictive skill demonstrated'. Skill is a property of expected repeated out-of-sample behaviour, and one event still contains variance. The reverse is registered with equal force: a negative BSS on one event does not retire the model.
