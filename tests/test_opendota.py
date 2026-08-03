import itertools
import json
from datetime import UTC, datetime

import pytest

from ti26.data.opendota import (
    EXPLORER_URL,
    MAP_QUERY,
    ExplorerError,
    explorer_query,
    month_windows,
)


def fake_transport(payload, calls=None):
    def transport(url):
        if calls is not None:
            calls.append(url)
        return json.dumps(payload).encode()
    return transport


def test_query_returns_rows_and_urlencodes_sql():
    calls = []
    rows = explorer_query(
        "select 1", fake_transport({"err": None, "rows": [{"a": 1}]}, calls)
    )
    assert rows == [{"a": 1}]
    assert calls[0].startswith(EXPLORER_URL)
    assert "select%201" in calls[0], "sql must be percent-encoded into the query string"


def test_server_reported_error_raises_rather_than_returning_empty():
    """The explorer returns HTTP 200 with an `err` body on SQL failure.

    Returning [] here would look exactly like 'this month had no matches'
    and would silently produce a hole in the ingested history.
    """
    with pytest.raises(ExplorerError, match="syntax error"):
        explorer_query("select bad", fake_transport({"err": "syntax error", "rows": None}))


def test_retries_transient_failures_then_succeeds():
    attempts = []

    def flaky(url):
        attempts.append(url)
        if len(attempts) < 3:
            raise OSError("connection reset")
        return json.dumps({"err": None, "rows": [{"ok": True}]}).encode()

    slept = []
    rows = explorer_query("select 1", flaky, sleep=slept.append)
    assert rows == [{"ok": True}]
    assert len(attempts) == 3
    assert slept == [1.0, 2.0], "backoff must double, not spin"


def test_gives_up_after_max_retries():
    def always_fails(url):
        raise OSError("connection reset")

    with pytest.raises(ExplorerError, match="3 attempts"):
        explorer_query("select 1", always_fails, max_retries=3, sleep=lambda s: None)


def test_map_query_selects_slots_so_the_roster_split_is_verifiable():
    """accounts[0:5] == radiant is an ASSUMPTION unless slots come back too.

    Task 2 validates the slot pattern; that is only possible if the query
    actually requests it.
    """
    assert "player_slot" in MAP_QUERY
    assert "slots" in MAP_QUERY
    assert "array_agg" in MAP_QUERY


def test_month_windows_tile_the_range_without_gaps_or_overlap():
    start = datetime(2025, 2, 1, tzinfo=UTC)
    end = datetime(2025, 5, 1, tzinfo=UTC)
    windows = month_windows(start, end)
    assert len(windows) == 3
    assert windows[0][0] == int(start.timestamp())
    assert windows[-1][1] == int(end.timestamp())
    for (_, prev_end), (next_start, _) in itertools.pairwise(windows):
        assert prev_end == next_start, "windows must abut exactly"
