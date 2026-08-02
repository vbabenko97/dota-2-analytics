# D2: Ingestion, Roster Canonicalization, Ratings and Rolling Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace D1's synthetic strength vector with ratings fitted from 18 months of real pro maps, and decide — against a gate pre-registered before any backtest ran — whether custom modelling is justified at all.

**Architecture:** Ingestion is one narrow seam: `explorer_query` is the only function in `src/ti26/` that touches the network, and it takes an injectable transport so every other test runs offline. Raw responses land in immutable timestamped snapshots and are never re-fetched; a normalization layer converts them to `MapRow`, and a stdlib `sqlite3` store answers `as_of`-bounded queries. Ratings are pure functions over an ordered map sequence keyed by `roster_version_id`, not by organization, so a re-branded org keeps its history and a new roster does not inherit one it never earned. The backtest harness replays tournaments at rolling cutoffs and is the only component permitted to declare the gate result.

**Tech Stack:** Python as declared by `requires-python` in `pyproject.toml:4` (currently `>=3.12`) — do not hard-code a version anywhere; `uv`, `pytest`, `numpy`, `scipy`, `PyYAML`, `ruff`, and the standard library (`sqlite3`, `urllib.request`, `gzip`, `json`, `hashlib`). **No new third-party dependencies.**

## Global Constraints

- **One network seam.** `src/ti26/data/opendota.py::explorer_query` is the only function in `src/ti26/` permitted to perform I/O against a remote host, and it accepts a `transport` callable so tests never hit the network. A network call anywhere else under `src/ti26/` is a plan violation.
- **Raw snapshots are immutable, enforced by the filesystem.** Snapshot chunks and manifests are created with exclusive-create mode (`"xb"`), never `exists()`-then-write. Re-running ingestion creates a new snapshot directory. Code that opens a path under `data/raw/` for writing without `x` mode is a plan violation.
- **Test the production call path, not a hand-assembled one.** If a test wires a collaborator that the real runner does not wire, the test proves nothing about the shipped system. Every rating model must be driven through `run_model`, and `run_model` must construct exactly what `cli_d2` constructs. A test that calls `RosterIndex.observe` directly while the runner never does is a plan violation, not a passing test. This is the defect pattern that dominated D1.
- **The gate's bootstrap is clustered, never iid over maps.** Maps within a series share teams, day, patch and momentum; iid resampling understates the interval and lets the gate pass on noise. Resample tournaments (falling back to two-stage tournament→series when tournaments are few), and align the two models' losses **by `match_id`**, never by position.
- **Predictions carry their own provenance.** Every `Prediction` records `fold_id`, `league_id`, `series_id`, `match_id`, `rated` and `reason`, so any metric can be re-derived, re-grouped, or audited without re-running the fit.
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
| `config/ti2026_teams.yaml` | The 16 Swiss-stage teams and their OpenDota `team_id`s. Populated from real data in Task 8, never fabricated |
| `src/ti26/teams.py` | Resolve the 16 configured teams to current `roster_version_id`s and fitted strengths |
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


def test_rewriting_a_manifest_raises(tmp_path):
    """The manifest is the index of what was fetched; overwriting it can make
    a snapshot claim contents it does not have."""
    entries = [{"name": "2025-02", "rows": 1, "start": 0, "end": 1}]
    write_manifest(tmp_path, "20260803T090501Z", entries)
    with pytest.raises(SnapshotExistsError):
        write_manifest(tmp_path, "20260803T090501Z", entries)


def test_the_original_bytes_survive_a_failed_overwrite(tmp_path):
    """An exists()-then-write implementation can truncate before it raises.

    This asserts the ORIGINAL content is intact after the failure, which is
    the property that actually matters and which a bare `pytest.raises`
    check would not catch.
    """
    write_snapshot(tmp_path, "20260803T090501Z", "2025-02", [{"original": True}])
    with pytest.raises(SnapshotExistsError):
        write_snapshot(tmp_path, "20260803T090501Z", "2025-02", [{"clobbered": True}])
    path = tmp_path / "20260803T090501Z" / "2025-02.json.gz"
    assert read_snapshot(path) == [{"original": True}]


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


def _exclusive_write(path: Path, payload: bytes) -> None:
    """Create-or-fail. `exists()` then write is a race, not a guarantee.

    Two ingest runs started in the same second share a snapshot id; with a
    check-then-write they would both pass the check and one would silently
    clobber the other. Exclusive create pushes the decision into the kernel.
    """
    try:
        with open(path, "xb") as fh:
            fh.write(payload)
    except FileExistsError as exc:
        raise SnapshotExistsError(
            f"{path} already exists; snapshots are immutable — use a new snapshot id"
        ) from exc


def write_snapshot(root: Path, sid: str, name: str, rows: list[dict]) -> Path:
    directory = root / sid
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json.gz"
    _exclusive_write(path, gzip.compress(json.dumps(rows).encode()))
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
    _exclusive_write(path, (json.dumps(payload, indent=2) + "\n").encode())
    return path
```

- [ ] **Step 8: Run the full task suite and lint**

Run: `.venv/bin/python -m pytest tests/test_opendota.py tests/test_snapshot.py -v && .venv/bin/ruff check .`
Expected: PASS (12 tests), lint clean

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
- Produces: `MapRow` frozen dataclass with fields `match_id: int, start_time: int, duration: int, radiant_win: bool, league_id: int | None, tier: str | None, radiant_team_id: int | None, dire_team_id: int | None, series_id: int | None, series_type: int | None, patch: str | None, radiant_accounts: tuple[int, ...], dire_accounts: tuple[int, ...], radiant_heroes: tuple[int, ...], dire_heroes: tuple[int, ...], has_null_team: bool, has_bad_roster: bool` and property `best_of: int`; `RosterSlotError(ValueError)`; `normalize_row(raw: dict) -> MapRow`; `normalize_all(raw: list[dict]) -> tuple[list[MapRow], dict[str, int]]` returning rows plus a counted rejection tally; `LeakageError(AssertionError)`; `ConflictingRowError(ValueError)`; `assert_no_leakage(rows: Sequence[MapRow], as_of: int) -> None`; `open_store(path: str | Path) -> sqlite3.Connection`; `insert_rows(conn, rows: Sequence[MapRow]) -> int` returning the count of **newly inserted** rows (exact duplicates are tolerated and not counted; conflicting duplicates raise); `load_rows(conn, as_of: int | None = None, since: int | None = None) -> list[MapRow]`.

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
from ti26.data.store import (
    ConflictingRowError,
    LeakageError,
    assert_no_leakage,
    insert_rows,
    load_rows,
    open_store,
)


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


def test_reinserting_an_identical_row_is_a_no_op(tmp_path):
    """Snapshots overlap at month edges on re-runs; a duplicated map would
    be rated twice and inflate a team's evidence for free."""
    conn = open_store(tmp_path / "d2.sqlite")
    insert_rows(conn, [row(1, 1000)])
    insert_rows(conn, [row(1, 1000), row(2, 2000)])
    assert [r.match_id for r in load_rows(conn)] == [1, 2]


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
    placeholders = ",".join("?" * len(_COLUMNS))
    inserted = 0
    with conn:  # rolls back the whole batch if anything raises
        for record in payload:
            existing = conn.execute(
                f"select {','.join(_COLUMNS)} from maps where match_id = ?", (record[0],)
            ).fetchone()
            if existing is None:
                conn.execute(
                    f"insert into maps ({','.join(_COLUMNS)}) values ({placeholders})", record
                )
                inserted += 1
            elif tuple(existing) != record:
                differing = [
                    _COLUMNS[i] for i in range(len(_COLUMNS)) if existing[i] != record[i]
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
Expected: PASS (19 tests), lint clean

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
- Produces: `roster_version_id(accounts: Iterable[int]) -> str` (16 hex chars); `load_aliases(path) -> dict[int, int]` mapping historical `team_id` → canonical `team_id`; `canonical_team_id(team_id: int | None, aliases: dict[int, int]) -> int | None`; `continuity(previous: Iterable[int], current: Iterable[int]) -> float` returning shared/5; `RosterIndex` with `.observe(row: MapRow) -> tuple[str, str]` returning `(radiant_rvid, dire_rvid)`, `.predecessor(rvid: str) -> str | None`, `.accounts(rvid: str) -> tuple[int, ...]`, `.continuity_with_predecessor(rvid: str) -> float` (measured shared-player fraction; 0.0 with no history), and `.history(rvid: str) -> int` (number of maps observed for that roster).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_roster.py
import pytest

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


def test_continuity_with_predecessor_measures_actual_overlap():
    """The inheritance weight is measured, not assumed.

    A one-player swap and a three-player rebuild must NOT receive the same
    weight; a fixed constant cannot tell them apart, which is precisely why
    the index stores account sets.
    """
    index = RosterIndex()
    index.observe(row(1, 100, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]))
    one_swap, _ = index.observe(row(2, 200, [1, 2, 3, 4, 91], [6, 7, 8, 9, 10]))
    assert index.continuity_with_predecessor(one_swap) == pytest.approx(0.8)

    other = RosterIndex()
    other.observe(row(1, 100, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]))
    rebuild, _ = other.observe(row(2, 200, [1, 2, 91, 92, 93], [6, 7, 8, 9, 10]))
    assert other.continuity_with_predecessor(rebuild) == pytest.approx(0.4)


def test_continuity_is_zero_for_a_roster_with_no_history():
    index = RosterIndex()
    first, _ = index.observe(row(1, 100, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]))
    assert index.continuity_with_predecessor(first) == 0.0


def test_aliases_chain_history_across_a_rebrand():
    """The alias table is inert unless observe() consults it. This test fails
    if `canonical_team_id` is dropped from the observe path."""
    index = RosterIndex(aliases={77: 10})
    index.observe(row(1, 100, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10], r_team=10))
    rebranded, _ = index.observe(row(2, 200, [1, 2, 3, 4, 91], [6, 7, 8, 9, 10], r_team=77))
    assert index.predecessor(rebranded) == roster_version_id([1, 2, 3, 4, 5])
    assert index.continuity_with_predecessor(rebranded) == pytest.approx(0.8)
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
    """Tracks which roster each canonical team most recently fielded.

    Stores the account set per roster, not just the id, so continuity can be
    computed from actual player overlap rather than assumed.
    """

    def __init__(self, aliases: dict[int, int] | None = None) -> None:
        self._aliases = aliases or {}
        self._latest_by_team: dict[int, str] = {}
        self._predecessor: dict[str, str | None] = {}
        self._accounts: dict[str, tuple[int, ...]] = {}
        self._maps: dict[str, int] = {}

    def observe(self, row: MapRow, count: bool = True) -> tuple[str, str]:
        """Register both rosters. `count=False` registers without tallying maps.

        Prediction needs a roster's predecessor resolved before the roster has
        played anything, so `predict` registers with `count=False`. Only team
        ids and player ids are read — never the outcome — so registering a
        future row cannot leak.
        """
        out = []
        for team_id, accounts in (
            (row.radiant_team_id, row.radiant_accounts),
            (row.dire_team_id, row.dire_accounts),
        ):
            rvid = roster_version_id(accounts)
            self._accounts.setdefault(rvid, tuple(sorted(accounts)))
            if count:
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

    def accounts(self, rvid: str) -> tuple[int, ...]:
        return self._accounts.get(rvid, ())

    def continuity_with_predecessor(self, rvid: str) -> float:
        """Measured shared-player fraction, or 0.0 when there is no history.

        This replaces a fixed inheritance weight. A fixed weight is right for
        a single substitution and badly wrong for a three-player change, and
        nothing in the id alone distinguishes the two cases.
        """
        previous = self.predecessor(rvid)
        if previous is None:
            return 0.0
        return continuity(self._accounts.get(previous, ()), self._accounts.get(rvid, ()))

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

**`PYTHONPATH` does not work here.** `pyproject.toml:18` sets `pythonpath = ["src"]`, and pytest *prepends* that to `sys.path`, so the real tracked `src/` wins over any `PYTHONPATH` entry and you test unmutated code while watching a green suite. Override the ini setting itself with `-o pythonpath=...`.

Run, copying to a scratch tree and mutating only the copy:

```bash
rm -rf /tmp/mut && cp -r src /tmp/mut
sed -i '' 's/sorted(accounts)/accounts/' /tmp/mut/ti26/roster.py
.venv/bin/python -m pytest tests/test_roster.py -o pythonpath=/tmp/mut -p no:cacheprovider -v
```

Expected: `test_roster_id_is_order_independent` FAILS.

Confirm the override actually took effect before trusting the result — if every test still passes, you are running the real source and the mutation proved nothing:

```bash
.venv/bin/python -m pytest tests/test_roster.py -o pythonpath=/tmp/mut \
  --collect-only -q 2>/dev/null | head -1
