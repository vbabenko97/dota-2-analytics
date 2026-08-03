"""The single network seam in this package.

Every other module takes data as an argument. This one is the only place a
remote host is contacted, and even here the transport is injectable so the
whole test suite runs offline.
"""

import json
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime

EXPLORER_URL = "https://api.opendota.com/api/explorer"

# Measured 2026-08-02: a full month (3,011 maps, 1.0 MB) returns in 0.44 s
# with no row cap. `slots` is selected alongside `accounts` so the
# radiant/dire split can be validated rather than assumed.
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


class ExplorerError(RuntimeError):
    """Explorer request failed, or returned a server-side SQL error."""


def http_transport(url: str) -> bytes:
    # Measured 2026-08-02: the endpoint returns 403 Forbidden to urllib's
    # default `Python-urllib/x.y` User-Agent and 200 to any ordinary one.
    # Confirmed with and without this header, same URL, same run.
    request = urllib.request.Request(url, headers={"User-Agent": "ti26-ingest/1.0"})
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def explorer_query(
    sql: str,
    transport: Callable[[str], bytes],
    max_retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict]:
    url = f"{EXPLORER_URL}?sql={urllib.parse.quote(sql)}"
    last: Exception | None = None
    for attempt in range(max_retries):
        try:
            payload = json.loads(transport(url))
        except Exception as exc:  # noqa: BLE001 -- network boundary: retry transport failures
            last = exc
            if attempt < max_retries - 1:
                sleep(2.0**attempt)
            continue
        # HTTP 200 with a non-null `err` is the explorer's SQL-failure shape.
        # Treating it as an empty month would silently hole the history.
        if payload.get("err"):
            raise ExplorerError(f"explorer rejected query: {payload['err']}")
        return payload.get("rows") or []
    raise ExplorerError(f"explorer request failed after {max_retries} attempts: {last}")


def month_windows(start: datetime, end: datetime) -> list[tuple[int, int]]:
    """Tile [start, end) into abutting calendar-month epoch-second windows."""
    windows: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        year, month = cursor.year, cursor.month
        nxt = datetime(
            year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=UTC
        )
        stop = min(nxt, end)
        windows.append((int(cursor.timestamp()), int(stop.timestamp())))
        cursor = stop
    return windows
