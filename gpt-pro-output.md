I’ll answer as a Bayesian sports-forecasting statistician and esports ML engineer, working to the standard of a Royal Statistical Society Guy Medal review.

**TL;DR**: Do not choose the teams yet. Build a reproducible map-level forecasting model, simulate the exact TI Swiss rules across many plausible unpublished schedules, and then solve a constrained optimization problem for the 16 prediction slots. Use Claude Code as the primary builder and Codex as an independent auditor in a separate worktree. The LLMs should write, test, and inspect the forecasting system. They should not personally decide that Falcons “feel like a 4-1 team,” because that would merely be astrology with shell access.

## 1. What you are actually predicting

The screen is not asking for a simple ranking. It requires one complete assignment:

* one team at 4-0;
* two teams at 4-1;
* five elimination-round winners;
* five elimination-round losers;
* two teams at 1-4;
* one team at 0-4.

The official format is five best-of-three Swiss rounds with 16 teams, followed by five elimination matches between the 3-2 and 2-3 teams. Round 1 is set by the organizer inside two initial groups, rounds 2 and 3 remain within those groups, round 4 is cross-group, and round 5 has modified pairing behavior. The five highest-ranked 3-2 teams then choose opponents from the five 2-3 teams. ([Dota 2][1])

The rankings are not based only on series records. Valve’s tie-break sequence includes:

1. series wins;
2. series losses;
3. total wins by previous opponents;
4. game win percentage;
5. opponents’ game win percentage;
6. average game duration, with shorter being better;
7. coin toss. ([Dota 2][1])

That has an important consequence: **your simulator must generate individual maps, 2-0 versus 2-1 series scores, and preferably approximate game durations**. A model that simulates only “Team A wins the Bo3” cannot reproduce the official standings correctly.

Predictions lock when the first match begins at 10:00 CST on August 13. Valve also notes that precisely zero players have ever predicted the entire Swiss stage correctly, a charming reminder that Dota players and certainty should rarely share a room. ([Dota 2][2])

For Vienna, 10:00 China Standard Time corresponds to 04:00 CEST. Treat the evening of August 12 as your operational deadline, rather than planning a heroic 03:57 data-engineering incident.

## 2. Treat the unpublished schedule as uncertainty, not missing data

Because Round 1 groups and matchups are organizer-set, a random bracket is not the truth. But waiting until the schedule appears also wastes most of your eleven days.

Build two modes.

### Pre-schedule mode

Simulate several explicit schedule families:

* **2025-like organizer scenario**: infer a plausible group and opening-pairing structure from the previous TI.
* **Seed-banded scenario**: divide teams by current rating bands, distribute one from each band into each group, then pair stronger against weaker teams in Round 1.
* **Uniform allowed scenario**: randomly generate legal two-group splits and Round 1 pairings.
* **Adversarial scenario**: search for legal schedules that are particularly bad for the proposed prediction card.

Do not silently average these together and pretend you discovered Valve’s intentions telepathically. Produce probabilities and recommended cards for each scenario separately, plus one robust card that survives reasonably well across all of them.

Last year, the opening TI matchups were published roughly two days before play, so a late schedule reveal would not be surprising. ([BLAST.tv][3])

### Post-schedule mode

Once Valve publishes the groups and Round 1 matches:

1. replace the schedule prior with the actual schedule;
2. rerun all simulations;
3. compare the new card with the robust pre-schedule card;
4. change only assignments supported by a meaningful probability improvement.

The system should therefore accept:

```text
--schedule-mode uncertain
--schedule-mode actual --schedule-file config/ti26_schedule.yaml
```

No model retraining is needed merely because the schedule appears. Only the tournament simulation and final assignment must be rerun.

## 3. Data design

### Use map-level match data

Collect approximately 12 to 18 months of professional maps, but apply time decay rather than imposing an arbitrary hard cutoff. Hyperparameters such as a 30-, 60-, 90-, or 180-day half-life should be selected through historical backtesting.

OpenDota exposes a documented match API, while STRATZ provides its current GraphQL API. Use one as the primary source and the other for reconciliation. Cache raw responses rather than letting an agent repeatedly query the internet and reinterpret whatever happens to arrive that afternoon. ([OpenDota][4])

Each map should contain at least:

```text
match_id
series_id
league_id
start_time
patch
radiant_team_id
dire_team_id
radiant_players[5]
dire_players[5]
winner
duration
lan_or_online
best_of
forfeit_flag
standin_flags
```

