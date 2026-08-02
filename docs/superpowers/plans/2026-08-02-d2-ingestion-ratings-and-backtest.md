# D2: Ingestion, Roster Canonicalization, Ratings and Rolling Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace D1's synthetic strength vector with ratings fitted from 18 months of real pro maps, and decide — against a gate pre-registered before any backtest ran — whether custom modelling is justified at all.

**Architecture:** Ingestion is one narrow seam: `explorer_query` is the only function in `src/ti26/` that touches the network, and it takes an injectable transport so every other test runs offline. Raw responses land in immutable timestamped snapshots and are never re-fetched; a normalization layer converts them to `MapRow`, and a stdlib `sqlite3` store answers `as_of`-bounded queries. Ratings are pure functions over an ordered map sequence keyed by `roster_version_id`, not by organization, so a re-branded org keeps its history and a new roster does not inherit one it never earned. The backtest harness replays tournaments at rolling cutoffs and is the only component permitted to declare the gate result.

**Tech Stack:** Python 3.13, `uv`, `pytest`, `numpy`, `scipy`, `PyYAML`, `ruff`, and the standard library (`sqlite3`, `urllib.request`, `gzip`, `json`, `hashlib`). **No new third-party dependencies.**

## Global Constraints

- **One network seam.** `src/ti26/data/opendota.py::explorer_query` is the only function in `src/ti26/` permitted to perform I/O against a remote host, and it accepts a `transport` callable so tests never hit the network. A network call anywhere else under `src/ti26/` is a plan violation.
- **Raw snapshots are immutable.** `data/raw/` is written once per snapshot id and never overwritten or edited. Re-running ingestion creates a new snapshot directory. Code that opens a path under `data/raw/` in any mode other than read is a plan violation.
- **The `as_of` leakage assertion is blocking.** `assert_no_leakage(rows, as_of)` raises if any row has `start_time > as_of`. Every rating fit and every backtest fold calls it. Per spec §IV this is "the single reproducibility check worth automating".
- **Pre-registered D2 forecast-value gate, verbatim from spec §II** (registered 2026-08-02, before any backtest was run): `mean(LL_elo − LL_glicko) ≥ 0.003` nats/map **AND** paired bootstrap 95% CI on that difference excludes 0. Both conditions. The threshold `0.003` is loaded from `config/d2_gate.yaml`; writing it as a literal in `src/` is a plan violation.
- **Fit on all ingested maps.** `tier` and `league_id` are covariates/weights, never an ingest-time or fit-time filter. Spec §III: a tier filter drops ~80% of 2026 maps for a metadata-maintenance reason unrelated to match quality.
- **Null team IDs are handled explicitly, never silently dropped.** ≈6.7% of maps carry one. They are flagged with `has_null_team` and excluded from rating updates with a counted, reported reason.
- **Statistical identity follows the roster.** Ratings are keyed by `roster_version_id = sha1(sorted(account_ids))[:16]`, never by `team_id`. Spec §III.
- Every random operation takes an explicit `random.Random` or `numpy.random.Generator` instance. Same seed + same inputs → identical outputs.
- Accuracy is computed and reported but **never used for model selection** (spec §II — not a proper scoring rule).
- Any reported score derived from the model's own probabilities carries the descriptive-only qualifier already used in `src/ti26/cli.py:62-65`.
- Tests that call `explorer_query` against the real API carry `@pytest.mark.slow` and are excluded from per-task loops. Per-task loops run `-m "not slow"`; Task 8 and final verification run the whole suite.
- Use `.venv/bin/python -m pytest` and `.venv/bin/ruff check` directly. `uv run` is blocked by the reliability plugin in this environment.

---

## File Structure

| File | Responsibility |
|---|---|
| `config/d2_gate.yaml` | Pre-registered gate thresholds and rating hyperparameters. Single source; no literals in `src/` |
| `src/ti26/data/__init__.py` | Package marker |
| `src/ti26/data/opendota.py` | The one network seam: `explorer_query(sql, transport)`; retry/backoff; no domain parsing |
| `src/ti26/data/snapshot.py` | Immutable snapshot write/read plus `manifest.json` |
| `src/ti26/data/schema.py` | `MapRow`, raw-row normalization, roster slot validation, quality flags |
| `src/ti26/data/store.py` | `sqlite3` store; `as_of`-bounded reads; `assert_no_leakage` |
| `src/ti26/roster.py` | `roster_version_id`, alias table, continuity-weighted initialization |
| `src/ti26/ratings/__init__.py` | Package marker; shared `Rating` type and `RatingModel` protocol |
| `src/ti26/ratings/elo.py` | Map-level Elo — the gate comparator |
| `src/ti26/ratings/glicko.py` | Roster-aware Glicko-2 — the gate candidate |
| `src/ti26/ratings/simple.py` | §V floor baselines: constant 0.5 and EWMA map win rate |
| `src/ti26/backtest.py` | Rolling event cutoffs, log loss / Brier / calibration, paired bootstrap, gate verdict |
| `src/ti26/duration.py` | Fit the duration model from real durations; sensitivity sweep |
| `src/ti26/cli_ingest.py` | `python -m ti26.cli_ingest` — snapshot → store |
| `src/ti26/cli_d2.py` | `python -m ti26.cli_d2` — fit, backtest, gate verdict, strengths → existing card CLI |

### Scope boundaries

**The public-rating fallback needs no new code.** Spec §X rung 3 — "public ratings piped straight into the simulator" — is the prescribed response to a gate FAIL. D1's `src/ti26/cli.py:23` already accepts `--strengths <csv>` with `team,strength` columns, so shipping the fallback means writing that CSV, not building an ingestion path for it. No task in this plan covers it because none is needed.

**Deferred by the spec's own build plan, not overlooked:** market/outright integration (§VIII, D3–D4), within-series dependence and the series shock (§VI, D4), the TI 2025 rules replay and posterior predictive checks (§IV, D4), and all meta/hero-pool work (§VIII, D5).

---

## Task 1: Explorer client and immutable snapshots

**Files:**
- Create: `src/ti26/data/__init__.py`, `src/ti26/data/opendota.py`, `src/ti26/data/snapshot.py`
- Test: `tests/test_opendota.py`, `tests/test_snapshot.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ExplorerError(RuntimeError)`; `explorer_query(sql: str, transport: Callable[[str], bytes], max_retries: int = 3, sleep: Callable[[float], None] = time.sleep) -> list[dict]`; `http_transport(url: str) -> bytes`; `EXPLORER_URL: str`; `month_windows(start: datetime, end: datetime) -> list[tuple[int, int]]` returning inclusive-exclusive epoch-second bounds; `MAP_QUERY: str`; `snapshot_id(now: datetime) -> str` returning `"YYYYMMDDTHHMMSSZ"`; `write_snapshot(root: Path, sid: str, name: str, rows: list[dict]) -> Path` writing gzipped JSON; `read_snapshot(path: Path) -> list[dict]`; `write_manifest(root: Path, sid: str, entries: list[dict]) -> Path`; `SnapshotExistsError(FileExistsError)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_opendota.py
import json
import pytest

from ti26.data.opendota import (
    EXPLORER_URL,
    MAP_QUERY,
    ExplorerError,
    explorer_query,
    month_windows,
)
from datetime import datetime, timezone


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
    start = datetime(2025, 2, 1, tzinfo=timezone.utc)
    end = datetime(2025, 5, 1, tzinfo=timezone.utc)
    windows = month_windows(start, end)
    assert len(windows) == 3
    assert windows[0][0] == int(start.timestamp())
    assert windows[-1][1] == int(end.timestamp())
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
        assert prev_end == next_start, "windows must abut exactly"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_opendota.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.data'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ti26/data/opendota.py
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
from datetime import datetime, timezone

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
    with urllib.request.urlopen(url, timeout=300) as response:
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
        except Exception as exc:  # network boundary: retry transport failures
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
            year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc
        )
        stop = min(nxt, end)
        windows.append((int(cursor.timestamp()), int(stop.timestamp())))
        cursor = stop
    return windows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_opendota.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Write the snapshot test**

```python
# tests/test_snapshot.py
import json
import pytest
from datetime import datetime, timezone

from ti26.data.snapshot import (
    SnapshotExistsError,
    read_snapshot,
    snapshot_id,
    write_manifest,
    write_snapshot,
)


def test_snapshot_id_is_sortable_utc():
    sid = snapshot_id(datetime(2026, 8, 3, 9, 5, 1, tzinfo=timezone.utc))
    assert sid == "20260803T090501Z"


def test_roundtrip_preserves_rows(tmp_path):
    rows = [{"match_id": 1, "accounts": [1, 2, 3]}, {"match_id": 2, "accounts": []}]
    path = write_snapshot(tmp_path, "20260803T090501Z", "2025-02", rows)
    assert path.suffixes[-2:] == [".json", ".gz"], "snapshots are gzipped JSON"
    assert read_snapshot(path) == rows


def test_rewriting_the_same_snapshot_raises(tmp_path):
    """Immutability is enforced by the code, not by convention.

    Spec VII: `data/raw` is never overwritten. A second run must create a new
    snapshot id; silently clobbering would destroy the only record of what
    the API returned at the earlier `as_of`.
    """
    write_snapshot(tmp_path, "20260803T090501Z", "2025-02", [{"a": 1}])
    with pytest.raises(SnapshotExistsError):
        write_snapshot(tmp_path, "20260803T090501Z", "2025-02", [{"a": 2}])


def test_manifest_records_counts_and_query_for_each_chunk(tmp_path):
    entries = [
        {"name": "2025-02", "rows": 2268, "start": 1738368000, "end": 1740787200},
        {"name": "2025-03", "rows": 2408, "start": 1740787200, "end": 1743465600},
    ]
    path = write_manifest(tmp_path, "20260803T090501Z", entries)
    manifest = json.loads(path.read_text())
    assert manifest["snapshot_id"] == "20260803T090501Z"
    assert manifest["total_rows"] == 4676
    assert manifest["entries"] == entries
```

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_snapshot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.data.snapshot'`

- [ ] **Step 7: Write the snapshot implementation**

```python
# src/ti26/data/snapshot.py
"""Immutable, timestamped raw snapshots.

Spec VII keeps `data/raw` immutable as its one non-negotiable reproducibility
guarantee: a fit is only re-runnable if the bytes it was fitted on still
exist exactly as fetched.
"""

import gzip
import json
from datetime import datetime
from pathlib import Path


class SnapshotExistsError(FileExistsError):
    """A snapshot chunk already exists; snapshots are never overwritten."""


def snapshot_id(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def write_snapshot(root: Path, sid: str, name: str, rows: list[dict]) -> Path:
    directory = root / sid
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json.gz"
    if path.exists():
        raise SnapshotExistsError(
            f"{path} already exists; snapshots are immutable — use a new snapshot id"
        )
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(rows, fh)
    return path


def read_snapshot(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def write_manifest(root: Path, sid: str, entries: list[dict]) -> Path:
    directory = root / sid
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.json"
    payload = {
        "snapshot_id": sid,
        "source": "opendota /explorer",
        "total_rows": sum(e["rows"] for e in entries),
        "entries": entries,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path
```

- [ ] **Step 8: Run the full task suite and lint**

Run: `.venv/bin/python -m pytest tests/test_opendota.py tests/test_snapshot.py -v && .venv/bin/ruff check .`
Expected: PASS (10 tests), lint clean

- [ ] **Step 9: Commit**

```bash
git add src/ti26/data tests/test_opendota.py tests/test_snapshot.py
git commit -m "feat: OpenDota explorer client and immutable snapshots"
```

---

## Task 2: Map schema normalization, sqlite store, leakage assertion

**Files:**
- Create: `src/ti26/data/schema.py`, `src/ti26/data/store.py`
- Test: `tests/test_schema.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `read_snapshot` from Task 1.
- Produces: `MapRow` frozen dataclass with fields `match_id: int, start_time: int, duration: int, radiant_win: bool, league_id: int | None, tier: str | None, radiant_team_id: int | None, dire_team_id: int | None, series_id: int | None, series_type: int | None, patch: str | None, radiant_accounts: tuple[int, ...], dire_accounts: tuple[int, ...], radiant_heroes: tuple[int, ...], dire_heroes: tuple[int, ...], has_null_team: bool, has_bad_roster: bool` and property `best_of: int`; `RosterSlotError(ValueError)`; `normalize_row(raw: dict) -> MapRow`; `normalize_all(raw: list[dict]) -> tuple[list[MapRow], dict[str, int]]` returning rows plus a counted rejection tally; `LeakageError(AssertionError)`; `assert_no_leakage(rows: Sequence[MapRow], as_of: int) -> None`; `open_store(path: str | Path) -> sqlite3.Connection`; `insert_rows(conn, rows: Sequence[MapRow]) -> int`; `load_rows(conn, as_of: int | None = None, since: int | None = None) -> list[MapRow]`.

- [ ] **Step 1: Write the failing schema test**

```python
# tests/test_schema.py
import pytest

from ti26.data.schema import MapRow, RosterSlotError, normalize_all, normalize_row

RADIANT_SLOTS = [0, 1, 2, 3, 4]
DIRE_SLOTS = [128, 129, 130, 131, 132]


