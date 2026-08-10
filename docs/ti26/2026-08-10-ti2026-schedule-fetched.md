# TI 2026 Round 1 schedule — fetched, and what it does NOT contain

**Fetched 2026-08-10 (~06:00 UTC) from <https://www.dota2.com/esports/ti15/schedule>**
with a headless browser (Playwright), accessibility-tree snapshot. The page is
JavaScript-rendered, same as the rules page; a plain HTTP fetch sees the shell
only.

**It is not an immutable input.** No snapshot binds it and no manifest hashes
it; the page can change and this file would not know. It is a dated observation,
archived for the same reason as
[the rules archive](2026-08-08-ti2026-rules-fetched.md).

## What the page showed

Eight series, all dated Thursday, August 13th, all labelled "The International /
Group Stage":

```
Thursday, August 13th
04:00 CEST  Team Falcons   vs LGD Gaming
04:00 CEST  Iron Wing      vs Nigma Galaxy
04:00 CEST  BoomBoys       vs OG
04:00 CEST  TEAM VISION    vs Team Resilience
07:00 CEST  Team Spirit    vs Xtreme Gaming
07:00 CEST  Team Liquid    vs Vici Gaming
07:00 CEST  Aurora Gaming  vs GamerLegion
07:00 CEST  Team Yandex    vs HULIGANI
```

Every configured team appears exactly once, so this is the full Round 1. Names
match `config/ti2026_teams.yaml` display names 1:1, with one cosmetic case
difference ("TEAM VISION" vs the configured "Team Vision") — the page styles
some names in caps, and a draw file must use the configured spelling, which is
what `load_group_draw` compares against.

The main esports page (<https://www.dota2.com/esports/ti15>, read in the same
session) lists the same eight pairings under "Next Match" and names sixteen
"Participating Teams" that match the configured field's display names. That is
a name-level observation only; the lock-day field re-confirmation in runbook
step 3 is still required, by identity rather than by name.

## What the page did NOT show: groups

**Neither the schedule page nor the main esports page publishes the group
assignment.** No "Group A"/"Group B" label appears anywhere. The two start
times (04:00 / 07:00) split the field into two eights, and under the published
rules Round 1 pairs inside groups — but reading the time blocks as the groups
would be an inference about broadcast scheduling, not evidence about the draw.
This project does not manufacture a draw from a timetable.

## Consequence for the runbook

Runbook step 5b anticipated the opposite arrival order ("the groups can be
announced first and the opening matchups later"). What actually arrived is
Round 1 without groups, and the accepted input cannot represent that:
`load_group_draw` (`src/ti26/groups.py`) requires a `groups:` mapping always
and refuses a file without one. Writing `data/ti2026_groups.yaml` therefore
has to wait for a groups publication.

This is the step 5b stop condition — "the published draw cannot be represented
exactly by the accepted input" — and the resolution is an owner decision, not a
workaround. The obvious paths:

- the groups are published before lock day (they gate Rounds 2–4, so they must
  exist by Round 2 at the latest): write the full file then, per step 5b;
- the groups are still unpublished at regeneration time: the owner decides
  whether to run unconditioned (step 5b's "neither published" branch — but that
  now knowingly discards a published Round 1) or to change `load_group_draw` to
  accept Round 1 alone. That is a shipping-path behavior change and is NOT
  authorized by this note.

Re-read the page on lock day whether or not this resolves; diff against this
archive.
