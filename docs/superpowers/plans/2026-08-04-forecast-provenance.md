# Forecast Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a committed raw snapshot, a rebuilt SQLite store, and every generated run bundle independently hash-verifiable from the repository without treating the SQLite file bytes as portable evidence.

**Architecture:** `ti26.data.snapshot` owns immutable raw chunks and validates the complete snapshot manifest before reload. A small new `ti26.provenance` module owns canonical JSON hashing, logical SQLite-store hashing, deterministic run-manifest construction, and fail-closed bundle verification; it has no forecast-model dependencies. `cli_ingest` is the only loader boundary: it validates a selected snapshot before normalizing a row, then records the rebuilt logical-store identity for later report-producing commands.

**Tech Stack:** Python 3.12 stdlib (`hashlib`, `json`, `sqlite3`, `platform`, `sys`), existing pytest and Ruff, SQLite, committed gzip JSON inputs, `.venv/bin/python`.

---

## File structure

- `src/ti26/data/snapshot.py` — snapshot-manifest schema, per-chunk digests, and strict pre-load validation.
- `src/ti26/cli_ingest.py` — use strict validation for `--snapshot`; record fresh-fetch query metadata required by the manifest.
- `src/ti26/provenance.py` — canonical hashing, logical store digest, run-manifest creation, and verification.
- `src/ti26/cli_provenance.py` — offline commands to print a store digest and verify a run bundle. This command must not fetch data.
- `tests/test_snapshot.py` — manifest validation and reload-tamper tests.
- `tests/test_provenance.py` — logical-store and run-bundle tamper tests.
- `.gitignore` — permit the explicitly pinned raw snapshot and future `reports/runs` bundles while retaining ignored scratch output.
- `data/raw/20260802T165535Z/` — the existing compressed input snapshot and an enriched generated `manifest.json`, committed as the historical pinned input. The identifier is an input label, not a claim about a result.

The manifest schemas below use `schema_version: 1` as a versioned input. Paths in every manifest are POSIX-relative to the repository root or the bundle root; absolute paths and `..` components are invalid.

### Task 1: Hash and validate immutable snapshot manifests

**Files:**
- Modify: `src/ti26/data/snapshot.py`
- Modify: `src/ti26/cli_ingest.py`
- Modify: `tests/test_snapshot.py`

- [ ] **Step 1: Add failing snapshot validation tests with mutation-killing docstrings**

Add these imports and tests to `tests/test_snapshot.py`. Keep the existing round-trip tests; add a docstring to every test added or changed in this task.

```python
from ti26.data.snapshot import SnapshotIntegrityError, validate_snapshot


def test_validate_snapshot_rejects_a_changed_chunk_before_rows_are_loaded(tmp_path):
    """Kills mutation: remove the SHA-256 comparison in validate_snapshot.

    The manifest's recorded digest remains for the original gzip bytes while
    the chunk is replaced with another valid gzip JSON payload.
    """
    sid = "example-snapshot"
    original = write_snapshot(tmp_path, sid, "part", [{"match_id": 1}])
    entry = {
        "name": "part",
        "rows": 1,
        "start": 10,
        "end": 20,
        "query": "select example",
        "sha256": sha256_file(original),
    }
    write_manifest(tmp_path, sid, [entry], retrieved_at="2026-08-04T00:00:00Z")
    original.write_bytes(gzip.compress(json.dumps([{"match_id": 2}]).encode()))

    with pytest.raises(SnapshotIntegrityError, match="sha256"):
        validate_snapshot(tmp_path, sid)


def test_validate_snapshot_rejects_an_unlisted_chunk(tmp_path):
    """Kills mutation: validate only manifest-listed chunks and ignore extras."""
    sid = "example-snapshot"
    listed = write_snapshot(tmp_path, sid, "listed", [{"match_id": 1}])
    entry = {
        "name": "listed",
        "rows": 1,
        "start": 10,
        "end": 20,
        "query": "select example",
        "sha256": sha256_file(listed),
    }
    write_manifest(tmp_path, sid, [entry], retrieved_at="2026-08-04T00:00:00Z")
    write_snapshot(tmp_path, sid, "unlisted", [{"match_id": 2}])

    with pytest.raises(SnapshotIntegrityError, match="unlisted"):
        validate_snapshot(tmp_path, sid)


def test_validate_snapshot_rejects_manifest_row_count_mismatch(tmp_path):
    """Kills mutation: trust entry['rows'] without decoding each chunk."""
    sid = "example-snapshot"
    chunk = write_snapshot(tmp_path, sid, "part", [{"match_id": 1}])
    write_manifest(
        tmp_path,
        sid,
        [{
            "name": "part", "rows": 2, "start": 10, "end": 20,
            "query": "select example", "sha256": sha256_file(chunk),
        }],
        retrieved_at="2026-08-04T00:00:00Z",
    )

    with pytest.raises(SnapshotIntegrityError, match="row count"):
        validate_snapshot(tmp_path, sid)
```