def raw(**overrides):
    row = {
        "match_id": 8925460065,
        "start_time": 1785661502,
        "duration": 2555,
        "radiant_win": True,
        "leagueid": 20009,
        "tier": "professional",
        "radiant_team_id": 10136357,
        "dire_team_id": 2586976,
        "series_id": 1126703,
        "series_type": 1,
        "patch": "7.41",
        "accounts": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "heroes": [11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
        "slots": RADIANT_SLOTS + DIRE_SLOTS,
    }
    row.update(overrides)
    return row


def test_roster_split_follows_slots_not_positional_assumption():
    row = normalize_row(raw())
    assert row.radiant_accounts == (1, 2, 3, 4, 5)
    assert row.dire_accounts == (6, 7, 8, 9, 10)


def test_out_of_order_slots_still_split_correctly():
    """array_agg ordering is a database guarantee we decline to trust blindly.

    Feeding deliberately shuffled slots proves the split reads `slots`
    rather than slicing [0:5] and hoping.
    """
    order = [128, 0, 129, 1, 130, 2, 131, 3, 132, 4]
    accounts = [106, 101, 107, 102, 108, 103, 109, 104, 110, 105]
    row = normalize_row(raw(slots=order, accounts=accounts, heroes=list(range(10))))
    assert row.radiant_accounts == (101, 102, 103, 104, 105)
    assert row.dire_accounts == (106, 107, 108, 109, 110)


@pytest.mark.parametrize(
    "slots",
    [
        [0, 1, 2, 3, 4, 128, 129, 130, 131],          # nine players
        [0, 1, 2, 3, 4, 5, 128, 129, 130, 131],       # six radiant
        [0, 0, 1, 2, 3, 128, 129, 130, 131, 132],     # duplicate slot
    ],
)
def test_malformed_rosters_raise(slots):
    with pytest.raises(RosterSlotError):
        normalize_row(raw(slots=slots, accounts=list(range(len(slots))),
                          heroes=list(range(len(slots)))))


def test_series_type_maps_to_best_of():
    assert normalize_row(raw(series_type=0)).best_of == 1
    assert normalize_row(raw(series_type=1)).best_of == 3
    assert normalize_row(raw(series_type=2)).best_of == 5


def test_unknown_series_type_falls_back_to_one_map_not_a_crash():
    """series_type 3 appears in real data (171/3011 in the sampled month).

    OpenDota does not document it. Treating it as a single map is a stated
    assumption, not a silent guess: `best_of` is only used for reporting,
    never for rating updates, which are per-map.
    """
    assert normalize_row(raw(series_type=3)).best_of == 1
    assert normalize_row(raw(series_type=None)).best_of == 1


def test_null_team_id_is_flagged_not_dropped():
    row = normalize_row(raw(dire_team_id=None))
    assert row.has_null_team is True
    assert row.match_id == 8925460065, "the row survives; only the flag changes"


def test_normalize_all_counts_rejections_instead_of_discarding_silently():
    good = raw()
    bad = raw(match_id=1, slots=[0, 1, 2, 3, 4, 128, 129, 130, 131],
              accounts=list(range(9)), heroes=list(range(9)))
    rows, tally = normalize_all([good, bad])
    assert len(rows) == 1
    assert tally == {"roster_slot_error": 1}, "every dropped row is accounted for"


def test_accounts_are_hashable_tuples_for_roster_keying():
    row = normalize_row(raw())
    assert isinstance(row.radiant_accounts, tuple)
    hash(row.radiant_accounts)  # must not raise — Task 3 hashes these
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.data.schema'`

- [ ] **Step 3: Write the schema implementation**

```python
# src/ti26/data/schema.py
"""Normalize raw explorer rows into a validated, hashable map record."""

from collections.abc import Sequence
from dataclasses import dataclass

RADIANT_SLOTS = frozenset(range(5))
DIRE_SLOTS = frozenset(range(128, 133))

# OpenDota series_type: 0=Bo1, 1=Bo3, 2=Bo5. Value 3 occurs in real data
# (171/3011 in the sampled month) and is undocumented; it and NULL fall back
# to 1. best_of is reporting-only — rating updates are per-map regardless.
_BEST_OF = {0: 1, 1: 3, 2: 5}


class RosterSlotError(ValueError):
    """A match's player slots do not form a legal 5v5 roster."""


@dataclass(frozen=True)
class MapRow:
    match_id: int
    start_time: int
    duration: int
    radiant_win: bool
    league_id: int | None
    tier: str | None
    radiant_team_id: int | None
    dire_team_id: int | None
    series_id: int | None
    series_type: int | None
    patch: str | None
    radiant_accounts: tuple[int, ...]
    dire_accounts: tuple[int, ...]
    radiant_heroes: tuple[int, ...]
    dire_heroes: tuple[int, ...]
    has_null_team: bool
    has_bad_roster: bool

    @property
    def best_of(self) -> int:
        return _BEST_OF.get(self.series_type, 1)


def _split(slots: Sequence, accounts: Sequence, heroes: Sequence, match_id) -> tuple:
    if not (len(slots) == len(accounts) == len(heroes)):
        raise RosterSlotError(f"match {match_id}: ragged slot/account/hero arrays")
    if len(slots) != 10:
        raise RosterSlotError(f"match {match_id}: expected 10 players, got {len(slots)}")
    slot_ints = [int(s) for s in slots]
    if len(set(slot_ints)) != 10:
        raise RosterSlotError(f"match {match_id}: duplicate player slots {slot_ints}")
    radiant, dire = ([], []), ([], [])
    for slot, account, hero in zip(slot_ints, accounts, heroes):
        target = radiant if slot in RADIANT_SLOTS else dire if slot in DIRE_SLOTS else None
        if target is None:
            raise RosterSlotError(f"match {match_id}: slot {slot} is neither radiant nor dire")
        target[0].append(int(account) if account is not None else -1)
        target[1].append(int(hero) if hero is not None else -1)
    if len(radiant[0]) != 5 or len(dire[0]) != 5:
        raise RosterSlotError(
            f"match {match_id}: {len(radiant[0])}v{len(dire[0])} is not a legal 5v5"
        )
    return tuple(radiant[0]), tuple(dire[0]), tuple(radiant[1]), tuple(dire[1])


def normalize_row(raw: dict) -> MapRow:
    r_acc, d_acc, r_hero, d_hero = _split(
        raw["slots"], raw["accounts"], raw["heroes"], raw["match_id"]
    )
    return MapRow(
        match_id=int(raw["match_id"]),
        start_time=int(raw["start_time"]),
        duration=int(raw["duration"]),
        radiant_win=bool(raw["radiant_win"]),
        league_id=raw.get("leagueid"),
        tier=raw.get("tier"),
        radiant_team_id=raw.get("radiant_team_id"),
        dire_team_id=raw.get("dire_team_id"),
        series_id=raw.get("series_id"),
        series_type=raw.get("series_type"),
        patch=raw.get("patch"),
        radiant_accounts=r_acc,
        dire_accounts=d_acc,
        radiant_heroes=r_hero,
        dire_heroes=d_hero,
        has_null_team=raw.get("radiant_team_id") is None or raw.get("dire_team_id") is None,
        has_bad_roster=-1 in r_acc or -1 in d_acc,
    )


def normalize_all(raw: list[dict]) -> tuple[list[MapRow], dict[str, int]]:
    rows: list[MapRow] = []
    tally: dict[str, int] = {}
    for item in raw:
        try:
            rows.append(normalize_row(item))
        except RosterSlotError:
            tally["roster_slot_error"] = tally.get("roster_slot_error", 0) + 1
    return rows, tally
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_schema.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Write the failing store test**

```python
# tests/test_store.py
import pytest

from ti26.data.schema import MapRow
from ti26.data.store import LeakageError, assert_no_leakage, insert_rows, load_rows, open_store


def row(match_id, start_time, **kw):
    base = dict(
        duration=2000, radiant_win=True, league_id=1, tier="professional",
        radiant_team_id=10, dire_team_id=20, series_id=5, series_type=1, patch="7.41",
        radiant_accounts=(1, 2, 3, 4, 5), dire_accounts=(6, 7, 8, 9, 10),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )
    base.update(kw)
    return MapRow(match_id=match_id, start_time=start_time, **base)


def test_roundtrip_preserves_every_field(tmp_path):
    conn = open_store(tmp_path / "d2.sqlite")
    original = row(1, 1000, tier=None, league_id=None, has_null_team=True)
    insert_rows(conn, [original])
    assert load_rows(conn) == [original]


def test_insert_is_idempotent_so_reingest_does_not_double_count(tmp_path):
    """Snapshots overlap at month edges on re-runs; a duplicated map would
    be rated twice and inflate a team's evidence for free."""
    conn = open_store(tmp_path / "d2.sqlite")
    insert_rows(conn, [row(1, 1000)])
    insert_rows(conn, [row(1, 1000), row(2, 2000)])
    assert [r.match_id for r in load_rows(conn)] == [1, 2]


def test_rows_load_in_start_time_order(tmp_path):
    conn = open_store(tmp_path / "d2.sqlite")
    insert_rows(conn, [row(3, 3000), row(1, 1000), row(2, 2000)])
    assert [r.start_time for r in load_rows(conn)] == [1000, 2000, 3000]


def test_as_of_excludes_the_future_at_the_boundary(tmp_path):
    conn = open_store(tmp_path / "d2.sqlite")
    insert_rows(conn, [row(1, 1000), row(2, 2000), row(3, 3000)])
    loaded = load_rows(conn, as_of=2000)
    assert [r.match_id for r in loaded] == [1, 2], "as_of is inclusive of its own second"
    assert all(r.start_time <= 2000 for r in loaded)


def test_leakage_assertion_raises_on_a_single_future_row():
    rows = [row(1, 1000), row(2, 2001)]
    with pytest.raises(LeakageError, match="2001"):
        assert_no_leakage(rows, as_of=2000)


def test_leakage_assertion_passes_at_the_exact_boundary():
    assert_no_leakage([row(1, 2000)], as_of=2000) is None
```

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.data.store'`

- [ ] **Step 7: Write the store implementation**

```python
# src/ti26/data/store.py
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

_COLUMNS = [
    "match_id", "start_time", "duration", "radiant_win", "league_id", "tier",
    "radiant_team_id", "dire_team_id", "series_id", "series_type", "patch",
    "radiant_accounts", "dire_accounts", "radiant_heroes", "dire_heroes",
    "has_null_team", "has_bad_roster",
]


class LeakageError(AssertionError):
    """A row dated after `as_of` reached a fit. Spec IV: blocking."""


def open_store(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    return conn


def insert_rows(conn: sqlite3.Connection, rows: Sequence[MapRow]) -> int:
    payload = [
        (
            r.match_id, r.start_time, r.duration, int(r.radiant_win), r.league_id, r.tier,
            r.radiant_team_id, r.dire_team_id, r.series_id, r.series_type, r.patch,
            json.dumps(list(r.radiant_accounts)), json.dumps(list(r.dire_accounts)),
            json.dumps(list(r.radiant_heroes)), json.dumps(list(r.dire_heroes)),
            int(r.has_null_team), int(r.has_bad_roster),
        )
        for r in rows
    ]
    placeholders = ",".join("?" * len(_COLUMNS))
    with conn:
        conn.executemany(
            f"insert or replace into maps ({','.join(_COLUMNS)}) values ({placeholders})",
            payload,
        )
    return len(payload)


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
        f"select {','.join(_COLUMNS)} from maps {where} order by start_time, match_id", params
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
```

- [ ] **Step 8: Run the full task suite and lint**

Run: `.venv/bin/python -m pytest tests/test_schema.py tests/test_store.py -v && .venv/bin/ruff check .`
Expected: PASS (17 tests), lint clean

- [ ] **Step 9: Commit**

```bash
git add src/ti26/data/schema.py src/ti26/data/store.py tests/test_schema.py tests/test_store.py
git commit -m "feat: map schema normalization, sqlite store, leakage assertion"
```

---

## Task 3: Roster canonicalization

**Files:**
- Create: `src/ti26/roster.py`, `config/team_aliases.yaml`
- Test: `tests/test_roster.py`

**Interfaces:**
- Consumes: `MapRow` from Task 2.
- Produces: `roster_version_id(accounts: Iterable[int]) -> str` (16 hex chars); `load_aliases(path) -> dict[int, int]` mapping historical `team_id` → canonical `team_id`; `canonical_team_id(team_id: int | None, aliases: dict[int, int]) -> int | None`; `continuity(previous: Iterable[int], current: Iterable[int]) -> float` returning shared/5; `RosterIndex` with `.observe(row: MapRow) -> tuple[str, str]` returning `(radiant_rvid, dire_rvid)`, `.predecessor(rvid: str) -> str | None`, and `.history(rvid: str) -> int` (number of maps observed for that roster).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_roster.py
from ti26.data.schema import MapRow
from ti26.roster import (
    RosterIndex,
    canonical_team_id,
    continuity,
    load_aliases,
    roster_version_id,
)


def row(match_id, start_time, radiant, dire, r_team=10, d_team=20):
    return MapRow(
        match_id=match_id, start_time=start_time, duration=2000, radiant_win=True,
        league_id=1, tier="professional", radiant_team_id=r_team, dire_team_id=d_team,
        series_id=1, series_type=1, patch="7.41",
        radiant_accounts=tuple(radiant), dire_accounts=tuple(dire),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


def test_roster_id_is_order_independent():
    assert roster_version_id([5, 3, 1, 4, 2]) == roster_version_id([1, 2, 3, 4, 5])


def test_roster_id_changes_when_a_single_player_changes():
    """The whole design rests on this: a substitution must produce a new
    statistical identity, otherwise roster-awareness is decorative."""
    assert roster_version_id([1, 2, 3, 4, 5]) != roster_version_id([1, 2, 3, 4, 6])


def test_roster_id_is_a_16_char_hex_digest():
    rvid = roster_version_id([1, 2, 3, 4, 5])
    assert len(rvid) == 16
    assert all(c in "0123456789abcdef" for c in rvid)


def test_roster_id_is_stable_across_processes():
    """sqlite rows written in one run are read in another, so the id must not
    depend on PYTHONHASHSEED. Python's built-in hash() would fail this."""
    import subprocess
    import sys

    script = (
        "from ti26.roster import roster_version_id; "
        "print(roster_version_id([5, 3, 1, 4, 2]))"
    )
    out = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, check=True,
        env={"PYTHONPATH": "src", "PYTHONHASHSEED": "1"},
    )
    assert out.stdout.strip() == roster_version_id([1, 2, 3, 4, 5])


def test_continuity_counts_shared_players_out_of_five():
    assert continuity([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == 1.0
    assert continuity([1, 2, 3, 4, 5], [1, 2, 3, 4, 9]) == 0.8
    assert continuity([1, 2, 3, 4, 5], [6, 7, 8, 9, 10]) == 0.0


def test_alias_maps_rebranded_org_to_canonical_id(tmp_path):
    path = tmp_path / "aliases.yaml"
    path.write_text("aliases:\n  - {from: 8255888, to: 9247354, note: Iron Wing}\n")
    aliases = load_aliases(path)
    assert canonical_team_id(8255888, aliases) == 9247354
    assert canonical_team_id(9247354, aliases) == 9247354, "canonical ids are fixed points"
    assert canonical_team_id(None, aliases) is None


def test_index_returns_distinct_ids_for_the_two_sides():
    index = RosterIndex()
    r, d = index.observe(row(1, 100, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]))
    assert r != d
    assert r == roster_version_id([1, 2, 3, 4, 5])


def test_predecessor_is_the_most_recent_roster_of_the_same_team():
    """A team that swaps one player should inherit from its own prior roster,
    not from the global prior. This is the re-brand / stand-in case in spec VI."""
    index = RosterIndex()
    index.observe(row(1, 100, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]))
    index.observe(row(2, 200, [1, 2, 3, 4, 9], [6, 7, 8, 9, 10]))
    new_rvid = roster_version_id([1, 2, 3, 4, 9])
    assert index.predecessor(new_rvid) == roster_version_id([1, 2, 3, 4, 5])


def test_first_roster_of_a_team_has_no_predecessor():
    index = RosterIndex()
    r, _ = index.observe(row(1, 100, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]))
    assert index.predecessor(r) is None