.venv/bin/python -c "import ti26.roster, sys; print(ti26.roster.__file__)"  # sanity: real path
```

Then clean up and verify nothing tracked was touched — a prior build left a mutation marker in committed source this way:

```bash
rm -rf /tmp/mut
git status --short   # must be empty
```

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
    """One out-of-sample forecast, carrying enough provenance to be re-grouped.

    `series_id` is what the clustered bootstrap resamples on and `fold_id`
    is what fold-integrity assertions check, so neither is optional.
    """

    fold_id: int
    match_id: int
    start_time: int
    league_id: int | None
    series_id: int | None
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
- Produces: `GlickoRating` frozen dataclass `(rating: float, rd: float, volatility: float)`; `expected_score(player, opponent) -> float`; `update_rating(player, results, tau) -> GlickoRating`; `GlickoModel(tau: float = 0.5, initial_rating: float = 1500.0, initial_rd: float = 350.0, initial_volatility: float = 0.06, period_seconds: int = 604800, roster_index: RosterIndex | None = None)` with `.rating_of(rvid, at_period: int | None = None) -> GlickoRating`, `.predict(row) -> float`, `.update(row) -> None`, `.flush() -> None`, `.strengths() -> dict[str, float]`, `.rating_deviations() -> dict[str, float]`, `.prior_driven(min_maps: int = 10) -> list[str]`, `.activity_report() -> list[dict]`.

**Three notes for the implementer:**

1. **Rating periods, not matches.** `update` accumulates into the current integer period and flushes when a row's `start_time` crosses a boundary; `flush` forces the pending period through.
2. **Idle time inflates RD.** A roster that plays nothing for `k` periods has its deviation grown to `sqrt(phi² + k·σ²)`, capped at `initial_rd`. This is lazy — computed in `rating_of` from `at_period`, not by sweeping every roster every period.
3. **The model owns the `RosterIndex` and calls `observe` itself** — `update` with counting, `predict` with `count=False`. Do not make the caller do it. A collaborator that only tests wire is a collaborator that is not in production.

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


def test_new_roster_inherits_without_the_test_wiring_the_index_by_hand():
    """Spec III: without continuity blending a re-branded org looks brand new.

    The model owns the index and calls `observe` itself. If a future change
    moves observation back out to the caller, this test fails -- which is the
    point: a test that wires collaborators the runner does not wire proves
    nothing about the shipped system.
    """
    index = RosterIndex()
    model = GlickoModel(roster_index=index, period_seconds=WEEK)
    for week in range(12):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.flush()

    swapped = [1, 2, 3, 4, 99]
    model.predict(row(99, 12 * WEEK, swapped, B))  # registers the new roster
    inherited = model.rating_of(roster_version_id(swapped))
    assert inherited.rating > 1500.0, "4/5 continuity carries most of the history"
    assert inherited.rd >= model.rating_of(roster_version_id(A)).rd, (
        "but the new roster is no more certain than the one that earned the rating"
    )


def test_inheritance_weight_tracks_measured_overlap():
    """A one-player swap must inherit MORE than a three-player rebuild.

    A fixed weight passes any single-scenario test; only comparing two
    different overlaps can catch it.
    """
    def build(new_roster):
        index = RosterIndex()
        model = GlickoModel(roster_index=index, period_seconds=WEEK)
        for week in range(12):
            model.update(row(week, week * WEEK, A, B, radiant_win=True))
        model.flush()
        model.predict(row(99, 12 * WEEK, new_roster, B))
        return model.rating_of(roster_version_id(new_roster)).rating

    one_swap = build([1, 2, 3, 4, 99])
    rebuild = build([1, 2, 97, 98, 99])
    assert one_swap > rebuild > 1500.0


def test_a_roster_with_no_shared_players_gets_the_global_prior():
    index = RosterIndex()
    model = GlickoModel(roster_index=index, period_seconds=WEEK)
    for week in range(12):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.flush()
    fresh = [91, 92, 93, 94, 95]
    model.predict(row(99, 12 * WEEK, fresh, B))
    assert model.rating_of(roster_version_id(fresh)).rating == pytest.approx(1500.0)


def test_idle_rosters_lose_certainty_every_empty_period():
    """Spec III measured recent volume collapsing. A team last seen months
    before TI must NOT arrive carrying a tight RD -- that error lands exactly
    in the tails where the 4-0 and 0-4 slots live.
    """
    model = GlickoModel(period_seconds=WEEK)
    for week in range(12):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.flush()
    active_rd = model.rating_of(roster_version_id(A)).rd

    after_10 = model.rating_of(roster_version_id(A), at_period=22).rd
    after_40 = model.rating_of(roster_version_id(A), at_period=52).rd
    assert after_10 > active_rd
    assert after_40 > after_10, "RD must keep growing across MULTIPLE idle periods"


def test_idle_inflation_never_exceeds_the_never_seen_prior():
    """Otherwise a long-idle roster becomes more uncertain than one that has
    never played, which is incoherent."""
    model = GlickoModel(period_seconds=WEEK, initial_rd=350.0)
    for week in range(12):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.flush()
    assert model.rating_of(roster_version_id(A), at_period=100_000).rd <= 350.0


def test_idle_inflation_does_not_move_the_point_rating():
    """Uncertainty grows; the estimate itself does not drift."""
    model = GlickoModel(period_seconds=WEEK)
    for week in range(12):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.flush()
    before = model.rating_of(roster_version_id(A)).rating
    assert model.rating_of(roster_version_id(A), at_period=60).rating == pytest.approx(before)


def test_a_long_idle_favourite_is_predicted_less_confidently():
    """The end-to-end consequence of inflation, through `predict` rather than
    through internals -- this is what actually reaches the card."""
    model = GlickoModel(period_seconds=WEEK)
    for week in range(12):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.flush()
    fresh = model.predict(row(500, 12 * WEEK, A, B))
    model.update(row(501, 60 * WEEK, C, [21, 22, 23, 24, 25], radiant_win=True))
    model.flush()
    stale = model.predict(row(502, 60 * WEEK, A, B))
    assert 0.5 < stale < fresh, "idle time pulls the forecast back toward even"


def test_the_two_expected_score_forms_are_deliberately_different():
    """Glickman specifies opponent-only RD for the UPDATE step and combined
    RD for outcome PREDICTION. Both are correct in their place. This pins the
    distinction so neither gets 'simplified' into the other.
    """
    from ti26.ratings.glicko import GlickoRating, _e, expected_score

    player = GlickoRating(1700.0, 350.0, 0.06)   # strong but very uncertain
    opponent = GlickoRating(1500.0, 30.0, 0.06)  # average and well known

    combined = expected_score(player, opponent)
    opponent_only = _e(
        (player.rating - 1500.0) / 173.7178,
        (opponent.rating - 1500.0) / 173.7178,
        opponent.rd / 173.7178,
    )
    assert combined < opponent_only, (
        "the prediction form must discount for the PLAYER's own uncertainty; "
        "the update form deliberately does not"
    )


def test_activity_report_gives_maps_per_roster_per_period():
    model = GlickoModel(period_seconds=WEEK)
    for week in range(3):
        for i in range(2):
            model.update(row(week * 10 + i, week * WEEK + i, A, B, radiant_win=True))
    model.flush()
    report = {r["roster_version_id"]: r for r in model.activity_report()}
    entry = report[roster_version_id(A)]
    assert entry["total_maps"] == 6
    assert entry["active_periods"] == 3
    assert entry["maps_by_period"] == {0: 2, 1: 2, 2: 2}


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
    """Win probability for FORECASTING, accounting for BOTH rating deviations.

    Glickman specifies two different expected-score forms and they are not
    interchangeable. Do not "simplify" one into the other:

    * `_e(mu, mu_j, phi_j)` above uses the OPPONENT's deviation only. That is
      the Glicko-2 update step, and it is what `update_rating` calls.
    * This function uses the COMBINED `sqrt(phi_a^2 + phi_b^2)`. That is the
      outcome-prediction form, and it is what a log-loss backtest needs:
      uncertainty about EITHER side must flatten the forecast toward 0.5.

    Using the opponent-only form here would let a roster we know nothing about
    still receive an extreme prediction, deleting the exact property that makes
    Glicko worth preferring to Elo (spec V).
    """
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
    """Glicko-2 over integer rating periods, with idle-time RD inflation.

    Two things distinguish this from a naive per-match implementation, and
    both matter given the measured collapse in recent match volume (spec III):

    1. A roster that stops playing gets LESS certain, not frozen. Idle periods
       inflate RD by `sqrt(phi^2 + k*sigma^2)`. Without this a team last seen
       in March 2026 would arrive at TI carrying a March-tight RD, and the
       error lands squarely in the tails where the 4-0 and 0-4 slots live.
    2. Inheritance is weighted by MEASURED player overlap, not a constant.
    """

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
        self._period_seconds = period_seconds
        self._index = roster_index
        self._ratings: dict[str, GlickoRating] = {}
        self._last_period: dict[str, int] = {}
        self._maps: dict[str, int] = {}
        self._maps_by_period: dict[int, dict[str, int]] = {}
        self._pending: dict[str, list[tuple[GlickoRating, float]]] = {}
        self._epoch: int | None = None
        self._current_period: int = 0
        self.skipped: dict[str, int] = {}

    def _period_of(self, start_time: int) -> int:
        if self._epoch is None:
            self._epoch = start_time
        return (start_time - self._epoch) // self._period_seconds

    def _inflate(self, rating: GlickoRating, periods: int) -> GlickoRating:
        """Idle-period RD growth, capped at the prior's uncertainty.

        Uncapped inflation would eventually make a long-idle roster MORE
        uncertain than one never seen at all, which is incoherent.
        """
        if periods <= 0:
            return rating
        phi = rating.rd / SCALE
        phi_star = math.sqrt(phi * phi + periods * rating.volatility**2)
        return GlickoRating(
            rating.rating, min(phi_star * SCALE, self._initial.rd), rating.volatility
        )

    def rating_of(self, rvid: str, at_period: int | None = None) -> GlickoRating:
        period = self._current_period if at_period is None else at_period
        if rvid not in self._ratings:
            return self._inherit(rvid, period)
        idle = period - self._last_period.get(rvid, period)
        return self._inflate(self._ratings[rvid], idle)

    def _inherit(self, rvid: str, period: int) -> GlickoRating:
        """Continuity-weighted initialization (spec III), overlap-measured."""
        if self._index is None:
            return self._initial
        predecessor = self._index.predecessor(rvid)
        if predecessor is None or predecessor not in self._ratings:
            return self._initial
        weight = self._index.continuity_with_predecessor(rvid)
        if weight <= 0.0:
            return self._initial
        prior = self.rating_of(predecessor, at_period=period)
        rating = weight * prior.rating + (1.0 - weight) * self._initial.rating
        # Variance blend: uncertainty must never fall below the predecessor's,
        # because this exact roster has played nothing.
        rd = math.sqrt(weight * prior.rd**2 + (1.0 - weight) * self._initial.rd**2)
        return GlickoRating(rating, max(rd, prior.rd), prior.volatility)

    def predict(self, row: MapRow) -> float:
        if self._index is not None:
            # Register rosters without counting maps. Uses team ids and player
            # ids only -- no outcome -- so it cannot leak.
            self._index.observe(row, count=False)
        a = self.rating_of(roster_version_id(row.radiant_accounts))
        b = self.rating_of(roster_version_id(row.dire_accounts))
        return expected_score(a, b)

    def update(self, row: MapRow) -> None:
        reason = skip_reason(row)
        if reason is not None:
            self.skipped[reason] = self.skipped.get(reason, 0) + 1
            return
        if self._index is not None:
            self._index.observe(row)

        period = self._period_of(row.start_time)
        if period > self._current_period:
            self.flush()
            self._current_period = period

        a = roster_version_id(row.radiant_accounts)
        b = roster_version_id(row.dire_accounts)
        ra, rb = self.rating_of(a), self.rating_of(b)
        score = 1.0 if row.radiant_win else 0.0
        self._pending.setdefault(a, []).append((rb, score))
        self._pending.setdefault(b, []).append((ra, 1.0 - score))
        for rvid in (a, b):
            self._maps[rvid] = self._maps.get(rvid, 0) + 1
            bucket = self._maps_by_period.setdefault(period, {})
            bucket[rvid] = bucket.get(rvid, 0) + 1

    def flush(self) -> None:
        if not self._pending:
            return
        updated = {
            rvid: update_rating(self.rating_of(rvid), results, self._tau)
            for rvid, results in self._pending.items()
        }
        self._ratings.update(updated)
        for rvid in updated:
            self._last_period[rvid] = self._current_period
        self._pending = {}

    def strengths(self) -> dict[str, float]:
        """Zero-centred logit strengths, inflated to the current period."""
        self.flush()
        if not self._ratings:
            return {}
        current = {rvid: self.rating_of(rvid) for rvid in self._ratings}
        mean = sum(r.rating for r in current.values()) / len(current)
        return {k: (r.rating - mean) * LOGIT_PER_GLICKO for k, r in current.items()}

    def rating_deviations(self) -> dict[str, float]:
        self.flush()
        return {rvid: self.rating_of(rvid).rd for rvid in self._ratings}

    def prior_driven(self, min_maps: int = 10) -> list[str]:
        return sorted(r for r in self._ratings if self._maps.get(r, 0) < min_maps)

    def activity_report(self) -> list[dict]:
        """Maps per roster per rating period, plus current idle length.

        Spec III measured recent volume collapsing to ~1,600 maps in the last
        90 days; this is how that shows up per team rather than in aggregate.
        """
        self.flush()
        rows = []
        for rvid in sorted(self._ratings):
            per_period = {
                period: counts[rvid]
                for period, counts in sorted(self._maps_by_period.items())
                if rvid in counts
            }
            rows.append(
                {
                    "roster_version_id": rvid,
                    "total_maps": self._maps.get(rvid, 0),
                    "active_periods": len(per_period),
                    "maps_by_period": per_period,
                    "idle_periods": self._current_period - self._last_period.get(rvid, 0),
                    "rating": self.rating_of(rvid).rating,
                    "rd": self.rating_of(rvid).rd,
                }
            )
        return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_glicko.py -v`
