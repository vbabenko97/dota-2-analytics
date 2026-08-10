"""Canonical hashing for durable forecast provenance inputs."""

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path, PurePosixPath

from ti26.data.store import SCHEMA, STORE_COLUMNS

_JSON_ARRAY_INDICES = tuple(
    STORE_COLUMNS.index(column)
    for column in ("radiant_accounts", "dire_accounts", "radiant_heroes", "dire_heroes")
)

RUN_MANIFEST_SCHEMA_VERSION = 1
_RUN_DESCRIPTOR_KEYS = frozenset(
    {
        "schema_version",
        "run_kind",
        "source_revision",
        "invocation",
        "snapshot",
        "store",
        "inputs",
        "runtime",
    }
)


class RunManifestError(ValueError):
    """A run bundle cannot substantiate its declared inputs or outputs."""


def canonical_json_bytes(value: object) -> bytes:
    """Encode JSON values in the project's deterministic representation."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def _descriptor_fields(descriptor: dict[str, object]) -> dict[str, object]:
    if set(descriptor) != _RUN_DESCRIPTOR_KEYS:
        raise RunManifestError("run descriptor has unsupported or missing keys")
    if descriptor["schema_version"] != RUN_MANIFEST_SCHEMA_VERSION:
        raise RunManifestError("unsupported run manifest schema_version")
    revision = descriptor["source_revision"]
    if (
        not isinstance(revision, str)
        or len(revision) != 40
        or any(char not in "0123456789abcdef" for char in revision)
    ):
        raise RunManifestError("source_revision must be a lowercase 40-character Git SHA")
    return {key: descriptor[key] for key in sorted(_RUN_DESCRIPTOR_KEYS)}


def run_id(descriptor: dict[str, object]) -> str:
    """Return SHA-256 of canonical manifest fields before outputs exist."""
    try:
        payload = canonical_json_bytes(_descriptor_fields(descriptor))
    except (TypeError, ValueError) as exc:
        raise RunManifestError("run descriptor is not canonical JSON") from exc
    return hashlib.sha256(payload).hexdigest()


def render_report_prefix(descriptor: dict[str, object]) -> str:
    """Return the required first line for a report in this run bundle."""
    return f"<!-- ti26-run: {run_id(descriptor)} manifest.json -->"


def _bundle_root(bundle: Path) -> Path:
    try:
        if bundle.is_symlink() or not bundle.is_dir():
            raise RunManifestError("bundle must be a directory, not a symlink")
        return bundle.resolve(strict=True)
    except OSError as exc:
        raise RunManifestError(f"invalid bundle: {bundle}") from exc


def _relative_file(root: Path, value: object, label: str) -> tuple[str, Path]:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RunManifestError(f"{label} path must be a non-empty POSIX-relative path")
    relative = PurePosixPath(value)
    if (
        not relative.parts
        or relative.is_absolute()
        or ".." in relative.parts
        or "." in relative.parts
        or relative.as_posix() != value
    ):
        raise RunManifestError(f"{label} path must be a non-empty POSIX-relative path")
    path = root.joinpath(*relative.parts)
    ancestor = root
    for part in relative.parts:
        ancestor /= part
        if ancestor.is_symlink():
            raise RunManifestError(f"{label} path must not use a symlink: {value}")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise RunManifestError(f"{label} path escapes its root: {value}") from exc
    if not path.is_file():
        raise RunManifestError(f"{label} path is not a regular file: {value}")
    return value, path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest_entries(
    root: Path, entries: object, label: str, *, verify: bool
) -> list[dict[str, str]]:
    if not isinstance(entries, list):
        raise RunManifestError(f"{label} must be a list")
    result: list[dict[str, str]] = []
    paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise RunManifestError(f"{label} entry must contain path and sha256")
        path_text, path = _relative_file(root, entry["path"], label)
        digest = entry["sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise RunManifestError(f"{label} has an invalid sha256: {path_text}")
        if path_text in paths:
            raise RunManifestError(f"{label} has a duplicate path: {path_text}")
        paths.add(path_text)
        if verify and _sha256_file(path) != digest:
            raise RunManifestError(f"{label} sha256 mismatch: {path_text}")
        result.append({"path": path_text, "sha256": digest})
    return result


def write_run_manifest(
    bundle: Path, descriptor: dict[str, object], output_paths: list[str]
) -> Path:
    """Write bundle/manifest.json after every declared output already exists."""
    root = _bundle_root(bundle)
    manifest_path = root / "manifest.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        raise RunManifestError(f"run manifest already exists: {manifest_path}")
    paths: set[str] = set()
    outputs: list[dict[str, str]] = []
    for output_path in output_paths:
        path_text, path = _relative_file(root, output_path, "output")
        if path_text in paths:
            raise RunManifestError(f"output has a duplicate path: {path_text}")
        paths.add(path_text)
        outputs.append({"path": path_text, "sha256": _sha256_file(path)})
    fields = _descriptor_fields(descriptor)
    manifest = {**fields, "run_id": run_id(descriptor), "outputs": outputs}
    try:
        with manifest_path.open("xb") as file:
            file.write(canonical_json_bytes(manifest) + b"\n")
    except FileExistsError as exc:
        raise RunManifestError(f"run manifest already exists: {manifest_path}") from exc
    return manifest_path


def _load_run_manifest(bundle: Path) -> tuple[Path, dict[str, object], str]:
    root = _bundle_root(bundle)
    manifest_path = root / "manifest.json"
    try:
        if manifest_path.is_symlink():
            raise RunManifestError("run manifest must not be a symlink")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunManifestError(f"invalid run manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise RunManifestError("run manifest must be a JSON object")
    expected_keys = _RUN_DESCRIPTOR_KEYS | {"run_id", "outputs"}
    if set(manifest) != expected_keys:
        raise RunManifestError("run manifest has unsupported or missing keys")
    descriptor = {key: manifest[key] for key in _RUN_DESCRIPTOR_KEYS}
    expected_run_id = run_id(descriptor)
    if manifest["run_id"] != expected_run_id:
        raise RunManifestError("run manifest run_id does not match descriptor")
    return root, manifest, expected_run_id


def _verify_run_outputs(
    root: Path, manifest: dict[str, object], expected_run_id: str
) -> None:
    outputs = _digest_entries(root, manifest["outputs"], "output", verify=True)
    for output in outputs:
        if output["path"].endswith(".md"):
            first_line = (root / output["path"]).read_text(encoding="utf-8").split("\n", 1)[0]
            if first_line != f"<!-- ti26-run: {expected_run_id} manifest.json -->":
                raise RunManifestError(
                    f"report run reference mismatch: {output['path']}"
                )


def verify_run_bundle(
    bundle: Path, repo_root: Path | None = None, against_revision: str | None = None
) -> dict[str, object]:
    """Fail closed on malformed paths, changed files, or unbound reports.

    Every check here is INTERNAL: it establishes that a bundle still describes
    the bytes it was built from. It cannot establish that the current source
    tree still produces those bytes, and for a while it did not occur to anyone
    that those are different questions -- a rating-model defect was corrected,
    every published number moved, and this function went on exiting 0 on a
    bundle no longer reproducible from HEAD.

    Pass `against_revision` to close that gap: the bundle is then also required
    to name that revision as the source it was generated from. Callers that are
    verifying a HISTORICAL bundle should leave it unset, because an old bundle
    naming an old revision is correct rather than stale.
    """
    root, manifest, expected_run_id = _load_run_manifest(bundle)
    try:
        input_root = (repo_root or Path.cwd()).resolve(strict=True)
    except OSError as exc:
        raise RunManifestError("invalid repository root") from exc
    _digest_entries(input_root, manifest["inputs"], "input", verify=True)
    _verify_run_outputs(root, manifest, expected_run_id)
    if against_revision is not None and manifest["source_revision"] != against_revision:
        raise RunManifestError(
            f"run manifest names source revision {manifest['source_revision']}, "
            f"not {against_revision}; the bundle does not describe this tree"
        )
    return manifest


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
    )


def _historical_input_entries(entries: object) -> list[dict[str, str]]:
    if not isinstance(entries, list):
        raise RunManifestError("input must be a list")
    result: list[dict[str, str]] = []
    paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise RunManifestError("input entry must contain path and sha256")
        path_text = entry["path"]
        if not isinstance(path_text, str) or not path_text or "\\" in path_text:
            raise RunManifestError("input path must be a non-empty POSIX-relative path")
        relative = PurePosixPath(path_text)
        if (
            not relative.parts
            or relative.is_absolute()
            or ".." in relative.parts
            or "." in relative.parts
            or relative.as_posix() != path_text
        ):
            raise RunManifestError("input path must be a non-empty POSIX-relative path")
        digest = entry["sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise RunManifestError(f"input has an invalid sha256: {path_text}")
        if path_text in paths:
            raise RunManifestError(f"input has a duplicate path: {path_text}")
        paths.add(path_text)
        result.append({"path": path_text, "sha256": digest})
    return result


def _git_blob(repo_root: Path, revision: str, path: str) -> bytes:
    listing = _git(repo_root, "ls-tree", "-z", revision, "--", path)
    records = [record for record in listing.stdout.split(b"\0") if record]
    if listing.returncode != 0 or not records:
        raise RunManifestError(f"input absent at source_revision: {path}")
    try:
        header, raw_path = records[0].split(b"\t", 1)
        mode, kind, _ = header.split(b" ", 2)
        listed_path = raw_path.decode("utf-8")
    except (UnicodeDecodeError, ValueError) as exc:
        raise RunManifestError(f"invalid Git tree entry for input: {path}") from exc
    if len(records) != 1 or listed_path != path:
        raise RunManifestError(f"input absent at source_revision: {path}")
    if kind != b"blob" or mode not in {b"100644", b"100755"}:
        raise RunManifestError(
            f"input is not a regular blob at source_revision: {path}"
        )
    object_name = f"{revision}:{path}"
    blob = _git(repo_root, "cat-file", "blob", object_name)
    if blob.returncode != 0:
        raise RunManifestError(f"cannot read input blob at source_revision: {path}")
    return blob.stdout


def verify_run_bundle_at_source_revision(
    bundle: Path, *, repo_root: Path
) -> dict[str, object]:
    """Verify declared inputs as Git blobs at the manifest's source commit."""
    root, manifest, expected_run_id = _load_run_manifest(bundle)
    try:
        repository = repo_root.resolve(strict=True)
    except OSError as exc:
        raise RunManifestError("invalid repository root") from exc
    revision = manifest["source_revision"]
    commit_type = _git(repository, "cat-file", "-t", revision)
    if commit_type.returncode != 0 or commit_type.stdout != b"commit\n":
        raise RunManifestError(
            f"source_revision is not a local Git commit: {revision}"
        )
    for entry in _historical_input_entries(manifest["inputs"]):
        blob = _git_blob(repository, revision, entry["path"])
        if hashlib.sha256(blob).hexdigest() != entry["sha256"]:
            raise RunManifestError(f"input sha256 mismatch: {entry['path']}")
    _verify_run_outputs(root, manifest, expected_run_id)
    return manifest