Add `hashlib` and `gzip` imports used by the test. Update every existing `write_manifest` call in this file to supply `retrieved_at`; any test that now expects a successful manifest must first write every named chunk and derive each `sha256` with `sha256_file`. In particular, rewrite `test_manifest_records_counts_and_query_for_each_chunk` to create `2025-02.json.gz` and `2025-03.json.gz` first, use the two resulting SHA-256 values in the entries, and assert the schema, endpoint, retrieval timestamp, total, and complete entries. Give it this docstring:

```python
"""Kills mutation: emit a manifest without the retrieval metadata schema."""
```

- [ ] **Step 2: Run snapshot tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_snapshot.py -q
```

Expected: collection fails because `SnapshotIntegrityError`, `validate_snapshot`, and/or `sha256_file` are not defined. Do not proceed if a test passes before its implementation exists.

- [ ] **Step 3: Implement the snapshot schema and strict validator**

In `src/ti26/data/snapshot.py`, add these exact public interfaces. Keep `write_snapshot` exclusive-create behavior unchanged.

```python
SNAPSHOT_SCHEMA_VERSION = 1


class SnapshotIntegrityError(ValueError):
    """A raw snapshot is missing, malformed, or differs from its manifest."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_snapshot(root: Path, sid: str) -> list[Path]:
    """Return validated chunks in manifest order; never load an unvalidated row."""
```

Implement `validate_snapshot` as follows:

1. Read exactly `root / sid / "manifest.json"`; reject a missing file or invalid JSON with `SnapshotIntegrityError`.
2. Require a JSON object with `schema_version == SNAPSHOT_SCHEMA_VERSION`, `snapshot_id == sid`, source endpoint string, UTC retrieval string, non-empty `entries` list, and integer `total_rows`.
3. For each entry require `name`, non-negative integer `rows`, integer `start` and `end`, non-empty string `query`, and a lowercase 64-hex-character `sha256`. Derive its path as `directory / f"{name}.json.gz"`; reject a name containing `/`, `\\`, or `..`.
4. Reject duplicate names, missing files, a digest mismatch, an invalid gzip/JSON list, or a decoded row count different from `rows`.
5. Compare the exact set of `*.json.gz` files in the directory with the paths named by the manifest; reject both missing and unexpected chunks.
6. Require `sum(entry["rows"] for entry in entries) == total_rows` and return paths in the manifest's entry order.

Change `write_manifest` to accept keyword-only `retrieved_at: str`, `source_endpoint: str = "https://api.opendota.com/api/explorer"`, and `source: str = "opendota /explorer"`. First extract the pure `snapshot_manifest_payload(...) -> dict[str, object]` helper so bootstrap tooling can regenerate the same manifest bytes. It must produce this canonical-shaped payload (normal JSON indentation is fine; hashing is performed elsewhere):

```python
{
    "schema_version": SNAPSHOT_SCHEMA_VERSION,
    "snapshot_id": sid,
    "source": source,
    "source_endpoint": source_endpoint,
    "retrieved_at": retrieved_at,
    "total_rows": sum(entry["rows"] for entry in entries),
    "entries": entries,
}
```

Require every entry passed to `write_manifest` to include the six fields checked above, then call `validate_snapshot(root, sid)` after the exclusive write so a producer cannot publish a self-inconsistent manifest. In `src/ti26/cli_ingest.py`, append each fresh entry with `query: sql` and `sha256: sha256_file(path)`, pass `now.isoformat().replace("+00:00", "Z")` as `retrieved_at`, and replace reload's `glob` block with `paths = validate_snapshot(raw_root, sid)`. Import the two new functions directly from `ti26.data.snapshot`.

- [ ] **Step 4: Run snapshot tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_snapshot.py -q
.venv/bin/python -m ruff check src/ti26/data/snapshot.py src/ti26/cli_ingest.py tests/test_snapshot.py
```

Expected: both commands pass. The validator must reject the byte-tampered but valid gzip fixture before `cli_ingest` can call `normalize_all`.

- [ ] **Step 5: Prove each new test rejects its named mutation**

Temporarily remove the digest comparison, then run only `test_validate_snapshot_rejects_a_changed_chunk_before_rows_are_loaded`; it must fail. Restore it. Temporarily replace the exact-set comparison with a subset comparison, run only `test_validate_snapshot_rejects_an_unlisted_chunk`; it must fail. Restore it. Temporarily delete the decoded-row-count branch, run only `test_validate_snapshot_rejects_manifest_row_count_mismatch`; it must fail. Restore all mutations and rerun the full snapshot test file.

- [ ] **Step 6: Commit the snapshot-validation slice**

```bash
git add src/ti26/data/snapshot.py src/ti26/cli_ingest.py tests/test_snapshot.py
git commit -m "feat: validate pinned raw snapshot chunks"
```

Commit body:

```text
Verified with tests/test_snapshot.py and Ruff; each new validator test was observed failing under its named mutation.
```

### Task 2: Add canonical hashing and logical SQLite-store identity

**Files:**
- Create: `src/ti26/provenance.py`
- Create: `tests/test_provenance.py`
- Modify: `src/ti26/data/store.py`

- [ ] **Step 1: Write failing logical-digest tests**

Create `tests/test_provenance.py` with this fixture and tests. Use the existing `row` helper from `tests/test_store.py` only by copying its small `MapRow` construction locally; tests must not depend on another test module.

```python
import sqlite3

from ti26.data.store import insert_rows, open_store
from ti26.provenance import logical_store_digest
from ti26.data.schema import MapRow


def _row(match_id: int, start_time: int, radiant_win: bool) -> MapRow:
    return MapRow(
        match_id=match_id, start_time=start_time, duration=100,
        radiant_win=radiant_win, league_id=1, tier="pro",
        radiant_team_id=10, dire_team_id=20, series_id=None, series_type=0,
        patch="x", radiant_accounts=(1, 2, 3, 4, 5),
        dire_accounts=(6, 7, 8, 9, 10), radiant_heroes=(1, 2, 3, 4, 5),
        dire_heroes=(6, 7, 8, 9, 10), has_null_team=False, has_bad_roster=False,
    )


def test_logical_store_digest_is_independent_of_insert_order(tmp_path):
    """Kills mutation: hash rows in insertion order rather than canonical match-id order."""
    first = open_store(tmp_path / "first.sqlite")
    second = open_store(tmp_path / "second.sqlite")
    rows = [_row(2, 20, False), _row(1, 10, True)]
    insert_rows(first, rows)
    insert_rows(second, list(reversed(rows)))

    assert logical_store_digest(first) == logical_store_digest(second)


def test_logical_store_digest_changes_when_a_stored_value_changes(tmp_path):
    """Kills mutation: digest only match ids and omit other stored values."""
    original = open_store(tmp_path / "original.sqlite")
    changed = open_store(tmp_path / "changed.sqlite")
    insert_rows(original, [_row(1, 10, True)])
    insert_rows(changed, [_row(1, 10, False)])

    assert logical_store_digest(original)["sha256"] != logical_store_digest(changed)["sha256"]
```

- [ ] **Step 2: Run logical-digest tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_provenance.py -q
```

Expected: collection fails because `ti26.provenance` and `logical_store_digest` do not exist.

- [ ] **Step 3: Implement deterministic store digest**

Create `src/ti26/provenance.py` with a single canonical JSON encoder and this interface:

```python
def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def logical_store_digest(conn: sqlite3.Connection) -> dict[str, int | str]:
    """Hash store schema and rows, not SQLite page-layout bytes."""
```

Import `SCHEMA` and `_COLUMNS` from `ti26.data.store`; move `_COLUMNS` to public `STORE_COLUMNS` first if Ruff/policy rejects importing a private name. The digest input is exactly:

```python
hasher.update(b"ti26-logical-store-v1\\0")
hasher.update(canonical_json_bytes({"schema": SCHEMA, "columns": STORE_COLUMNS}))
for record in conn.execute(
    f"select {','.join(STORE_COLUMNS)} from maps order by match_id"
):
    values = list(record)
    for index in (11, 12, 13, 14):
        values[index] = json.loads(values[index])
    hasher.update(b"\\n")
    hasher.update(canonical_json_bytes(values))
```

Count rows in the same loop and return exactly:

```python
{"algorithm": "sha256", "schema_version": 1, "row_count": count, "sha256": hasher.hexdigest()}
```

This normalizes JSON-array whitespace from SQLite before hashing, uses only durable logical values, and includes the schema text so a schema change changes the identity. Do not hash the `.sqlite` file itself.

- [ ] **Step 4: Run digest tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_provenance.py -q
.venv/bin/python -m ruff check src/ti26/provenance.py src/ti26/data/store.py tests/test_provenance.py
```

Expected: both tests and Ruff pass.

- [ ] **Step 5: Prove each digest test rejects its named mutation**

Temporarily remove `order by match_id`, run only `test_logical_store_digest_is_independent_of_insert_order`, and observe failure. Restore it. Temporarily replace `values` with `[values[0]]`, run only `test_logical_store_digest_changes_when_a_stored_value_changes`, and observe failure. Restore it and rerun `tests/test_provenance.py`.

- [ ] **Step 6: Commit the logical-store slice**

```bash
git add src/ti26/provenance.py src/ti26/data/store.py tests/test_provenance.py
git commit -m "feat: identify rebuilt stores by logical digest"
```

Commit body:

```text
Verified with tests/test_provenance.py and Ruff; each new digest test was observed failing under its named mutation.
```

### Task 3: Create and verify deterministic run bundles

**Files:**
- Modify: `src/ti26/provenance.py`
- Create: `src/ti26/cli_provenance.py`
- Modify: `tests/test_provenance.py`

- [ ] **Step 1: Write failing run-manifest tests**

Append these tests to `tests/test_provenance.py`. They use authored fixture contents, not historical forecast results.

```python
from ti26.provenance import (
    RunManifestError,
    render_report_prefix,
    verify_run_bundle,
    write_run_manifest,
)


def _descriptor(tmp_path):
    source = tmp_path / "input.yaml"
    source.write_text("seed: 1\\n")
    return {
        "schema_version": 1,
        "run_kind": "example",
        "source_revision": "a" * 40,
        "invocation": {"argv": ["example", "--seed", "1"], "seeds": [1]},
        "snapshot": {"snapshot_id": "example", "manifest_path": "input.yaml", "manifest_sha256": sha256_file(source)},
        "store": {"algorithm": "sha256", "schema_version": 1, "row_count": 0, "sha256": "b" * 64},
        "inputs": [{"path": "input.yaml", "sha256": sha256_file(source)}],
        "runtime": {"python": "test"},
    }


def test_verify_run_bundle_rejects_a_changed_report(tmp_path):
    """Kills mutation: skip SHA-256 validation for outputs ending in .md."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    descriptor = _descriptor(tmp_path)
    (bundle / "report.md").write_text(f"{render_report_prefix(descriptor)}\\noriginal\\n")
    manifest_path = write_run_manifest(bundle, descriptor, ["report.md"])
    manifest = json.loads(manifest_path.read_text())
    (bundle / "report.md").write_text(
        f"<!-- ti26-run: {manifest['run_id']} manifest.json -->\\ntampered\\n"
    )

    with pytest.raises(RunManifestError, match="report.md"):
        verify_run_bundle(bundle)