def test_predecessor_ignores_a_different_team_with_a_similar_roster():
    """Predecessor lookup is keyed by canonical team, not by player overlap.

    Without this, two unrelated orgs sharing a stand-in would chain histories.
    """
    index = RosterIndex()
    index.observe(row(1, 100, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10], r_team=10))
    r2, _ = index.observe(row(2, 200, [1, 2, 3, 4, 99], [6, 7, 8, 9, 10], r_team=77))
    assert index.predecessor(r2) is None, "team 77 has no history despite 4 shared players"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_roster.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.roster'`

- [ ] **Step 3: Write the implementation**

```python
# src/ti26/roster.py
"""Statistical identity follows the roster, not the organization (spec III)."""

import hashlib
from collections.abc import Iterable
from pathlib import Path

import yaml

from ti26.data.schema import MapRow


def roster_version_id(accounts: Iterable[int]) -> str:
    joined = ",".join(str(a) for a in sorted(accounts))
    return hashlib.sha1(joined.encode()).hexdigest()[:16]


def continuity(previous: Iterable[int], current: Iterable[int]) -> float:
    return len(set(previous) & set(current)) / 5.0


def load_aliases(path: str | Path) -> dict[int, int]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return {int(entry["from"]): int(entry["to"]) for entry in data.get("aliases", [])}


def canonical_team_id(team_id: int | None, aliases: dict[int, int]) -> int | None:
    if team_id is None:
        return None
    return aliases.get(int(team_id), int(team_id))


class RosterIndex:
    """Tracks which roster each canonical team most recently fielded."""

    def __init__(self, aliases: dict[int, int] | None = None) -> None:
        self._aliases = aliases or {}
        self._latest_by_team: dict[int, str] = {}
        self._predecessor: dict[str, str | None] = {}
        self._maps: dict[str, int] = {}

    def observe(self, row: MapRow) -> tuple[str, str]:
        out = []
        for team_id, accounts in (
            (row.radiant_team_id, row.radiant_accounts),
            (row.dire_team_id, row.dire_accounts),
        ):
            rvid = roster_version_id(accounts)
            self._maps[rvid] = self._maps.get(rvid, 0) + 1
            canonical = canonical_team_id(team_id, self._aliases)
            if canonical is not None:
                previous = self._latest_by_team.get(canonical)
                if rvid not in self._predecessor:
                    self._predecessor[rvid] = previous
                self._latest_by_team[canonical] = rvid
            else:
                self._predecessor.setdefault(rvid, None)
            out.append(rvid)
        return out[0], out[1]

    def predecessor(self, rvid: str) -> str | None:
        return self._predecessor.get(rvid)

    def history(self, rvid: str) -> int:
        return self._maps.get(rvid, 0)
```

- [ ] **Step 4: Create the alias config**

```yaml
# config/team_aliases.yaml
# Historical team_id -> canonical team_id.
#
# An empty list is the CORRECT starting state: an alias is a claim that two
# distinct OpenDota team_ids are the same organization, and inventing one
# silently merges two teams' histories. Step 5 resolves the four re-brands
# spec VI names, against real data, before any entry appears here.
#
# Provenance for every entry: inferred (a reading of org identity, not an
# official statement).
aliases: []
```

- [ ] **Step 5: Resolve the four re-brands spec §VI names**

An empty alias table makes `canonical_team_id` an identity function, so this step is what gives Task 3 its purpose. Spec §VI names Iron Wing, Team Vision, BoomBoys and HULIGANI. Find their ids:

```bash
.venv/bin/python - <<'PY'
import json, urllib.parse, urllib.request
sql = """
select t.team_id, t.name, count(*) as maps,
       min(m.start_time) as first_seen, max(m.start_time) as last_seen
from teams t
join matches m on m.radiant_team_id = t.team_id or m.dire_team_id = t.team_id
where t.name ilike any (array['%iron wing%','%vision%','%boomboys%','%huligani%'])
group by 1,2 order by last_seen desc
"""
url = "https://api.opendota.com/api/explorer?sql=" + urllib.parse.quote(sql)
rows = json.load(urllib.request.urlopen(url, timeout=120))["rows"]
for r in rows:
    print(f"{r['team_id']:>10}  {r['name'][:32]:<32} maps={r['maps']:<5} "
          f"first={r['first_seen']} last={r['last_seen']}")
PY
```

Add an entry **only** where two ids have non-overlapping date ranges and the later one continues the earlier roster — that is the signature of a re-brand rather than two coexisting orgs. Write each as `- {from: <old_id>, to: <new_id>, note: <org name>}`. If the evidence is ambiguous for an org, leave it out and record why in the ledger; a wrong alias is worse than a missing one, because it fabricates history for a team that never earned it.

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_roster.py -v`
Expected: PASS (9 tests)

- [ ] **Step 7: Verify the tests discriminate by mutation**

Copy `src/ti26/roster.py` to `/tmp/roster_mutant.py`, change `sorted(accounts)` to `accounts` (dropping order-independence), and run the suite against the copy with an explicit `PYTHONPATH` override. **The `pythonpath = ["src"]` setting in `pyproject.toml:18` silently re-resolves imports to the real tracked source**, so without the override you will test unmutated code and see a false pass.

Run:
```bash
cp -r src /tmp/mut && cp /tmp/roster_mutant.py /tmp/mut/ti26/roster.py
PYTHONPATH=/tmp/mut .venv/bin/python -m pytest tests/test_roster.py -p no:cacheprovider -v
```
Expected: `test_roster_id_is_order_independent` FAILS. Then `rm -rf /tmp/mut /tmp/roster_mutant.py` and confirm `git status` is clean — never mutate tracked source.

- [ ] **Step 8: Commit**

```bash
git add src/ti26/roster.py config/team_aliases.yaml tests/test_roster.py
git commit -m "feat: roster-hash canonicalization with alias table and predecessor chain"
```

---

## Task 4: Elo baseline — the gate comparator

**Files:**
- Create: `src/ti26/ratings/__init__.py`, `src/ti26/ratings/elo.py`, `src/ti26/ratings/simple.py`, `config/d2_gate.yaml`
- Test: `tests/test_elo.py`, `tests/test_simple.py`

**Interfaces:**
- Consumes: `MapRow` (Task 2), `RosterIndex`, `roster_version_id` (Task 3).
- Produces: `Prediction` frozen dataclass `(match_id: int, start_time: int, p_radiant: float, rated: bool, reason: str | None)`; `RatingModel` protocol with `.predict(row) -> float` and `.update(row) -> None`; `EloModel(k: float = 20.0, initial: float = 1500.0, scale: float = 400.0)` with `.rating(rvid) -> float`, `.predict(row) -> float`, `.update(row) -> None`, `.strengths() -> dict[str, float]` returning **logit-scale** strengths ready for `ti26.montecarlo`; `ConstantModel(p: float = 0.5)`; `EwmaModel(half_life_maps: float = 30.0)`; `load_gate_config(path) -> GateConfig` exposing `.min_margin_nats`, `.bootstrap_draws`, `.bootstrap_ci`, `.elo_k`, `.glicko_tau`, `.ewma_half_life_maps`, `.seed`.

- [ ] **Step 1: Write the gate config**

```yaml
# config/d2_gate.yaml
# Pre-registered 2026-08-02, BEFORE any backtest was run. See spec II.
# Changing min_margin_nats after observing a result voids the gate.
gate:
  min_margin_nats: 0.003
  bootstrap_draws: 10000
  bootstrap_ci: 0.95
  seed: 20260802

hyperparameters:
  elo_k: 20.0
  glicko_tau: 0.5
  ewma_half_life_maps: 30.0

provenance:
  min_margin_nats: pre_registered
  elo_k: set_not_searched          # spec VII: hyperparameters are set, not searched
  glicko_tau: set_not_searched     # 0.5 is the Glickman reference value
  ewma_half_life_maps: set_not_searched
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_elo.py
import math

import pytest

from ti26.data.schema import MapRow
from ti26.ratings import load_gate_config
from ti26.ratings.elo import EloModel


def row(match_id, start_time, radiant, dire, radiant_win=True, **kw):
    base = dict(
        duration=2000, league_id=1, tier="professional",
        radiant_team_id=10, dire_team_id=20, series_id=1, series_type=1, patch="7.41",
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )
    base.update(kw)
    return MapRow(
        match_id=match_id, start_time=start_time, radiant_win=radiant_win,
        radiant_accounts=tuple(radiant), dire_accounts=tuple(dire), **base
    )


A = [1, 2, 3, 4, 5]
B = [6, 7, 8, 9, 10]


def test_unseen_rosters_predict_exactly_even():
    model = EloModel()
    assert model.predict(row(1, 100, A, B)) == pytest.approx(0.5)


def test_winner_gains_exactly_what_the_loser_loses():
    from ti26.roster import roster_version_id

    model = EloModel(k=20.0)
    model.update(row(1, 100, A, B, radiant_win=True))
    ra = model.rating(roster_version_id(A))
    rb = model.rating(roster_version_id(B))
    assert ra == pytest.approx(1510.0)
    assert rb == pytest.approx(1490.0)
    assert (ra - 1500.0) == pytest.approx(-(rb - 1500.0)), "Elo is zero-sum"


def test_repeated_wins_increase_predicted_probability_monotonically():
    model = EloModel()
    seen = []
    for i in range(5):
        seen.append(model.predict(row(i, 100 + i, A, B)))
        model.update(row(i, 100 + i, A, B, radiant_win=True))
    assert seen == sorted(seen)
    assert seen[0] == pytest.approx(0.5)
    assert seen[-1] > 0.55


def test_null_team_rows_are_not_rated_and_say_why():
    """Spec III: never silently dropped. The row is skipped for rating
    updates, but the skip is counted with a reason."""
    model = EloModel()
    model.update(row(1, 100, A, B, radiant_win=True, has_null_team=True))
    from ti26.roster import roster_version_id
    assert model.rating(roster_version_id(A)) == 1500.0
    assert model.skipped == {"null_team": 1}


def test_bad_roster_rows_are_not_rated():
    model = EloModel()
    model.update(row(1, 100, A, B, radiant_win=True, has_bad_roster=True))
    assert model.skipped == {"bad_roster": 1}


