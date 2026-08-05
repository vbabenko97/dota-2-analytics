import gzip
import json
import zlib
from datetime import UTC, datetime

import pytest

from ti26 import cli_ingest
from ti26.data.snapshot import (
    SnapshotExistsError,
    SnapshotIntegrityError,
    read_snapshot,
    sha256_file,
    snapshot_id,
    snapshot_manifest_payload,
    validate_snapshot,
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


@pytest.mark.parametrize("name", ["", "..", "../escaped", "nested/part", "nested\\part"])
def test_write_snapshot_rejects_unsafe_chunk_names(tmp_path, name):
    """Kills mutation: omit chunk-name validation from write_snapshot."""
    with pytest.raises(SnapshotIntegrityError, match="chunk name"):
        write_snapshot(tmp_path, "example-snapshot", name, [{"match_id": 1}])


def test_write_snapshot_rejects_a_symlinked_snapshot_directory(tmp_path):
    """Kills mutation: omit the write_snapshot directory symlink rejection."""
    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / "alias").symlink_to(target, target_is_directory=True)

    with pytest.raises(SnapshotIntegrityError, match="symlink"):
        write_snapshot(tmp_path, "alias", "part", [{"match_id": 1}])

    assert not (target / "part.json.gz").exists()


def test_write_snapshot_resolves_destination_before_exclusive_write(tmp_path):
    """Kills mutation: call _exclusive_write before resolving the chunk destination."""
    directory = tmp_path / "example-snapshot"
    directory.mkdir()
    outside = tmp_path / "outside.json.gz"
    outside.write_bytes(b"original")
    (directory / "part.json.gz").symlink_to(outside)

    with pytest.raises(SnapshotIntegrityError, match="symlink|escapes"):
        write_snapshot(tmp_path, "example-snapshot", "part", [{"match_id": 1}])

    assert outside.read_bytes() == b"original"


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
    """Kills mutation: write a manifest with overwrite mode instead of exclusive create."""
    chunk = write_snapshot(tmp_path, "20260803T090501Z", "2025-02", [{"a": 1}])
    entries = [
        {
            "name": "2025-02",
            "rows": 1,
            "start": 0,
            "end": 1,
            "query": "select example",
            "sha256": sha256_file(chunk),
        }
    ]
    write_manifest(tmp_path, "20260803T090501Z", entries, retrieved_at="2026-08-04T00:00:00Z")
    with pytest.raises(SnapshotExistsError):
        write_manifest(
            tmp_path, "20260803T090501Z", entries, retrieved_at="2026-08-04T00:00:00Z"
        )


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


@pytest.mark.parametrize(
    ("sid", "retrieved_at"),
    [
        ("20260803T090501Z", "2026-08-04T00:00:00Z"),
        ("20260804T090501Z", "2026-08-04T12:34:56Z"),
    ],
)
def test_manifest_records_counts_and_query_for_each_chunk(tmp_path, sid, retrieved_at):
    """Kills mutation: hardcode retrieved_at instead of using the supplied timestamp."""
    first = write_snapshot(
        tmp_path, sid, "2025-02", [{"match_id": 1}, {"match_id": 2}]
    )
    second = write_snapshot(tmp_path, sid, "2025-03", [{"match_id": 3}])
    entries = [
        {
            "name": "2025-02",
            "rows": 2,
            "start": 1738368000,
            "end": 1740787200,
            "query": "select february",
            "sha256": sha256_file(first),
        },
        {
            "name": "2025-03",
            "rows": 1,
            "start": 1740787200,
            "end": 1743465600,
            "query": "select march",
            "sha256": sha256_file(second),
        },
    ]
    path = write_manifest(tmp_path, sid, entries, retrieved_at=retrieved_at)
    manifest = json.loads(path.read_text())
    assert manifest["schema_version"] == 1
    assert manifest["snapshot_id"] == sid
    assert manifest["source_endpoint"] == "https://api.opendota.com/api/explorer"
    assert manifest["retrieved_at"] == retrieved_at
    assert manifest["total_rows"] == 3
    assert len(manifest["entries"]) == 2
    assert manifest["entries"] == entries


