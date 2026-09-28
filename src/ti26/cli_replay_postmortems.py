"""Offline replay attestation for the frozen TI 2026 postmortems.

This command verifies a retrospective replay at the recorded producer revision.
It does not assert that either frozen report was generated at that revision:
the reports predate this attestation and carry their own frozen output digests.
"""

import argparse
import contextlib
import hashlib
import io
import json
import sqlite3
import subprocess
from pathlib import Path, PurePosixPath

from ti26 import cli_card_postmortem, cli_ingest, cli_playoff_postmortem
from ti26.data.snapshot import sha256_file, validate_snapshot
from ti26.provenance import canonical_json_bytes, logical_store_digest

MANIFEST_SCHEMA_VERSION = 1
DEFAULT_SNAPSHOT = "20260816T115509Z"
DEFAULT_MANIFESTS = (
    Path("reports/postmortems/group-replay.manifest.json"),
    Path("reports/postmortems/playoff-replay.manifest.json"),
)


class ReplayAttestationError(ValueError):
    """A replay input, tool, or frozen output differs from its attestation."""


def _sha256(path: Path) -> str:
    return sha256_file(path)


def _repo_file(repo_root: Path, value: object, label: str) -> tuple[str, Path]:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ReplayAttestationError(f"{label} must be a non-empty POSIX-relative path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or not relative.parts
        or "." in relative.parts
        or ".." in relative.parts
        or relative.as_posix() != value
    ):
        raise ReplayAttestationError(f"{label} must be a non-empty POSIX-relative path")
    path = repo_root.joinpath(*relative.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(repo_root)
    except (OSError, ValueError) as exc:
        raise ReplayAttestationError(f"{label} escapes the repository: {value}") from exc
    if path.is_symlink() or not path.is_file():
        raise ReplayAttestationError(f"{label} is not a regular file: {value}")
    return value, path


def _digest_entries(repo_root: Path, entries: object, label: str) -> list[dict[str, str]]:
    if not isinstance(entries, list) or not entries:
        raise ReplayAttestationError(f"{label} must be a non-empty list")
    checked: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ReplayAttestationError(f"{label} entry must contain path and sha256")
        path_text, path = _repo_file(repo_root, entry["path"], label)
        digest = entry["sha256"]
        if not isinstance(digest, str) or len(digest) != 64:
            raise ReplayAttestationError(f"{label} has an invalid sha256: {path_text}")
        if path_text in seen:
            raise ReplayAttestationError(f"{label} has a duplicate path: {path_text}")
        if _sha256(path) != digest:
            raise ReplayAttestationError(f"{label} sha256 mismatch: {path_text}")
        seen.add(path_text)
        checked.append({"path": path_text, "sha256": digest})
    return checked


def _git_blob_digest(repo_root: Path, revision: str, path: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"{revision}:{path}"],
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise ReplayAttestationError(f"source file absent at producer revision: {path}")
    return hashlib.sha256(result.stdout).hexdigest()


def load_and_verify_manifest(path: Path, repo_root: Path) -> dict[str, object]:
    """Load one static attestation and verify every bound repository input."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReplayAttestationError(f"invalid replay manifest: {path}") from exc
    required = {
        "schema_version",
        "kind",
        "attestation",
        "producer_source_revision",
        "producer_source_files",
        "replay_tooling",
        "inputs",
        "frozen_output",
        "invocation",
    }
    if not isinstance(manifest, dict):
        raise ReplayAttestationError("replay manifest must be an object")
    expected_keys = required | (
        {"store_path_normalization", "expected_store"}
        if manifest.get("kind") == "playoff"
        else set()
    )
    if set(manifest) != expected_keys:
        raise ReplayAttestationError("replay manifest has unsupported or missing keys")
    if manifest["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ReplayAttestationError("unsupported replay manifest schema_version")
    if manifest["attestation"] != "retrospective-replay-not-original-run-provenance":
        raise ReplayAttestationError("replay manifest does not state its retrospective scope")
    revision = manifest["producer_source_revision"]
    if (
        not isinstance(revision, str)
        or len(revision) != 40
        or any(char not in "0123456789abcdef" for char in revision)
    ):
        raise ReplayAttestationError("producer_source_revision must be a Git SHA")
    producer_files = _digest_entries(
        repo_root, manifest["producer_source_files"], "producer source"
    )
    for entry in producer_files:
        if _git_blob_digest(repo_root, revision, entry["path"]) != entry["sha256"]:
            raise ReplayAttestationError(
                f"producer source differs at producer revision: {entry['path']}"
            )
    _digest_entries(repo_root, manifest["replay_tooling"], "replay tooling")
    _digest_entries(repo_root, manifest["inputs"], "input")
    frozen = manifest["frozen_output"]
    if not isinstance(frozen, dict) or set(frozen) != {"path", "sha256"}:
        raise ReplayAttestationError("frozen_output must contain path and sha256")
    _digest_entries(repo_root, [frozen], "frozen output")
    if not isinstance(manifest["invocation"], list) or not all(
        isinstance(item, str) for item in manifest["invocation"]
    ):
        raise ReplayAttestationError("invocation must be a string list")
    return manifest


def _render(main, argv: list[str]) -> str:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = main(argv)
    if exit_code != 0:
        raise ReplayAttestationError(f"postmortem producer exited {exit_code}")
    return output.getvalue()


def _normalise_store_path(rendered: str, generated: Path, frozen_path: str) -> str:
    generated_text = str(generated)
    count = rendered.count(generated_text)
    if count != 1:
        raise ReplayAttestationError(f"expected one rendered store path, found {count}")
    return rendered.replace(generated_text, frozen_path)


def replay(
    *, repo_root: Path, raw: Path, snapshot: str, store: Path, manifests: tuple[Path, Path]
) -> dict[str, object]:
    """Build a new store and compare both reports to their frozen bytes."""
    if store.exists() or store.is_symlink():
        raise ReplayAttestationError(f"refusing to overwrite store: {store}")
    group_manifest, playoff_manifest = (
        load_and_verify_manifest(path, repo_root) for path in manifests
    )
    if group_manifest["kind"] != "group" or playoff_manifest["kind"] != "playoff":
        raise ReplayAttestationError("replay manifests must be group then playoff")
    snapshot_inputs = [
        entry for entry in playoff_manifest["inputs"] if entry["path"].endswith("/manifest.json")
    ]
    if len(snapshot_inputs) != 1:
        raise ReplayAttestationError("playoff manifest must bind one snapshot manifest")
    snapshot_input = snapshot_inputs[0]
    if snapshot_input["path"] != f"data/raw/{snapshot}/manifest.json":
        raise ReplayAttestationError("playoff manifest does not bind the requested snapshot")
    if _sha256(raw / snapshot / "manifest.json") != snapshot_input["sha256"]:
        raise ReplayAttestationError("requested snapshot manifest differs from attestation")
    validate_snapshot(raw, snapshot)
    store.parent.mkdir(parents=True, exist_ok=True)
    cli_ingest.main(["--raw", str(raw), "--snapshot", snapshot, "--store", str(store)])
    connection = sqlite3.connect(f"file:{store.resolve()}?mode=ro", uri=True)
    try:
        store_digest = logical_store_digest(connection)
    finally:
        connection.close()
    expected = playoff_manifest["expected_store"]
    if not isinstance(expected, dict) or set(expected) != {
        "algorithm",
        "schema_version",
        "row_count",
        "sha256",
    }:
        raise ReplayAttestationError("expected_store must be a logical-store digest")
    if store_digest != expected:
        raise ReplayAttestationError("rebuilt store logical digest differs from attestation")

    group_rendered = _render(cli_card_postmortem.main, list(group_manifest["invocation"]))
    group_frozen = repo_root / group_manifest["frozen_output"]["path"]
    if group_rendered.encode("utf-8") != group_frozen.read_bytes():
        raise ReplayAttestationError("group postmortem differs from frozen output")

    if playoff_manifest["invocation"].count("{store}") != 1:
        raise ReplayAttestationError("playoff invocation must contain one store placeholder")
    playoff_args = [
        str(store) if value == "{store}" else value for value in playoff_manifest["invocation"]
    ]
    playoff_rendered = _render(cli_playoff_postmortem.main, playoff_args)
    normalisation = playoff_manifest.get("store_path_normalization")
    if not isinstance(normalisation, dict) or set(normalisation) != {"frozen_path"}:
        raise ReplayAttestationError("playoff manifest has no exact store-path normalization")
    playoff_frozen = repo_root / playoff_manifest["frozen_output"]["path"]
    normalised = _normalise_store_path(playoff_rendered, store, normalisation["frozen_path"])
    if normalised.encode("utf-8") != playoff_frozen.read_bytes():
        raise ReplayAttestationError("playoff postmortem differs beyond its printed store path")
    return {
        "group": "byte-equal",
        "playoff": "equal-after-exact-store-path-normalization",
        "snapshot": snapshot,
        "store": store_digest,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--raw", default="data/raw")
    parser.add_argument("--store", required=True)
    parser.add_argument("--group-manifest", default=str(DEFAULT_MANIFESTS[0]))
    parser.add_argument("--playoff-manifest", default=str(DEFAULT_MANIFESTS[1]))
    args = parser.parse_args(argv)
    result = replay(
        repo_root=Path.cwd(),
        raw=Path(args.raw),
        snapshot=args.snapshot,
        store=Path(args.store),
        manifests=(Path(args.group_manifest), Path(args.playoff_manifest)),
    )
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