def test_strengths_are_logit_scale_and_centred():
    """montecarlo.category_marginals consumes logit-scale strengths where a
    difference of 1.0 means ~73% map win probability. Handing it raw Elo
    points (difference of 400) would produce a degenerate simulation."""
    model = EloModel()
    for i in range(10):
        model.update(row(i, 100 + i, A, B, radiant_win=True))
    strengths = model.strengths()
    from ti26.roster import roster_version_id
    gap = strengths[roster_version_id(A)] - strengths[roster_version_id(B)]
    elo_gap = model.rating(roster_version_id(A)) - model.rating(roster_version_id(B))
    assert gap == pytest.approx(elo_gap * math.log(10) / 400.0)
    assert sum(strengths.values()) == pytest.approx(0.0, abs=1e-9), "centred at zero"


def test_gate_config_loads_the_preregistered_margin():
    config = load_gate_config("config/d2_gate.yaml")
    assert config.min_margin_nats == 0.003
    assert config.bootstrap_ci == 0.95
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_elo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.ratings'`

- [ ] **Step 4: Write the shared ratings module**

```python
# src/ti26/ratings/__init__.py
"""Shared types for rating models.

All models expose the same two-method surface so the backtest harness in
`ti26.backtest` can drive any of them without special-casing.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from ti26.data.schema import MapRow


@dataclass(frozen=True)
class Prediction:
    match_id: int
    start_time: int
    p_radiant: float
    rated: bool
    reason: str | None = None


class RatingModel(Protocol):
    def predict(self, row: MapRow) -> float: ...
    def update(self, row: MapRow) -> None: ...


@dataclass(frozen=True)
class GateConfig:
    min_margin_nats: float
    bootstrap_draws: int
    bootstrap_ci: float
    seed: int
    elo_k: float
    glicko_tau: float
    ewma_half_life_maps: float


def load_gate_config(path: str | Path) -> GateConfig:
    data = yaml.safe_load(Path(path).read_text())
    gate, hyper = data["gate"], data["hyperparameters"]
    return GateConfig(
        min_margin_nats=float(gate["min_margin_nats"]),
        bootstrap_draws=int(gate["bootstrap_draws"]),
        bootstrap_ci=float(gate["bootstrap_ci"]),
        seed=int(gate["seed"]),
        elo_k=float(hyper["elo_k"]),
        glicko_tau=float(hyper["glicko_tau"]),
        ewma_half_life_maps=float(hyper["ewma_half_life_maps"]),
    )


def skip_reason(row: MapRow) -> str | None:
    """Why this row cannot drive a rating update, or None if it can."""
    if row.has_null_team:
        return "null_team"
    if row.has_bad_roster:
        return "bad_roster"
    return None
```

- [ ] **Step 5: Write the Elo implementation**

```python
# src/ti26/ratings/elo.py
"""Map-level Elo keyed by roster, the comparator for the D2 gate (spec V)."""

import math

from ti26.data.schema import MapRow
from ti26.ratings import skip_reason
from ti26.roster import roster_version_id

# Elo points -> logit scale. A 400-point gap is 10:1 odds by construction,
# so the conversion factor is ln(10)/400.
LOGIT_PER_ELO = math.log(10) / 400.0


class EloModel:
    def __init__(self, k: float = 20.0, initial: float = 1500.0, scale: float = 400.0) -> None:
        self._k = k
        self._initial = initial
        self._scale = scale
        self._ratings: dict[str, float] = {}
        self.skipped: dict[str, int] = {}

    def rating(self, rvid: str) -> float:
        return self._ratings.get(rvid, self._initial)

    def predict(self, row: MapRow) -> float:
        ra = self.rating(roster_version_id(row.radiant_accounts))
        rb = self.rating(roster_version_id(row.dire_accounts))
        return 1.0 / (1.0 + 10.0 ** ((rb - ra) / self._scale))

    def update(self, row: MapRow) -> None:
        reason = skip_reason(row)
        if reason is not None:
            self.skipped[reason] = self.skipped.get(reason, 0) + 1
            return
        a = roster_version_id(row.radiant_accounts)
        b = roster_version_id(row.dire_accounts)
        expected = self.predict(row)
        outcome = 1.0 if row.radiant_win else 0.0
        delta = self._k * (outcome - expected)
        self._ratings[a] = self.rating(a) + delta
        self._ratings[b] = self.rating(b) - delta

    def strengths(self) -> dict[str, float]:
        """Logit-scale, zero-centred strengths for `ti26.montecarlo`."""
        if not self._ratings:
            return {}
        mean = sum(self._ratings.values()) / len(self._ratings)
        return {k: (v - mean) * LOGIT_PER_ELO for k, v in self._ratings.items()}
```

- [ ] **Step 6: Write the floor baselines**

```python
# src/ti26/ratings/simple.py
"""Spec V floors 1 and 3: constant and exponentially weighted recent form."""

import math

from ti26.data.schema import MapRow
from ti26.ratings import skip_reason
from ti26.roster import roster_version_id


class ConstantModel:
    """Floor 1: every map 50/50. Log loss = ln 2 = 0.693."""

    def __init__(self, p: float = 0.5) -> None:
        self._p = p
        self.skipped: dict[str, int] = {}

    def predict(self, row: MapRow) -> float:
        return self._p

    def update(self, row: MapRow) -> None:
        return None


class EwmaModel:
    """Floor 3: exponentially weighted map win rate, no opponent adjustment."""

    def __init__(self, half_life_maps: float = 30.0) -> None:
        self._decay = 0.5 ** (1.0 / half_life_maps)
        self._wins: dict[str, float] = {}
        self._total: dict[str, float] = {}
        self.skipped: dict[str, int] = {}

    def _rate(self, rvid: str) -> float:
        total = self._total.get(rvid, 0.0)
        return self._wins.get(rvid, 0.0) / total if total > 0 else 0.5

    def predict(self, row: MapRow) -> float:
        a = self._rate(roster_version_id(row.radiant_accounts))
        b = self._rate(roster_version_id(row.dire_accounts))
        # Two independent win rates compared on the logit scale, clipped so a
        # roster with a perfect record does not yield an infinite logit.
        eps = 1e-6
        la = math.log(min(max(a, eps), 1 - eps) / (1 - min(max(a, eps), 1 - eps)))
        lb = math.log(min(max(b, eps), 1 - eps) / (1 - min(max(b, eps), 1 - eps)))
        return 1.0 / (1.0 + math.exp(-(la - lb)))

    def update(self, row: MapRow) -> None:
        reason = skip_reason(row)
        if reason is not None:
            self.skipped[reason] = self.skipped.get(reason, 0) + 1
            return
        for accounts, won in (
            (row.radiant_accounts, row.radiant_win),
            (row.dire_accounts, not row.radiant_win),
        ):
            rvid = roster_version_id(accounts)
            self._wins[rvid] = self._wins.get(rvid, 0.0) * self._decay + (1.0 if won else 0.0)
            self._total[rvid] = self._total.get(rvid, 0.0) * self._decay + 1.0
```

- [ ] **Step 7: Write the floor-baseline test**

```python
# tests/test_simple.py
import math

import pytest

from ti26.data.schema import MapRow
from ti26.ratings.simple import ConstantModel, EwmaModel


def row(match_id, radiant, dire, radiant_win=True):
    return MapRow(
        match_id=match_id, start_time=100 + match_id, duration=2000,
        radiant_win=radiant_win, league_id=1, tier="professional",
        radiant_team_id=10, dire_team_id=20, series_id=1, series_type=1, patch="7.41",
        radiant_accounts=tuple(radiant), dire_accounts=tuple(dire),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


A, B = [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]


def test_constant_model_log_loss_is_ln_two():
    model = ConstantModel()
    assert -math.log(model.predict(row(1, A, B))) == pytest.approx(math.log(2))


def test_ewma_starts_even_and_moves_toward_the_winner():
    model = EwmaModel(half_life_maps=30.0)
    assert model.predict(row(1, A, B)) == pytest.approx(0.5)
    for i in range(10):
        model.update(row(i, A, B, radiant_win=True))
    assert model.predict(row(99, A, B)) > 0.7


def test_ewma_forgets_old_results_faster_with_a_shorter_half_life():
    """A half-life that does nothing would make the parameter decorative.

    Both models see the same 10 losses then 10 wins; the shorter half-life
    must end up more convinced by the recent wins.
    """
    fast, slow = EwmaModel(half_life_maps=3.0), EwmaModel(half_life_maps=100.0)
    for model in (fast, slow):
        for i in range(10):
            model.update(row(i, A, B, radiant_win=False))
        for i in range(10, 20):
            model.update(row(i, A, B, radiant_win=True))
    assert fast.predict(row(99, A, B)) > slow.predict(row(99, A, B))


def test_ewma_predictions_stay_in_the_open_unit_interval():
    """An unbeaten roster must not produce p = 1.0; log loss would be inf and
    a single upset would dominate every metric."""
    model = EwmaModel(half_life_maps=30.0)
    for i in range(200):
        model.update(row(i, A, B, radiant_win=True))
    p = model.predict(row(999, A, B))
    assert 0.0 < p < 1.0
```

- [ ] **Step 8: Run the full task suite and lint**

Run: `.venv/bin/python -m pytest tests/test_elo.py tests/test_simple.py -v && .venv/bin/ruff check .`
Expected: PASS (11 tests), lint clean

- [ ] **Step 9: Commit**

```bash
git add src/ti26/ratings config/d2_gate.yaml tests/test_elo.py tests/test_simple.py
git commit -m "feat: Elo comparator, floor baselines, pre-registered gate config"
```

---

## Task 5: Roster-aware Glicko-2 — the gate candidate

**Files:**
- Create: `src/ti26/ratings/glicko.py`
- Test: `tests/test_glicko.py`

**Interfaces:**
- Consumes: `MapRow`, `skip_reason`, `RosterIndex`, `roster_version_id`, `continuity`.
- Produces: `GlickoRating` frozen dataclass `(rating: float, rd: float, volatility: float)`; `GlickoModel(tau: float = 0.5, initial_rating: float = 1500.0, initial_rd: float = 350.0, initial_volatility: float = 0.06, period_seconds: int = 604800, roster_index: RosterIndex | None = None)` with `.rating_of(rvid) -> GlickoRating`, `.predict(row) -> float`, `.update(row) -> None`, `.flush() -> None`, `.strengths() -> dict[str, float]`, `.prior_driven(min_maps: int = 10) -> list[str]`.

**Note for the implementer:** Glicko-2 updates in *rating periods*, not per match. `update` accumulates results into the current period and flushes when a row's `start_time` crosses a period boundary; `flush` forces the pending period through. `predict` must reflect rating-deviation inflation, which is the entire reason spec §V prefers Glicko here.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_glicko.py
import pytest

from ti26.data.schema import MapRow
from ti26.ratings.glicko import GlickoModel
from ti26.roster import RosterIndex, roster_version_id

WEEK = 604800


def row(match_id, start_time, radiant, dire, radiant_win=True, **kw):
    base = dict(
        duration=2000, league_id=1, tier="professional",
        radiant_team_id=10, dire_team_id=20, series_id=1, series_type=1, patch="7.41",
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )
    base.update(kw)
    return MapRow(
        match_id=match_id, start_time=start_time, radiant_win=radiant_win,
        radiant_accounts=tuple(radiant), dire_accounts=tuple(dire), **base
    )


A, B, C = [1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12, 13, 14, 15]


def test_glickman_reference_example_reproduces_published_values():
    """Glickman's Glicko-2 worked example (glicko.net/glicko/glicko2.pdf).

    Player r=1500 RD=200 vol=0.06 vs three opponents (1400/30 W, 1550/100 L,
    1700/300 L) with tau=0.5 gives r'=1464.06, RD'=151.52, vol'=0.05999.
    Reproducing a published fixture is the only test here that can catch an
    algebra error in the volatility iteration; everything else would pass
    with a plausible-but-wrong update rule.
    """
    from ti26.ratings.glicko import GlickoRating, update_rating

    result = update_rating(
        GlickoRating(1500.0, 200.0, 0.06),
        [
            (GlickoRating(1400.0, 30.0, 0.06), 1.0),
            (GlickoRating(1550.0, 100.0, 0.06), 0.0),
            (GlickoRating(1700.0, 300.0, 0.06), 0.0),
        ],
        tau=0.5,
    )
    assert result.rating == pytest.approx(1464.06, abs=0.02)
    assert result.rd == pytest.approx(151.52, abs=0.02)
    assert result.volatility == pytest.approx(0.05999, abs=0.0001)


def test_unrated_rosters_predict_even():
    model = GlickoModel()
    assert model.predict(row(1, 0, A, B)) == pytest.approx(0.5)


def test_rating_deviation_shrinks_with_evidence():
    """The RD is the whole reason spec V prefers Glicko over Elo here."""
    model = GlickoModel()
    before = model.rating_of(roster_version_id(A)).rd
    for week in range(8):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.flush()
    assert model.rating_of(roster_version_id(A)).rd < before