def test_manifest_total_rows_sums_chunk_rows(tmp_path):
    """Kills mutation: calculate total_rows as len(entries)."""
    sid = "example-snapshot"
    chunk = write_snapshot(tmp_path, sid, "part", [{"match_id": 1}, {"match_id": 2}])
    entry = {
        "name": "part",
        "rows": 2,
        "start": 10,
        "end": 20,
        "query": "select example",
        "sha256": sha256_file(chunk),
    }

    path = write_manifest(tmp_path, sid, [entry], retrieved_at="2026-08-04T00:00:00Z")

    assert json.loads(path.read_text())["total_rows"] == 2


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
    manifest_path = write_manifest(
        tmp_path,
        sid,
        [
            {
                "name": "part",
                "rows": 1,
                "start": 10,
                "end": 20,
                "query": "select example",
                "sha256": sha256_file(chunk),
            }
        ],
        retrieved_at="2026-08-04T00:00:00Z",
    )
    manifest = json.loads(manifest_path.read_text())
    manifest["entries"][0]["rows"] = 2
    manifest["total_rows"] = 2
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(SnapshotIntegrityError, match="row count"):
        validate_snapshot(tmp_path, sid)


def test_validate_snapshot_wraps_invalid_manifest_utf8_as_integrity_error(tmp_path):
    """Kills mutation: remove UnicodeDecodeError from the manifest read guard."""
    sid = "example-snapshot"
    chunk = write_snapshot(tmp_path, sid, "part", [{"match_id": 1}])
    manifest_path = write_manifest(
        tmp_path,
        sid,
        [
            {
                "name": "part",
                "rows": 1,
                "start": 10,
                "end": 20,
                "query": "select example",
                "sha256": sha256_file(chunk),
            }
        ],
        retrieved_at="2026-08-04T00:00:00Z",
    )
    manifest_path.write_bytes(b"\xff")

    with pytest.raises(SnapshotIntegrityError):
        validate_snapshot(tmp_path, sid)


def test_validate_snapshot_wraps_invalid_chunk_utf8_as_integrity_error(tmp_path):
    """Kills mutation: remove UnicodeDecodeError from the chunk decode guard."""
    sid = "example-snapshot"
    chunk = write_snapshot(tmp_path, sid, "part", [{"match_id": 1}])
    manifest_path = write_manifest(
        tmp_path,
        sid,
        [
            {
                "name": "part",
                "rows": 1,
                "start": 10,
                "end": 20,
                "query": "select example",
                "sha256": sha256_file(chunk),
            }
        ],
        retrieved_at="2026-08-04T00:00:00Z",
    )
    chunk.write_bytes(gzip.compress(b"\xff"))
    manifest = json.loads(manifest_path.read_text())
    manifest["entries"][0]["sha256"] = sha256_file(chunk)
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(SnapshotIntegrityError):
        validate_snapshot(tmp_path, sid)


def test_validate_snapshot_wraps_a_zlib_decode_error(tmp_path):
    """Kills mutation: remove zlib.error from the chunk decode guard."""
    sid = "example-snapshot"
    chunk = write_snapshot(tmp_path, sid, "part", [{"match_id": 1}])
    manifest_path = write_manifest(
        tmp_path,
        sid,
        [
            {
                "name": "part",
                "rows": 1,
                "start": 10,
                "end": 20,
                "query": "select example",
                "sha256": sha256_file(chunk),
            }
        ],
        retrieved_at="2026-08-04T00:00:00Z",
    )
    chunk.write_bytes(bytes.fromhex("1f8b0800000000000003") + b"not-deflate")
    manifest = json.loads(manifest_path.read_text())
    manifest["entries"][0]["sha256"] = sha256_file(chunk)
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(SnapshotIntegrityError) as caught:
        validate_snapshot(tmp_path, sid)

    assert isinstance(caught.value.__cause__, zlib.error)


@pytest.mark.parametrize("sid", ["../outside", "/tmp/absolute"])
def test_validate_snapshot_rejects_unsafe_snapshot_ids(tmp_path, sid):
    """Kills mutation: join an absolute or parent-traversal sid without containment checks."""
    with pytest.raises(SnapshotIntegrityError, match="snapshot id"):
        validate_snapshot(tmp_path, sid)


def test_validate_snapshot_rejects_a_chunk_symlink(tmp_path):
    """Kills mutation: remove the chunk_path.is_symlink() rejection."""
    sid = "example-snapshot"
    outside = tmp_path / "outside.json.gz"
    outside.write_bytes(gzip.compress(json.dumps([{"match_id": 1}]).encode()))
    directory = tmp_path / sid
    directory.mkdir()
    chunk = directory / "part.json.gz"
    chunk.symlink_to(outside)
    (directory / "manifest.json").write_text(
        json.dumps(
            snapshot_manifest_payload(
                sid,
                [
                    {
                        "name": "part",
                        "rows": 1,
                        "start": 10,
                        "end": 20,
                        "query": "select example",
                        "sha256": sha256_file(outside),
                    }
                ],
                retrieved_at="2026-08-04T00:00:00Z",
            )
        )
    )

    with pytest.raises(SnapshotIntegrityError, match="symlink"):
        validate_snapshot(tmp_path, sid)


