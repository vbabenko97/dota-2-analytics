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

## TI 2025's elimination round did not follow the published rule

Supplied by the owner alongside the transcript: the final Swiss standings table,
and [Noxville's contemporaneous bracket
analysis](https://x.com/Noxville/status/1964403594217869671).

**How "distance in ranking" is actually scored.** Not on overall ranking
position — every 3-2 team outranks every 2-3 team, so the total is invariant
across matchings and the rule would say nothing. It is the seed WITHIN each
record class, summed over the matching. The real pairs were seeds (1,5), (2,1),
(3,3), (4,4), (5,2), summing to 8.

`ti26.cli_pairing_check` now reproduces that analysis from the committed store:

| quantity | value |
|---|---|
| real bracket | 8 |
| best reachable without a rematch | 10 |
| best ignoring rematches | 12 |
| pairs the engine shares with the real bracket | 3 of 5 |

The 12 was unreachable because it required teams to meet twice, which is why
repeat avoidance has to be applied before distance rather than after.

**The one-swap deviation has a documented cause outside the rules.** Teams were
notified on 6 September of a previously non-existent constraint — no more than
two series per day — which was never publicly announced. It forced HEROIC onto
Yakult; the rule-following pairing was HEROIC vs Spirit and Falcons vs Yakult.
That is exactly the difference between 8 and 10, and it accounts for the two
pairs the engine does not share.

So the published rule reproduces the event to within one swap, and the swap is
explained by an unpublished mid-tournament change. **This is not a defect the
model can fix, and not one it should.** An organiser constraint that is not in
the rules, not announced, and applied mid-event is not forecastable; the engine
follows the published rule and the deviation is recorded here.

It also settles a question the previous day's work could not: the elimination
round is paired algorithmically, not chosen by the teams. The analysis treats it
as an optimisation throughout, which is evidence against the chooser model the
design spec assumed — independent of the transcript.

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