def test_uncertain_favourite_is_predicted_less_confidently_than_a_certain_one():
    """Two rosters with identical point ratings but different RD must NOT
    receive the same prediction. If they do, the RD is decorative and Glicko
    reduces to Elo with extra steps.
    """
    from ti26.ratings.glicko import GlickoRating, expected_score

    certain = expected_score(GlickoRating(1700.0, 30.0, 0.06), GlickoRating(1500.0, 30.0, 0.06))
    uncertain = expected_score(GlickoRating(1700.0, 30.0, 0.06), GlickoRating(1500.0, 350.0, 0.06))
    assert certain > uncertain
    assert uncertain > 0.5, "still a favourite, just less emphatically"


def test_results_only_take_effect_after_the_period_closes():
    """Within-period results must not leak into a same-period prediction —
    that is a miniature version of the leakage the spec IV cutoff prevents."""
    model = GlickoModel(period_seconds=WEEK)
    baseline = model.predict(row(0, 0, A, B))
    model.update(row(1, 100, A, B, radiant_win=True))
    assert model.predict(row(2, 200, A, B)) == pytest.approx(baseline)
    model.update(row(3, 2 * WEEK, C, B, radiant_win=True))  # crosses the boundary
    assert model.predict(row(4, 2 * WEEK + 1, A, B)) > baseline


def test_new_roster_inherits_from_its_predecessor_not_the_global_prior():
    """Spec III: without continuity blending a re-branded org looks brand new,
    which is badly wrong for a roster that has played together for a year."""
    index = RosterIndex()
    model = GlickoModel(roster_index=index, period_seconds=WEEK)
    for week in range(12):
        r = row(week, week * WEEK, A, B, radiant_win=True)
        index.observe(r)
        model.update(r)
    model.flush()

    swapped = [1, 2, 3, 4, 99]
    new_row = row(99, 20 * WEEK, swapped, B)
    index.observe(new_row)
    inherited = model.rating_of(roster_version_id(swapped))
    assert inherited.rating > 1500.0, "4/5 continuity carries most of the history"
    assert inherited.rd > model.rating_of(roster_version_id(A)).rd, (
        "but the new roster is less certain than the one that earned the rating"
    )


def test_prior_driven_rosters_are_reported():
    """Spec III measured finding: thin recent samples are the DEFAULT, so the
    report must name which teams are running on the prior."""
    model = GlickoModel(period_seconds=WEEK)
    for week in range(15):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.update(row(99, 16 * WEEK, C, B, radiant_win=True))
    model.flush()
    flagged = model.prior_driven(min_maps=10)
    assert roster_version_id(C) in flagged
    assert roster_version_id(A) not in flagged


def test_skipped_rows_are_counted_with_a_reason():
    model = GlickoModel()
    model.update(row(1, 0, A, B, has_null_team=True))
    assert model.skipped == {"null_team": 1}


def test_strengths_are_logit_scale_and_centred():
    model = GlickoModel(period_seconds=WEEK)
    for week in range(8):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.flush()
    strengths = model.strengths()
    assert sum(strengths.values()) == pytest.approx(0.0, abs=1e-9)
    assert strengths[roster_version_id(A)] > strengths[roster_version_id(B)]
    assert abs(strengths[roster_version_id(A)]) < 10.0, "logit scale, not rating points"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_glicko.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.ratings.glicko'`

- [ ] **Step 3: Write the implementation**

```python
# src/ti26/ratings/glicko.py
"""Roster-aware Glicko-2 (Glickman 2013), map-level.

The rating deviation is the reason spec V prefers this over Elo: qualifier
teams and freshly assembled rosters genuinely are uncertain, and the measured
collapse in recent match volume (spec III) makes thin evidence the norm.
"""

import math
from dataclasses import dataclass

from ti26.data.schema import MapRow
from ti26.ratings import skip_reason
from ti26.roster import RosterIndex, continuity, roster_version_id

SCALE = 173.7178  # Glicko-2 internal scale conversion
LOGIT_PER_GLICKO = math.log(10) / 400.0


@dataclass(frozen=True)
class GlickoRating:
    rating: float
    rd: float
    volatility: float


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / (math.pi * math.pi))


def _e(mu: float, mu_j: float, phi_j: float) -> float:
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def expected_score(player: GlickoRating, opponent: GlickoRating) -> float:
    """Win probability accounting for BOTH rating deviations."""
    mu = (player.rating - 1500.0) / SCALE
    mu_j = (opponent.rating - 1500.0) / SCALE
    phi = math.sqrt(player.rd**2 + opponent.rd**2) / SCALE
    return 1.0 / (1.0 + math.exp(-_g(phi) * (mu - mu_j)))


def _solve_volatility(delta: float, phi: float, v: float, sigma: float, tau: float) -> float:
    """Illinois-variant regula falsi, per Glickman step 5."""
    a = math.log(sigma * sigma)
    delta_sq, phi_sq = delta * delta, phi * phi

    def f(x: float) -> float:
        ex = math.exp(x)
        numerator = ex * (delta_sq - phi_sq - v - ex)
        denominator = 2.0 * (phi_sq + v + ex) ** 2
        return numerator / denominator - (x - a) / (tau * tau)

    A = a
    if delta_sq > phi_sq + v:
        B = math.log(delta_sq - phi_sq - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        B = a - k * tau

    fa, fb = f(A), f(B)
    for _ in range(100):
        if abs(B - A) <= 1e-6:
            break
        C = A + (A - B) * fa / (fb - fa)
        fc = f(C)
        if fc * fb <= 0:
            A, fa = B, fb
        else:
            fa /= 2.0
        B, fb = C, fc
    return math.exp(A / 2.0)


def update_rating(
    player: GlickoRating, results: list[tuple[GlickoRating, float]], tau: float
) -> GlickoRating:
    """One Glicko-2 rating period for one player."""
    mu = (player.rating - 1500.0) / SCALE
    phi = player.rd / SCALE

    if not results:
        # No games: only uncertainty grows.
        phi_star = math.sqrt(phi * phi + player.volatility**2)
        return GlickoRating(player.rating, phi_star * SCALE, player.volatility)

    v_inv = 0.0
    delta_sum = 0.0
    for opponent, score in results:
        mu_j = (opponent.rating - 1500.0) / SCALE
        phi_j = opponent.rd / SCALE
        g_j = _g(phi_j)
        e_j = _e(mu, mu_j, phi_j)
        v_inv += g_j * g_j * e_j * (1.0 - e_j)
        delta_sum += g_j * (score - e_j)
    v = 1.0 / v_inv
    delta = v * delta_sum

    sigma_prime = _solve_volatility(delta, phi, v, player.volatility, tau)
    phi_star = math.sqrt(phi * phi + sigma_prime * sigma_prime)
    phi_prime = 1.0 / math.sqrt(1.0 / (phi_star * phi_star) + 1.0 / v)
    mu_prime = mu + phi_prime * phi_prime * delta_sum

    return GlickoRating(mu_prime * SCALE + 1500.0, phi_prime * SCALE, sigma_prime)


class GlickoModel:
    def __init__(
        self,
        tau: float = 0.5,
        initial_rating: float = 1500.0,
        initial_rd: float = 350.0,
        initial_volatility: float = 0.06,
        period_seconds: int = 604800,
        roster_index: RosterIndex | None = None,
    ) -> None:
        self._tau = tau
        self._initial = GlickoRating(initial_rating, initial_rd, initial_volatility)
        self._period = period_seconds
        self._index = roster_index
        self._ratings: dict[str, GlickoRating] = {}
        self._maps: dict[str, int] = {}
        self._pending: dict[str, list[tuple[GlickoRating, float]]] = {}
        self._period_start: int | None = None
        self.skipped: dict[str, int] = {}

    def rating_of(self, rvid: str) -> GlickoRating:
        if rvid in self._ratings:
            return self._ratings[rvid]
        return self._inherit(rvid)

    def _inherit(self, rvid: str) -> GlickoRating:
        """Continuity-weighted initialization (spec III)."""
        if self._index is None:
            return self._initial
        predecessor = self._index.predecessor(rvid)
        if predecessor is None or predecessor not in self._ratings:
            return self._initial
        prior = self._ratings[predecessor]
        # Continuity is unknown from the id alone; the index stores the
        # predecessor, so weight by how much of the rating we can justify
        # carrying. Full continuity would mean the id had not changed at all,
        # so the achievable maximum here is 4/5.
        weight = 0.8
        rating = weight * prior.rating + (1.0 - weight) * self._initial.rating
        # Uncertainty must INCREASE relative to the predecessor: this roster
        # has never played. Blend toward the prior RD rather than away.
        rd = math.sqrt(weight * prior.rd**2 + (1.0 - weight) * self._initial.rd**2)
        return GlickoRating(rating, max(rd, prior.rd * 1.1), prior.volatility)

    def predict(self, row: MapRow) -> float:
        a = self.rating_of(roster_version_id(row.radiant_accounts))
        b = self.rating_of(roster_version_id(row.dire_accounts))
        return expected_score(a, b)

    def update(self, row: MapRow) -> None:
        reason = skip_reason(row)
        if reason is not None:
            self.skipped[reason] = self.skipped.get(reason, 0) + 1
            return
        if self._period_start is None:
            self._period_start = row.start_time
        if row.start_time - self._period_start >= self._period:
            self.flush()
            self._period_start = row.start_time

        a = roster_version_id(row.radiant_accounts)
        b = roster_version_id(row.dire_accounts)
        ra, rb = self.rating_of(a), self.rating_of(b)
        score = 1.0 if row.radiant_win else 0.0
        self._pending.setdefault(a, []).append((rb, score))
        self._pending.setdefault(b, []).append((ra, 1.0 - score))
        self._maps[a] = self._maps.get(a, 0) + 1
        self._maps[b] = self._maps.get(b, 0) + 1

    def flush(self) -> None:
        if not self._pending:
            return
        updated = {
            rvid: update_rating(self.rating_of(rvid), results, self._tau)
            for rvid, results in self._pending.items()
        }
        self._ratings.update(updated)
        self._pending = {}

    def strengths(self) -> dict[str, float]:
        self.flush()
        if not self._ratings:
            return {}
        mean = sum(r.rating for r in self._ratings.values()) / len(self._ratings)
        return {k: (r.rating - mean) * LOGIT_PER_GLICKO for k, r in self._ratings.items()}

    def prior_driven(self, min_maps: int = 10) -> list[str]:
        return sorted(r for r in self._ratings if self._maps.get(r, 0) < min_maps)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_glicko.py -v`