def test_validate_snapshot_rejects_a_symlinked_snapshot_directory_within_root(tmp_path):
    """Kills mutation: omit the snapshot directory is_symlink() rejection."""
    sid = "alias"
    target = tmp_path / "target"
    target.mkdir()
    chunk = target / "part.json.gz"
    chunk.write_bytes(gzip.compress(json.dumps([{"match_id": 1}]).encode()))
    (target / "manifest.json").write_text(
        json.dumps(
            snapshot_manifest_payload(
                sid,
                [
                    {
                        "name": "part",
                        "rows": 1,
                        "start": 10,
                        "end": 20,
                        "query": "select example",
                        "sha256": sha256_file(chunk),
                    }
                ],
                retrieved_at="2026-08-04T00:00:00Z",
            )
        )
    )
    (tmp_path / sid).symlink_to(target, target_is_directory=True)

    with pytest.raises(SnapshotIntegrityError, match="symlink"):
        validate_snapshot(tmp_path, sid)


@pytest.mark.parametrize("value", [True, 1.0])
def test_validate_snapshot_rejects_noninteger_schema_version(tmp_path, value):
    """Kills mutation: compare schema_version by equality without checking integer type."""
    sid = "example-snapshot"
    chunk = write_snapshot(tmp_path, sid, "part", [{"match_id": 1}])
    manifest_path = write_manifest(
        tmp_path,
        sid,
        [
            {
                "name": "part",
                "rows": 1,
                "start": 10,
                "end": 20,
                "query": "select example",
                "sha256": sha256_file(chunk),
            }
        ],
        retrieved_at="2026-08-04T00:00:00Z",
    )
    manifest = json.loads(manifest_path.read_text())
    manifest["schema_version"] = value
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(SnapshotIntegrityError):
        validate_snapshot(tmp_path, sid)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("source", " "),
        ("source", " source"),
        ("source_endpoint", " "),
        ("source_endpoint", " https://api.opendota.com/api/explorer"),
    ],
)
def test_validate_snapshot_rejects_unstripped_source_metadata(tmp_path, key, value):
    """Kills mutation: replace stripped source checks with string truthiness checks."""
    sid = "example-snapshot"
    chunk = write_snapshot(tmp_path, sid, "part", [{"match_id": 1}])
    manifest_path = write_manifest(
        tmp_path,
        sid,
        [
            {
                "name": "part",
                "rows": 1,
                "start": 10,
                "end": 20,
                "query": "select example",
                "sha256": sha256_file(chunk),
            }
        ],
        retrieved_at="2026-08-04T00:00:00Z",
    )
    manifest = json.loads(manifest_path.read_text())
    manifest[key] = value
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(SnapshotIntegrityError):
        validate_snapshot(tmp_path, sid)


@pytest.mark.parametrize(
    "value", ["2026-08-04T00:00:00+00:00", "2026-99-04T00:00:00Z"]
)
def test_validate_snapshot_rejects_noncanonical_retrieval_timestamp(tmp_path, value):
    """Kills mutation: validate retrieved_at only by checking its Z suffix."""
    sid = "example-snapshot"
    chunk = write_snapshot(tmp_path, sid, "part", [{"match_id": 1}])
    manifest_path = write_manifest(
        tmp_path,
        sid,
        [
            {
                "name": "part",
                "rows": 1,
                "start": 10,
                "end": 20,
                "query": "select example",
                "sha256": sha256_file(chunk),
            }
        ],
        retrieved_at="2026-08-04T00:00:00Z",
    )
    manifest = json.loads(manifest_path.read_text())
    manifest["retrieved_at"] = value
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(SnapshotIntegrityError):
        validate_snapshot(tmp_path, sid)


def test_validate_snapshot_requires_start_before_end(tmp_path):
    """Kills mutation: remove the start >= end entry rejection."""
    sid = "example-snapshot"
    chunk = write_snapshot(tmp_path, sid, "part", [{"match_id": 1}])
    manifest_path = write_manifest(
        tmp_path,
        sid,
        [
            {
                "name": "part",
                "rows": 1,
                "start": 10,
                "end": 20,
                "query": "select example",
                "sha256": sha256_file(chunk),
            }
        ],
        retrieved_at="2026-08-04T00:00:00Z",
    )
    manifest = json.loads(manifest_path.read_text())
    manifest["entries"][0]["start"] = 20
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(SnapshotIntegrityError):
        validate_snapshot(tmp_path, sid)


