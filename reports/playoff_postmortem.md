# TI 2026 playoff card postmortem

**DIAGNOSTIC.** It gates nothing and alters no card. Registered in
`docs/superpowers/specs/2026-08-23-playoff-card-postmortem.md`, merged before
this producer existed and before any number below had been computed.

Exact over all 2**14 coherent brackets. No seed, no Monte Carlo error: the leaves carry structure and probability on the same walk, so there is no generator whose stream would have to be pinned and no replicate count to report.

Store: `data/processed/ti2026-postgroup.sqlite`. Cards: `data/ti2026_playoff_cards.yaml`. Outcome: `data/ti2026_playoff_outcome.yaml`.
Topology **cross-feed**, read from the cards file.

## 1. Hit-count distribution under the model's own probabilities

| card | role | E[S] frozen | E[S] enumerated | SD[S] | realised | P(S<s) | P(S=s) | P(S>s) |
|---|---|---|---|---|---|---|---|---|
| **A-model** | headline | 4.3615 | 4.3615 | 2.4733 | **11/14** | 0.988639 | 0.007606 | 0.003755 |
| B-override-iron-wing | attribution | 4.2820 | 4.2820 | 2.4738 | 8/14 | 0.894324 | 0.050090 | 0.055585 |
| C-override-liquid | attribution | 4.2545 | 4.2545 | 2.4691 | 8/14 | 0.891883 | 0.051363 | 0.056755 |
| D-override-both | attribution | 4.2002 | 4.2002 | 2.4345 | 5/14 | 0.572436 | 0.133690 | 0.293874 |
| E-owner | attribution | 4.1356 | 4.1356 | 2.3646 | 4/14 | 0.434748 | 0.155759 | 0.409492 |
| F-gpt-5-6-xhigh | external | 4.1886 | 4.1886 | 2.4222 | 5/14 | 0.572532 | 0.144016 | 0.283452 |
| G-gemini-3-1-pro | external | 4.0707 | 4.0707 | 2.3389 | 3/14 | 0.273811 | 0.168597 | 0.557592 |
| **H-owner-final** | headline | 4.2039 | 4.2039 | 2.4073 | **7/14** | 0.821199 | 0.081898 | 0.096903 |

`P(S < s)`, `P(S = s)` and `P(S > s)` are reported separately because for a discrete `S` the cumulative tails are **not** complements. Derive either from these three; do not treat one as the other's complement.

`A-model` is the exact argmax of `E[S]` over all 16384 coherent
brackets, so its distribution is the most favourable available and is not
exchangeable with the other seven.

## Full distributions

| card | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A-model | 0.0329 | 0.0918 | 0.1268 | 0.1477 | 0.1549 | 0.1386 | 0.1111 | 0.0810 | 0.0540 | 0.0326 | 0.0172 | 0.0076 | 0.0028 | 0.0008 | 0.0001 |
| B-override-iron-wing | 0.0362 | 0.1031 | 0.1322 | 0.1368 | 0.1469 | 0.1421 | 0.1161 | 0.0810 | 0.0501 | 0.0290 | 0.0158 | 0.0072 | 0.0026 | 0.0007 | 0.0001 |
| C-override-liquid | 0.0377 | 0.0984 | 0.1319 | 0.1497 | 0.1534 | 0.1356 | 0.1075 | 0.0777 | 0.0514 | 0.0306 | 0.0159 | 0.0069 | 0.0025 | 0.0007 | 0.0001 |
| D-override-both | 0.0375 | 0.1002 | 0.1413 | 0.1504 | 0.1431 | 0.1337 | 0.1131 | 0.0819 | 0.0505 | 0.0269 | 0.0127 | 0.0057 | 0.0023 | 0.0007 | 0.0001 |
| E-owner | 0.0411 | 0.0854 | 0.1468 | 0.1615 | 0.1558 | 0.1359 | 0.1077 | 0.0769 | 0.0460 | 0.0241 | 0.0112 | 0.0049 | 0.0020 | 0.0006 | 0.0001 |
| F-gpt-5-6-xhigh | 0.0372 | 0.0996 | 0.1391 | 0.1499 | 0.1467 | 0.1440 | 0.1136 | 0.0749 | 0.0448 | 0.0258 | 0.0144 | 0.0065 | 0.0024 | 0.0008 | 0.0001 |
| G-gemini-3-1-pro | 0.0413 | 0.0928 | 0.1397 | 0.1686 | 0.1622 | 0.1370 | 0.1039 | 0.0711 | 0.0419 | 0.0229 | 0.0113 | 0.0047 | 0.0018 | 0.0006 | 0.0001 |
| H-owner-final | 0.0349 | 0.0987 | 0.1407 | 0.1529 | 0.1454 | 0.1346 | 0.1140 | 0.0819 | 0.0503 | 0.0267 | 0.0121 | 0.0052 | 0.0020 | 0.0006 | 0.0001 |

Printed in full so no single tail can be quoted without its distribution visible beside it.

## 2. Per-slot proper scores, model against the coin

| forecast | Brier (unscaled sum) | log loss (nats) |
|---|---|---|
| model slot marginals | 0.673332 | 1.370842 |
| coin slot marginals (reference) | 0.732143 | 1.485315 |

`BSS = +0.080327`, `dLL = +0.114473` nats (positive favours the model).

Brier here is the UNSCALED sum form, twice `backtest.brier`'s binary convention. The two are on different scales and must never be compared. The reference is structural: it depends on the topology and the seeding, not on who won.

This scores the 14 stated slot MARGINALS and says nothing about the joint distribution over brackets. The slots are DEPENDENT -- not 14 independent observations -- so no standard error over slots is reported.

## What these numbers do not license

Neither family establishes predictive skill, alone or together. The no-skill question was already answered against the coin by `cli_playoff_score`; the probabilities here are against the model's own distribution, so adding them to that result would count one event twice.

A small `P(S > s)` admits two readings this event cannot separate: the model was underconfident and understated a card it had got right, or the outcome was a favourable draw from a correctly-specified distribution. Both were registered in advance and neither may be presented as the finding.

The group card expected 4.5879 and realised 5; this card expected 4.3615 and realised 11. That pair is not two independent measurements -- same model, same store, overlapping teams, and the group results are inputs to these strengths. No composite statistic over the two is registered.
