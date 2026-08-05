"""sqlite3 store plus the blocking `as_of` leakage assertion (spec IV)."""

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from ti26.data.schema import MapRow

SCHEMA = """
create table if not exists maps (
    match_id        integer primary key,
    start_time      integer not null,
    duration        integer not null,
    radiant_win     integer not null,
    league_id       integer,
    tier            text,
    radiant_team_id integer,
    dire_team_id    integer,
    series_id       integer,
    series_type     integer,
    patch           text,
    radiant_accounts text not null,
    dire_accounts    text not null,
    radiant_heroes   text not null,
    dire_heroes      text not null,
    has_null_team   integer not null,
    has_bad_roster  integer not null
);
create index if not exists maps_start_time on maps(start_time);
"""

STORE_COLUMNS = (
    "match_id", "start_time", "duration", "radiant_win", "league_id", "tier",
    "radiant_team_id", "dire_team_id", "series_id", "series_type", "patch",
    "radiant_accounts", "dire_accounts", "radiant_heroes", "dire_heroes",
    "has_null_team", "has_bad_roster",
)


class LeakageError(AssertionError):
    """A row dated after `as_of` reached a fit. Spec IV: blocking."""


class ConflictingRowError(ValueError):
    """The same match_id arrived twice with different content."""


def open_store(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    return conn


def _tuple_of(r: MapRow) -> tuple:
    return (
        r.match_id, r.start_time, r.duration, int(r.radiant_win), r.league_id, r.tier,
        r.radiant_team_id, r.dire_team_id, r.series_id, r.series_type, r.patch,
        json.dumps(list(r.radiant_accounts)), json.dumps(list(r.dire_accounts)),
        json.dumps(list(r.radiant_heroes)), json.dumps(list(r.dire_heroes)),
        int(r.has_null_team), int(r.has_bad_roster),
    )


def insert_rows(conn: sqlite3.Connection, rows: Sequence[MapRow]) -> int:
    """Insert, tolerating exact duplicates and rejecting conflicting ones.

    `insert or replace` would let a later snapshot silently rewrite history:
    the same match_id arriving with a different winner would overwrite the
    earlier record with no trace. Same id + same bytes is a re-ingest; same
    id + different bytes is a data-integrity failure that must surface.

    The whole batch runs in one transaction, so a conflict anywhere rolls the
    batch back and leaves the store exactly as it was.
    """
    payload = [_tuple_of(r) for r in rows]
    placeholders = ",".join("?" * len(STORE_COLUMNS))
    inserted = 0
    with conn:  # rolls back the whole batch if anything raises
        for record in payload:
            existing = conn.execute(
                f"select {','.join(STORE_COLUMNS)} from maps where match_id = ?", (record[0],)
            ).fetchone()
            if existing is None:
                conn.execute(
                    f"insert into maps ({','.join(STORE_COLUMNS)}) values ({placeholders})", record
                )
                inserted += 1
            elif tuple(existing) != record:
                differing = [
                    STORE_COLUMNS[i]
                    for i in range(len(STORE_COLUMNS))
                    if existing[i] != record[i]
                ]
                raise ConflictingRowError(
                    f"match_id={record[0]} already stored with different values "
                    f"in {differing}; refusing to overwrite ingested history"
                )
    return inserted


def load_rows(
    conn: sqlite3.Connection, as_of: int | None = None, since: int | None = None
) -> list[MapRow]:
    clauses, params = [], []
    if as_of is not None:
        clauses.append("start_time <= ?")
        params.append(as_of)
    if since is not None:
        clauses.append("start_time >= ?")
        params.append(since)
    where = f"where {' and '.join(clauses)}" if clauses else ""
    cursor = conn.execute(
        f"select {','.join(STORE_COLUMNS)} from maps {where} order by start_time, match_id", params
    )
    return [
        MapRow(
            match_id=r[0], start_time=r[1], duration=r[2], radiant_win=bool(r[3]),
            league_id=r[4], tier=r[5], radiant_team_id=r[6], dire_team_id=r[7],
            series_id=r[8], series_type=r[9], patch=r[10],
            radiant_accounts=tuple(json.loads(r[11])), dire_accounts=tuple(json.loads(r[12])),
            radiant_heroes=tuple(json.loads(r[13])), dire_heroes=tuple(json.loads(r[14])),
            has_null_team=bool(r[15]), has_bad_roster=bool(r[16]),
        )
        for r in cursor
    ]


def assert_no_leakage(rows: Sequence[MapRow], as_of: int) -> None:
    future = [r for r in rows if r.start_time > as_of]
    if future:
        worst = max(r.start_time for r in future)
        raise LeakageError(
            f"{len(future)} row(s) dated after as_of={as_of}; latest start_time={worst}"
        )
