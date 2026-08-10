<!-- ti26-run: 61c63f4aa32c573cdbc7e4abe48e08308801f1ff3cb8e5629a4ae446d5d22b6b manifest.json -->
# D2 gate result

**Verdict: FAIL**

Pre-registered 2026-08-02 in `config/d2_gate.yaml`, before any backtest ran:

- required margin: `mean(LL_elo - LL_glicko) >= 0.003` nats/map
- required significance: paired bootstrap 95% CI excludes 0

Observed margin: **-0.00356** nats/map, CI [-0.02037, 0.00649]

Interval method: cluster bootstrap over 191 tournaments. Maps compared: 26830.

Excluded from scoring: 2093 maps (2093 null_team). 28923 out-of-sample maps total minus 2093 excluded is 26830 compared -- the model itself declined to rate these rows (`null_team`/`bad_roster`), so the gate scores only the population it was willing to train on, per spec IV.

The interval is a **cluster** bootstrap, not an iid one over maps: maps inside a series share teams, day, patch and momentum, and treating them as independent would understate the interval and let this gate pass on noise.

Folds: 192 tournaments, 28923 out-of-sample maps.

## Backtest metrics

| model | log loss | Brier | accuracy | cal. slope | cal. intercept |
|---|---|---|---|---|---|
| constant | 0.69315 | 0.25000 | 0.5212 | nan | nan |
| ewma | 0.70655 | 0.25540 | 0.5265 | 0.213 | 0.084 |
| elo | 0.69446 | 0.25047 | 0.5363 | 0.445 | 0.085 |
| glicko | 0.69802 | 0.25099 | 0.5431 | 0.405 | 0.085 |

Accuracy is reported but never used for selection (spec II): it is not a proper scoring rule.

## Floor check (spec V)

Spec V: each rating model must beat the constant 50/50 floor on rolling out-of-sample log loss to be trusted as a strength source. Checked here independently of the Elo-vs-Glicko significance gate above -- a model can lose that comparison and still clear the floor, or win it and still lose to a coin flip.

| model | log loss | vs floor | cleared |
|---|---|---|---|
| constant | 0.69315 | -- | -- (floor) |
| ewma | 0.70655 | +0.01340 | **NO** |
| elo | 0.69446 | +0.00131 | **NO** |
| glicko | 0.69802 | +0.00487 | **NO** |

**Selected model for the card: elo. Floor cleared: NO.**

**No card ships from our fit.** the elo-vs-glicko gate failed under `--final-model auto` (spec X: rung 3 is the default on a failed gate, never a quiet fallback to rung 2), so no card is written and no other model is silently substituted in its place. Spec X rung 3: use public ratings (Noxville/datdota) instead -- write a `team,strength` CSV and run `python -m ti26.cli --strengths <file>`.

## Consequence

**Do not proceed to D3.** Reasons: margin -0.00356 < pre-registered 0.003 nats/map; bootstrap 95% CI [-0.02037, 0.00649] includes 0

## Duration model (spec XII)

Fitted from 41082 real map durations, conditioned on pre-match rating gap: `log_mean=7.5793`, `log_sigma=0.2806`, `gap_coefficient=-0.0015` (SE 0.0058, material=False). The placeholder was 7.65 / 0.25 with provenance `arbitrary`.

**Config staleness check:** `config/ti2026_rules.yaml` currently has `log_mean=7.5793`, `log_sigma=0.2806`. Matches the fit above; a card built this run used these current values.

## Card

Status: REFUSED: the elo-vs-glicko gate failed under --final-model auto, so per spec X rung 3 no card ships from our fit -- regardless of whether elo would separately clear the spec V floor (here: not cleared; see the Floor check table).

## Roster staleness (spec III)

Two independent checks per configured team: does the SAME roster appear later under a different, unaliased team_id (a possible migration -- this is exactly how the Tundra Esports/1win entry went stale until a human fact-check caught it), and how long since this roster's last map relative to the store's own most recent map. A migration hit does not by itself mean the entry is wrong: several configured teams are already-confirmed duplicate team_id registrations for the SAME org (Xtreme Gaming, HULIGANI, Team Resilience -- see `ti2026_teams.yaml`'s ledger) and produce this identical signature. This check WARNS rather than hard-failing `cli_d2` for exactly that reason: a hard fail would block a correct run on those every time. Every hit below needs a human cross-check against what is already documented before being treated as new news.

| team | team_id | last map | stale (days) | possible migration |
|---|---|---|---|---|
| Aurora Gaming | 9467224 | 2026-07-15 | 18.1 | -- |
| BoomBoys | 8255888 | 2026-08-01 | 1.0 | -- |
| GamerLegion | 9964962 | 2026-08-02 | 0.1 | -- |
| HULIGANI | 10149530 | 2026-06-28 | 35.1 | **team_id=10208009 on 2026-07-31 (5/5 accounts)** |
| Iron Wing | 10182357 | 2026-08-02 | 0.0 | -- |
| LGD Gaming | 10150538 | 2026-08-01 | 1.2 | **team_id=10208068 on 2026-08-01 (5/5 accounts)** |
| Nigma Galaxy | 10136357 | 2026-08-02 | 0.2 | -- |
| OG | 2586976 | 2026-08-02 | 0.2 | -- |
| Team Falcons | 9247354 | 2026-08-02 | 0.0 | -- |
| Team Liquid | 2163 | 2026-08-01 | 0.8 | -- |
| Team Resilience | 5017210 | 2026-06-18 | 45.3 | **team_id=10207984 on 2026-07-31 (5/5 accounts)** |
| Team Spirit | 7119388 | 2026-07-16 | 17.1 | -- |
| Team Vision | 9572001 | 2026-06-25 | 37.9 | **team_id=9824702 on 2026-07-07 (5/5 accounts)** |
| Team Yandex | 9823272 | 2026-07-19 | 14.2 | -- |
| Vici Gaming | 726228 | 2026-08-01 | 1.2 | -- |
| Xtreme Gaming | 8261500 | 2026-07-14 | 19.0 | **team_id=10208071 on 2026-07-31 (5/5 accounts)** |

**5 configured team(s) show a possible migration: Xtreme Gaming (team_id=8261500 -> 10208071), Team Vision (team_id=9572001 -> 9824702), HULIGANI (team_id=10149530 -> 10208009), Team Resilience (team_id=5017210 -> 10207984), LGD Gaming (team_id=10150538 -> 10208068).** Check each against `ti2026_teams.yaml`'s ledger before the card ships.

## Duration sensitivity

Strengths used for this sweep: diagnostic only, not endorsed: disqualified elo strengths (16 teams). The sweep measures the SIMULATOR's sensitivity to the duration parameter, not the quality of these strengths -- it runs regardless of the floor verdict above.

| log_sigma | max abs delta vs fitted |
|---|---|
| 0.2806 | 0.00000 |
| 0.1403 | 0.00280 |
| 0.4209 | 0.00272 |
| 0.2500 | 0.00124 |

Largest movement in any single category probability when the duration parameter is varied. Spec §XII requires this parameter's influence to be reported rather than assumed away. The table above is that report; this run measures the movement, not the share of any ranking the parameter accounts for.