Expected: PASS (10 tests). The Glickman fixture test is the load-bearing one — if it fails, the volatility iteration or the scale conversion is wrong, and no amount of monotonicity testing will find it.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check .
git add src/ti26/ratings/glicko.py tests/test_glicko.py
git commit -m "feat: roster-aware Glicko-2 with continuity inheritance"
```

---

## Task 6: Rolling backtest harness, metrics, and the gate

**Files:**
- Create: `src/ti26/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `MapRow`, `assert_no_leakage`, `RatingModel`, `GateConfig`.
- Produces: `Fold` frozen dataclass `(league_id: int, as_of: int, n_train: int, n_test: int)`; `rolling_folds(rows, min_train: int = 500) -> list[Fold]`; `run_model(rows, model_factory, folds) -> list[Prediction]`; `per_map_log_loss(predictions, rows) -> np.ndarray` (the per-map vector the paired bootstrap consumes); `log_loss(predictions, rows) -> float`; `brier(predictions, rows) -> float`; `accuracy(predictions, rows) -> float`; `calibration(predictions, rows) -> tuple[float, float]` returning `(slope, intercept)`; `paired_bootstrap(losses_a, losses_b, draws, ci, seed) -> tuple[float, float, float]` returning `(mean_diff, lo, hi)`; `GateResult` frozen dataclass `(margin: float, ci_low: float, ci_high: float, passed: bool, reasons: list[str])`; `evaluate_gate(elo_losses, glicko_losses, config) -> GateResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backtest.py
import math

import numpy as np
import pytest

from ti26.data.schema import MapRow
from ti26.ratings import GateConfig, Prediction
from ti26.backtest import (
    accuracy,
    brier,
    calibration,
    evaluate_gate,
    log_loss,
    paired_bootstrap,
    rolling_folds,
)


def row(match_id, start_time, league_id, radiant_win=True):
    return MapRow(
        match_id=match_id, start_time=start_time, duration=2000, radiant_win=radiant_win,
        league_id=league_id, tier="professional", radiant_team_id=10, dire_team_id=20,
        series_id=1, series_type=1, patch="7.41",
        radiant_accounts=(1, 2, 3, 4, 5), dire_accounts=(6, 7, 8, 9, 10),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


def pred(match_id, p):
    return Prediction(match_id=match_id, start_time=match_id, p_radiant=p, rated=True)


DAY = 86400


def test_folds_cut_24h_before_each_tournaments_first_match():
    rows = (
        [row(i, i * 100, league_id=1) for i in range(600)]
        + [row(1000 + i, 10_000_000 + i * 100, league_id=2) for i in range(50)]
    )
    folds = rolling_folds(rows, min_train=500)
    assert len(folds) == 1
    fold = folds[0]
    assert fold.league_id == 2
    assert fold.as_of == 10_000_000 - DAY, "cutoff is 24h before the first match (spec IV)"
    assert fold.n_test == 50


def test_tournaments_without_enough_history_are_skipped():
    """A fold fitted on 20 maps produces a number, not evidence."""
    rows = [row(i, i * 100, league_id=1) for i in range(20)] + [
        row(1000 + i, 10_000_000 + i * 100, league_id=2) for i in range(50)
    ]
    assert rolling_folds(rows, min_train=500) == []


def test_log_loss_of_a_perfect_forecaster_is_zero():
    rows = [row(1, 1, 1, radiant_win=True), row(2, 2, 1, radiant_win=False)]
    predictions = [pred(1, 1 - 1e-12), pred(2, 1e-12)]
    assert log_loss(predictions, rows) == pytest.approx(0.0, abs=1e-9)


def test_log_loss_of_the_constant_baseline_is_ln_two():
    rows = [row(i, i, 1, radiant_win=i % 2 == 0) for i in range(10)]
    predictions = [pred(i, 0.5) for i in range(10)]
    assert log_loss(predictions, rows) == pytest.approx(math.log(2))


def test_log_loss_is_finite_for_a_confidently_wrong_forecast():
    """An unclipped 0.0 would give inf and destroy every downstream metric."""
    rows = [row(1, 1, 1, radiant_win=True)]
    assert math.isfinite(log_loss([pred(1, 0.0)], rows))


def test_brier_matches_hand_computation():
    rows = [row(1, 1, 1, radiant_win=True), row(2, 2, 1, radiant_win=False)]
    predictions = [pred(1, 0.8), pred(2, 0.3)]
    assert brier(predictions, rows) == pytest.approx((0.04 + 0.09) / 2)


def test_accuracy_is_reported_but_distinguishable_from_log_loss():
    """Spec II: accuracy is reported, never used for selection. This test
    exists to prove the two metrics can disagree, which is exactly why."""
    rows = [row(1, 1, 1, radiant_win=True), row(2, 2, 1, radiant_win=True)]
    confident = [pred(1, 0.99), pred(2, 0.51)]
    timid = [pred(1, 0.51), pred(2, 0.51)]
    assert accuracy(confident, rows) == accuracy(timid, rows) == 1.0
    assert log_loss(confident, rows) < log_loss(timid, rows)


def test_calibration_of_a_well_calibrated_forecaster_has_slope_near_one():
    rng = np.random.default_rng(7)
    ps = rng.uniform(0.05, 0.95, size=4000)
    outcomes = rng.uniform(size=4000) < ps
    rows = [row(i, i, 1, radiant_win=bool(o)) for i, o in enumerate(outcomes)]
    predictions = [pred(i, float(p)) for i, p in enumerate(ps)]
    slope, intercept = calibration(predictions, rows)
    assert slope == pytest.approx(1.0, abs=0.15)
    assert intercept == pytest.approx(0.0, abs=0.15)


def test_calibration_detects_an_overconfident_forecaster():
    """Spec VI names over-dispersion at large gaps as THE failure mode to
    hunt. A calibration function that cannot detect it is useless."""
    rng = np.random.default_rng(11)
    truth = rng.uniform(0.2, 0.8, size=4000)
    outcomes = rng.uniform(size=4000) < truth
    logits = np.log(truth / (1 - truth))
    inflated = 1 / (1 + np.exp(-2.0 * logits))  # twice as extreme as reality
    rows = [row(i, i, 1, radiant_win=bool(o)) for i, o in enumerate(outcomes)]
    predictions = [pred(i, float(p)) for i, p in enumerate(inflated)]
    slope, _ = calibration(predictions, rows)
    assert slope < 0.75, "overconfidence must show up as slope well below 1"


def test_paired_bootstrap_ci_excludes_zero_for_a_real_difference():
    rng = np.random.default_rng(3)
    a = rng.normal(0.700, 0.10, size=5000)
    b = a - 0.01  # b is genuinely better by 0.01 nats on every map
    mean, lo, hi = paired_bootstrap(a, b, draws=2000, ci=0.95, seed=1)
    assert mean == pytest.approx(0.01, abs=0.002)
    assert lo > 0.0


def test_paired_bootstrap_ci_includes_zero_for_pure_noise():
    rng = np.random.default_rng(4)
    a = rng.normal(0.700, 0.10, size=5000)
    b = rng.normal(0.700, 0.10, size=5000)
    _, lo, hi = paired_bootstrap(a, b, draws=2000, ci=0.95, seed=1)
    assert lo < 0.0 < hi


def test_bootstrap_is_paired_not_independent():
    """Pairing is the entire point: the same maps are hard for both models.

    Independent resampling would inflate the CI enormously on correlated
    losses, so a much narrower CI here proves the pairing is real.
    """
    rng = np.random.default_rng(5)
    shared = rng.normal(0.700, 0.30, size=4000)  # large shared variance
    a = shared + rng.normal(0, 0.01, size=4000)
    b = shared + rng.normal(0, 0.01, size=4000) - 0.005
    _, lo, hi = paired_bootstrap(a, b, draws=2000, ci=0.95, seed=1)
    assert (hi - lo) < 0.01, "paired CI must not carry the shared variance"


def config(**kw):
    base = dict(
        min_margin_nats=0.003, bootstrap_draws=2000, bootstrap_ci=0.95, seed=1,
        elo_k=20.0, glicko_tau=0.5, ewma_half_life_maps=30.0,
    )
    base.update(kw)
    return GateConfig(**base)


def test_gate_requires_both_conditions_margin_and_significance():
    rng = np.random.default_rng(9)
    elo = rng.normal(0.700, 0.05, size=8000)

    # Significant but below the pre-registered margin -> FAIL.
    small = elo - 0.0005
    result = evaluate_gate(elo, small, config())
    assert result.passed is False
    assert any("margin" in r for r in result.reasons)

    # Large margin but swamped by noise -> FAIL.
    noisy = elo - 0.004 + rng.normal(0, 0.5, size=8000)
    result = evaluate_gate(elo, noisy, config())
    assert result.passed is False
    assert any("CI" in r for r in result.reasons)

    # Both conditions met -> PASS.
    good = elo - 0.006
    result = evaluate_gate(elo, good, config())
    assert result.passed is True
    assert result.reasons == []


def test_gate_reads_the_margin_from_config_not_a_literal():
    """Pre-registration is meaningless if the threshold is hard-coded in two
    places and only one of them is the registered one."""
    rng = np.random.default_rng(13)
    elo = rng.normal(0.700, 0.02, size=8000)
    candidate = elo - 0.004
    assert evaluate_gate(elo, candidate, config(min_margin_nats=0.003)).passed is True
    assert evaluate_gate(elo, candidate, config(min_margin_nats=0.010)).passed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_backtest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.backtest'`

- [ ] **Step 3: Write the implementation**

```python
# src/ti26/backtest.py
"""Rolling event-cutoff backtesting and the pre-registered D2 gate.

Random train/test splitting is invalid here (spec IV): it lets future matches
inform past predictions, producing excellent metrics and useless forecasts.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from ti26.data.schema import MapRow
from ti26.data.store import assert_no_leakage
from ti26.ratings import GateConfig, Prediction

DAY_SECONDS = 86400
EPS = 1e-15


@dataclass(frozen=True)
class Fold:
    league_id: int
    as_of: int
    n_train: int
    n_test: int


@dataclass(frozen=True)
class GateResult:
    margin: float
    ci_low: float
    ci_high: float
    passed: bool
    reasons: list[str] = field(default_factory=list)


def rolling_folds(rows: Sequence[MapRow], min_train: int = 500) -> list[Fold]:
    """One fold per tournament, cut 24h before its first match."""
    ordered = sorted(rows, key=lambda r: (r.start_time, r.match_id))
    first_seen: dict[int, int] = {}
    for row in ordered:
        if row.league_id is not None and row.league_id not in first_seen:
            first_seen[row.league_id] = row.start_time

    folds = []
    for league_id, first in sorted(first_seen.items(), key=lambda kv: kv[1]):
        as_of = first - DAY_SECONDS
        n_train = sum(1 for r in ordered if r.start_time <= as_of)
        n_test = sum(1 for r in ordered if r.league_id == league_id)
        if n_train < min_train:
            continue
        folds.append(Fold(league_id=league_id, as_of=as_of, n_train=n_train, n_test=n_test))
    return folds


def run_model(
    rows: Sequence[MapRow],
    model_factory: Callable[[], object],
    folds: Sequence[Fold],
) -> list[Prediction]:
    """Refit from scratch at each cutoff, then predict that tournament."""
    ordered = sorted(rows, key=lambda r: (r.start_time, r.match_id))
    predictions: list[Prediction] = []
    for fold in folds:
        train = [r for r in ordered if r.start_time <= fold.as_of]
        assert_no_leakage(train, fold.as_of)  # spec IV: blocking
        model = model_factory()
        for row in train:
            model.update(row)
        if hasattr(model, "flush"):
            model.flush()
        for row in ordered:
            if row.league_id != fold.league_id:
                continue
            predictions.append(
                Prediction(
                    match_id=row.match_id,
                    start_time=row.start_time,
                    p_radiant=model.predict(row),
                    rated=True,
                )
            )
    return predictions


def _aligned(predictions: Sequence[Prediction], rows: Sequence[MapRow]) -> tuple:
    outcomes = {r.match_id: r.radiant_win for r in rows}
    ps, ys = [], []
    for prediction in predictions:
        if prediction.match_id in outcomes:
            ps.append(min(max(prediction.p_radiant, EPS), 1.0 - EPS))
            ys.append(1.0 if outcomes[prediction.match_id] else 0.0)
    return np.asarray(ps), np.asarray(ys)


def per_map_log_loss(predictions: Sequence[Prediction], rows: Sequence[MapRow]) -> np.ndarray:
    ps, ys = _aligned(predictions, rows)
    return -(ys * np.log(ps) + (1 - ys) * np.log(1 - ps))


def log_loss(predictions: Sequence[Prediction], rows: Sequence[MapRow]) -> float:
    return float(per_map_log_loss(predictions, rows).mean())


def brier(predictions: Sequence[Prediction], rows: Sequence[MapRow]) -> float:
    ps, ys = _aligned(predictions, rows)
    return float(((ps - ys) ** 2).mean())


def accuracy(predictions: Sequence[Prediction], rows: Sequence[MapRow]) -> float:
    """Reported only. Spec II forbids using this for selection."""
    ps, ys = _aligned(predictions, rows)
    return float(((ps >= 0.5) == (ys >= 0.5)).mean())


def calibration(
    predictions: Sequence[Prediction], rows: Sequence[MapRow]
) -> tuple[float, float]:
    """Logistic recalibration: fit y ~ intercept + slope * logit(p).

    Slope 1 / intercept 0 is perfect. Slope < 1 means over-dispersion — the
    failure mode spec VI names as the one to hunt.
    """
    ps, ys = _aligned(predictions, rows)
    x = np.log(ps / (1 - ps))
    slope, intercept = 1.0, 0.0
    for _ in range(50):  # Newton-Raphson on the logistic likelihood
        z = intercept + slope * x
        mu = 1.0 / (1.0 + np.exp(-z))
        w = np.clip(mu * (1 - mu), 1e-12, None)
        residual = ys - mu
        design = np.column_stack([np.ones_like(x), x])
        hessian = design.T @ (design * w[:, None])
        gradient = design.T @ residual
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            break
        intercept += step[0]
        slope += step[1]
        if np.max(np.abs(step)) < 1e-10:
            break
    return float(slope), float(intercept)


def paired_bootstrap(
    losses_a: Sequence[float],
    losses_b: Sequence[float],
    draws: int,
    ci: float,
    seed: int,
) -> tuple[float, float, float]:
    """Bootstrap the mean of per-map differences, resampling PAIRS.

    Pairing matters: the same maps are hard for both models, so independent
    resampling would carry the shared variance into the interval and hide
    real differences.
    """
    a = np.asarray(losses_a, dtype=float)
    b = np.asarray(losses_b, dtype=float)
    if a.shape != b.shape:
        raise ValueError(f"paired bootstrap needs equal lengths, got {a.shape} and {b.shape}")
    diff = a - b
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(diff), size=(draws, len(diff)))
    means = diff[indices].mean(axis=1)
    alpha = (1.0 - ci) / 2.0
    lo, hi = np.quantile(means, [alpha, 1.0 - alpha])
    return float(diff.mean()), float(lo), float(hi)


def evaluate_gate(
    elo_losses: Sequence[float], glicko_losses: Sequence[float], config: GateConfig
) -> GateResult:
    """The pre-registered gate. BOTH conditions, per spec II."""
    margin, lo, hi = paired_bootstrap(
        elo_losses, glicko_losses, config.bootstrap_draws, config.bootstrap_ci, config.seed
    )
    reasons = []
    if margin < config.min_margin_nats:
        reasons.append(
            f"margin {margin:.5f} < pre-registered {config.min_margin_nats} nats/map"
        )
    if lo <= 0.0:
        reasons.append(f"bootstrap {config.bootstrap_ci:.0%} CI [{lo:.5f}, {hi:.5f}] includes 0")
    return GateResult(
        margin=margin, ci_low=lo, ci_high=hi, passed=not reasons, reasons=reasons
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_backtest.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check .
git add src/ti26/backtest.py tests/test_backtest.py
git commit -m "feat: rolling backtest, calibration, paired bootstrap, pre-registered gate"
```

---

## Task 7: Fit the duration model from real data