### Canonicalize rosters, not organization names

Several TI client names are aliases:

* Iron Wing is the 1win roster formerly associated with Tundra;
* Team Vision is PARIVISION;
* BoomBoys is BetBoom Team;
* HULIGANI is the former L1GA roster. ([Escorenews][5])

Create both:

```text
display_team_id
roster_version_id = hash(sorted(player_account_ids))
```

The statistical identity should primarily follow the roster, while the organization name remains a display label. Otherwise, your pipeline will decide that Tundra vanished, 1win materialized from the ether, and Iron Wing has no match history. Machines are wonderfully literal in exactly the least convenient moments.

For roster changes, initialize the new roster from a weighted combination of:

* the previous team’s rating;
* individual players’ recent team ratings;
* a regional or global prior;
* roster continuity, based on the number and roles of retained players.

### Use the remaining pre-TI events

PARIVISION, competing at TI as Team Vision, won the recent Esports World Cup final against BetBoom/BoomBoys 3-1. That event should be one of the strongest recent LAN signals. ([Esports World Cup][6])

Two more tournaments run through approximately August 5:

* 1win Essence II includes nine TI-bound teams, although it is online;
* Games of the Future includes several TI teams and is being played offline in Astana. ([GosuGamers][7])

Also, the Summer Scrub update and gameplay update 7.41e have just landed. Do not assume every concurrent tournament immediately changed patches. Store the actual patch for every map and verify it before treating those matches as 7.41e evidence. ([Dota 2][8])

The sensible model is:

* long-term roster strength;
* strongly weighted recent form;
* a heavily regularized current-patch residual;
* LAN versus online effect;
* uncertainty inflation for teams with little top-level data.

Do not manually add “EWC champion bonus +50.” Let the model discover whether that result predicts future maps.

## 4. The forecasting models

Build at least two genuinely different models.

### Model A: roster-aware Glicko-2

Glicko-2 maintains a rating, rating deviation, and volatility. The rating deviation is particularly useful for qualifier teams or newly assembled rosters, where pretending to know their strength precisely would be statistical cosplay. ([glicko.net][9])

Test both:

* map-level updates;
* series-level updates.

For this particular tournament, map-level is likely more useful because map scores affect official tie-breakers.

### Model B: dynamic Bradley-Terry

Use a time-varying paired-comparison model:

[
\operatorname{logit} P(A \text{ wins a map against } B)
=======================================================

s_A(t)-s_B(t)
+\beta^\top X
]

where (s_A(t)) and (s_B(t)) are evolving team or roster strengths, and (X) can contain a small number of pre-match features:

* LAN versus online;
* roster continuity;
* region;
* patch;
* recent inactivity;
* possibly side, if side assignment information is available.

Dynamic Bradley-Terry models are designed for timestamped competitions where competitor ability changes over time. ([Proceedings of Machine Learning Research][10])

Do not begin with a neural network. There are only so many relevant tier-one Dota matches, rosters mutate constantly, and patches rearrange the game every few months. An LSTM will mostly learn to be confidently decorative.

### Combine and calibrate

Blend the models on the log-odds scale:

[
\operatorname{logit}(p)
=======================

w,\operatorname{logit}(p_{\text{BT}})
+
(1-w),\operatorname{logit}(p_{\text{Glicko}})
]

Choose (w) through rolling historical validation, not from aesthetic preference.

Then apply out-of-fold probability calibration, such as logistic recalibration. Evaluate using:

* log loss;
* Brier score;
* calibration plots;
* calibration slope and intercept;
* accuracy only as a secondary metric.

Brier score and logarithmic score are proper scoring rules, meaning they reward honest probability estimates rather than merely rewarding whichever side happened to exceed 50 percent. ([arXiv][11])

A public Noxville Glicko and Monte Carlo forecast already exists. Use it as an external baseline, not as the answer. The published million-simulation result was produced before several important recent events, so it is now mainly useful for detecting whether your own model has become wildly eccentric. ([CyberScore][12])

## 5. Validation without leaking the future

Random train-test splitting is invalid here. It would let matches from the future help estimate the past, which is a lovely way to obtain excellent metrics and useless forecasts.

Use rolling event cutoffs:

1. Choose a historical tournament.
2. Set the data cutoff to 24 hours before that tournament began.
3. Reconstruct rosters exactly as they existed at that cutoff.
4. Fit using only earlier matches.
5. predict every map and series in the tournament.
6. advance to the next tournament.

Your baseline comparisons should include:

* Glicko-2 alone;
* Elo;
* exponentially weighted recent map win rate;
* current public Noxville rating, where historically available;
* a simple bookmaker-market benchmark, kept outside model training unless you explicitly decide to include it.

The sophisticated model survives only if it improves out-of-sample log loss or Brier score without damaging calibration. Complexity is not a sacrament.

For the full tournament layer, TI 2025 is the closest historical format. Perform two replays:

* **Actual-schedule replay**: use the known 2025 opening schedule and test whether your pre-event model would have produced sensible category probabilities.
* **Hidden-schedule replay**: pretend the opening schedule was unavailable and run your schedule-scenario ensemble.

One tournament is not enough for strong statistical claims. It is enough to expose catastrophic rules-engine bugs.

## 6. Implement the Swiss simulator exactly

For each simulated TI:

1. Sample each roster’s latent strength from its estimated uncertainty distribution.
2. Sample a schedule scenario when the real schedule is unknown.
3. For every Bo3, sample a temporary series-level shock.
4. Simulate individual maps until one team gets two wins.
5. Record the 2-0 or 2-1 score.
6. Sample durations from a recent empirical duration model.
7. Recalculate the official standings and tie-breakers.
8. Generate the next-round pairings under the official constraints.
9. Simulate the five elimination-round opponent choices.
10. Simulate those five Bo3s.
11. Record each team’s final prediction category.

A series-level shock matters because maps in the same series are not independent. One team may have discovered a draft advantage, be playing poorly that day, or have apparently replaced its brains with five decorative couriers.

### Pairing implementation

The record groups are tiny. Do not bury the pairing logic inside an opaque optimization library.

Enumerate all legal perfect matchings, then select lexicographically by:

1. required group and record constraints;
2. minimum number of repeated opponents;
3. minimum ranking distance;
4. maximum ranking distance for the relevant Round 5 elimination matches;
5. random selection among exact ties.

With at most eight teams in a record group, brute-force matching is small, transparent, and testable.

### Elimination opponent choice

The 3-2 teams choose among the 2-3 teams. Because this is a new strategic variable, run three assumptions:

* rational choice: choose the opponent with the highest predicted win probability;
* noisy rational choice: use a Plackett-Luce or softmax choice model;
* random choice.

Report sensitivity. Do not quietly assume that professional teams will make the choice your code considers optimal. Humans have coaches specifically so they can disagree in more organized ways.

### Essential simulator tests

At minimum:

```text
Every simulation ends with category counts [1, 2, 5, 5, 2, 1].
Every team belongs to exactly one category.
No team plays itself.
No repeat opponent occurs unless unavoidable.
Rounds 2 and 3 remain within initial groups.
Round 4 is cross-group.
Probability rows sum to 1.
Category probability columns sum to their slot capacities.
With 16 identically rated teams, each team receives approximately
capacity(category) / 16 probability for every category.
The same data, config, and random seed reproduce byte-identical outputs.
No training row occurs after the declared as_of timestamp.
```

Run simulations in batches until:

* the chosen card remains unchanged for several batches;
* the largest Monte Carlo standard error is below your chosen threshold.

At 250,000 simulations, the worst-case sampling standard error for a single probability is roughly 0.1 percentage point. Running one million because the number looks reassuring is optional human ritual, not methodology.

## 7. Convert probabilities into the actual prediction card

After simulation, you obtain:

[
P_{i,c}
=======

P(\text{team }i\text{ finishes in category }c)
]

Do not independently choose the highest-probability team for each category. You will duplicate teams and violate slot capacities.

Define binary variables (x_{i,c}):

[
x_{i,c} =
\begin{cases}
1,&\text{team }i\text{ is assigned to category }c\
0,&\text{otherwise}
\end{cases}
]

Solve:

[
\max_x \sum_{i,c}x_{i,c}P_{i,c}
]

subject to:

[
\sum_c x_{i,c}=1
]

and:

[
\sum_i x_{i,c}=k_c
]

where (k_c) is 1, 2, 5, 5, 2, or 1.

This maximizes the expected number of correct entries. It can be solved by expanding categories into 16 individual slots and applying the Hungarian algorithm.

