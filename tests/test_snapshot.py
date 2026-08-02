import json
from datetime import UTC, datetime

import pytest

from ti26.data.snapshot import (
    SnapshotExistsError,
    read_snapshot,
    snapshot_id,
    write_manifest,
    write_snapshot,
)


def test_snapshot_id_is_sortable_utc():
    sid = snapshot_id(datetime(2026, 8, 3, 9, 5, 1, tzinfo=UTC))
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