**Files:**
- Create: `src/ti26/duration.py`
- Modify: `config/ti2026_rules.yaml` (provenance for `duration_model`), `docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md` (provenance vocabulary)
- Test: `tests/test_duration.py`

**Interfaces:**
- Consumes: `MapRow` (Task 2), `EloModel.strengths` (Task 4).
- Produces: `DurationFit` frozen dataclass `(log_mean: float, log_sigma: float, gap_coefficient: float, gap_se: float, n: int, material: bool)`; `fit_duration_model(rows: Sequence[MapRow], gaps: Mapping[int, float] | None = None) -> DurationFit`; `sensitivity_sweep(sigmas: Sequence[float]) -> list[float]` returning the placeholder-vs-fitted spread; `MIN_DURATION_SECONDS: int = 600`; `MAX_DURATION_SECONDS: int = 9000`.

**Why this task exists:** spec §XII — the duration resolver is consulted on 4.79 lookups per ranking call in 300/300 simulated tournaments, roughly 30% of the field, and it is currently driven by a log-normal we invented (`log_mean: 7.65`, `log_sigma: 0.25`, provenance `arbitrary`). It is load-bearing, not decorative.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_duration.py
import math

import numpy as np
import pytest

from ti26.data.schema import MapRow
from ti26.duration import (
    MAX_DURATION_SECONDS,
    MIN_DURATION_SECONDS,
    fit_duration_model,
)


