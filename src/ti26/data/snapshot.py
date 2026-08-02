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
