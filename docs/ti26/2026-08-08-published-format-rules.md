> **Superseded as a current TI 2026 rules source.** The group-stage rules Valve
> later published are bound as immutable evidence at
> [`data/evidence/rules/b46dd6641b308dfa577c2e4fe93d41a3120499b0a86af1332a2f8230a96f5b5b/manifest.json`](../../data/evidence/rules/b46dd6641b308dfa577c2e4fe93d41a3120499b0a86af1332a2f8230a96f5b5b/manifest.json).
> This transcript remains below, unchanged, as historical evidence of what the
> owner saw on the morning it was supplied. The known difference between its
> morning state and the later capture is exactly why it remains.

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

## The compendium card itself, 2026-08-08

The owner also supplied a screenshot of the TI 2026 compendium's group-stage
card. It labels its six categories in the product's own words, over sixteen
named team slots:

```
4-0                       One undefeated team
4-1                       Two teams with 4 Wins and 1 loss
ELIMINATION ROUND WINNER  Five teams that win in the Elimination Round
ELIMINATION ROUND LOSER   Five teams that lose in the Elimination Round
1-4                       Two teams with 1 win and 4 losses
0-4                       One unvictorious team
```

This is the format stated by the thing being predicted. It fixes `n_teams`,
`advance_at_wins` and `eliminate_at_losses` directly, and `total_rounds`
follows: a team advances at four wins and is out at four losses, so the longest
possible Swiss record is 4-1 or 1-4 and the stage is exactly five rounds. The
capacities `[1, 2, 5, 5, 2, 1]` are the counts it prints.

Those four values were previously tagged `reported_official`, meaning a
secondhand report nothing here could check against the source. They are no
longer secondhand, and they now carry `compendium_ui_2026`. **They are still not
`official`**: this is a screenshot relayed by a human, not a fetch this
repository can repeat, and no test here can re-verify it. After this change no
value in `config/ti2026_rules.yaml` carries `reported_official` at all.

The card also confirms the sixteen teams and their compendium-facing names:
TEAM VISION, TEAM YANDEX, TEAM FALCONS, AURORA GAMING, BOOMBOYS, TEAM SPIRIT,
TEAM LIQUID, IRON WING, NIGMA GALAXY, XTREME GAMING, LGD GAMING, VICI GAMING,
OG, GAMERLEGION, TEAM RESILIENCE, HULIGANI — the same sixteen
`config/ti2026_teams.yaml` configures, independently of the field check run the
day before.

What it says nothing about: pairing, ranking, tiebreaks or seeding. Those remain
inherited from TI 2025 and tagged `owner_transcript_2025_inherited`.

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

`ti26.cli_pairing_check` reproduces that analysis from the committed store. The
current figures are in
[`reports/pairing_check/pairing_check.json`](../../reports/pairing_check/pairing_check.json)
under `elimination_pairing_rule`, and are deliberately not copied here.

**This section carried a table until 2026-08-09, and it was wrong.** It read a
best-reachable distance of 10 and 3 of 5 pairs shared. Those came from an engine
that had ranking criteria 3 and 4 transposed and no duration criterion — the
state between commits `23beac3` and `106c409` on 2026-08-08. Under the corrected
ranking the reachable optimum is higher and the shared-pair count is lower.

The unconstrained optimum was unreachable because it required teams to meet
twice, which is why repeat avoidance has to be applied before distance rather
than after. That part stands.

**The deviation has a documented cause outside the rules.** Teams were notified
on 6 September of a previously non-existent constraint — no more than two series
per day — which was never publicly announced. It forced HEROIC onto Yakult; the
rule-following pairing was HEROIC vs Spirit and Falcons vs Yakult. The producer
carries this as a `known_deviations` entry so the finding travels with its
explanation.

**What is WITHDRAWN is the conclusion that the rule reproduces the event to
within one swap.** That rested on the shortfall being exactly the size of this
one swap, and under the corrected ranking it is twice that. One unannounced swap
does not account for the whole gap. Whether the remainder is the rule being
wrong, or the ranking being TI 2026's rather than TI 2025's, is unresolved and
recorded as such in the producer's `rule_year` block.

**This is still not a defect the model can fix, and not one it should.** An
organiser constraint that is not in the rules, not announced, and applied
mid-event is not forecastable; the engine follows the published rule and the
deviation is recorded here.

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
