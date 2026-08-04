"""The SQL a snapshot was fetched with, separated from the code that fetches.

These templates are versioned inputs: a raw snapshot's manifest records the
exact query text each chunk came from, so the manifest can be regenerated
offline from committed bytes without importing the network seam.
"""

# `slots` is selected alongside `accounts` so the radiant/dire split can be
# validated rather than assumed. Bigint columns come back from the explorer as
# JSON strings, so callers cast defensively rather than assume an int.
MAP_QUERY = """
select m.match_id, m.start_time, m.duration, m.radiant_win, m.leagueid, l.tier,
       m.radiant_team_id, m.dire_team_id, m.series_id, m.series_type, mp.patch,
       array_agg(pm.account_id  order by pm.player_slot) as accounts,
       array_agg(pm.hero_id     order by pm.player_slot) as heroes,
       array_agg(pm.player_slot order by pm.player_slot) as slots
from matches m
join match_patch    mp on mp.match_id = m.match_id
join player_matches pm on pm.match_id = m.match_id
left join leagues    l on l.leagueid  = m.leagueid
where m.start_time >= {start} and m.start_time < {end}
group by 1,2,3,4,5,6,7,8,9,10,11
"""


# `team_rating` is a SEPARATE table from `teams`, which carries no rating
# columns at all (see docs/audits/2026-08-02-rung3-source-research.md). This is
# the table backing OpenDota's public, documented `GET /teams` REST endpoint.
# `wins`/`losses`/`last_match_time` are as of that team_id's most recent
# recorded match. Like MAP_QUERY, bigint columns (`team_id`, `last_match_time`)
# come back as JSON strings.
TEAM_RATING_QUERY = """
select team_id, rating, wins, losses, last_match_time
from team_rating
where team_id in ({team_ids})
"""
