import pytest

from ti26.data.schema import MapRow, normalize_row
from ti26.data.store import (
    ConflictingRowError,
    LeakageError,
    assert_no_leakage,
    insert_rows,
    load_rows,
    open_store,
)


def row(match_id, start_time, **kw):
    base = {
        "duration": 2000, "radiant_win": True, "league_id": 1, "tier": "professional",
        "radiant_team_id": 10, "dire_team_id": 20, "series_id": 5, "series_type": 1,
        "patch": "7.41",
        "radiant_accounts": (1, 2, 3, 4, 5), "dire_accounts": (6, 7, 8, 9, 10),
        "radiant_heroes": (1, 2, 3, 4, 5), "dire_heroes": (6, 7, 8, 9, 10),
        "has_null_team": False, "has_bad_roster": False,
    }
    base.update(kw)
    return MapRow(match_id=match_id, start_time=start_time, **base)


def test_roundtrip_preserves_every_field(tmp_path):
    conn = open_store(tmp_path / "d2.sqlite")
    original = row(1, 1000, tier=None, league_id=None, has_null_team=True)
    insert_rows(conn, [original])
    assert load_rows(conn) == [original]


def test_reinserting_an_identical_row_is_a_no_op(tmp_path):
    """Snapshots overlap at month edges on re-runs; a duplicated map would
    be rated twice and inflate a team's evidence for free."""
    conn = open_store(tmp_path / "d2.sqlite")
    insert_rows(conn, [row(1, 1000)])
    insert_rows(conn, [row(1, 1000), row(2, 2000)])
    assert [r.match_id for r in load_rows(conn)] == [1, 2]


def test_numeric_string_optional_int_field_survives_reingest(tmp_path):
    """The explorer can serialize an optional int column (e.g. leagueid) as a
    JSON string. sqlite's integer affinity coerces it to int on write, so
    normalize_row must cast it too — otherwise a re-ingest of the same raw
    row compares a fresh string against a stored int and trips a spurious
    ConflictingRowError."""
    raw_row = {
        "match_id": 1, "start_time": 1000, "duration": 2000, "radiant_win": True,
        "leagueid": "20009", "tier": "professional",
        "radiant_team_id": 10, "dire_team_id": 20,
        "series_id": 5, "series_type": 1, "patch": "7.41",
        "accounts": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "heroes": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "slots": [0, 1, 2, 3, 4, 128, 129, 130, 131, 132],
    }
    conn = open_store(tmp_path / "d2.sqlite")
    insert_rows(conn, [normalize_row(raw_row)])
    insert_rows(conn, [normalize_row(raw_row)])  # re-ingest must not raise
    assert load_rows(conn)[0].league_id == 20009


def test_reinserting_a_CONFLICTING_row_raises(tmp_path):
    """`insert or replace` would silently let a later snapshot rewrite
    history — the same match_id arriving with a different winner or roster
    would overwrite the earlier record and no one would ever know.

    Same id + different content is a data-integrity failure, not an update.
    """
    conn = open_store(tmp_path / "d2.sqlite")
    insert_rows(conn, [row(1, 1000, radiant_win=True)])
    with pytest.raises(ConflictingRowError, match="match_id=1"):
        insert_rows(conn, [row(1, 1000, radiant_win=False)])


def test_a_rejected_conflict_leaves_the_original_intact(tmp_path):
    conn = open_store(tmp_path / "d2.sqlite")
    original = row(1, 1000, radiant_win=True)
    insert_rows(conn, [original])
    with pytest.raises(ConflictingRowError):
        insert_rows(conn, [row(2, 2000), row(1, 1000, radiant_win=False)])
    stored = load_rows(conn)
    assert original in stored
    assert all(r.radiant_win for r in stored if r.match_id == 1)
    assert [r.match_id for r in stored] == [1], "match_id=2 must not leak from a rolled-back batch"


def test_rows_load_in_start_time_order(tmp_path):
    """match_id order is DELIBERATELY decorrelated from start_time order
    (ascending match_id 1,2,3 maps to start_time 3000,1000,2000, not
    1000,2000,3000) -- an implementation that ordered by match_id instead
    of start_time would return [3000, 1000, 2000], not this. A fixture
    where the two orders coincide (as an earlier version of this test had:
    match_id 3,1,2 inserted but start_time already ascending 1000-3000 with
    match_id, so `order by match_id` and `order by start_time` land on the
    identical sequence) cannot tell the two apart -- the same trap already
    fixed in `rating_gaps` and `latest_rosters`.
    """
    conn = open_store(tmp_path / "d2.sqlite")
    insert_rows(conn, [row(1, 3000), row(2, 1000), row(3, 2000)])
    assert [r.start_time for r in load_rows(conn)] == [1000, 2000, 3000]


def test_as_of_excludes_the_future_at_the_boundary(tmp_path):
    conn = open_store(tmp_path / "d2.sqlite")
    insert_rows(conn, [row(1, 1000), row(2, 2000), row(3, 3000)])
    loaded = load_rows(conn, as_of=2000)
    assert [r.match_id for r in loaded] == [1, 2], "as_of is inclusive of its own second"
    assert all(r.start_time <= 2000 for r in loaded)


def test_since_excludes_the_past_at_the_boundary(tmp_path):
    conn = open_store(tmp_path / "d2.sqlite")
    insert_rows(conn, [row(1, 1000), row(2, 2000), row(3, 3000)])
    loaded = load_rows(conn, since=2000)
    assert [r.match_id for r in loaded] == [2, 3], "since is inclusive of its own second"
    assert all(r.start_time >= 2000 for r in loaded)


def test_leakage_assertion_raises_on_a_single_future_row():
    rows = [row(1, 1000), row(2, 2001)]
    with pytest.raises(LeakageError, match="2001"):
        assert_no_leakage(rows, as_of=2000)


def test_leakage_assertion_passes_at_the_exact_boundary():
    assert_no_leakage([row(1, 2000)], as_of=2000)