def _live_store_schema(conn: sqlite3.Connection) -> dict[str, object]:
    """Return the durable `maps` table schema from the connected database."""
    return {
        "objects": [
            list(record)
            for record in conn.execute(
                """select type, name, tbl_name, sql from sqlite_schema
                   where name not like 'sqlite_%' and sql is not null
                   order by type, name, tbl_name, sql"""
            )
        ]
    }


def logical_store_digest(conn: sqlite3.Connection) -> dict[str, int | str]:
    """Hash store schema and rows, not SQLite page-layout bytes."""
    if conn.in_transaction:
        raise ValueError("cannot digest a store with an open transaction")
    conn.execute("begin")
    try:
        hasher = hashlib.sha256()
        hasher.update(b"ti26-logical-store-v1\0")
        hasher.update(canonical_json_bytes({"schema": SCHEMA, "columns": STORE_COLUMNS}))
        hasher.update(b"\n")
        hasher.update(canonical_json_bytes({"live_schema": _live_store_schema(conn)}))
        count = 0
        for record in conn.execute(f"select {','.join(STORE_COLUMNS)} from maps order by match_id"):
            values = list(record)
            for index in _JSON_ARRAY_INDICES:
                values[index] = json.loads(values[index])
            hasher.update(b"\n")
            hasher.update(canonical_json_bytes(values))
            count += 1
        return {
            "algorithm": "sha256",
            "schema_version": 1,
            "row_count": count,
            "sha256": hasher.hexdigest(),
        }
    finally:
        conn.rollback()