Produce two cards:

1. **Expected-score card**, maximizing average expected correct predictions.
2. **Robust card**, maximizing the minimum or lower-tail expected score across schedule scenarios.

If in-game categories have unequal point values, multiply (P_{i,c}) by the category’s point weight before optimization.

Optimizing the probability of a completely perfect card is a different problem because category outcomes are dependent. You would need the full joint tournament simulations rather than marginal probabilities. Given Valve’s historical note about zero perfect Swiss cards, maximizing expected score is the more defensible primary objective. ([Dota 2][2])

## 8. How to divide the work between Claude Code and Codex

Use one as the builder and the other as an independent falsifier.

My preferred arrangement:

* **Claude Code**: primary implementation and orchestration.
* **Codex**: independent review, differential tests, leakage audit, and rules-engine audit in a separate Git worktree.

Claude Code supports persistent `CLAUDE.md` project instructions, filesystem-defined subagents under `.claude/agents/`, deterministic lifecycle hooks, and MCP connections. ([Claude][13])

Current Codex supports repository instructions through `AGENTS.md`, local subagent workflows, `/agent` inspection, project-scoped MCP configuration, and isolated worktrees for parallel agents. ([OpenAI Developers][14])

Do not let both tools edit the same files simultaneously. Use:

```text
ti26-forecast/          Claude Code primary worktree
ti26-forecast-audit/    Codex audit worktree
```

For the rules engine, it is worth asking Codex to create a small independent reference implementation. Differential-test it against Claude’s production implementation using identical synthetic tournaments. Two implementations disagreeing is useful information. Two chatbots congratulating each other is not.

### Suggested repository

```text
ti26-forecast/
├── CLAUDE.md
├── AGENTS.md
├── SPEC.md
├── ASSUMPTIONS.md
├── EXPERIMENTS.md
├── pyproject.toml
├── config/
│   ├── teams.yaml
│   ├── aliases.yaml
│   ├── model.yaml
│   ├── schedule_scenarios.yaml
│   └── ti2026_rules.yaml
├── data/
│   ├── raw/
│   ├── interim/
│   └── processed/
├── src/ti26/
│   ├── ingest/
│   ├── entities/
│   ├── ratings/
│   ├── models/
│   ├── backtest/
│   ├── simulator/
│   ├── optimizer/
│   └── reporting/
├── tests/
│   ├── test_data_cutoffs.py
│   ├── test_roster_identity.py
│   ├── test_pairing_rules.py
│   ├── test_tiebreakers.py
│   ├── test_simulator_properties.py
│   └── test_optimizer.py
└── reports/
```

Keep a canonical agent contract and copy its hard constraints into both `CLAUDE.md` and `AGENTS.md`. Add a CI check that detects instruction drift.

### Claude Code agents

Create narrowly scoped agents:

```text
.claude/agents/data-auditor.md
.claude/agents/rules-engineer.md
.claude/agents/statistical-reviewer.md
.claude/agents/leakage-red-team.md
.claude/agents/reproducibility-auditor.md
```

The data auditor should not edit models. The statistician should not rewrite ingestion. The reviewer should preferably be read-only.

Use hooks to:

* block modification of immutable `data/raw`;
* block accidental access to secret files;
* run formatting and static checks after edits;
* run targeted tests after simulator changes;
* require the full test suite before completion;
* reject a final report if it lacks the Git SHA, data-manifest SHA, config SHA, cutoff timestamp, and random seed.

Use MCP only for read-only access or documentation. For actual forecasting data, ordinary Python ingestion scripts that cache timestamped JSON are more reproducible than allowing an agent to query a live MCP source midway through reasoning.

## 9. Eleven-day execution plan

### August 1 to 2

Write and freeze:

* `SPEC.md`;
* official rule transcription;
* aliases and roster identities;
* raw data schema;
* data provenance format;
* simulator property tests.

Do this before modeling. Otherwise, the model will be “temporarily” built around whatever data happened to be easiest, and temporary decisions are humanity’s most durable infrastructure.

### August 3 to 5

Implement:

* OpenDota and STRATZ ingestion;
* roster-version normalization;
* immutable raw snapshots;
* Glicko-2 baseline;
* dynamic Bradley-Terry baseline;
* rolling backtest harness.

Ingest the completed 1win Essence II and Games of the Future results when available.

### August 6 to 7

Run model selection:

* decay half-life;
* roster carryover strength;
* feature ablations;
* calibration;
* Glicko versus Bradley-Terry versus ensemble.

Freeze the winning specification. After this point, new matches may update parameters, but should not inspire frantic hand-tuning.

### August 8 to 9

Implement:

* exact Swiss pairing and ranking;
* map-score and duration simulation;
* elimination opponent choice;
* schedule-scenario ensemble;
* constrained card optimizer.

Run at least 100,000 provisional simulations.

### August 10

Codex performs a read-only audit:

* future leakage;
* incorrect roster identities;
* incorrect 2026 rules;
* unstable pairings;
* tie-break bugs;
* suspicious feature engineering;
* reproducibility failures.

Claude Code fixes only findings supported by tests or evidence.

### August 11

Generate:

* provisional expected-score card;
* provisional robust card;
* schedule sensitivity report;
* model comparison report;
* uncertainty report.

Set an automated schedule watcher or at least perform several official-page checks.

### August 12

Final run:

```text
fetch latest results
validate data manifest
update official rosters
load actual schedule if published
fit frozen model specification
run 500,000 simulations
optimize expected and robust cards
compare assignments
write final report
enter predictions
```

Finish by approximately 22:00 Vienna time. Keep an automated late-schedule rerun available, but do not structure your life around being awake at 04:00 because Valve enjoys suspense.

## 10. Ready-to-paste implementation prompt

Use this with either Claude Code or Codex:

```text
You are the lead engineer for a reproducible forecasting system for
The International 2026 Dota 2 group stage.

OBJECTIVE

Maximize the expected number of correct assignments across these fixed
prediction categories:

- 4-0: 1 team
- 4-1: 2 teams
- Elimination Round winner: 5 teams
- Elimination Round loser: 5 teams
- 1-4: 2 teams
- 0-4: 1 team

The opening groups and Round 1 matchups are currently unknown and are set
by the tournament organizer. Treat them as explicit uncertainty, not as
random facts silently assumed by the implementation.

NON-NEGOTIABLE REQUIREMENTS

1. Predictions must be produced only by executable code and recorded data.
   Never select teams using LLM intuition.

2. Every external input must have:
   - source
   - retrieved_at
   - event_time
   - as_of cutoff
   - content hash

3. Raw source snapshots are immutable.

4. No temporal leakage:
   - no random train/test split
   - all validation is rolling and event-based
   - no feature may contain information unavailable at prediction time

5. Canonicalize teams by roster version.
   Organization and TI display names are aliases only.

6. Implement the official TI 2026 Swiss pairing, ranking, tiebreak, and
   elimination-choice rules exactly.
   Any organizer behavior not specified by the official rules must appear
   as a named stochastic schedule scenario.

7. Simulate maps, not only series winners, because game-win percentage and
   average duration are official tiebreakers.

8. Every random operation must accept an explicit seed.

9. Re-running the same git commit, data manifest, config, cutoff, and seed
   must produce identical outputs.

10. Do not produce a final team card until:
    - unit tests pass
    - property tests pass
    - rolling backtests are complete
    - probability calibration is reported
    - a simple Glicko baseline is included

MODELS

Implement:
- roster-aware Glicko-2 baseline
- time-decayed dynamic Bradley-Terry map model
- out-of-fold calibrated ensemble

Select hyperparameters through rolling historical backtests using log loss,
Brier score, and calibration. Accuracy is secondary.

SIMULATOR

For each simulated tournament:
- sample uncertain team strengths
- sample a legal initial schedule scenario when schedule is unknown
- simulate individual maps and series scores
- simulate game durations
- apply exact standings and tiebreakers
- generate legal subsequent pairings
- model elimination opponent selection
- record one of the six final categories for each team

The simulator must satisfy these invariants:
- final category counts are exactly [1, 2, 5, 5, 2, 1]
- each team has exactly one category
- no self-pairings
- no illegal repeats
- rounds 2 and 3 remain within initial groups
- round 4 is cross-group
- category probabilities sum correctly
- equal-strength teams produce symmetric probabilities

OPTIMIZER

Given P[team, category], solve the constrained assignment that maximizes
expected correct predictions.

Also produce a robust assignment that maximizes lower-tail performance
across schedule scenarios.

DELIVERABLES

- SPEC.md
- ASSUMPTIONS.md
- EXPERIMENTS.md
- data_manifest.json
- category_probabilities.csv
- matchup_probabilities.csv
- schedule_sensitivity.csv
- recommended_card_expected.json
- recommended_card_robust.json
- backtest_report.md
- final_report.md
- complete automated test suite

Every report must include:
- git SHA
- data manifest SHA
- config SHA
- as_of cutoff
- random seed
- model version
- backtest metrics

WORKFLOW

First inspect the repository and write a detailed implementation plan.
Then create the specification and tests before production code.

Use independent subagents for:
- source and roster audit
- statistical methodology audit
- Swiss rules audit
- leakage audit
- reproducibility audit

Only one agent may write a given subsystem at a time.
Reviewers should be read-only unless explicitly assigned a separate worktree.

Do not claim completion unless every required command was actually run and
its output is reported.
```