Expected: PASS (19 tests). The Glickman fixture test is the load-bearing one — if it fails, the volatility iteration or the scale conversion is wrong, and no amount of monotonicity testing will find it.

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
- Produces: `Fold` frozen dataclass `(fold_id: int, league_id: int, as_of: int, first_match: int, n_train: int, n_test: int)`; `FoldIntegrityError(AssertionError)`; `assert_fold_integrity(folds, rows) -> None`; `rolling_folds(rows, min_train: int = 500) -> list[Fold]`; `run_model(rows, model_factory, folds) -> list[Prediction]`; `per_map_log_loss(predictions, rows) -> np.ndarray`; `log_loss(predictions, rows) -> float`; `brier(predictions, rows) -> float`; `accuracy(predictions, rows) -> float`; `calibration(predictions, rows) -> tuple[float, float]` returning `(slope, intercept)`; `MisalignedPredictionsError(ValueError)`; `paired_differences(predictions_a, predictions_b, rows) -> tuple[np.ndarray, np.ndarray, np.ndarray]` returning `(diff, tournament, series)` aligned by `match_id`; `paired_cluster_bootstrap(diff, tournament, series, draws, ci, seed, memory_budget=2_000_000) -> tuple[float, float, float, str]` returning `(mean_diff, lo, hi, method)`; `MIN_TOURNAMENTS_FOR_SINGLE_STAGE: int = 30`; `GateResult` frozen dataclass `(margin, ci_low, ci_high, passed, method, n_maps, reasons)`; `evaluate_gate(predictions_elo, predictions_glicko, rows, config) -> GateResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backtest.py
import math

import numpy as np
import pytest

from ti26.data.schema import MapRow
from ti26.ratings import GateConfig, Prediction
from ti26.backtest import (
    FoldIntegrityError,
    MisalignedPredictionsError,
    accuracy,
    assert_fold_integrity,
    brier,
    calibration,
    evaluate_gate,
    log_loss,
    paired_cluster_bootstrap,
    paired_differences,
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


def pred(match_id, p, league_id=1, series_id=0, fold_id=0):
    return Prediction(
        fold_id=fold_id, match_id=match_id, start_time=match_id, league_id=league_id,
        series_id=series_id, p_radiant=p, rated=True,
    )


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
    assert fold.first_match == 10_000_000
    assert fold.n_test == 50
    assert fold.fold_id == 0


def test_fold_integrity_accepts_well_formed_folds():
    rows = (
        [row(i, i * 100, league_id=1) for i in range(600)]
        + [row(1000 + i, 10_000_000 + i * 100, league_id=2) for i in range(50)]
    )
    assert assert_fold_integrity(rolling_folds(rows, min_train=500), rows) is None


def test_fold_integrity_rejects_a_cutoff_that_does_not_precede_its_tournament():
    """A cutoff at or after the first match means the model trained on the
    tournament it is being scored on -- the exact leakage spec IV forbids,
    and it produces excellent metrics."""
    from ti26.backtest import Fold

    rows = [row(1, 5_000, league_id=7)]
    bad = [Fold(fold_id=0, league_id=7, as_of=5_000, first_match=5_000, n_train=1, n_test=1)]
    with pytest.raises(FoldIntegrityError, match="not before"):
        assert_fold_integrity(bad, rows)


def test_fold_integrity_rejects_a_league_appearing_twice():
    """Duplicated folds double-weight one tournament in the gate."""
    from ti26.backtest import Fold

    rows = [row(1, 5_000, league_id=7)]
    dupes = [
        Fold(fold_id=0, league_id=7, as_of=1_000, first_match=5_000, n_train=1, n_test=1),
        Fold(fold_id=1, league_id=7, as_of=2_000, first_match=5_000, n_train=1, n_test=1),
    ]
    with pytest.raises(FoldIntegrityError, match="more than one fold"):
        assert_fold_integrity(dupes, rows)


def test_fold_integrity_rejects_a_miscounted_test_set():
    from ti26.backtest import Fold

    rows = [row(1, 5_000, league_id=7), row(2, 6_000, league_id=7)]
    wrong = [Fold(fold_id=0, league_id=7, as_of=1_000, first_match=5_000, n_train=9, n_test=5)]
    with pytest.raises(FoldIntegrityError, match="n_test=5"):
        assert_fold_integrity(wrong, rows)


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


def clustered(n_tournaments, series_per_tournament, maps_per_series, effect, noise, seed):
    """Build (diff, tournament, series) with variance living BETWEEN series.

    Every map in a series shares one draw, which is the correlation structure
    an iid map-level bootstrap wrongly ignores.
    """
    rng = np.random.default_rng(seed)
    diff, tournaments, series = [], [], []
    sid = 0
    for t in range(n_tournaments):
        for _ in range(series_per_tournament):
            shared = rng.normal(effect, noise)
            for _ in range(maps_per_series):
                diff.append(shared + rng.normal(0, 0.001))
                tournaments.append(t)
                series.append(sid)
            sid += 1
    return np.asarray(diff), np.asarray(tournaments), np.asarray(series)


def test_cluster_bootstrap_ci_excludes_zero_for_a_real_difference():
    diff, tour, ser = clustered(40, 12, 3, effect=0.02, noise=0.01, seed=3)
    mean, lo, hi, method = paired_cluster_bootstrap(diff, tour, ser, 2000, 0.95, seed=1)
    assert mean == pytest.approx(0.02, abs=0.004)
    assert lo > 0.0
    assert "tournaments" in method


def test_cluster_bootstrap_ci_includes_zero_for_pure_noise():
    diff, tour, ser = clustered(40, 12, 3, effect=0.0, noise=0.05, seed=4)
    _, lo, hi, _ = paired_cluster_bootstrap(diff, tour, ser, 2000, 0.95, seed=1)
    assert lo < 0.0 < hi


def test_clustered_interval_is_wider_than_the_iid_one():
    """THE test for this task. When correlation lives between series, an iid
    map-level bootstrap sees 3x more independent evidence than exists and
    reports a CI that is too narrow -- which is how a gate passes on noise.

    If this fails, the clustering is cosmetic.
    """
    diff, tour, ser = clustered(40, 12, 3, effect=0.0, noise=0.05, seed=5)
    _, c_lo, c_hi, _ = paired_cluster_bootstrap(diff, tour, ser, 2000, 0.95, seed=1)

    rng = np.random.default_rng(1)
    idx = rng.integers(0, len(diff), size=(2000, len(diff)))
    iid = diff[idx].mean(axis=1)
    i_lo, i_hi = np.quantile(iid, [0.025, 0.975])

    assert (c_hi - c_lo) > 1.5 * (i_hi - i_lo)


def test_two_stage_path_engages_when_tournaments_are_few():
    """With a handful of tournaments, single-stage resampling has too few
    distinct draws; the second stage keeps the distribution usable."""
    diff, tour, ser = clustered(4, 30, 3, effect=0.01, noise=0.02, seed=6)
    mean, lo, hi, method = paired_cluster_bootstrap(diff, tour, ser, 1000, 0.95, seed=1)
    assert "two-stage" in method
    assert np.isfinite(lo) and np.isfinite(hi) and lo < hi


def test_bootstrap_memory_budget_does_not_change_the_answer():
    """Batching is an implementation detail; a tiny budget must give the same
    interval as a large one, or the batching is wrong."""
    diff, tour, ser = clustered(40, 6, 3, effect=0.01, noise=0.02, seed=7)
    big = paired_cluster_bootstrap(diff, tour, ser, 1000, 0.95, seed=1, memory_budget=2_000_000)
    small = paired_cluster_bootstrap(diff, tour, ser, 1000, 0.95, seed=1, memory_budget=50)
    assert big[:3] == pytest.approx(small[:3])


def test_bootstrap_is_seed_reproducible():
    diff, tour, ser = clustered(40, 6, 3, effect=0.01, noise=0.02, seed=8)
    first = paired_cluster_bootstrap(diff, tour, ser, 500, 0.95, seed=42)
    second = paired_cluster_bootstrap(diff, tour, ser, 500, 0.95, seed=42)
    assert first == second


def test_losses_align_by_match_id_not_by_position():
    """If one model's prediction list is reordered, the paired difference must
    be unchanged. Positional zipping would silently compare unrelated maps.
    """
    rows = [row(i, i, 1, radiant_win=i % 3 == 0) for i in range(50)]
    a = [pred(i, 0.4 + 0.004 * i) for i in range(50)]
    b = [pred(i, 0.5) for i in range(50)]
    straight, _, _ = paired_differences(a, b, rows)
    shuffled, _, _ = paired_differences(a, list(reversed(b)), rows)
    assert straight == pytest.approx(shuffled)


def test_mismatched_prediction_sets_raise():
    rows = [row(i, i, 1) for i in range(10)]
    a = [pred(i, 0.5) for i in range(10)]
    b = [pred(i, 0.5) for i in range(9)]
    with pytest.raises(MisalignedPredictionsError, match="10 vs 9"):
        paired_differences(a, b, rows)


def test_a_prediction_with_no_matching_row_does_not_shift_the_pairing():
    """Dropping an unmatched prediction must not slide every later pair by one.

    Zipping predictions against a filtered loss array does exactly that, and
    it fails silently: the arrays still have equal length, so nothing raises
    and the gate quietly compares unrelated maps.
    """
    rows = [row(i, i, 1, radiant_win=i % 2 == 0) for i in range(10)]
    extra = 999  # present in both prediction sets, absent from `rows`
    a = [pred(i, 0.3 + 0.05 * i) for i in range(10)] + [pred(extra, 0.9)]
    b = [pred(i, 0.5) for i in range(10)] + [pred(extra, 0.1)]

    with_extra, _, _ = paired_differences(a, b, rows)
    without_extra, _, _ = paired_differences(a[:-1], b[:-1], rows)
    assert with_extra == pytest.approx(without_extra)
    assert len(with_extra) == 10


def test_null_series_ids_become_singleton_clusters_not_one_giant_cluster():
    """Collapsing every unlabelled map into a single shared cluster would
    make the CI absurdly wide and the gate unpassable for a data reason."""
    rows = [row(i, i, 1) for i in range(20)]
    a = [pred(i, 0.6, series_id=None) for i in range(20)]
    b = [pred(i, 0.5, series_id=None) for i in range(20)]
    _, _, series = paired_differences(a, b, rows)
    assert len(set(series.tolist())) == 20


def config(**kw):
    base = dict(
        min_margin_nats=0.003, bootstrap_draws=1000, bootstrap_ci=0.95, seed=1,
        elo_k=20.0, glicko_tau=0.5, ewma_half_life_maps=30.0,
    )
    base.update(kw)
    return GateConfig(**base)


def gate_fixture(edge, jitter, seed, n_tournaments=40, series_per=10, maps_per=3):
    """Two prediction sets over the same maps, where B is better by `edge`.

    Built as real Prediction objects over real rows so the gate exercises the
    same alignment and clustering path the runner uses.
    """
    rng = np.random.default_rng(seed)
    rows, a, b = [], [], []
    match_id = 0
    sid = 0
    for t in range(n_tournaments):
        for _ in range(series_per):
            base = rng.uniform(0.35, 0.65)
            shift = rng.normal(edge, jitter)
            for _ in range(maps_per):
                won = rng.random() < base
                rows.append(row(match_id, match_id, league_id=t, radiant_win=won))
                pa = base if won else 1 - base
                pb = min(max(pa + shift, 0.01), 0.99)
                a.append(pred(match_id, pa if won else 1 - pa, league_id=t,
                              series_id=sid, fold_id=t))
                b.append(pred(match_id, pb if won else 1 - pb, league_id=t,
                              series_id=sid, fold_id=t))
                match_id += 1
            sid += 1
    return a, b, rows


def test_gate_requires_both_conditions_margin_and_significance():
    # Consistent small edge to B, low between-series noise -> PASS.
    a, b, rows = gate_fixture(edge=0.05, jitter=0.005, seed=9)
    result = evaluate_gate(a, b, rows, config())
    assert result.passed is True
    assert result.reasons == []
    assert result.n_maps == len(rows)

    # No edge at all -> margin condition fails.
    a, b, rows = gate_fixture(edge=0.0, jitter=0.005, seed=10)
    result = evaluate_gate(a, b, rows, config())
    assert result.passed is False
    assert any("margin" in r for r in result.reasons)

    # Real average edge, but swamped by between-series noise -> CI fails.
    a, b, rows = gate_fixture(edge=0.02, jitter=0.60, seed=11)
    result = evaluate_gate(a, b, rows, config())
    assert result.passed is False
    assert any("CI" in r for r in result.reasons)


def test_gate_reads_the_margin_from_config_not_a_literal():
    """Pre-registration is meaningless if the threshold is hard-coded in two
    places and only one of them is the registered one."""
    a, b, rows = gate_fixture(edge=0.05, jitter=0.005, seed=13)
    assert evaluate_gate(a, b, rows, config(min_margin_nats=0.003)).passed is True
    assert evaluate_gate(a, b, rows, config(min_margin_nats=10.0)).passed is False


def test_gate_records_which_bootstrap_method_it_used():
    """The report prints this; a silently-swapped method would change the CI
    without changing anything a reader can see."""
    a, b, rows = gate_fixture(edge=0.05, jitter=0.005, seed=14)
    assert "tournaments" in evaluate_gate(a, b, rows, config()).method
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
from ti26.ratings import GateConfig, Prediction, skip_reason

DAY_SECONDS = 86400
EPS = 1e-15


@dataclass(frozen=True)
class Fold:
    fold_id: int
    league_id: int
    as_of: int
    first_match: int
    n_train: int
    n_test: int


class FoldIntegrityError(AssertionError):
    """A fold violated a property the backtest's validity depends on."""


def assert_fold_integrity(folds: Sequence[Fold], rows: Sequence[MapRow]) -> None:
    """Check the properties that make a rolling backtest mean anything.

    Every one of these has silently produced good-looking, worthless metrics
    in real projects, so they are assertions rather than comments.
    """
    by_id = {}
    for fold in folds:
        if fold.fold_id in by_id:
            raise FoldIntegrityError(f"duplicate fold_id {fold.fold_id}")
        by_id[fold.fold_id] = fold

    seen_leagues = set()
    for fold in folds:
        if fold.league_id in seen_leagues:
            raise FoldIntegrityError(
                f"league {fold.league_id} appears in more than one fold; its maps "
                "would be scored twice and weighted double in the gate"
            )
        seen_leagues.add(fold.league_id)

        if fold.as_of >= fold.first_match:
            raise FoldIntegrityError(
                f"fold {fold.fold_id}: as_of={fold.as_of} is not before its first "
                f"match at {fold.first_match}"
            )
        test_rows = [r for r in rows if r.league_id == fold.league_id]
        if not test_rows:
            raise FoldIntegrityError(f"fold {fold.fold_id} has no test rows")
        earliest = min(r.start_time for r in test_rows)
        if earliest <= fold.as_of:
            raise FoldIntegrityError(
                f"fold {fold.fold_id}: a test map at {earliest} is at or before "
                f"as_of={fold.as_of}; it was in the training set"
            )
        if fold.n_test != len(test_rows):
            raise FoldIntegrityError(
                f"fold {fold.fold_id}: n_test={fold.n_test} but {len(test_rows)} rows match"
            )


@dataclass(frozen=True)
class GateResult:
    margin: float
    ci_low: float
    ci_high: float
    passed: bool
    method: str
    n_maps: int
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
        folds.append(
            Fold(
                fold_id=len(folds),
                league_id=league_id,
                as_of=as_of,
                first_match=first,
                n_train=n_train,
                n_test=n_test,
            )
        )
    return folds


def run_model(
    rows: Sequence[MapRow],
    model_factory: Callable[[], object],
    folds: Sequence[Fold],
) -> list[Prediction]:
    """Refit from scratch at each cutoff, then predict that tournament.

    The factory must return a fully wired model — the same object `cli_d2`
    constructs. Nothing here injects collaborators the runner would not.
    """
    ordered = sorted(rows, key=lambda r: (r.start_time, r.match_id))
    assert_fold_integrity(folds, ordered)
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
            reason = skip_reason(row)
            predictions.append(
                Prediction(
                    fold_id=fold.fold_id,
                    match_id=row.match_id,
                    start_time=row.start_time,
                    league_id=row.league_id,
                    series_id=row.series_id,
                    p_radiant=model.predict(row),
                    rated=reason is None,
                    reason=reason,
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


class MisalignedPredictionsError(ValueError):
    """Two models produced predictions over different match sets."""


def paired_differences(
    predictions_a: Sequence[Prediction],
    predictions_b: Sequence[Prediction],
    rows: Sequence[MapRow],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Align two models' per-map losses BY match_id, not by position.

    Positional alignment is a silent corruption waiting to happen: the moment
    one model skips a row the other rates, every subsequent pair is mismatched
    and the gate compares unrelated maps while looking perfectly healthy.
    """
    outcomes = {r.match_id: r.radiant_win for r in rows}

    def losses(predictions: Sequence[Prediction]) -> dict[int, float]:
        # Computed here rather than by zipping against `per_map_log_loss`,
        # which filters unmatched predictions out and would shift every
        # subsequent pairing by one -- silently, and only sometimes.
        out = {}
        for prediction in predictions:
            if prediction.match_id not in outcomes:
                continue
            p = min(max(prediction.p_radiant, EPS), 1.0 - EPS)
            y = 1.0 if outcomes[prediction.match_id] else 0.0
            out[prediction.match_id] = -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
        return out

    loss_a, loss_b = losses(predictions_a), losses(predictions_b)
    if set(loss_a) != set(loss_b):
        only_a = sorted(set(loss_a) - set(loss_b))[:5]
        only_b = sorted(set(loss_b) - set(loss_a))[:5]
        raise MisalignedPredictionsError(
            f"prediction sets differ: {len(loss_a)} vs {len(loss_b)} matches; "
            f"only in A {only_a}, only in B {only_b}"
        )

    cluster = {p.match_id: (p.league_id, p.series_id) for p in predictions_a}
    match_ids = sorted(loss_a)
    diff = np.asarray([loss_a[m] - loss_b[m] for m in match_ids], dtype=float)
    tournament = np.asarray([cluster[m][0] if cluster[m][0] is not None else -1 for m in match_ids])
    # A null series_id would silently merge unrelated maps into one cluster,
    # so fall back to the match's own id: a singleton cluster, never a merge.
    series = np.asarray(
        [cluster[m][1] if cluster[m][1] is not None else -m for m in match_ids]
    )
    return diff, tournament, series


# Below this many tournaments, resampling whole tournaments yields too few
# distinct draws to form a usable distribution, so the second stage is added.
MIN_TOURNAMENTS_FOR_SINGLE_STAGE = 30

# Peak elements held by any one bootstrap batch. Batches are sized from this,
# so memory stays flat regardless of `draws`.
BOOTSTRAP_MEMORY_BUDGET = 2_000_000


def paired_cluster_bootstrap(
    diff: np.ndarray,
    tournament: np.ndarray,
    series: np.ndarray,
    draws: int,
    ci: float,
    seed: int,
    memory_budget: int = BOOTSTRAP_MEMORY_BUDGET,
) -> tuple[float, float, float, str]:
    """Cluster bootstrap over tournaments, falling back to two stages.

    Maps within a series share teams, day, patch and momentum, so iid
    resampling over maps treats ~3 correlated observations as 3 independent
    ones, understates the interval, and lets the gate pass on noise.

    Resampling WHOLE tournaments is the conservative choice: every correlated
    unit inside moves together. When tournaments are few, a second stage
    resamples series within each drawn tournament so the distribution is not
    degenerate. Returns the method actually used, which the report prints.
    """
    if len(diff) == 0:
        raise ValueError("no paired differences to bootstrap")

    # Collapse to series-level sums/counts first: the unit of resampling is
    # never the individual map.
    series_keys, series_inverse = np.unique(series, return_inverse=True)
    series_sum = np.bincount(series_inverse, weights=diff)
    series_cnt = np.bincount(series_inverse).astype(float)
    series_tournament = np.zeros(len(series_keys), dtype=tournament.dtype)
    series_tournament[series_inverse] = tournament

    tournament_keys, tournament_inverse = np.unique(series_tournament, return_inverse=True)
    n_tournaments = len(tournament_keys)
    rng = np.random.default_rng(seed)
    alpha = (1.0 - ci) / 2.0
    means: list[np.ndarray] = []

    if n_tournaments >= MIN_TOURNAMENTS_FOR_SINGLE_STAGE:
        method = f"cluster bootstrap over {n_tournaments} tournaments"
        t_sum = np.bincount(tournament_inverse, weights=series_sum)
        t_cnt = np.bincount(tournament_inverse, weights=series_cnt)
        batch = max(1, memory_budget // max(n_tournaments, 1))
        remaining = draws
        while remaining > 0:
            b = min(batch, remaining)
            idx = rng.integers(0, n_tournaments, size=(b, n_tournaments))
            means.append(t_sum[idx].sum(axis=1) / t_cnt[idx].sum(axis=1))
            remaining -= b
    else:
        method = (
            f"two-stage cluster bootstrap (tournament then series) over "
            f"{n_tournaments} tournaments"
        )
        by_tournament = [np.flatnonzero(tournament_inverse == t) for t in range(n_tournaments)]
        n_series = np.asarray([len(s) for s in by_tournament])
        width = int(n_series.max())
        padded_sum = np.zeros((n_tournaments, width))
        padded_cnt = np.zeros((n_tournaments, width))
        for t, members in enumerate(by_tournament):
            padded_sum[t, : len(members)] = series_sum[members]
            padded_cnt[t, : len(members)] = series_cnt[members]

        batch = max(1, memory_budget // max(n_tournaments * width, 1))
        positions = np.arange(width)[None, None, :]
        remaining = draws
        while remaining > 0:
            b = min(batch, remaining)
            t_idx = rng.integers(0, n_tournaments, size=(b, n_tournaments))
            counts = n_series[t_idx][..., None]
            s_idx = (rng.random((b, n_tournaments, width)) * counts).astype(np.int64)
            mask = positions < counts
            sums = np.take_along_axis(padded_sum[t_idx], s_idx, axis=2) * mask
            cnts = np.take_along_axis(padded_cnt[t_idx], s_idx, axis=2) * mask
            means.append(sums.sum(axis=(1, 2)) / cnts.sum(axis=(1, 2)))
            remaining -= b

    distribution = np.concatenate(means)
    lo, hi = np.quantile(distribution, [alpha, 1.0 - alpha])
    return float(diff.mean()), float(lo), float(hi), method


def evaluate_gate(
    predictions_elo: Sequence[Prediction],
    predictions_glicko: Sequence[Prediction],
    rows: Sequence[MapRow],
    config: GateConfig,
) -> GateResult:
    """The pre-registered gate. BOTH conditions, per spec II."""
    diff, tournament, series = paired_differences(predictions_elo, predictions_glicko, rows)
    margin, lo, hi, method = paired_cluster_bootstrap(
        diff, tournament, series, config.bootstrap_draws, config.bootstrap_ci, config.seed
    )
    reasons = []
    if margin < config.min_margin_nats:
        reasons.append(
            f"margin {margin:.5f} < pre-registered {config.min_margin_nats} nats/map"
        )
    if lo <= 0.0:
        reasons.append(f"bootstrap {config.bootstrap_ci:.0%} CI [{lo:.5f}, {hi:.5f}] includes 0")
    return GateResult(
        margin=margin,
        ci_low=lo,
        ci_high=hi,
        passed=not reasons,
        reasons=reasons,
        method=method,
        n_maps=len(diff),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_backtest.py -v`
