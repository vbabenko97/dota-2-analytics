# The published format rules, as transcribed by the project owner

**Supplied 2026-08-08 by the project owner.** This is the archived copy this
repository never had. Until now every format value here reached the code
secondhand, through citations the originating session could not open, from a
JavaScript-rendered page that returned no body — a failure reproduced again on
2026-08-07.

**What this document is:** a human transcription, pasted by the owner, committed
verbatim. It is not a fetch, and no automated check can confirm it against
Valve. That is why the provenance tags it supports are `owner_transcript_2026`
and `owner_transcript_2025_inherited` rather than `official`, which remains
forbidden by `tests/test_rules.py`.

**Why it matters:** it contradicted the implementation in three places. See
[the correction register](../audits/2026-08-04-correction-register.md).

---

## TI 2025

```
Group Stage (branded as The Road to The International) – September 4 - 7
Swiss-system of sixteen teams
All matches are Bo3
Top three teams advance to playoffs
4th to 13th place teams proceed to a special elimination round
Remaining teams are eliminated
Swiss Pairing Rules
Teams are ranked from best to worst based on the following criteria, evaluated in order
Number of Matches Won
Number of Matches Lost
Percentage of Games Won
Total Number of Matches Won by Opponents Played
Average Percentage of Games Won by Opponents Played
Coin Toss
Teams are paired using the General Swiss Pairing Rules. Rounds that have modifications to these rules are notated below
Teams with the same record are paired against each other
Avoid repeat pairings when possible
Minimize the distance in ranking between the teams when possible
Modifications to the General Swiss Pairing Rules by Round:
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
No special modifications to the General Swiss Pairing Rules
Elimination Round
Teams with a 3-2 record will be paired against teams with a 2-3 record
Distance in ranking between teams is maximized when possible
Elimination Round
Five teams advance to playoffs
Remaining teams are eliminated
```

## TI 2026, as published on 2026-08-08

```
Group Stage (August 13 - 16)
Swiss-system of sixteen teams
All matches are Bo3
Top three teams advance to playoffs
4th to 13th place teams proceed to an elimination round
Remaining teams are eliminated
Elimination Round
Five teams advance to playoffs
Remaining teams are eliminated
```

**The 2026 text has no Swiss Pairing Rules section and no schedule.** As of five
days before the lock, Valve has published the shape of the group stage and not
the rules by which it pairs.

## What this repository takes from each

From the **2026** text, directly: sixteen teams, Bo3 throughout, top three
advance, 4th–13th to an elimination round, five of those advance, the rest are
eliminated. That fixes `n_teams`, the series length, and the whole category
capacity structure `[1, 2, 5, 5, 2, 1]`.

Note what the 2026 text does *not* state: the number of Swiss rounds, and the
win and loss thresholds. Five rounds is corroborated by secondary reporting
(recorded in `config/ti2026_rules.yaml`), and `advance_at_wins: 4` /
`eliminate_at_losses: 4` are implied by the compendium's own 4-0 / 4-1 / 1-4 /
0-4 prediction categories, which exist under no other rule. Implied is not
stated, and both remain tagged accordingly.

From the **2025** text, inherited: the ranking criteria and their order, the
general pairing rules, the per-round modifications, and the elimination round's
pairing rule. TI 2025 is the only event that has ever run this format, and
`ti26.cli_pairing_check` reproduces its structure exactly from the committed
store, so inheriting is the best available option. It is still an assumption,
and if Valve publishes a 2026 pairing section before the lock it supersedes
every value tagged `owner_transcript_2025_inherited`.

## The three things it corrected

1. **Ranking criteria 3 and 4 were transposed.** The published order is
   percentage of games won *then* opponents' matches won. `tiebreak.py` had
   opponents' matches won third.
2. **`avg_duration` was not a criterion at all.** The published list is six
   entries ending in Coin Toss. The implementation had seven, with an average
   duration criterion sixth, and `rank_teams` raised if a tie reached it without
   a duration source. The design spec asserted at line 232 that average duration
   was an official tiebreaker; no source supports that.
3. **Maximum ranking distance was applied in the wrong round.** The published
   text gives Round 5 no special modifications and puts distance maximisation in
   the Elimination Round. The implementation did the reverse, and modelled the
   elimination round as each 3-2 team *choosing* its opponent — a model the spec
   introduced at line 574 and no source supports.