def test_verify_run_bundle_rejects_a_report_with_the_wrong_run_reference(tmp_path):
    """Kills mutation: verify report hashes but never bind report text to manifest run_id."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "report.md").write_text("<!-- ti26-run: wrong manifest.json -->\\nbody\\n")
    write_run_manifest(bundle, _descriptor(tmp_path), ["report.md"])

    with pytest.raises(RunManifestError, match="run reference"):
        verify_run_bundle(bundle)


def test_run_id_changes_when_invocation_input_changes(tmp_path):
    """Kills mutation: derive run_id from run_kind alone and ignore invocation metadata."""
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    first_descriptor = _descriptor(tmp_path)
    second_descriptor = _descriptor(tmp_path)
    (one / "report.md").write_text(f"{render_report_prefix(first_descriptor)}\\n")
    second_descriptor["invocation"]["seeds"] = [2]
    (two / "report.md").write_text(f"{render_report_prefix(second_descriptor)}\\n")
    first = write_run_manifest(one, first_descriptor, ["report.md"])
    second = write_run_manifest(two, second_descriptor, ["report.md"])

    assert json.loads(first.read_text())["run_id"] != json.loads(second.read_text())["run_id"]
```

Before the first test writes its report, adjust its text after manifest creation only to preserve the test's intentional output-hash mismatch. The report-reference test must keep the wrong reference unchanged through writing. Add `json`, `pytest`, and `sha256_file` imports as needed.

- [ ] **Step 2: Run run-manifest tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_provenance.py -q
```

Expected: collection fails because `RunManifestError`, `write_run_manifest`, and `verify_run_bundle` do not exist.

- [ ] **Step 3: Implement run-manifest writing and fail-closed verification**

Extend `src/ti26/provenance.py` with:

```python
RUN_MANIFEST_SCHEMA_VERSION = 1


class RunManifestError(ValueError):
    """A run bundle cannot substantiate its declared inputs or outputs."""


def run_id(descriptor: dict[str, object]) -> str:
    """Return SHA-256 of canonical manifest fields before outputs exist."""


def write_run_manifest(
    bundle: Path, descriptor: dict[str, object], output_paths: list[str]
) -> Path:
    """Write bundle/manifest.json after every declared output already exists."""


def verify_run_bundle(bundle: Path) -> dict[str, object]:
    """Fail closed on malformed paths, changed files, or unbound reports."""
```

`run_id` must reject descriptors missing exactly these keys: `schema_version`, `run_kind`, `source_revision`, `invocation`, `snapshot`, `store`, `inputs`, and `runtime`. Copy only those fields, canonical-encode them, and return `sha256`. It must reject any schema version other than `RUN_MANIFEST_SCHEMA_VERSION`; `source_revision` must be a 40-character lowercase Git SHA. It intentionally does not include outputs so its value is computable before reports can reference it.

`write_run_manifest` must:

1. reject an existing `bundle / "manifest.json"`;
2. require each supplied output to be a non-empty relative path under `bundle` with no `..`, require it exists and is a regular file, and reject duplicates;
3. add `run_id` and `outputs: [{"path": relative, "sha256": sha256_file(file)}]` to a copy of the descriptor;
4. write canonical JSON followed by one newline through exclusive create;
5. return `bundle / "manifest.json"`.

`verify_run_bundle` must parse exactly that file, recreate the run ID from its non-output descriptor fields, compare every declared input path and output path digest, and reject non-relative input paths. Input paths are relative to the repository root supplied as `repo_root: Path | None = None`, defaulting to `Path.cwd()`; call it as `verify_run_bundle(bundle, repo_root=tmp_path)` in tests. It must reject a missing digest, changed content, missing file, `../` escape, or duplicate path. For every declared Markdown output, require line one to equal:

```python
f"<!-- ti26-run: {manifest['run_id']} manifest.json -->"
```

This verifies the report-to-manifest direction. A later report producer is responsible for rendering all report numbers from a declared machine-readable result; no generic text parser is introduced here.

Create `src/ti26/cli_provenance.py` with a standard `main(argv: list[str] | None = None) -> int`. It has two mutually exclusive subcommands:

```text
store-digest --store PATH
verify-run --bundle PATH [--repo-root PATH]
snapshot-manifest --raw PATH --snapshot SID --replace-existing-manifest
```

`store-digest` and `verify-run` print canonical JSON of their function result and return zero. `snapshot-manifest` prints the generated manifest path and returns zero. Its only allowed replacement target is `raw / snapshot / "manifest.json"`, and it requires `--replace-existing-manifest` when that file exists. Let `SnapshotIntegrityError` and `RunManifestError` surface as a non-zero command failure; do not catch them into a success status. This CLI is offline and must not import `ti26.data.opendota`; pass the `MAP_QUERY` template into its snapshot-manifest helper from `cli_ingest` or move that constant into a network-free module first.

- [ ] **Step 4: Run GREEN tests after implementing the report-prefix primitive**

The manifest must hash the completed report, but the report needs the run ID. `render_report_prefix(descriptor) -> str` solves that cycle by returning the final prefix from `run_id(descriptor)` before any output is written. The test fixtures above already call this helper. Run:

```bash
.venv/bin/python -m pytest tests/test_provenance.py -q
.venv/bin/python -m ruff check src/ti26/provenance.py src/ti26/cli_provenance.py tests/test_provenance.py
```

Expected: all pass. The intentional changed-report test must fail only after it changes content; the wrong-reference test must fail while its output digest remains valid.

- [ ] **Step 5: Prove each run-manifest test rejects its named mutation**

Temporarily exempt `.md` files from output digest validation and observe `test_verify_run_bundle_rejects_a_changed_report` fail. Restore it. Temporarily remove the Markdown-first-line check and observe `test_verify_run_bundle_rejects_a_report_with_the_wrong_run_reference` fail. Restore it. Temporarily make `run_id` hash only `run_kind` and observe `test_run_id_changes_when_invocation_input_changes` fail. Restore it, then rerun `tests/test_provenance.py`.

- [ ] **Step 6: Commit the run-bundle primitive slice**

```bash
git add src/ti26/provenance.py src/ti26/cli_provenance.py tests/test_provenance.py
git commit -m "feat: bind generated runs to hash manifests"
```

Commit body:

```text
Verified with tests/test_provenance.py and Ruff; each new manifest test was observed failing under its named mutation.
```

### Task 4: Commit and rebuild the pinned raw snapshot

**Files:**
- Modify: `.gitignore`
- Modify: `data/raw/20260802T165535Z/manifest.json`
- Add: `data/raw/20260802T165535Z/*.json.gz` (the exact existing chunks; enumerate with `git status`, do not use a broad glob)
- Modify: `tests/test_snapshot.py` only if the existing manifest fixture needs a schema field to match Task 1

- [ ] **Step 1: Write a failing reload-boundary test**

Add this test to `tests/test_snapshot.py`; it exercises CLI I/O but does not touch network:

```python
from ti26.cli_ingest import main as ingest_main


def test_snapshot_reload_validates_before_opening_the_destination_store(tmp_path):
    """Kills mutation: cli_ingest reloads globbed chunks without validate_snapshot."""
    raw = tmp_path / "raw"
    sid = "example-snapshot"
    chunk = write_snapshot(raw, sid, "part", [{"not": "a normalizable map"}])
    write_manifest(
        raw,
        sid,
        [{
            "name": "part", "rows": 1, "start": 10, "end": 20,
            "query": "select example", "sha256": sha256_file(chunk),
        }],
        retrieved_at="2026-08-04T00:00:00Z",
    )
    chunk.write_bytes(gzip.compress(json.dumps([{"tampered": True}]).encode()))
    store = tmp_path / "processed" / "d2.sqlite"

    with pytest.raises(SnapshotIntegrityError):
        ingest_main(["--raw", str(raw), "--snapshot", sid, "--store", str(store)])
    assert not store.exists()
```

Add this producer test to `tests/test_provenance.py` as well:

```python
def test_snapshot_manifest_command_derives_chunk_digest_and_query(tmp_path):
    """Kills mutation: hash decoded JSON rather than the committed gzip chunk bytes."""
    raw = tmp_path / "raw"
    sid = "20260804T000000Z"
    chunk = write_snapshot(raw, sid, "part", [{"match_id": 1}])
    (raw / sid / "manifest.json").write_text(json.dumps({
        "snapshot_id": sid,
        "source": "opendota /explorer",
        "total_rows": 1,
        "entries": [{"name": "part", "rows": 1, "start": 10, "end": 20}],
    }))

    assert provenance_main([
        "snapshot-manifest", "--raw", str(raw), "--snapshot", sid,
        "--replace-existing-manifest",
    ]) == 0
    manifest = json.loads((raw / sid / "manifest.json").read_text())
    assert manifest["entries"][0]["sha256"] == sha256_file(chunk)
    assert manifest["entries"][0]["query"] == MAP_QUERY.format(start=10, end=20)
    assert validate_snapshot(raw, sid) == [chunk]
```

Import `main as provenance_main` from `ti26.cli_provenance` and `MAP_QUERY` from the module that owns the network-free query constant. If retaining the constant in `ti26.data.opendota` would cause the offline CLI to import networking code, move `MAP_QUERY` into new `ti26.data.queries` and update `cli_ingest` to import it from there. The new test's precise mutation is comparing the hash of `read_snapshot(chunk)`'s reserialized JSON instead of `sha256_file(chunk)`; gzip metadata makes those different byte sequences.

- [ ] **Step 2: Run the reload test to verify RED or an intentional first failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_snapshot.py::test_snapshot_reload_validates_before_opening_the_destination_store tests/test_provenance.py::test_snapshot_manifest_command_derives_chunk_digest_and_query -q
```

Expected: FAIL before Tasks 1 and 3 are implemented. If those tasks are already committed, both must PASS and are regression checks for the pinned-reload and bootstrap-producer boundaries.

- [ ] **Step 3: Generate the complete manifest from the existing immutable chunk bytes**

Do not fetch, recompress, rename, or overwrite any `.json.gz` chunk. Add a small offline `snapshot-manifest` subcommand to `src/ti26/cli_provenance.py` so the manifest is emitted by committed code rather than by an editor. It accepts `--raw PATH --snapshot SID --replace-existing-manifest`. Its inputs are the existing chunks, the prior manifest's `start`/`end` values, and the committed `MAP_QUERY` template. It derives `query` as `MAP_QUERY.format(start=entry["start"], end=entry["end"])`, derives `retrieved_at` from the parseable snapshot identifier in UTC, preserves the committed OpenDota endpoint, and derives each `sha256` with `sha256_file`. The explicit replace flag may replace only `raw / sid / "manifest.json"`; it must reject a different target. This is bootstrap metadata enrichment before the snapshot is first committed, not permission to overwrite raw chunks or a committed pinned manifest.

The committed `manifest.json` must validate with:

```bash
.venv/bin/python -m ti26.cli_provenance snapshot-manifest --raw data/raw --snapshot 20260802T165535Z --replace-existing-manifest
.venv/bin/python -c "from pathlib import Path; from ti26.data.snapshot import validate_snapshot; print([p.name for p in validate_snapshot(Path('data/raw'), '20260802T165535Z')])"
```

Expected: a list containing every committed `.json.gz` chunk exactly once. This is a producer check, not a published empirical result.

- [ ] **Step 4: Change ignore rules narrowly and stage only the pinned snapshot**

Replace the data/report portion of `.gitignore` with:

```gitignore
# Data — only deliberately pinned raw snapshots are tracked.
data/raw/*
!data/raw/*/
!data/raw/**/*.json.gz
!data/raw/**/manifest.json
data/interim/
data/processed/

# Generated output — tracked only when a reproducible run bundle deliberately adds it.
reports/*
!reports/runs/
!reports/runs/**
```

Before staging, inspect exactly which candidate files are unignored:

```bash
git check-ignore -v data/raw/20260802T165535Z/manifest.json
git status --short --untracked-files=all data/raw/20260802T165535Z
```

The first command should produce no ignore rule. Stage the manifest and enumerate each of the snapshot's present `.json.gz` files explicitly in the command after reviewing `git status`; do not stage any other raw snapshot or ignored processed store.

- [ ] **Step 5: Rebuild a fresh store and prove the logical identity is stable**

Use two distinct temporary directories so no existing processed artifact is read or overwritten:

```bash
snapshot_tmp_one=$(mktemp -d)
snapshot_tmp_two=$(mktemp -d)
.venv/bin/python -m ti26.cli_ingest --raw data/raw --snapshot 20260802T165535Z --store "$snapshot_tmp_one/d2.sqlite"
.venv/bin/python -m ti26.cli_ingest --raw data/raw --snapshot 20260802T165535Z --store "$snapshot_tmp_two/d2.sqlite"
.venv/bin/python -m ti26.cli_provenance store-digest --store "$snapshot_tmp_one/d2.sqlite"
.venv/bin/python -m ti26.cli_provenance store-digest --store "$snapshot_tmp_two/d2.sqlite"
```

Expected: both JSON objects are byte-for-byte identical. Record the resulting digest only in the generated run manifest that consumes this rebuilt store, never copy it into this authored plan, a code comment, or a commit message. If the logical digests differ, stop: report the differing invocation/output and do not publish a bundle.

- [ ] **Step 6: Prove the reload test rejects its named mutation, then run the affected suite**

Temporarily replace `validate_snapshot(raw_root, sid)` in `cli_ingest` with the former `glob("*.json.gz")` behavior. Run the focused reload test and observe it fail because the destination store is created or a normalization path is reached. Restore validation. Temporarily hash `canonical_json_bytes(read_snapshot(chunk))` in the snapshot-manifest producer rather than `sha256_file(chunk)`, run only `test_snapshot_manifest_command_derives_chunk_digest_and_query`, and observe failure. Restore byte hashing. Then run:

```bash
.venv/bin/python -m pytest tests/test_snapshot.py tests/test_provenance.py -q
.venv/bin/python -m ruff check .
git diff --check
```

Expected: all commands pass.

- [ ] **Step 7: Commit the pinned-input and rebuild slice**

```bash
git add .gitignore data/raw/20260802T165535Z/manifest.json \
  data/raw/20260802T165535Z/2025-02.json.gz \
  data/raw/20260802T165535Z/2025-03.json.gz \
  data/raw/20260802T165535Z/2025-04.json.gz \
  data/raw/20260802T165535Z/2025-05.json.gz \
  data/raw/20260802T165535Z/2025-06.json.gz \
  data/raw/20260802T165535Z/2025-07.json.gz \
  data/raw/20260802T165535Z/2025-08.json.gz \
  data/raw/20260802T165535Z/2025-09.json.gz \
  data/raw/20260802T165535Z/2025-10.json.gz \
  data/raw/20260802T165535Z/2025-11.json.gz \
  data/raw/20260802T165535Z/2025-12.json.gz \
  data/raw/20260802T165535Z/2026-01.json.gz \
  data/raw/20260802T165535Z/2026-02.json.gz \
  data/raw/20260802T165535Z/2026-03.json.gz \
  data/raw/20260802T165535Z/2026-04.json.gz \
  data/raw/20260802T165535Z/2026-05.json.gz \
  data/raw/20260802T165535Z/2026-06.json.gz \
  data/raw/20260802T165535Z/2026-07.json.gz \
  data/raw/20260802T165535Z/2026-08.json.gz tests/test_snapshot.py
git commit -m "data: pin and verify forecast input snapshot"
```

Commit body:

```text
Verified by strict snapshot reload into two fresh stores, equal logical-store digests, focused provenance tests, Ruff, and the named reload-mutation failure.
```

### Task 5: Require provenance primitives at every later publication boundary

**Files:**
- Modify: `src/ti26/provenance.py`
- Modify: `tests/test_provenance.py`
- Modify: `docs/superpowers/specs/2026-08-04-ti26-reproducible-forecast-design.md` only if an interface name above changes during implementation

- [ ] **Step 1: Add a failing manifest input-tamper test**

```python
def test_verify_run_bundle_rejects_a_changed_declared_input(tmp_path):
    """Kills mutation: validate outputs but not manifest-declared input digests."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    descriptor = _descriptor(tmp_path)
    prefix = render_report_prefix(descriptor)
    (bundle / "report.md").write_text(f"{prefix}\\nbody\\n")
    write_run_manifest(bundle, descriptor, ["report.md"])
    (tmp_path / "input.yaml").write_text("seed: 2\\n")

    with pytest.raises(RunManifestError, match="input.yaml"):
        verify_run_bundle(bundle, repo_root=tmp_path)