Expected: PASS (27 tests). `test_clustered_interval_is_wider_than_the_iid_one` is the load-bearing one — if it fails, the clustering is cosmetic and the gate is running on an interval that is too narrow.

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
- Produces: `DurationFit` frozen dataclass `(log_mean: float, log_sigma: float, gap_coefficient: float, gap_se: float, n: int, material: bool)`; `fit_duration_model(rows: Sequence[MapRow], gaps: Mapping[int, float] | None = None) -> DurationFit`; `rating_gaps(rows: Sequence[MapRow], model) -> dict[int, float]` (absolute pre-match logit gap per `match_id`, predict-then-update so it cannot leak); `sensitivity_sweep(strengths, rules, sigmas: Sequence[float], n_sims: int = 20000, seed: int = 0) -> list[dict]` returning one `{log_sigma, max_abs_delta, is_baseline}` per sigma, compared against the first entry; `MIN_DURATION_SECONDS: int = 600`; `MAX_DURATION_SECONDS: int = 9000`.

**Both `rating_gaps` and `sensitivity_sweep` must be called by `cli_d2` in Task 8.** A conditioning argument the runner never passes is a conditioning that does not exist, and a sweep nobody runs cannot report how much the card depends on an invented parameter.

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


def test_rating_gaps_are_computed_before_the_result_is_known():
    """Predict-then-update. If the model were updated first, the gap for a map
    would encode that map's own outcome and the duration fit would be
    conditioned on the future."""
    from ti26.ratings.elo import EloModel
    from ti26.duration import rating_gaps

    A, B = [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]
    rows = [
        MapRow(
            match_id=i, start_time=100 + i, duration=2000, radiant_win=True,
            league_id=1, tier="professional", radiant_team_id=10, dire_team_id=20,
            series_id=1, series_type=1, patch="7.41",
            radiant_accounts=tuple(A), dire_accounts=tuple(B),
            radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
            has_null_team=False, has_bad_roster=False,
        )
        for i in range(10)
    ]
    gaps = rating_gaps(rows, EloModel())
    assert gaps[0] == pytest.approx(0.0), "the first map has no prior evidence at all"
    assert gaps[9] > gaps[1], "the gap widens as A keeps winning"
    assert set(gaps) == {r.match_id for r in rows}