Then give the other tool this audit prompt:

```text
Audit commit <SHA> as an adversarial statistical and rules-engine reviewer.

Do not accept the implementation's own claims.

Try to falsify:
1. absence of temporal leakage
2. roster and alias correctness
3. official Swiss pairing implementation
4. tiebreak calculation
5. map-to-series simulation
6. schedule uncertainty handling
7. elimination opponent-choice assumptions
8. calibration methodology
9. optimizer correctness
10. deterministic reproducibility

Construct minimal counterexamples and property tests for every suspected
defect. Do not modify production code. Return findings ordered by severity,
with exact file locations, commands run, evidence, and proposed regression
tests.
```

The correct strategy is therefore: **build now, forecast provisionally under schedule uncertainty, freeze methodology before the last results arrive, and rerun immediately when the actual groups appear**. The final prediction may still be wrong, but at least it will be wrong for documented, reproducible reasons, which is approximately as much dignity as probability allows.

[1]: https://www.dota2.com/esports/ti15/tirules?utm_source=chatgpt.com "Dota 2 Esports"
[2]: https://www.dota2.com/newsentry/678505520073540063?utm_source=chatgpt.com "The International: Predictions, Fantasy, and Supporter Bundles"
[3]: https://blast.tv/dota/news/dota-2-the-international-2025-ti14-group-stage-schedule?utm_source=chatgpt.com "Dota 2 The International 2025 (TI14) Group Stage schedule revealed"
[4]: https://api.opendota.com/api?utm_source=chatgpt.com "https://api.opendota.com/api"
[5]: https://escorenews.com/en/dota-2/article/79956-who-are-iron-wing-vision-boomboys-and-huligani-at-the-international-2026-where-is-tundra-and-parivision-in-ti15-compendium?utm_source=chatgpt.com "Who are Iron Wing, Vision, BoomBoys and Huligani at The International 2026. Where is Tundra and Parivision in TI15 Compendium — Escorenews"
[6]: https://esportsworldcup.com/en/press-releases/pvision-surpass-regional-rivals-to-win-dota-2-at-ewc-2026?utm_source=chatgpt.com "Esports World Cup | Press Releases"
[7]: https://www.gosugamers.net/dota2/news/78867-dota-2-1win-essence-ii-offers-one-final-look-at-teams-before-the-international-2026-begins?utm_source=chatgpt.com "Dota 2 1win Essence II offers one final look at teams before The International 2026 begins | GosuGamers"
[8]: https://www.dota2.com/summerscrub2026?l=english&utm_source=chatgpt.com "Summer Scrub 2026"
[9]: https://www.glicko.net/glicko/glicko2.pdf?utm_source=chatgpt.com "https://www.glicko.net/glicko/glicko2.pdf"
[10]: https://proceedings.mlr.press/v108/bong20a/bong20a.pdf?utm_source=chatgpt.com "https://proceedings.mlr.press/v108/bong20a/bong20a.pdf"
[11]: https://arxiv.org/html/2504.01781v4?utm_source=chatgpt.com "Proper scoring rules for estimation and forecast evaluation"
[12]: https://cyberscore.live/en/news/the-international-2026-favorites-based-on-simulation-by-noxville/?utm_source=chatgpt.com "The International 2026: Noxville ran a million tournament simulations and identified the statistical favorites | CyberScore"
[13]: https://code.claude.com/docs/en/memory?utm_source=chatgpt.com "How Claude remembers your project - Claude Code Docs"
[14]: https://developers.openai.com/codex/subagents/ "Subagents | ChatGPT Learn"
