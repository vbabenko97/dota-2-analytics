"""Offline provenance inspection and snapshot-manifest generation.

This command never touches the network. It reads committed bytes and prints or
writes what they hash to.
"""

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ti26.data.queries import MAP_QUERY
from ti26.data.snapshot import (
    SnapshotIntegrityError,
    read_snapshot,
    sha256_file,
    write_manifest,
)
from ti26.provenance import canonical_json_bytes, logical_store_digest, verify_run_bundle


def _print_json(value: object) -> None:
    print(canonical_json_bytes(value).decode("utf-8"))


def _retrieved_at_from_snapshot_id(sid: str) -> str:
    """Derive the retrieval instant from the snapshot identifier, not the clock.

    A wall-clock stamp would make a regenerated manifest differ on every run,
    which would defeat the point of pinning the input.
    """
    try:
        stamp = datetime.strptime(sid, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise SnapshotIntegrityError(
            f"snapshot id {sid!r} is not a %Y%m%dT%H%M%SZ timestamp"
        ) from exc
    return stamp.isoformat().replace("+00:00", "Z")


def _enrich_entry(directory: Path, entry: object) -> dict[str, object]:
    """Carry a prior entry's counts forward and derive its query and digest.

    `rows` is carried, never recounted: the prior manifest is the only
    independent record of how many rows were fetched, so recomputing it from
    the chunk would make the check self-satisfying. The decoded length is
    compared against it here and again inside `write_manifest`.
    """
    if not isinstance(entry, dict):
        raise SnapshotIntegrityError("prior snapshot manifest entry must be an object")
    missing = {"name", "rows", "start", "end"} - set(entry)
    if missing:
        raise SnapshotIntegrityError(
            f"prior snapshot manifest entry is missing {sorted(missing)}"
        )
    name = entry["name"]
    chunk = directory / f"{name}.json.gz"
    if not chunk.is_file():
        raise SnapshotIntegrityError(f"snapshot chunk is missing: {chunk.name}")
    decoded = read_snapshot(chunk)
    if len(decoded) != entry["rows"]:
        raise SnapshotIntegrityError(
            f"snapshot chunk row count mismatch: {chunk.name} holds {len(decoded)} rows, "
            f"the prior manifest recorded {entry['rows']}"
        )
    return {
        "name": name,
        "rows": entry["rows"],
        "start": entry["start"],
        "end": entry["end"],
        "query": MAP_QUERY.format(start=entry["start"], end=entry["end"]),
        "sha256": sha256_file(chunk),
    }


def snapshot_manifest(raw: Path, sid: str, *, replace_existing: bool) -> Path:
    """Regenerate a snapshot manifest from its committed chunk bytes.

    Bootstrap metadata enrichment: it adds the per-chunk query and digest that
    a pre-provenance manifest lacks. It reads raw chunks and never writes them.
    """
    directory = raw / sid
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise SnapshotIntegrityError(f"no prior snapshot manifest at {manifest_path}")
    if not replace_existing:
        raise SnapshotIntegrityError(
            f"{manifest_path} exists; pass --replace-existing-manifest to regenerate it"
        )
    try:
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotIntegrityError(f"invalid prior snapshot manifest: {manifest_path}") from exc
    if not isinstance(prior, dict) or not isinstance(prior.get("entries"), list):
        raise SnapshotIntegrityError(f"invalid prior snapshot manifest: {manifest_path}")

    # Everything is computed and cross-checked before the prior manifest is
    # removed, so a failure here leaves the committed input untouched.
    entries = [_enrich_entry(directory, entry) for entry in prior["entries"]]
    retrieved_at = _retrieved_at_from_snapshot_id(sid)
    manifest_path.unlink()
    return write_manifest(raw, sid, entries, retrieved_at=retrieved_at)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect offline forecast provenance")
    commands = parser.add_subparsers(dest="command", required=True)
    store_digest = commands.add_parser("store-digest")
    store_digest.add_argument("--store", required=True)
    verify_run = commands.add_parser("verify-run")
    verify_run.add_argument("--bundle", required=True)
    verify_run.add_argument("--repo-root", default=None)
    verify_run.add_argument(
        "--against-revision",
        default=None,
        help=(
            "require the bundle to name this source revision; pass "
            "$(git rev-parse HEAD) to check that it still describes this tree, "
            "and omit it when verifying a historical bundle"
        ),
    )
    manifest = commands.add_parser("snapshot-manifest")
    manifest.add_argument("--raw", required=True)
    manifest.add_argument("--snapshot", required=True)
    manifest.add_argument("--replace-existing-manifest", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "store-digest":
        store = Path(args.store)
        connection = sqlite3.connect(f"file:{store.resolve()}?mode=ro", uri=True)
        try:
            _print_json(logical_store_digest(connection))
        finally:
            connection.close()
    elif args.command == "snapshot-manifest":
        written = snapshot_manifest(
            Path(args.raw), args.snapshot, replace_existing=args.replace_existing_manifest
        )
        print(written)
    else:
        repo_root = Path(args.repo_root) if args.repo_root is not None else None
        _print_json(
            verify_run_bundle(
                Path(args.bundle),
                repo_root=repo_root,
                against_revision=args.against_revision,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