def test_sensitivity_sweep_reports_zero_delta_for_its_own_baseline():
    from ti26.duration import sensitivity_sweep
    from ti26.rules import load_rules

    rules = load_rules("config/ti2026_rules.yaml")
    strengths = {f"t{i:02d}": (i - 7.5) * 0.15 for i in range(16)}
    result = sensitivity_sweep(strengths, rules, [0.25, 0.45], n_sims=2000, seed=3)
    assert result[0]["is_baseline"] is True
    assert result[0]["max_abs_delta"] == 0.0
    assert result[1]["max_abs_delta"] >= 0.0


@pytest.mark.slow
def test_sensitivity_sweep_detects_that_log_sigma_moves_the_card():
    """Spec XII: this parameter steers ~30% of every ranking, so a sweep that
    reports no movement at any sigma would mean the resolver is not wired in.

    Marked slow: it needs enough simulations that the delta is signal rather
    than Monte Carlo noise.
    """
    from ti26.duration import sensitivity_sweep
    from ti26.rules import load_rules

    rules = load_rules("config/ti2026_rules.yaml")
    strengths = {f"t{i:02d}": 0.0 for i in range(16)}  # fully tied: duration decides
    result = sensitivity_sweep(strengths, rules, [0.05, 1.20], n_sims=60000, seed=5)
    assert result[1]["max_abs_delta"] > 0.005


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