```

- [ ] **Step 2: Run it to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_provenance.py::test_verify_run_bundle_rejects_a_changed_declared_input -q
```

Expected: FAIL until `verify_run_bundle` checks the `inputs` array against `repo_root`.

- [ ] **Step 3: Implement input-path and input-digest checks**

In `verify_run_bundle`, process each `inputs` item using the same relative-path validator as outputs, except resolve it against `repo_root`. Reject `Path.is_absolute()`, `..` anywhere in `PurePosixPath(path).parts`, paths that do not exist as regular files, non-string `sha256`, and digest mismatches. Do not permit a caller to omit input validation because the run manifest exists; a manifest is evidence only when its declared inputs still match.

- [ ] **Step 4: Run GREEN and mutation verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_provenance.py -q
.venv/bin/python -m ruff check src/ti26/provenance.py tests/test_provenance.py
```

Temporarily skip the input-digest comparison, run only `test_verify_run_bundle_rejects_a_changed_declared_input`, observe failure, restore the comparison, and rerun the same focused test.

- [ ] **Step 5: Commit the publication-boundary guard**

```bash
git add src/ti26/provenance.py tests/test_provenance.py
git commit -m "fix: reject run bundles with changed declared inputs"
```

Commit body:

```text
Verified with tests/test_provenance.py and Ruff; the input-digest test was observed failing when its named validation was removed.
```

## Plan self-review

- Spec coverage: Task 1 supplies per-chunk SHA-256 metadata and fail-closed snapshot reload; Task 2 supplies a schema-plus-row logical store identity; Task 3 supplies deterministic manifests, output hashes, report references, and an offline verifier; Task 4 commits the pinned raw input and proves a two-rebuild equality; Task 5 closes the input-tamper gap. Configuration and lock-file hashing are represented by the generic `inputs` array and will be supplied by the gate/card/D4 producers in their separate plan.
- No unsupported result values: the only date, seed, identifiers, query strings, and fixture rows in this plan are authored test or invocation inputs. This plan deliberately does not state any snapshot row count, digest, model score, or card assignment.
- Placeholder scan: no `TODO`, `TBD`, “implement later”, “appropriate error handling”, or cross-task shorthand remains. Every code change has a concrete interface or algorithm, tests include their named mutation docstrings, and every TDD task has RED, GREEN, mutation, and commit commands.
- Type consistency: `sha256_file`, `validate_snapshot`, `logical_store_digest`, `run_id`, `render_report_prefix`, `write_run_manifest`, and `verify_run_bundle` have one spelling and compatible `Path`/dictionary interfaces throughout. `verify_run_bundle` receives `repo_root` for declared inputs and hashes output paths relative to its bundle.

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-04-forecast-provenance.md`. Execute it subagent-driven: one fresh implementer per task, then a spec-compliance review and a code-quality review before the next task. This plan does not authorize any network fetch, raw-chunk overwrite, gate change, card-structure change, or publication action.
