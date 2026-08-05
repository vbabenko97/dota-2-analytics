"""Immutable, timestamped raw snapshots.

Spec VII keeps `data/raw` immutable as its one non-negotiable reproducibility
guarantee: a fit is only re-runnable if the bytes it was fitted on still
exist exactly as fetched.
"""

import gzip
import hashlib
import json
import re
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SNAPSHOT_SCHEMA_VERSION = 1


class SnapshotIntegrityError(ValueError):
    """A raw snapshot is missing, malformed, or differs from its manifest."""


class SnapshotExistsError(FileExistsError):
    """A snapshot chunk already exists; snapshots are never overwritten."""


@dataclass(frozen=True)
class ValidatedSnapshotChunk:
    """A chunk whose exact bytes, digest, and decoded rows have been validated."""

    path: Path
    rows: tuple[dict, ...]


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
    _validate_chunk_name(name)
    directory = _create_snapshot_directory(root, sid)
    path = _write_destination(directory, f"{name}.json.gz")
    _exclusive_write(path, gzip.compress(json.dumps(rows).encode()))
    return path


def read_snapshot(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot_manifest_payload(
    sid: str,
    entries: list[dict],
    *,
    retrieved_at: str,
    source_endpoint: str = "https://api.opendota.com/api/explorer",
    source: str = "opendota /explorer",
) -> dict[str, object]:
    """Build the versioned, portable manifest payload for a raw snapshot."""
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_id": sid,
        "source": source,
        "source_endpoint": source_endpoint,
        "retrieved_at": retrieved_at,
        "total_rows": sum(entry["rows"] for entry in entries),
        "entries": entries,
    }


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_snapshot_id(sid: str) -> None:
    if not isinstance(sid, str) or not sid or Path(sid).is_absolute() or "/" in sid or "\\" in sid or ".." in sid:
        raise SnapshotIntegrityError("snapshot id must be a single relative path component")


def _validate_chunk_name(name: object) -> str:
    if (
        not isinstance(name, str)
        or not name
        or Path(name).is_absolute()
        or "/" in name
        or "\\" in name
        or ".." in name
    ):
        raise SnapshotIntegrityError("snapshot chunk name must be a single relative path component")
    return name


def _snapshot_directory(root: Path, sid: str) -> Path:
    _validate_snapshot_id(sid)
    directory = root / sid
    if directory.is_symlink():
        raise SnapshotIntegrityError(f"snapshot directory must not be a symlink: {sid}")
    try:
        resolved_root = root.resolve(strict=True)
        resolved_directory = directory.resolve(strict=True)
        resolved_directory.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise SnapshotIntegrityError(f"snapshot directory escapes raw root: {sid}") from exc
    if not resolved_directory.is_dir():
        raise SnapshotIntegrityError(f"snapshot directory is not a directory: {sid}")
    return resolved_directory


def _create_snapshot_directory(root: Path, sid: str) -> Path:
    _validate_snapshot_id(sid)
    try:
        root.mkdir(parents=True, exist_ok=True)
        directory = root / sid
        if directory.is_symlink():
            raise SnapshotIntegrityError(f"snapshot directory must not be a symlink: {sid}")
        directory.mkdir(exist_ok=True)
    except OSError as exc:
        raise SnapshotIntegrityError(f"unable to create snapshot directory: {sid}") from exc
    return _snapshot_directory(root, sid)


def _write_destination(directory: Path, filename: str) -> Path:
    path = directory / filename
    if path.is_symlink():
        raise SnapshotIntegrityError(f"snapshot destination must not be a symlink: {filename}")
    try:
        resolved_directory = directory.resolve(strict=True)
        resolved_path = path.resolve(strict=False)
        resolved_path.relative_to(resolved_directory)
    except (OSError, ValueError) as exc:
        raise SnapshotIntegrityError(f"snapshot destination escapes snapshot directory: {filename}") from exc
    return path