def rating_gaps(rows: Sequence[MapRow], model) -> dict[int, float]:
    """Absolute pre-match logit gap per map, from a model walked in time order.

    Predict-then-update, so the gap for a map never sees that map's result.
    Spec XII requires the duration fit be conditioned at minimum on rating
    gap; this is what supplies it.
    """
    gaps: dict[int, float] = {}
    for row in sorted(rows, key=lambda r: (r.start_time, r.match_id)):
        p = min(max(model.predict(row), 1e-6), 1.0 - 1e-6)
        gaps[row.match_id] = abs(math.log(p / (1.0 - p)))
        model.update(row)
    return gaps


def sensitivity_sweep(
    strengths: Mapping[str, float],
    rules,
    sigmas: Sequence[float],
    n_sims: int = 20000,
    seed: int = 0,
) -> list[dict]:
    """How far does the card move across plausible `log_sigma` values?

    Spec XII: the duration parameter steers ~30% of every ranking, so the
    honest report is not just a point estimate but how much the answer depends
    on it. Compares each sigma's category marginals against the first sigma in
    the list, which the caller passes as the fitted value.
    """
    from dataclasses import replace

    from ti26.montecarlo import category_marginals
    from ti26.types import Category

    baseline: dict[str, dict] | None = None
    out: list[dict] = []
    for sigma in sigmas:
        marginals = category_marginals(
            dict(strengths), replace(rules, duration_log_sigma=sigma), n_sims=n_sims, seed=seed
        )
        if baseline is None:
            baseline = marginals
            out.append({"log_sigma": sigma, "max_abs_delta": 0.0, "is_baseline": True})
            continue
        delta = max(
            abs(marginals[team][category] - baseline[team][category])
            for team in baseline
            for category in Category
        )
        out.append({"log_sigma": sigma, "max_abs_delta": float(delta), "is_baseline": False})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_duration.py -v -m "not slow"`
Expected: PASS (8 tests, 1 deselected)

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
- Create: `src/ti26/cli_ingest.py`, `src/ti26/teams.py`, `src/ti26/cli_d2.py`, `config/ti2026_teams.yaml`
- Modify: `config/ti2026_rules.yaml` (fitted duration values + provenance)
- Test: `tests/test_teams.py`, `tests/test_cli_d2.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7, plus `ti26.rules.load_rules`, `ti26.montecarlo.category_marginals` and **`ti26.cli.main`** from D1.
- Produces: `TeamEntry` frozen dataclass `(name: str, team_id: int)`; `UnresolvedTeamError(ValueError)`; `load_teams(path) -> list[TeamEntry]`; `latest_rosters(rows, aliases) -> dict[int, str]`; `resolve_rosters(rows, teams, aliases) -> dict[str, str]`; `team_strengths(resolved, strengths) -> tuple[dict[str, float], list[str]]`; `ti26.cli_ingest.main(argv) -> int` writing `data/raw/<sid>/*.json.gz`, `manifest.json`, and `data/processed/d2.sqlite`; `ti26.cli_d2.main(argv) -> int` writing `reports/d2_gate.md`, `reports/backtest_metrics.csv`, `reports/duration_fit.json`, `reports/duration_sensitivity.json`, `reports/strengths.csv`, and — via `ti26.cli.main(["--strengths", ...])` — `reports/recommended_card.json`.

**The end-to-end requirement, stated once so it cannot be missed:** `cli_d2` fits the selected model on all data, resolves the 16 configured teams to their current rosters, writes `reports/strengths.csv`, and **calls D1's card generator with `--strengths` pointing at that file**. Invoking `ti26.cli` without `--strengths` silently produces a card from a synthetic ladder (`src/ti26/cli.py:15-16`) and is a plan violation.

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

- [ ] **Step 2: Write the team-resolution module**

```python
# src/ti26/teams.py
"""Resolve the 16 configured Swiss-stage teams to rosters and strengths.

D1's card generator takes a strength per team name. This is the bridge from
rating-space (keyed by roster hash) to card-space (keyed by the names a human
types into Valve's form).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from ti26.data.schema import MapRow
from ti26.roster import canonical_team_id, roster_version_id


@dataclass(frozen=True)
class TeamEntry:
    name: str
    team_id: int


class UnresolvedTeamError(ValueError):
    """A configured team could not be tied to any roster in the store."""


def load_teams(path: str | Path) -> list[TeamEntry]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    entries = data.get("teams") or []
    teams = [TeamEntry(name=str(e["name"]), team_id=int(e["team_id"])) for e in entries]
    names = [t.name for t in teams]
    if len(set(names)) != len(names):
        raise UnresolvedTeamError(f"duplicate team names in {path}: {names}")
    ids = [t.team_id for t in teams]
    if len(set(ids)) != len(ids):
        raise UnresolvedTeamError(f"duplicate team_ids in {path}: {ids}")
    return teams


def latest_rosters(
    rows: Sequence[MapRow], aliases: Mapping[int, int]
) -> dict[int, str]:
    """Most recently fielded roster per canonical team id."""
    latest: dict[int, tuple[int, str]] = {}
    for row in sorted(rows, key=lambda r: (r.start_time, r.match_id)):
        for team_id, accounts in (
            (row.radiant_team_id, row.radiant_accounts),
            (row.dire_team_id, row.dire_accounts),
        ):
            canonical = canonical_team_id(team_id, dict(aliases))
            if canonical is None:
                continue
            latest[canonical] = (row.start_time, roster_version_id(accounts))
    return {team_id: rvid for team_id, (_, rvid) in latest.items()}


def resolve_rosters(
    rows: Sequence[MapRow], teams: Sequence[TeamEntry], aliases: Mapping[int, int]
) -> dict[str, str]:
    """Map each configured team name to its current roster_version_id.

    Raises listing EVERY unresolved team at once. Resolving fifteen of sixteen
    and silently defaulting the last would put a prior-driven team on the card
    with no indication it was guessed.
    """
    current = latest_rosters(rows, aliases)
    resolved, missing = {}, []
    for team in teams:
        canonical = canonical_team_id(team.team_id, dict(aliases))
        if canonical is None or canonical not in current:
            missing.append(f"{team.name} (team_id={team.team_id})")
            continue
        resolved[team.name] = current[canonical]
    if missing:
        raise UnresolvedTeamError(
            f"{len(missing)} of {len(teams)} teams have no maps in the store: "
            + "; ".join(missing)
        )
    return resolved


def team_strengths(
    resolved: Mapping[str, str], strengths: Mapping[str, float]
) -> tuple[dict[str, float], list[str]]:
    """Attach a fitted strength to each team; report which fell back to the prior.

    A zero-centred logit strength of 0.0 IS the average-team prior, so an
    unrated roster is not an error — but it must be named, per spec III's
    requirement to report which teams are prior-driven.
    """
    out, prior_driven = {}, []
    for name, rvid in resolved.items():
        if rvid in strengths:
            out[name] = float(strengths[rvid])
        else:
            out[name] = 0.0
            prior_driven.append(name)
    return out, sorted(prior_driven)
```

- [ ] **Step 3: Write the team-resolution test**

```python
# tests/test_teams.py
import pytest

from ti26.data.schema import MapRow
from ti26.roster import roster_version_id
from ti26.teams import (
    TeamEntry,
    UnresolvedTeamError,
    latest_rosters,
    load_teams,
    resolve_rosters,
    team_strengths,
)


def row(match_id, start_time, r_team, d_team, radiant, dire):
    return MapRow(
        match_id=match_id, start_time=start_time, duration=2000, radiant_win=True,
        league_id=1, tier="professional", radiant_team_id=r_team, dire_team_id=d_team,
        series_id=1, series_type=1, patch="7.41",
        radiant_accounts=tuple(radiant), dire_accounts=tuple(dire),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


A_OLD, A_NEW, B = [1, 2, 3, 4, 5], [1, 2, 3, 4, 9], [6, 7, 8, 9, 10]


def test_latest_roster_wins_over_an_earlier_one():
    """A team that substituted last week must be carried at its CURRENT
    roster, not the one that accumulated the rating."""
    rows = [row(1, 100, 10, 20, A_OLD, B), row(2, 200, 10, 20, A_NEW, B)]
    assert latest_rosters(rows, {})[10] == roster_version_id(A_NEW)


def test_aliases_are_applied_when_resolving():
    rows = [row(1, 100, 77, 20, A_NEW, B)]
    resolved = resolve_rosters(rows, [TeamEntry("Rebranded", 10)], {77: 10})
    assert resolved["Rebranded"] == roster_version_id(A_NEW)


def test_every_unresolved_team_is_reported_at_once():
    """Fifteen of sixteen resolving is not a partial success."""
    rows = [row(1, 100, 10, 20, A_NEW, B)]
    teams = [TeamEntry("Known", 10), TeamEntry("Ghost", 999), TeamEntry("Spectre", 998)]
    with pytest.raises(UnresolvedTeamError, match="2 of 3") as exc:
        resolve_rosters(rows, teams, {})
    assert "Ghost" in str(exc.value) and "Spectre" in str(exc.value)


def test_duplicate_names_or_ids_are_rejected(tmp_path):
    path = tmp_path / "teams.yaml"
    path.write_text("teams:\n  - {name: X, team_id: 1}\n  - {name: X, team_id: 2}\n")
    with pytest.raises(UnresolvedTeamError, match="duplicate team names"):
        load_teams(path)

    path.write_text("teams:\n  - {name: X, team_id: 1}\n  - {name: Y, team_id: 1}\n")
    with pytest.raises(UnresolvedTeamError, match="duplicate team_ids"):
        load_teams(path)


def test_unrated_rosters_get_the_average_prior_and_are_named():
    resolved = {"Rated": "aaa", "New": "bbb"}
    strengths, prior_driven = team_strengths(resolved, {"aaa": 0.7})
    assert strengths == {"Rated": 0.7, "New": 0.0}
    assert prior_driven == ["New"], "spec III: prior-driven teams must be reported"
```

