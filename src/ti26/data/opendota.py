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

from ti26.data.queries import MAP_QUERY, TEAM_RATING_QUERY

EXPLORER_URL = "https://api.opendota.com/api/explorer"

__all__ = [
    "EXPLORER_URL",
    "MAP_QUERY",
    "TEAM_RATING_QUERY",
    "ExplorerError",
    "explorer_query",
    "http_transport",
    "month_windows",
]


class ExplorerError(RuntimeError):
    """Explorer request failed, or returned a server-side SQL error."""


def http_transport(url: str) -> bytes:
    # A custom User-Agent is set deliberately, not left at urllib's default --
    # see docs/audits/2026-08-02-d2-build-ledger.md's implementer-deviations
    # section for why this was needed. That was a one-off manual observation,
    # not something this module re-checks or a test can reproduce offline
    # (this is the network seam this test suite never calls), so it is not
    # restated as a measurement here.
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