def _validate_manifest_payload(sid: str, payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise SnapshotIntegrityError("snapshot manifest must be a JSON object")
    if not _is_int(payload.get("schema_version")) or payload["schema_version"] != SNAPSHOT_SCHEMA_VERSION:
        raise SnapshotIntegrityError("unsupported snapshot manifest schema_version")
    if payload.get("snapshot_id") != sid:
        raise SnapshotIntegrityError("snapshot manifest snapshot_id does not match requested snapshot")
    if (
        not isinstance(payload.get("source"), str)
        or not payload["source"].strip()
        or payload["source"] != payload["source"].strip()
    ):
        raise SnapshotIntegrityError("snapshot manifest source must be a non-empty string")
    if (
        not isinstance(payload.get("source_endpoint"), str)
        or not payload["source_endpoint"].strip()
        or payload["source_endpoint"] != payload["source_endpoint"].strip()
    ):
        raise SnapshotIntegrityError("snapshot manifest source_endpoint must be a non-empty string")
    retrieved_at = payload.get("retrieved_at")
    if not isinstance(retrieved_at, str) or not retrieved_at.endswith("Z"):
        raise SnapshotIntegrityError("snapshot manifest retrieved_at must be a UTC string")
    try:
        parsed_retrieved_at = datetime.fromisoformat(retrieved_at)
    except ValueError as exc:
        raise SnapshotIntegrityError("snapshot manifest retrieved_at must be an ISO UTC timestamp") from exc
    if (
        parsed_retrieved_at.tzinfo != UTC
        or parsed_retrieved_at.isoformat().replace("+00:00", "Z") != retrieved_at
    ):
        raise SnapshotIntegrityError("snapshot manifest retrieved_at must be a canonical UTC timestamp")
    if not _is_int(payload.get("total_rows")) or payload["total_rows"] < 0:
        raise SnapshotIntegrityError("snapshot manifest total_rows must be a non-negative integer")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise SnapshotIntegrityError("snapshot manifest entries must be a non-empty list")
    if not all(isinstance(entry, dict) for entry in entries):
        raise SnapshotIntegrityError("snapshot manifest entries must be objects")
    return payload


def _validated_manifest(root: Path, sid: str) -> tuple[Path, dict[str, object]]:
    directory = _snapshot_directory(root, sid)
    path = directory / "manifest.json"
    try:
        if path.is_symlink():
            raise SnapshotIntegrityError("snapshot manifest must not be a symlink")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
        raise SnapshotIntegrityError(f"invalid snapshot manifest: {path}") from exc
    return directory, _validate_manifest_payload(sid, payload)


def _read_validated_chunk(path: Path, digest: str, rows: int) -> ValidatedSnapshotChunk:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise SnapshotIntegrityError(f"unable to read snapshot chunk: {path.name}") from exc
    if hashlib.sha256(payload).hexdigest() != digest:
        raise SnapshotIntegrityError(f"snapshot chunk sha256 mismatch: {path.name}")
    try:
        decoded = json.loads(gzip.decompress(payload))
    except (EOFError, OSError, UnicodeDecodeError, json.JSONDecodeError, zlib.error) as exc:
        raise SnapshotIntegrityError(f"snapshot chunk is not valid gzip JSON: {path.name}") from exc
    if not isinstance(decoded, list):
        raise SnapshotIntegrityError(f"snapshot chunk must contain a JSON list: {path.name}")
    if len(decoded) != rows:
        raise SnapshotIntegrityError(f"snapshot chunk row count mismatch: {path.name}")
    return ValidatedSnapshotChunk(path=path, rows=tuple(decoded))


def _validate_payload(
    directory: Path, sid: str, payload: dict[str, object]
) -> list[ValidatedSnapshotChunk]:
    if payload.get("snapshot_id") != sid:
        raise SnapshotIntegrityError("snapshot manifest snapshot_id does not match requested snapshot")
    entries = payload["entries"]
    manifest_total_rows = payload["total_rows"]
    assert isinstance(entries, list)
    assert _is_int(manifest_total_rows)
    chunks: list[ValidatedSnapshotChunk] = []
    names: set[str] = set()
    total_rows = 0
    try:
        resolved_directory = directory.resolve(strict=True)
    except OSError as exc:
        raise SnapshotIntegrityError(f"unable to resolve snapshot directory: {sid}") from exc

    for entry in entries:
        assert isinstance(entry, dict)
        name = _validate_chunk_name(entry.get("name"))
        rows = entry.get("rows")
        start = entry.get("start")
        end = entry.get("end")
        query = entry.get("query")
        digest = entry.get("sha256")
        if name in names:
            raise SnapshotIntegrityError(f"snapshot manifest has duplicate chunk {name}")
        if not _is_int(rows) or rows < 0 or not _is_int(start) or not _is_int(end) or start >= end:
            raise SnapshotIntegrityError(f"snapshot manifest has invalid metadata for {name}")
        if not isinstance(query, str) or not query.strip():
            raise SnapshotIntegrityError(f"snapshot manifest has an invalid query for {name}")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SnapshotIntegrityError(f"snapshot manifest has an invalid sha256 for {name}")

        chunk_path = directory / f"{name}.json.gz"
        if chunk_path.is_symlink():
            raise SnapshotIntegrityError(f"snapshot chunk must not be a symlink: {chunk_path.name}")
        try:
            resolved_chunk = chunk_path.resolve(strict=True)
            resolved_chunk.relative_to(resolved_directory)
        except (OSError, ValueError) as exc:
            raise SnapshotIntegrityError(f"snapshot chunk escapes snapshot directory: {chunk_path.name}") from exc
        if not chunk_path.is_file():
            raise SnapshotIntegrityError(f"snapshot chunk is missing: {chunk_path.name}")

        names.add(name)
        chunks.append(_read_validated_chunk(chunk_path, digest, rows))
        total_rows += rows

    try:
        actual_paths = set(directory.glob("*.json.gz"))
    except OSError as exc:
        raise SnapshotIntegrityError(f"unable to enumerate snapshot chunks: {sid}") from exc
    expected_paths = {chunk.path for chunk in chunks}
    if actual_paths != expected_paths:
        differences = actual_paths.symmetric_difference(expected_paths)
        raise SnapshotIntegrityError(
            "snapshot manifest chunk set mismatch: "
            + ", ".join(sorted(path.name for path in differences))
        )
    if total_rows != manifest_total_rows:
        raise SnapshotIntegrityError("snapshot manifest total_rows does not match entry row counts")
    return chunks


def validate_snapshot(root: Path, sid: str) -> list[ValidatedSnapshotChunk]:
    """Return validated decoded chunks in manifest order; never reopen untrusted rows."""
    directory, payload = _validated_manifest(root, sid)
    return _validate_payload(directory, sid, payload)


def write_manifest(
    root: Path,
    sid: str,
    entries: list[dict],
    *,
    retrieved_at: str,
    source_endpoint: str = "https://api.opendota.com/api/explorer",
    source: str = "opendota /explorer",
) -> Path:
    required_fields = {"name", "rows", "start", "end", "query", "sha256"}
    if (
        not isinstance(entries, list)
        or not entries
        or any(not isinstance(entry, dict) or not required_fields.issubset(entry) for entry in entries)
    ):
        raise SnapshotIntegrityError("snapshot manifest entries are missing required fields")
    if any(not _is_int(entry["rows"]) or entry["rows"] < 0 for entry in entries):
        raise SnapshotIntegrityError("snapshot manifest entry rows must be non-negative integers")
    payload = snapshot_manifest_payload(
        sid,
        entries,
        retrieved_at=retrieved_at,
        source_endpoint=source_endpoint,
        source=source,
    )
    directory = _create_snapshot_directory(root, sid)
    _validate_payload(directory, sid, _validate_manifest_payload(sid, payload))
    path = _write_destination(directory, "manifest.json")
    _exclusive_write(path, (json.dumps(payload, indent=2) + "\n").encode())
    validate_snapshot(root, sid)
    return path