- [ ] **Step 4: Create the team config**

```yaml
# config/ti2026_teams.yaml
# The 16 teams in the TI 2026 Swiss stage, with their OpenDota team_ids.
#
# Starts EMPTY on purpose. Step 5 populates it from the store; inventing an
# id here would silently put another organization's rating on the card.
# `cli_d2` refuses to produce a card unless exactly `rules.n_teams` entries
# resolve, so an incomplete file fails loudly rather than shipping a guess.
teams: []
```

- [ ] **Step 5: Populate the team config from real data**

List the organizations most active in recent tier-1 play, then fill in the 16 that are actually in the Swiss stage:

```bash
.venv/bin/python - <<'PY'
import sqlite3, json, collections
conn = sqlite3.connect("data/processed/d2.sqlite")
cutoff = conn.execute("select max(start_time) - 180*86400 from maps").fetchone()[0]
counts = collections.Counter()
for r_id, d_id in conn.execute(
    "select radiant_team_id, dire_team_id from maps where start_time > ? "
    "and tier in ('premium','professional')", (cutoff,)
):
    for t in (r_id, d_id):
        if t is not None:
            counts[t] += 1
print(json.dumps(counts.most_common(40), indent=1))
PY
```

Names come from the same explorer `teams` table used in Task 3 Step 5. Write each confirmed entry as `- {name: <display name>, team_id: <id>}`. **Do not pad the list to 16 with guesses** — if the field is not fully known yet, leave the file short and record in the ledger that the card step is blocked pending the team list. A card built on the wrong sixteen teams is worse than no card.

- [ ] **Step 6: Write the D2 runner**

```python
# src/ti26/cli_d2.py
"""Fit ratings, run the rolling backtest, report the pre-registered verdict."""

import argparse
import csv
import json
from dataclasses import replace
from pathlib import Path

from ti26.backtest import (
    accuracy,
    brier,
    calibration,
    evaluate_gate,
    log_loss,
    rolling_folds,
    run_model,
)
from ti26.cli import main as cli_main
from ti26.data.store import load_rows, open_store
from ti26.duration import fit_duration_model, rating_gaps, sensitivity_sweep
from ti26.ratings import load_gate_config
from ti26.ratings.elo import EloModel
from ti26.ratings.glicko import GlickoModel
from ti26.ratings.simple import ConstantModel, EwmaModel
from ti26.roster import RosterIndex, load_aliases
from ti26.rules import load_rules
from ti26.teams import load_teams, resolve_rosters, team_strengths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D2: fit ratings and evaluate the gate")
    parser.add_argument("--store", default="data/processed/d2.sqlite")
    parser.add_argument("--gate-config", default="config/d2_gate.yaml")
    parser.add_argument("--rules", default="config/ti2026_rules.yaml")
    parser.add_argument("--aliases", default="config/team_aliases.yaml")
    parser.add_argument("--teams", default="config/ti2026_teams.yaml")
    parser.add_argument("--min-train", type=int, default=500)
    parser.add_argument("--final-model", choices=["auto", "elo", "glicko"], default="auto")
    parser.add_argument("--card-sims", type=int, default=250_000)
    parser.add_argument("--card-seed", type=int, default=1)
    parser.add_argument("--skip-card", action="store_true",
                        help="stop after the gate; use when the team list is not yet known")
    parser.add_argument("--out", default="reports")
    args = parser.parse_args(argv)

    config = load_gate_config(args.gate_config)
    rules = load_rules(args.rules)
    aliases = load_aliases(args.aliases)
    rows = load_rows(open_store(args.store))
    if not rows:
        raise SystemExit(f"{args.store} is empty; run `python -m ti26.cli_ingest` first")

    folds = rolling_folds(rows, min_train=args.min_train)
    if not folds:
        raise SystemExit(f"no tournament had {args.min_train}+ prior maps; lower --min-train")

    # The SAME factories are used for the backtest and for the final fit, so a
    # collaborator missing here is missing in both -- never in only one.
    models = {
        "constant": lambda: ConstantModel(),
        "ewma": lambda: EwmaModel(half_life_maps=config.ewma_half_life_maps),
        "elo": lambda: EloModel(k=config.elo_k),
        "glicko": lambda: GlickoModel(
            tau=config.glicko_tau, roster_index=RosterIndex(aliases)
        ),
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

    result = evaluate_gate(predictions["elo"], predictions["glicko"], rows, config)

    # --- Final fit on everything, then the card -------------------------------
    selected = args.final_model
    if selected == "auto":
        selected = "glicko" if result.passed else "elo"

    final = models[selected]()
    for row in rows:
        final.update(row)
    final.flush()
    fitted = final.strengths()

    # Rating gap per map from a SEPARATE Elo pass, predict-then-update, so the
    # duration fit is conditioned on gap without ever seeing a map's own result.
    gaps = rating_gaps(rows, EloModel(k=config.elo_k))
    duration_fit = fit_duration_model(rows, gaps=gaps)
    (out / "duration_fit.json").write_text(
        json.dumps(
            {
                "log_mean": duration_fit.log_mean,
                "log_sigma": duration_fit.log_sigma,
                "gap_coefficient": duration_fit.gap_coefficient,
                "gap_se": duration_fit.gap_se,
                "gap_effect_material": duration_fit.material,
                "n": duration_fit.n,
                "placeholder_log_mean": 7.65,
                "placeholder_log_sigma": 0.25,
                "note": "spec XII: this parameter steers ~30% of every ranking",
            },
            indent=2,
        )
        + "\n"
    )

    card_status = "skipped (--skip-card)"
    sweep: list[dict] = []
    prior_driven: list[str] = []
    if not args.skip_card:
        teams = load_teams(args.teams)
        if len(teams) != rules.n_teams:
            raise SystemExit(
                f"{args.teams} lists {len(teams)} teams but the rules require "
                f"{rules.n_teams}; populate it or pass --skip-card"
            )
        resolved = resolve_rosters(rows, teams, aliases)
        strengths, prior_driven = team_strengths(resolved, fitted)

        strengths_path = out / "strengths.csv"
        with strengths_path.open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["team", "strength", "roster_version_id", "prior_driven"])
            for name in sorted(strengths):
                writer.writerow(
                    [name, f"{strengths[name]:.6f}", resolved[name], name in prior_driven]
                )

        # The card comes from the D1 generator, fed OUR fitted strengths --
        # not from its synthetic fallback ladder.
        card_rc = cli_main(
            [
                "--strengths", str(strengths_path),
                "--rules", args.rules,
                "--n-sims", str(args.card_sims),
                "--seed", str(args.card_seed),
                "--out", str(out),
            ]
        )
        if card_rc != 0:
            raise SystemExit(f"card generation failed with exit code {card_rc}")
        card_status = f"generated from {selected} strengths ({len(strengths)} teams)"

        # Spec XII: report how much the card depends on the duration parameter.
        sweep = sensitivity_sweep(
            strengths,
            replace(rules, duration_log_sigma=duration_fit.log_sigma),
            [duration_fit.log_sigma, duration_fit.log_sigma * 0.5,
             duration_fit.log_sigma * 1.5, 0.25],
            n_sims=max(20_000, args.card_sims // 10),
            seed=args.card_seed,
        )
        (out / "duration_sensitivity.json").write_text(json.dumps(sweep, indent=2) + "\n")

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
        f"Interval method: {result.method}. Maps compared: {result.n_maps}.",
        "",
        "The interval is a **cluster** bootstrap, not an iid one over maps: maps "
        "inside a series share teams, day, patch and momentum, and treating them "
        "as independent would understate the interval and let this gate pass on noise.",
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
        "## Duration model (spec XII)",
        "",
        f"Fitted from {duration_fit.n} real map durations, conditioned on pre-match "
        f"rating gap: `log_mean={duration_fit.log_mean:.4f}`, "
        f"`log_sigma={duration_fit.log_sigma:.4f}`, "
        f"`gap_coefficient={duration_fit.gap_coefficient:.4f}` "
        f"(SE {duration_fit.gap_se:.4f}, material={duration_fit.material}). "
        "The placeholder was 7.65 / 0.25 with provenance `arbitrary`.",
        "",
        "## Card",
        "",
        f"Status: {card_status}. Final model: **{selected}** "
        f"({'gate passed' if result.passed else 'gate failed — Elo is the shipped fit'}).",
    ]
    if not args.skip_card and prior_driven:
        lines += [
            "",
            f"**Prior-driven teams ({len(prior_driven)}):** " + ", ".join(prior_driven)
            + ". These carry the average-team prior, not a fitted rating.",
        ]
    if not result.passed:
        lines += [
            "",
            "Spec §X rung 3 makes public ratings the default when this gate fails. "
            "To ship that instead, write a `team,strength` CSV and run "
            "`python -m ti26.cli --strengths <file>`.",
        ]
    if sweep:
        lines += [
            "",
            "## Duration sensitivity",
            "",
            "| log_sigma | max abs delta vs fitted |",
            "|---|---|",
        ] + [
            f"| {s['log_sigma']:.4f} | {s['max_abs_delta']:.5f} |" for s in sweep
        ] + [
            "",
            "Largest movement in any single category probability when the duration "
            "parameter is varied. Spec §XII: this parameter is consulted on roughly "
            "30% of every ranking, so its influence is reported rather than assumed away.",
        ]
    (out / "d2_gate.md").write_text("\n".join(lines) + "\n")

    print(f"gate: {verdict} (margin {result.margin:.5f}, CI [{result.ci_low:.5f}, "
          f"{result.ci_high:.5f}], {result.method})")
    print(f"card: {card_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Write the end-to-end test**

```python
# tests/test_cli_d2.py
import csv
import json

import pytest

from ti26.cli_d2 import main as d2_main
from ti26.data.schema import MapRow
from ti26.data.store import insert_rows, open_store

WEEK = 604800