def row(match_id, duration, radiant_team_id=10, dire_team_id=20):
    return MapRow(
        match_id=match_id, start_time=100 + match_id, duration=duration, radiant_win=True,
        league_id=1, tier="professional", radiant_team_id=radiant_team_id,
        dire_team_id=dire_team_id, series_id=1, series_type=1, patch="7.41",
        radiant_accounts=(1, 2, 3, 4, 5), dire_accounts=(6, 7, 8, 9, 10),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


def test_recovers_the_parameters_of_a_known_lognormal():
    """The only test that can catch an estimator that is confidently wrong."""
    rng = np.random.default_rng(17)
    durations = rng.lognormal(mean=7.5, sigma=0.30, size=20000)
    rows = [row(i, int(d)) for i, d in enumerate(durations) if 600 < d < 9000]
    fit = fit_duration_model(rows)
    assert fit.log_mean == pytest.approx(7.5, abs=0.02)
    assert fit.log_sigma == pytest.approx(0.30, abs=0.02)
    assert fit.n == len(rows)


def test_implausible_durations_are_excluded():
    """Sub-10-minute results are forfeits and abandons, not games. Spec VI
    says flag and downweight rather than silently keep."""
    rng = np.random.default_rng(19)
    good = [row(i, int(d)) for i, d in enumerate(rng.lognormal(7.5, 0.25, size=5000))
            if MIN_DURATION_SECONDS < d < MAX_DURATION_SECONDS]
    junk = [row(90000 + i, 45) for i in range(500)]
    fit = fit_duration_model(good + junk)
    assert fit.n == len(good), "the 500 junk rows must not enter the fit"
    assert fit.log_mean == pytest.approx(7.5, abs=0.05)


def test_empty_input_raises_rather_than_returning_the_placeholder():
    """Silently falling back to the invented 7.65/0.25 would let a broken
    ingest ship a card steered by a fabricated parameter, which is exactly
    the failure spec XII documents."""
    with pytest.raises(ValueError, match="no usable durations"):
        fit_duration_model([])


def test_gap_coefficient_is_recovered_when_a_real_effect_exists():
    """Spec XII requires the fit be conditioned at minimum on rating gap."""
    rng = np.random.default_rng(23)
    gaps, rows = {}, []
    for i in range(20000):
        gap = float(rng.uniform(0, 2.0))
        # Bigger mismatches end faster: -0.15 log-seconds per unit of gap.
        duration = math.exp(7.6 - 0.15 * gap + rng.normal(0, 0.25))
        if MIN_DURATION_SECONDS < duration < MAX_DURATION_SECONDS:
            gaps[i] = gap
            rows.append(row(i, int(duration)))
    fit = fit_duration_model(rows, gaps=gaps)
    assert fit.gap_coefficient == pytest.approx(-0.15, abs=0.02)
    assert fit.material is True


def test_gap_effect_is_reported_immaterial_when_it_is_noise():
    """A decision rule that always says 'material' is not a decision rule."""
    rng = np.random.default_rng(29)
    gaps, rows = {}, []
    for i in range(20000):
        gaps[i] = float(rng.uniform(0, 2.0))
        duration = math.exp(7.6 + rng.normal(0, 0.25))  # no gap dependence
        if MIN_DURATION_SECONDS < duration < MAX_DURATION_SECONDS:
            rows.append(row(i, int(duration)))
    fit = fit_duration_model(rows, gaps=gaps)
    assert abs(fit.gap_coefficient) < 0.02
    assert fit.material is False


def test_fitted_sigma_differs_from_the_invented_placeholder():
    """If the fit reproduces 0.25 exactly, someone wired the placeholder
    through instead of estimating. Real pro durations are more dispersed."""
    rng = np.random.default_rng(31)
    durations = rng.lognormal(mean=7.55, sigma=0.34, size=15000)
    rows = [row(i, int(d)) for i, d in enumerate(durations)
            if MIN_DURATION_SECONDS < d < MAX_DURATION_SECONDS]
    fit = fit_duration_model(rows)
    assert abs(fit.log_sigma - 0.25) > 0.03
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_duration.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.duration'`

- [ ] **Step 3: Write the implementation**

```python
# src/ti26/duration.py
"""Fit the average-duration tiebreak model from real match durations.

Spec XII: the resolver is consulted on ~30% of ranking instances in every
simulated tournament, and until this task runs it is driven by an invented
log-normal tagged `arbitrary`. That parameter is steering a meaningful share
of simulated standings, so it gets estimated, not guessed.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from ti26.data.schema import MapRow

# Below 10 minutes a pro map is a forfeit or an abandon; above 2.5 hours it is
# a data error. Both are excluded from the fit and counted.
MIN_DURATION_SECONDS = 600
MAX_DURATION_SECONDS = 9000

# A gap effect counts as material when it shifts the conditional mean by at
# least 10% of the residual spread across the observed inter-quartile gap
# range. Below that it cannot move a duration tiebreak often enough to matter.
MATERIALITY_FRACTION = 0.10


@dataclass(frozen=True)
class DurationFit:
    log_mean: float
    log_sigma: float
    gap_coefficient: float
    gap_se: float
    n: int
    material: bool


def fit_duration_model(
    rows: Sequence[MapRow], gaps: Mapping[int, float] | None = None
) -> DurationFit:
    usable = [
        r for r in rows if MIN_DURATION_SECONDS < r.duration < MAX_DURATION_SECONDS
    ]
    if not usable:
        raise ValueError("no usable durations in range; refusing to fall back to a placeholder")

    logs = np.log(np.asarray([r.duration for r in usable], dtype=float))

    if gaps is None:
        return DurationFit(
            log_mean=float(logs.mean()),
            log_sigma=float(logs.std(ddof=1)),
            gap_coefficient=0.0,
            gap_se=float("nan"),
            n=len(usable),
            material=False,
        )

    paired = [(gaps[r.match_id], math.log(r.duration)) for r in usable if r.match_id in gaps]
    if len(paired) < 100:
        return DurationFit(
            log_mean=float(logs.mean()),
            log_sigma=float(logs.std(ddof=1)),
            gap_coefficient=0.0,
            gap_se=float("nan"),
            n=len(usable),
            material=False,
        )

    x = np.asarray([p[0] for p in paired])
    y = np.asarray([p[1] for p in paired])
    design = np.column_stack([np.ones_like(x), x])
    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
    intercept, slope = float(coefficients[0]), float(coefficients[1])

    residuals = y - design @ coefficients
    dof = len(y) - 2
    sigma = float(np.sqrt((residuals**2).sum() / dof))
    covariance = sigma**2 * np.linalg.inv(design.T @ design)
    slope_se = float(np.sqrt(covariance[1, 1]))

    q1, q3 = np.quantile(x, [0.25, 0.75])
    shift = abs(slope) * (q3 - q1)
    material = shift >= MATERIALITY_FRACTION * sigma and abs(slope) > 2 * slope_se

    return DurationFit(
        log_mean=intercept + slope * float(x.mean()),
        log_sigma=sigma,
        gap_coefficient=slope,
        gap_se=slope_se,
        n=len(usable),
        material=bool(material),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_duration.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Add the `empirical` provenance tag to the spec**

The four-tag vocabulary in the spec (`official`, `logically_forced`, `inferred`, `arbitrary`) has no value for "estimated from data", which is what `duration_model` becomes after this task. Edit the block in §XII "Rules provenance tagging" to add a fifth line, immediately after `arbitrary`:

```
empirical         — estimated from observed data; see the fit report for n and CI
```

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/python -m pytest -m "not slow" -q && .venv/bin/ruff check .
git add src/ti26/duration.py tests/test_duration.py docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md
git commit -m "feat: fit the duration tiebreak model from real durations"
```

---

## Task 8: Ingest CLI, D2 runner, gate report, end-to-end verification

**Files:**
- Create: `src/ti26/cli_ingest.py`, `src/ti26/cli_d2.py`
- Modify: `config/ti2026_rules.yaml` (fitted duration values + provenance)
- Test: `tests/test_cli_d2.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7, plus `ti26.montecarlo.category_marginals`, `ti26.optimize.solve_card`, `ti26.rules.load_rules` from D1.
- Produces: `ti26.cli_ingest.main(argv) -> int` writing `data/raw/<sid>/*.json.gz`, `manifest.json`, and `data/processed/d2.sqlite`; `ti26.cli_d2.main(argv) -> int` writing `reports/d2_gate.md`, `reports/backtest_metrics.csv`, `reports/duration_fit.json`, `reports/strengths.csv`.

- [ ] **Step 1: Write the ingest CLI**

```python
# src/ti26/cli_ingest.py
"""Snapshot the explorer, then load the snapshot into the store.

Fetch and load are separate phases on purpose: the snapshot is immutable and
re-loadable, so a schema change never costs another 18 months of API calls.
"""

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ti26.data.opendota import MAP_QUERY, explorer_query, http_transport, month_windows
from ti26.data.schema import normalize_all
from ti26.data.snapshot import read_snapshot, snapshot_id, write_manifest, write_snapshot
from ti26.data.store import insert_rows, open_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest pro maps from OpenDota /explorer")
    parser.add_argument("--months", type=int, default=18)
    parser.add_argument("--raw", default="data/raw")
    parser.add_argument("--store", default="data/processed/d2.sqlite")
    parser.add_argument("--snapshot", default=None, help="reload an existing snapshot id")
    args = parser.parse_args(argv)

    raw_root = Path(args.raw)
    if args.snapshot:
        sid = args.snapshot
        paths = sorted((raw_root / sid).glob("*.json.gz"))
        if not paths:
            raise SystemExit(f"no snapshot chunks under {raw_root / sid}")
    else:
        now = datetime.now(timezone.utc)
        sid = snapshot_id(now)
        start = now - timedelta(days=30 * args.months)
        entries, paths = [], []
        for start_epoch, end_epoch in month_windows(start, now):
            sql = MAP_QUERY.format(start=start_epoch, end=end_epoch)
            rows = explorer_query(sql, http_transport)
            name = datetime.fromtimestamp(start_epoch, timezone.utc).strftime("%Y-%m")
            paths.append(write_snapshot(raw_root, sid, name, rows))
            entries.append(
                {"name": name, "rows": len(rows), "start": start_epoch, "end": end_epoch}
            )
            print(f"{name}: {len(rows)} maps")
        write_manifest(raw_root, sid, entries)

    store_path = Path(args.store)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    conn = open_store(store_path)

    total, tally = 0, {}
    for path in paths:
        rows, chunk_tally = normalize_all(read_snapshot(path))
        total += insert_rows(conn, rows)
        for key, count in chunk_tally.items():
            tally[key] = tally.get(key, 0) + count

    print(f"snapshot {sid}: loaded {total} maps into {store_path}")
    if tally:
        print(f"rejected: {tally}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Write the D2 runner**

```python
# src/ti26/cli_d2.py
"""Fit ratings, run the rolling backtest, report the pre-registered verdict."""

import argparse
import csv
import json
from pathlib import Path

from ti26.backtest import (
    accuracy,
    brier,
    calibration,
    evaluate_gate,
    log_loss,
    per_map_log_loss,
    rolling_folds,
    run_model,
)
from ti26.data.store import load_rows, open_store
from ti26.duration import fit_duration_model
from ti26.ratings import load_gate_config
from ti26.ratings.elo import EloModel
from ti26.ratings.glicko import GlickoModel
from ti26.ratings.simple import ConstantModel, EwmaModel
from ti26.roster import RosterIndex


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D2: fit ratings and evaluate the gate")
    parser.add_argument("--store", default="data/processed/d2.sqlite")
    parser.add_argument("--gate-config", default="config/d2_gate.yaml")
    parser.add_argument("--min-train", type=int, default=500)
    parser.add_argument("--out", default="reports")
    args = parser.parse_args(argv)

    config = load_gate_config(args.gate_config)
    rows = load_rows(open_store(args.store))
    if not rows:
        raise SystemExit(f"{args.store} is empty; run `python -m ti26.cli_ingest` first")

    folds = rolling_folds(rows, min_train=args.min_train)
    if not folds:
        raise SystemExit(f"no tournament had {args.min_train}+ prior maps; lower --min-train")

    models = {
        "constant": lambda: ConstantModel(),
        "ewma": lambda: EwmaModel(half_life_maps=config.ewma_half_life_maps),
        "elo": lambda: EloModel(k=config.elo_k),
        "glicko": lambda: GlickoModel(tau=config.glicko_tau, roster_index=RosterIndex()),
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    predictions, metrics = {}, {}
    for name, factory in models.items():
        predictions[name] = run_model(rows, factory, folds)
        slope, intercept = calibration(predictions[name], rows)
        metrics[name] = {
            "log_loss": log_loss(predictions[name], rows),
            "brier": brier(predictions[name], rows),
            "accuracy": accuracy(predictions[name], rows),
            "calibration_slope": slope,
            "calibration_intercept": intercept,
            "n_predictions": len(predictions[name]),
        }

    with (out / "backtest_metrics.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["model", *sorted(next(iter(metrics.values())))])
        for name in models:
            writer.writerow([name, *(metrics[name][k] for k in sorted(metrics[name]))])

    result = evaluate_gate(
        per_map_log_loss(predictions["elo"], rows),
        per_map_log_loss(predictions["glicko"], rows),
        config,
    )

    duration_fit = fit_duration_model(rows)
    (out / "duration_fit.json").write_text(
        json.dumps(
            {
                "log_mean": duration_fit.log_mean,
                "log_sigma": duration_fit.log_sigma,
                "gap_coefficient": duration_fit.gap_coefficient,
                "n": duration_fit.n,
                "placeholder_log_mean": 7.65,
                "placeholder_log_sigma": 0.25,
                "note": "spec XII: this parameter steers ~30% of every ranking",
            },
            indent=2,
        )
        + "\n"
    )

    verdict = "PASS" if result.passed else "FAIL"
    lines = [
        "# D2 gate result",
        "",
        f"**Verdict: {verdict}**",
        "",
        "Pre-registered 2026-08-02 in `config/d2_gate.yaml`, before any backtest ran:",
        "",
        f"- required margin: `mean(LL_elo - LL_glicko) >= {config.min_margin_nats}` nats/map",
        f"- required significance: paired bootstrap {config.bootstrap_ci:.0%} CI excludes 0",
        "",
        f"Observed margin: **{result.margin:.5f}** nats/map, "
        f"CI [{result.ci_low:.5f}, {result.ci_high:.5f}]",
        "",
        f"Folds: {len(folds)} tournaments, {sum(f.n_test for f in folds)} out-of-sample maps.",
        "",
        "## Backtest metrics",
        "",
        "| model | log loss | Brier | accuracy | cal. slope | cal. intercept |",
        "|---|---|---|---|---|---|",
    ]
    for name in models:
        m = metrics[name]
        lines.append(
            f"| {name} | {m['log_loss']:.5f} | {m['brier']:.5f} | {m['accuracy']:.4f} | "
            f"{m['calibration_slope']:.3f} | {m['calibration_intercept']:.3f} |"
        )
    lines += [
        "",
        "Accuracy is reported but never used for selection (spec II): it is not a proper "
        "scoring rule.",
        "",
        "## Consequence",
        "",
        (
            "Proceed to D3 dynamic Bradley-Terry development."
            if result.passed
            else "**Do not proceed to D3.** Ship the public-rating fallback (spec X, rung 3). "
            "Reasons: " + "; ".join(result.reasons)
        ),
        "",
        f"## Duration model (spec XII)",
        "",
        f"Fitted from {duration_fit.n} real map durations: "
        f"`log_mean={duration_fit.log_mean:.4f}`, `log_sigma={duration_fit.log_sigma:.4f}` "
        f"(placeholder was 7.65 / 0.25, provenance `arbitrary`).",
    ]
    (out / "d2_gate.md").write_text("\n".join(lines) + "\n")

    print(f"gate: {verdict} (margin {result.margin:.5f}, CI [{result.ci_low:.5f}, "
          f"{result.ci_high:.5f}])")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Write the end-to-end test**

```python
# tests/test_cli_d2.py
import csv
import json
from pathlib import Path

import pytest

from ti26.cli_d2 import main as d2_main
from ti26.data.schema import MapRow
from ti26.data.store import insert_rows, open_store

WEEK = 604800


def row(match_id, start_time, league_id, radiant, dire, radiant_win, duration=2000):
    return MapRow(
        match_id=match_id, start_time=start_time, duration=duration,
        radiant_win=radiant_win, league_id=league_id, tier="professional",
        radiant_team_id=hash(tuple(radiant)) % 1000, dire_team_id=hash(tuple(dire)) % 1000,
        series_id=match_id // 3, series_type=1, patch="7.41",
        radiant_accounts=tuple(radiant), dire_accounts=tuple(dire),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


def seeded_store(path, n_teams=16, n_maps=1200):
    """Deterministic ladder: lower-indexed rosters are genuinely stronger."""
    import random

    rng = random.Random(4)
    rosters = [[t * 5 + p for p in range(5)] for t in range(n_teams)]
    strength = {t: (n_teams - t) * 0.2 for t in range(n_teams)}
    rows = []
    for i in range(n_maps):
        a, b = rng.sample(range(n_teams), 2)
        p = 1 / (1 + pow(2.718281828, -(strength[a] - strength[b])))
        league = 1 if i < n_maps - 200 else 2
        rows.append(
            row(i, i * 3600, league, rosters[a], rosters[b], rng.random() < p,
                duration=int(rng.lognormvariate(7.55, 0.33)))
        )
    conn = open_store(path)
    insert_rows(conn, rows)
    return conn


def test_end_to_end_produces_a_gate_report_and_metrics(tmp_path):
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    assert d2_main(["--store", str(store), "--out", str(out), "--min-train", "200"]) == 0

    report = (out / "d2_gate.md").read_text()
    assert "**Verdict:" in report
    assert "0.003" in report, "the pre-registered margin must appear in the report"

    with (out / "backtest_metrics.csv").open() as fh:
        metrics = {r["model"]: r for r in csv.DictReader(fh)}
    assert set(metrics) == {"constant", "ewma", "elo", "glicko"}
    assert float(metrics["constant"]["log_loss"]) == pytest.approx(0.6931, abs=1e-3)


def test_rating_models_beat_the_constant_floor_on_separable_data(tmp_path):
    """If Elo cannot beat 50/50 on a deterministic ladder, the harness is
    broken -- this is the sanity check that the wiring works at all, and it
    is distinct from the gate, which compares Elo against Glicko."""
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    d2_main(["--store", str(store), "--out", str(out), "--min-train", "200"])
    with (out / "backtest_metrics.csv").open() as fh:
        metrics = {r["model"]: float(r["log_loss"]) for r in csv.DictReader(fh)}
    assert metrics["elo"] < metrics["constant"]
    assert metrics["glicko"] < metrics["constant"]


def test_duration_fit_is_written_and_differs_from_the_placeholder(tmp_path):
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    d2_main(["--store", str(store), "--out", str(out), "--min-train", "200"])
    fit = json.loads((out / "duration_fit.json").read_text())
    assert fit["n"] > 500
    assert abs(fit["log_sigma"] - 0.25) > 0.02, "fitted, not the placeholder"


def test_empty_store_fails_loudly(tmp_path):
    store = tmp_path / "empty.sqlite"
    open_store(store)
    with pytest.raises(SystemExit, match="empty"):
        d2_main(["--store", str(store), "--out", str(tmp_path / "reports")])


def test_reported_verdict_agrees_with_the_reported_numbers(tmp_path):
    """A report that says PASS regardless is worse than no report.

    Asserting a specific verdict on synthetic data would be brittle -- which
    model wins on a toy ladder is not something this plan should predict.
    What must ALWAYS hold is internal consistency: the verdict printed has to
    follow from the margin and CI printed beside it, under the two
    pre-registered conditions. A hardcoded verdict fails this on some run.
    """
    import re

    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    d2_main(["--store", str(store), "--out", str(out), "--min-train", "200"])
    report = (out / "d2_gate.md").read_text()

    verdict = re.search(r"\*\*Verdict: (PASS|FAIL)\*\*", report).group(1)
    margin = float(re.search(r"Observed margin: \*\*(-?[\d.]+)\*\*", report).group(1))
    ci_low = float(re.search(r"CI \[(-?[\d.]+),", report).group(1))

    expected = "PASS" if (margin >= 0.003 and ci_low > 0.0) else "FAIL"
    assert verdict == expected, (
        f"report says {verdict} but margin={margin} ci_low={ci_low} implies {expected}"
    )
    if verdict == "FAIL":
        assert "Do not proceed to D3" in report
    else:
        assert "Proceed to D3" in report
```

- [ ] **Step 4: Run the test to verify it fails, then passes**

Run: `.venv/bin/python -m pytest tests/test_cli_d2.py -v`
Expected first: FAIL with `ModuleNotFoundError: No module named 'ti26.cli_d2'`. After Steps 1–2 are in place: PASS (5 tests).

- [ ] **Step 5: Run the real ingest**

```bash
.venv/bin/python -m ti26.cli_ingest --months 18
```
Expected: ~19 monthly lines totalling ≈41,600 maps, an immutable snapshot under `data/raw/<sid>/`, and `data/processed/d2.sqlite`. Record the snapshot id and the rejection tally in the ledger. If the row count is below 35,000, stop and report rather than proceeding — the spec's §III figures were measured on 2026-08-02 and a large shortfall means the query or the window is wrong.

- [ ] **Step 6: Run the real D2 evaluation**

```bash
.venv/bin/python -m ti26.cli_d2
```
Expected: `reports/d2_gate.md` with a verdict, `reports/backtest_metrics.csv`, `reports/duration_fit.json`.

**Report the verdict as it comes out.** A FAIL is a legitimate, pre-registered outcome meaning "ship the public-rating fallback and stop"; it is not a defect to be tuned away. Do not adjust `min_margin_nats`, `elo_k`, `glicko_tau`, or `--min-train` in response to seeing the result.

- [ ] **Step 7: Write the fitted duration values into the rules config**

Replace the `duration_model` block in `config/ti2026_rules.yaml` with the values from `reports/duration_fit.json`, and change its provenance from `arbitrary` to `empirical`:

```yaml
duration_model:
  log_mean: <fitted value from reports/duration_fit.json>
  log_sigma: <fitted value from reports/duration_fit.json>
  fitted_from_n_maps: <n from reports/duration_fit.json>
```

and in the `provenance` block:

```yaml
  duration_model: empirical   # fitted in D2; see reports/duration_fit.json
```

- [ ] **Step 8: Confirm the D1 suite still passes with the fitted values**

Run: `.venv/bin/python -m pytest -q`
Expected: all 427 D1 tests plus the new D2 tests pass. The D1 tests must not depend on the placeholder duration constants; if any fails, it was asserting against `7.65`/`0.25` rather than against behaviour, and that is a genuine defect to fix in the test, not a reason to revert the fitted values.

- [ ] **Step 9: Generate a card from fitted strengths**

```bash
.venv/bin/python -m ti26.cli --n-sims 250000 --seed 1
```
Expected: `reports/category_probabilities.csv` and `reports/recommended_card.json`. This closes the spec §II **engineering gate**: a legal card produced end-to-end with the leakage assertion passing.

- [ ] **Step 10: Lint and commit**

```bash
.venv/bin/ruff check .
git add src/ti26/cli_ingest.py src/ti26/cli_d2.py tests/test_cli_d2.py config/ti2026_rules.yaml
git commit -m "feat: ingest CLI, D2 gate runner, fitted duration model"
```

---

## Verification Criteria

D2 is complete when all of the following hold, each with named evidence:

| Check | Evidence |
|---|---|
| Full suite green | `.venv/bin/python -m pytest -q` reports 0 failures across D1 + D2 |
| Lint clean | `.venv/bin/ruff check .` reports `All checks passed!` |
| No new dependencies | `pyproject.toml` dependency list unchanged from D1 |
| One network seam | `grep -rn "urllib.request\|http" src/ti26/ --include=*.py` matches only `data/opendota.py` |
| No gate literal in source | `grep -rn "0\.003" src/` returns nothing |
| Leakage assertion active | `run_model` calls `assert_no_leakage` once per fold; `tests/test_store.py` proves it raises |
| Ingest completed | `data/raw/<sid>/manifest.json` exists with `total_rows` ≥ 35,000 |
| Gate reported honestly | `reports/d2_gate.md` states PASS or FAIL with the observed margin and CI, and no config value was changed after the run |
| Duration model fitted | `config/ti2026_rules.yaml` carries `duration_model: empirical` and values from `reports/duration_fit.json` |
| Engineering gate | `reports/recommended_card.json` exists and assigns 16 teams to the derived capacities |

**Known limitation to carry forward, not to fix here:** the continuity weight in `GlickoModel._inherit` is fixed at 0.8 rather than computed from actual player overlap, because `RosterIndex.predecessor` returns an id, not an overlap fraction. This is honest for the common single-substitution case and wrong for a two- or three-player change. Record it in the ledger; D3 either threads the overlap through or states why 0.8 is adequate.