def test_validate_snapshot_rejects_a_whitespace_query(tmp_path):
    """Kills mutation: replace query.strip() validation with string truthiness."""
    sid = "example-snapshot"
    chunk = write_snapshot(tmp_path, sid, "part", [{"match_id": 1}])
    manifest_path = write_manifest(
        tmp_path,
        sid,
        [
            {
                "name": "part",
                "rows": 1,
                "start": 10,
                "end": 20,
                "query": "select example",
                "sha256": sha256_file(chunk),
            }
        ],
        retrieved_at="2026-08-04T00:00:00Z",
    )
    manifest = json.loads(manifest_path.read_text())
    manifest["entries"][0]["query"] = " \t "
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(SnapshotIntegrityError):
        validate_snapshot(tmp_path, sid)


def test_write_manifest_rejects_invalid_payload_before_publishing(tmp_path):
    """Kills mutation: exclusively write a malformed manifest before prevalidation."""
    sid = "example-snapshot"
    chunk = write_snapshot(tmp_path, sid, "part", [{"match_id": 1}])
    entries = [
        {
            "name": "part",
            "rows": 1,
            "start": 10,
            "end": 20,
            "query": " ",
            "sha256": sha256_file(chunk),
        }
    ]

    with pytest.raises(SnapshotIntegrityError):
        write_manifest(tmp_path, sid, entries, retrieved_at="2026-08-04T00:00:00Z")

    assert not (tmp_path / sid / "manifest.json").exists()


def test_write_manifest_rejects_a_noninteger_row_count_before_summing(tmp_path):
    """Kills mutation: sum entry rows before validating their integer type."""
    sid = "example-snapshot"
    chunk = write_snapshot(tmp_path, sid, "part", [{"match_id": 1}])
    entries = [
        {
            "name": "part",
            "rows": "1",
            "start": 10,
            "end": 20,
            "query": "select example",
            "sha256": sha256_file(chunk),
        }
    ]

    with pytest.raises(SnapshotIntegrityError, match="rows"):
        write_manifest(tmp_path, sid, entries, retrieved_at="2026-08-04T00:00:00Z")

    assert not (tmp_path / sid / "manifest.json").exists()


def test_cli_ingest_tampered_reload_does_not_open_store_or_normalize(tmp_path, monkeypatch):
    """Kills mutation: call open_store before validate_snapshot on reload."""
    sid = "example-snapshot"
    chunk = write_snapshot(tmp_path, sid, "part", [{"match_id": 1}])
    entry = {
        "name": "part",
        "rows": 1,
        "start": 10,
        "end": 20,
        "query": "select example",
        "sha256": sha256_file(chunk),
    }
    write_manifest(tmp_path, sid, [entry], retrieved_at="2026-08-04T00:00:00Z")
    chunk.write_bytes(gzip.compress(json.dumps([{"match_id": 2}]).encode()))
    calls = []
    monkeypatch.setattr(cli_ingest, "open_store", lambda path: calls.append(("open_store", path)))
    monkeypatch.setattr(cli_ingest, "normalize_all", lambda rows: calls.append(("normalize_all", rows)))

    with pytest.raises(SnapshotIntegrityError):
        cli_ingest.main(["--snapshot", sid, "--raw", str(tmp_path), "--store", str(tmp_path / "x.sqlite")])

    assert calls == []


def test_cli_ingest_normalizes_rows_captured_during_validation(tmp_path, monkeypatch):
    """Kills mutation: reopen chunk.path after validate_snapshot returns captured rows."""
    sid = "example-snapshot"
    chunk = write_snapshot(tmp_path, sid, "part", [{"match_id": 1}])
    entry = {
        "name": "part",
        "rows": 1,
        "start": 10,
        "end": 20,
        "query": "select example",
        "sha256": sha256_file(chunk),
    }
    write_manifest(tmp_path, sid, [entry], retrieved_at="2026-08-04T00:00:00Z")
    real_validate_snapshot = cli_ingest.validate_snapshot

    def validate_then_tamper(root, snapshot_id):
        validated = real_validate_snapshot(root, snapshot_id)
        chunk.write_bytes(gzip.compress(json.dumps([{"match_id": 2}]).encode()))
        return validated

    normalized = []
    monkeypatch.setattr(cli_ingest, "validate_snapshot", validate_then_tamper)
    monkeypatch.setattr(cli_ingest, "open_store", lambda path: object())
    monkeypatch.setattr(
        cli_ingest,
        "normalize_all",
        lambda rows: (normalized.extend(rows) or [], {}),
    )
    monkeypatch.setattr(cli_ingest, "insert_rows", lambda conn, rows: 0)

    result = cli_ingest.main(
        ["--snapshot", sid, "--raw", str(tmp_path), "--store", str(tmp_path / "x.sqlite")]
    )

    assert result == 0
    assert normalized == [{"match_id": 1}]