def row(match_id, start_time, league_id, radiant, dire, radiant_win,
        r_team, d_team, series_id, duration=2000):
    return MapRow(
        match_id=match_id, start_time=start_time, duration=duration,
        radiant_win=radiant_win, league_id=league_id, tier="professional",
        radiant_team_id=r_team, dire_team_id=d_team,
        series_id=series_id, series_type=1, patch="7.41",
        radiant_accounts=tuple(radiant), dire_accounts=tuple(dire),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


def seeded_store(path, n_teams=16, n_series=1200, maps_per_series=3):
    """Deterministic ladder: lower-indexed rosters are genuinely stronger.

    Team ids are `1000 + index` so `config/ti2026_teams.yaml` fixtures can
    reference them; `hash()` would vary with PYTHONHASHSEED. Maps are grouped
    into real series so the clustered bootstrap has clusters to resample, and
    tournaments are spread across many league ids so the single-stage path is
    the one actually exercised.
    """
    import random

    rng = random.Random(4)
    rosters = [[t * 5 + p for p in range(5)] for t in range(n_teams)]
    strength = {t: (n_teams - t) * 0.2 for t in range(n_teams)}
    rows, match_id = [], 0
    for s in range(n_series):
        a, b = rng.sample(range(n_teams), 2)
        p = 1 / (1 + pow(2.718281828, -(strength[a] - strength[b])))
        # First 900 series are history; the rest are spread over 40 tournaments
        # so `rolling_folds` produces enough folds for tournament clustering.
        league = 1 if s < 900 else 100 + (s % 40)
        for _ in range(maps_per_series):
            rows.append(
                row(match_id, match_id * 600, league, rosters[a], rosters[b],
                    rng.random() < p, r_team=1000 + a, d_team=1000 + b, series_id=s,
                    duration=int(rng.lognormvariate(7.55, 0.33)))
            )
            match_id += 1
    conn = open_store(path)
    insert_rows(conn, rows)
    return conn


def write_team_config(path, n_teams=16):
    lines = ["teams:"]
    for t in range(n_teams):
        lines.append(f"  - {{name: Team{t:02d}, team_id: {1000 + t}}}")
    path.write_text("\n".join(lines) + "\n")
    return path


def test_end_to_end_produces_a_gate_report_and_metrics(tmp_path):
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    assert d2_main(
        ["--store", str(store), "--out", str(out), "--min-train", "200", "--skip-card"]
    ) == 0

    report = (out / "d2_gate.md").read_text()
    assert "**Verdict:" in report
    assert "0.003" in report, "the pre-registered margin must appear in the report"
    assert "cluster" in report.lower(), "the interval method must be stated"

    with (out / "backtest_metrics.csv").open() as fh:
        metrics = {r["model"]: r for r in csv.DictReader(fh)}
    assert set(metrics) == {"constant", "ewma", "elo", "glicko"}
    assert float(metrics["constant"]["log_loss"]) == pytest.approx(0.6931, abs=1e-3)


def test_the_card_is_built_from_fitted_strengths_not_the_synthetic_ladder(tmp_path):
    """THE end-to-end test for this task.

    D1's `cli.py` falls back to a synthetic ladder when `--strengths` is
    absent, so a runner that forgets to pass it still writes a plausible card
    and every other assertion here would pass. Pinning the card to the
    strengths file is what makes the pipeline real.
    """
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    teams = write_team_config(tmp_path / "teams.yaml")

    assert d2_main([
        "--store", str(store), "--out", str(out), "--min-train", "200",
        "--teams", str(teams), "--card-sims", "3000", "--card-seed", "7",
    ]) == 0

    with (out / "strengths.csv").open() as fh:
        strengths = list(csv.DictReader(fh))
    assert len(strengths) == 16
    assert {r["team"] for r in strengths} == {f"Team{t:02d}" for t in range(16)}
    assert len({r["strength"] for r in strengths}) > 1, "a flat vector means nothing was fitted"

    card = json.loads((out / "recommended_card.json").read_text())
    assert set(card["assignments"]) == {f"Team{t:02d}" for t in range(16)}, (
        "the card must name OUR teams; the synthetic ladder would emit t00..t15"
    )


def test_missing_teams_fail_loudly_rather_than_shipping_a_partial_card(tmp_path):
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    teams = write_team_config(tmp_path / "teams.yaml", n_teams=9)
    with pytest.raises(SystemExit, match="9 teams"):
        d2_main([
            "--store", str(store), "--out", str(tmp_path / "reports"),
            "--min-train", "200", "--teams", str(teams),
        ])


def test_duration_sensitivity_is_reported(tmp_path):
    """Spec XII requires reporting how far the card moves with the duration
    parameter, not just fitting it."""
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    teams = write_team_config(tmp_path / "teams.yaml")
    d2_main([
        "--store", str(store), "--out", str(out), "--min-train", "200",
        "--teams", str(teams), "--card-sims", "3000",
    ])
    sweep = json.loads((out / "duration_sensitivity.json").read_text())
    assert sweep[0]["is_baseline"] is True
    assert len(sweep) >= 3
    assert all("max_abs_delta" in s for s in sweep)


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

- [ ] **Step 8: Run the tests to verify they fail, then pass**

Run: `.venv/bin/python -m pytest tests/test_teams.py tests/test_cli_d2.py -v`
Expected first: FAIL with `ModuleNotFoundError`. After the implementation steps: PASS (12 tests).

`test_the_card_is_built_from_fitted_strengths_not_the_synthetic_ladder` is the load-bearing one. D1's `cli.py:15-16` silently falls back to a synthetic `t00..t15` ladder when `--strengths` is absent, so a runner that forgets to pass it still writes a complete, plausible-looking card — and every other assertion in the file still passes. Asserting the card names *our* teams is what makes the pipeline real rather than decorative.

- [ ] **Step 9: Run the real ingest**

```bash
.venv/bin/python -m ti26.cli_ingest --months 18
```
Expected: ~19 monthly lines totalling ≈41,600 maps, an immutable snapshot under `data/raw/<sid>/`, and `data/processed/d2.sqlite`. Record the snapshot id and the rejection tally in the ledger. If the row count is below 35,000, stop and report rather than proceeding — the spec's §III figures were measured on 2026-08-02 and a large shortfall means the query or the window is wrong.

- [ ] **Step 10: Run the real D2 evaluation**

If `config/ti2026_teams.yaml` is fully populated:

```bash
.venv/bin/python -m ti26.cli_d2
```

If the Swiss field is not yet known, run the gate alone and record in the ledger that the card is blocked on the team list:

```bash
.venv/bin/python -m ti26.cli_d2 --skip-card
```

Expected: `reports/d2_gate.md` with a verdict and the interval method, `reports/backtest_metrics.csv`, `reports/duration_fit.json`, and — unless skipped — `reports/strengths.csv`, `reports/duration_sensitivity.json`, `reports/recommended_card.json`.

**Report the verdict as it comes out.** A FAIL is a legitimate, pre-registered outcome meaning "ship the public-rating fallback and stop"; it is not a defect to be tuned away. Do not adjust `min_margin_nats`, `elo_k`, `glicko_tau`, `--min-train`, or the bootstrap clustering in response to seeing the result.

**Also report the cluster count.** If `d2_gate.md` says the two-stage method was used, that means fewer than 30 tournaments cleared `--min-train`, and the interval rests on a small number of clusters. Say so plainly rather than quoting the CI as if it came from 40.

- [ ] **Step 11: Write the fitted duration values into the rules config**

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

- [ ] **Step 12: Confirm the D1 suite still passes with the fitted values**

Run: `.venv/bin/python -m pytest -q`
Expected: all 427 D1 tests plus the new D2 tests pass. The D1 tests must not depend on the placeholder duration constants; if any fails, it was asserting against `7.65`/`0.25` rather than against behaviour, and that is a genuine defect to fix in the test, not a reason to revert the fitted values.

- [ ] **Step 13: Re-run the card on the fitted duration model**

Step 10 produced the card using the duration values that were in the config *at that time*. Step 11 changed them, so regenerate:

```bash
.venv/bin/python -m ti26.cli_d2
```

Compare `reports/duration_sensitivity.json` against the card: if `max_abs_delta` at the ±50% sigma settings exceeds ~0.02, say so in the ledger — it means a meaningful share of the card rests on a parameter with only this fit behind it.

- [ ] **Step 14: Lint and commit**

```bash
.venv/bin/ruff check .
git add src/ti26/cli_ingest.py src/ti26/cli_d2.py src/ti26/teams.py \
        tests/test_cli_d2.py tests/test_teams.py \
        config/ti2026_rules.yaml config/ti2026_teams.yaml
git commit -m "feat: ingest CLI, D2 gate runner, team resolution, fitted duration model"
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
| Fold integrity enforced | `run_model` calls `assert_fold_integrity`; `tests/test_backtest.py` proves each check fires |
| Snapshots immutable by mode | `grep -rn "open(" src/ti26/data/snapshot.py` shows only `"xb"` and read modes; no `exists()` guard |
| No silent row overwrites | `grep -rn "insert or replace" src/` returns nothing |
| Bootstrap is clustered | `reports/d2_gate.md` names the method; `test_clustered_interval_is_wider_than_the_iid_one` passes |
| Losses aligned by id | `paired_differences` raises on mismatched key sets; positional zipping absent from `src/` |
| Idle rosters lose certainty | `test_idle_rosters_lose_certainty_every_empty_period` and the multi-period cases pass |
| Inheritance is measured | `grep -rn "0\.8" src/ti26/ratings/glicko.py` returns nothing; weight comes from `continuity_with_predecessor` |
| Ingest completed | `data/raw/<sid>/manifest.json` exists with `total_rows` ≥ 35,000 |
| Gate reported honestly | `reports/d2_gate.md` states PASS or FAIL with the observed margin, CI, interval method and cluster count, and no config value was changed after the run |
| Duration model fitted **and conditioned** | `reports/duration_fit.json` carries a non-null `gap_coefficient` and `gap_se`; `config/ti2026_rules.yaml` carries `duration_model: empirical` |
| Sensitivity reported | `reports/duration_sensitivity.json` exists with ≥3 sigma settings |
| Engineering gate, end to end | `reports/strengths.csv` holds 16 fitted strengths and `reports/recommended_card.json` assigns **those 16 team names** — not `t00..t15` — to the derived capacities |

**Known limitations to carry forward, not to fix here:**

1. **`sensitivity_sweep` varies `log_sigma` only.** The fit also estimates a rating-gap coefficient, but D1's `DurationResolver` takes scalar `log_mean`/`log_sigma` and has no per-pair conditioning hook. If `duration_fit.material` comes back true, the fitted gap effect is *measured but not yet applied*, and the report must say so rather than implying the simulator uses it. Threading it through is a D3 decision.
2. **Tournament clustering assumes a league id identifies a tournament.** OpenDota league ids can span multi-stage events months apart, which would over-cluster and widen the interval. Conservative in the direction that makes the gate harder to pass, so it is acceptable here — but note the cluster count in the ledger.
