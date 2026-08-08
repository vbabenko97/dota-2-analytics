# TI 2026 Group Stage Rules — fetched, verbatim

**Fetched 2026-08-08 from <https://www.dota2.com/esports/ti15/tirules>** with a
headless browser (Playwright), `document.body.innerText`.

This is the first successful retrieval of this page in the project's history.
Every prior attempt returned a heading with no body, because the page is
JavaScript-rendered and a plain HTTP fetch sees the shell only — recorded in the
design spec, re-confirmed 2026-08-07, and the sole reason
`config/ti2026_rules.yaml` has carried `reported_official` and
`owner_transcript_2025_inherited` tags rather than `official`.

**It is not an immutable input.** No snapshot binds it and no manifest hashes
it; the page can change and this file would not know. It is a dated observation,
archived because the alternative — citing a URL that renders empty to anyone who
tries it without a browser — is what this project spent a week correcting.

Earlier the same day, the owner's check of the TI 2026 page found a format
section and recorded that **"the 2026 text has no Swiss Pairing Rules section
and no schedule"**
([published format rules](2026-08-08-published-format-rules.md)). The section
below was present at 18:02 UTC. Either it was published in the interim or it was
missed; the archived text is what the page said when read.

## Verbatim

```
The International: Group Stage Rules
Teams are ranked from best to worst based on the following criteria, evaluated in order:
Number of Matches Won
Number of Matches Lost
Total Number of Matches Won by Opponents Played
Percentage of Games Won
Average Percentage of Games Won by Opponents Played
Average Game Duration (Shorter is Better)
Coin Toss


Teams are paired using the General Swiss Pairing Rules. Rounds that have modifications to these rules are notated below
Teams with the same record are paired against each other
Avoid repeat pairings when possible
Minimize the distance in ranking between the teams when possible


Modifications to the General Swiss Pairing Rules by Round
Round 1
Teams are split into two different Groups
Matchups are set by the tournament organizer, with teams playing other members of their group
Round 2
Teams are only matched against other members of their initial group
Round 3
Teams are only matched against other members of their initial group
Round 4
Teams are only matched against members of the other group
Round 5
For matches where the loser is eliminated, maximize the distance in ranking between the teams


Elimination Round
Starting with the best 3-2 team, they will choose any of the five 2-3 teams as their opponent.
The next best 3-2 team will then choose any of the remaining 2-3 teams as their opponent.
Repeat the above until all teams have chosen an opponent.
The International: Seeding
All eight teams that qualify to The International will be seeded based on their final Swiss Ranking
```

## How this differs from TI 2025, and from what is currently configured

TI 2026 is **not** TI 2025 with the numbers changed. Four differences, and the
implementation is currently wrong on all four — because on 2026-08-08 it was
"corrected" against a transcript of **TI 2025's** rules, which was the best
source available at the time.

| # | TI 2026, as fetched | TI 2025, as transcribed | `config/ti2026_rules.yaml` today |
|---|---|---|---|
| 1 | criterion 3 is opponents' matches won, 4 is percentage of games won | 3 is percentage of games won, 4 is opponents' matches won | TI 2025's order — **wrong for 2026** |
| 2 | criterion 6 is **Average Game Duration (shorter is better)**, 7 criteria total | no duration criterion, 6 total | no duration — **wrong for 2026** |
| 3 | Round 5: **maximize distance where the loser is eliminated** | Round 5: no special modifications | no Round 5 modification — **wrong for 2026** |
| 4 | Elimination Round: best 3-2 team **chooses** its opponent, then the next, and so on | Elimination Round: distance is maximized | `maximize_ranking_distance: true` — **wrong for 2026** |

Note the direction of the error. The implementation held all four of these
correctly **before** 2026-08-08, and commit `23beac3` changed them to match TI
2025. The design spec's original values were right for TI 2026 and were
overwritten with a better-sourced version of the wrong year's rules.

The two rules that the transcript could not confirm and that this page settles
in the implementation's favour — group structure and the within/cross-group
round assignments — are unchanged and correct.

## What is still not answered here

- **The Round 1 matchups.** The page says they are set by the tournament
  organizer within the groups. It does not give them, and the groups themselves
  were unannounced as of this fetch. `--groups` already accepts exact Round 1
  pairings as well as group membership, so no code change is needed when they
  appear.
- **Whether this page will change again before the lock.** Valve added this
  section during the day it was first checked. The near-lock runbook's field
  confirmation step should re-fetch this page too, not just the team list.
