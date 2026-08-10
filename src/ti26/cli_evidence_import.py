"""Offline owner-capture importer for TI 2026 release evidence.

Every subcommand reads only local, owner-supplied bytes: a capture, a source
metadata JSON, an authority-registry JSON, and (for non-rules kinds) a facts
JSON. It resolves the actual Git `HEAD` for a real import through the one
fixed local-Git boundary, `clean_head_revision`, and otherwise makes no
subprocess or network call. Its audited production import graph is exactly
`argparse`, `hashlib`, `json`, `pathlib`, `subprocess`, and `ti26.evidence`.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from ti26.evidence import (
    EvidenceError,
    EvidenceExistsError,
    authoritative_source_keys_for,
    canonical_evidence_json_bytes,
    evidence_id_for_manifest,
    evidence_record_path,
    extract_ti2026_published_format,
    extract_ti2026_rules,
    load_evidence_catalog,
    load_source_registry,
    safe_relative_file,
    validate_evidence_manifest,
    validate_kind_payload,
    validate_record_sources,
    write_evidence_record,
)

_KIND_BY_COMMAND = {
    "rules": "rules",
    "rules-format": "rules",
    "participants": "participants",
    "rosters": "rosters",
    "draw": "draws",
}
_NORMALIZED_PATH_BY_KIND = {
    "participants": "participants.json",
    "rosters": "rosters.json",
    "draws": "draw.json",
}
_PUBLISHED_FORMAT_SUBJECT = "rules:ti2026:valve:published-format"
_SOURCE_KEYS = frozenset(
    {
        "source_url_key",
        "capture_method",
        "available_at_utc",
        "published_at_utc",
        "retrieved_at_utc",
        "assertion",
        "observed_at_utc",
        "supported_through_utc",
        "authoritative_source_keys_checked",
        "attestation",
        "construction",
    }
)
_SAFE_KEY_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")


def clean_head_revision(repo_root: Path) -> str:
    """Resolve the actual, clean Git `HEAD` -- the importer's sole subprocess use.

    No caller may supply a revision directly: this is the only place the
    importer trusts a working-tree state, and it insists that state is clean
    (including untracked files) before resolving `HEAD`.
    """
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.stdout.strip() or status.returncode != 0:
        raise EvidenceError("evidence import requires a clean Git checkout")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    revision = head.stdout.strip()
    if (
        head.returncode != 0
        or len(revision) != 40
        or any(char not in "0123456789abcdef" for char in revision)
    ):
        raise EvidenceError("cannot resolve a clean lower-case 40-hex HEAD revision")
    return revision


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_captures(raw: list[str]) -> dict[str, bytes]:
    """Parse `SOURCE_URL_KEY=PATH` pairs with no shell interpretation."""
    captures: dict[str, bytes] = {}
    for entry in raw:
        if "=" not in entry:
            raise EvidenceError(f"--capture must be SOURCE_URL_KEY=PATH: {entry!r}")
        key, _, path_text = entry.partition("=")
        if not key:
            raise EvidenceError(f"--capture source_url_key must be non-empty: {entry!r}")
        if key in captures:
            raise EvidenceError(f"--capture has a duplicate source_url_key: {key}")
        path = Path(path_text)
        if not path.is_file():
            raise EvidenceError(f"--capture path is not a regular file: {path}")
        captures[key] = path.read_bytes()
    return captures


def _load_source_metadata(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise EvidenceError(f"--source must be a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"--source is not valid JSON: {path}") from exc
    if not isinstance(payload, dict) or set(payload) != _SOURCE_KEYS:
        raise EvidenceError("--source metadata has unsupported or missing keys")
    return payload


def _safe_source_key_component(source_url_key: str) -> str:
    return "".join(char if char in _SAFE_KEY_CHARS else "-" for char in source_url_key)


def _capture_payload_path(command: str, source_url_key: str, primary_key: str) -> str:
    """Map one capture to its deterministic destination payload path."""
    if source_url_key == primary_key:
        if command == "rules":
            return "rendered.txt"
        if command == "rules-format":
            return "format-rendered.txt"
    return f"captures/{_safe_source_key_component(source_url_key)}.bin"


def _normalized_fact(
    command: str, kind: str, primary_bytes: bytes, facts_path: str | None, assertion: str
) -> tuple[str, bytes]:
    """Extract or validate-and-canonicalize the normalized fact payload.

    Returns `(payload_path, canonical_bytes)`, computed for every assertion --
    a dry run prints its digest even when it is never written -- but only a
    `present` observation ever declares it as a manifest payload.
    """
    if command == "rules":
        extracted = extract_ti2026_rules(primary_bytes.decode("utf-8"))
        return "extracted.json", canonical_evidence_json_bytes(extracted) + b"\n"
    if command == "rules-format":
        extracted = extract_ti2026_published_format(primary_bytes.decode("utf-8"))
        return "format-extracted.json", canonical_evidence_json_bytes(extracted) + b"\n"
    raw = json.loads(Path(facts_path).read_text(encoding="utf-8"))
    validated = validate_kind_payload(kind, raw, assertion=assertion)
    return _NORMALIZED_PATH_BY_KIND[kind], canonical_evidence_json_bytes(validated) + b"\n"


def validate_existing_exact(
    root: Path,
    kind: str,
    evidence_id: str,
    manifest: dict[str, object],
    payloads: dict[str, bytes],
) -> Path | None:
    """Return an existing destination only if it is complete and byte-identical.

    Pure preflight ahead of any `--supersedes`/current-tip validation: an
    absent destination returns `None` (genuinely new content, which still
    must clear supersession validation before anything is written); an
    existing but incomplete or divergent destination raises
    `EvidenceExistsError` without touching it. This mirrors
    `write_evidence_record`'s own reuse contract so an identical retry never
    has to satisfy supersession rules a second time.
    """
    destination = evidence_record_path(root, kind, evidence_id)
    if destination.is_symlink():
        raise EvidenceExistsError(f"evidence destination must not be a symlink: {destination}")
    if not destination.exists():
        return None
    if not destination.is_dir():
        raise EvidenceExistsError(
            f"evidence destination exists and is not a directory: {destination}"
        )
    manifest_path = destination / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise EvidenceExistsError(f"evidence destination is incomplete: {destination}")
    try:
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceExistsError(
            f"evidence destination manifest is unreadable: {destination}"
        ) from exc
    try:
        validate_evidence_manifest(destination, existing_manifest, verify_payloads=True)
    except EvidenceError as exc:
        raise EvidenceExistsError(f"evidence destination manifest is invalid: {destination}") from exc
    if canonical_evidence_json_bytes(existing_manifest) != canonical_evidence_json_bytes(manifest):
        raise EvidenceExistsError(
            f"evidence destination content differs from the requested record: {destination}"
        )
    for path_text, data in payloads.items():
        _, file_path = safe_relative_file(destination, path_text, "payload")
        if not file_path.is_file() or file_path.read_bytes() != data:
            raise EvidenceExistsError(
                f"evidence destination payload differs from requested bytes: {path_text}"
            )
    return destination


def _current_tip_ids(records: tuple, kind: str, subject_key: str) -> frozenset[str]:
    """Return every existing `(kind, subject_key)` record not superseded by another.

    Deliberately ignores any temporal cutoff: every record already published
    beneath `root` is current knowledge regardless of its own availability
    timestamp. Filtering by the *incoming* candidate's timestamp instead
    would let a backdated candidate claim no prior tip existed simply because
    existing evidence happens to declare a later `available_at_utc`.
    """
    matching = tuple(
        record for record in records if record.kind == kind and record.subject_key == subject_key
    )
    superseded = {predecessor for record in matching for predecessor in record.supersedes}
    return frozenset(record.evidence_id for record in matching if record.evidence_id not in superseded)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ti26.cli_evidence_import")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("rules", "rules-format", "participants", "rosters", "draw"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--root", required=True)
        sub.add_argument("--event-id", required=True)
        sub.add_argument("--subject-key", required=True)
        sub.add_argument("--source-registry", required=True)
        sub.add_argument("--source", required=True)
        sub.add_argument("--capture", action="append", default=[], required=True)
        sub.add_argument("--supersedes", action="append", default=[])
        sub.add_argument("--dry-run", action="store_true")
        if name in ("rules", "rules-format"):
            sub.add_argument("--facts", default=None)
        else:
            sub.add_argument("--facts", required=True)
    return parser


def _run_command(args: argparse.Namespace) -> Path | None:
    command = args.command
    kind = _KIND_BY_COMMAND[command]

    captures = _parse_captures(args.capture)
    source_meta = _load_source_metadata(Path(args.source))
    primary_key = source_meta["source_url_key"]

    if command in ("rules", "rules-format") and args.facts is not None:
        raise EvidenceError(f"{command} import forbids --facts")
    if command not in ("rules", "rules-format") and args.facts is None:
        raise EvidenceError(f"{command} import requires --facts")
    if command == "rules-format" and args.subject_key != _PUBLISHED_FORMAT_SUBJECT:
        raise EvidenceError(f"rules-format import accepts only subject {_PUBLISHED_FORMAT_SUBJECT!r}")

    assertion = source_meta["assertion"]
    if command in ("rules", "rules-format", "participants", "rosters") and assertion != "present":
        raise EvidenceError(f"{command} import accepts only a present observation")
    if command == "draw" and assertion not in ("present", "absent"):
        raise EvidenceError("draw import accepts only a present or absent observation")

    # A present observation's primary capture is load-bearing (it is the
    # sole extraction/attestation subject and must be `captures[0]`); an
    # absent observation's completeness is defined purely by the
    # registry-derived checked-authority set, independent of which source
    # `source.source_url_key` happens to name.
    if assertion == "present" and primary_key not in captures:
        raise EvidenceError(f"the primary capture is required: {primary_key}")
    primary_bytes = captures.get(primary_key, b"")

    if args.dry_run:
        for key in sorted(captures):
            path_name = _capture_payload_path(command, key, primary_key)
            print(f"{path_name} {_sha256_bytes(captures[key])}")
        _, fact_bytes = _normalized_fact(command, kind, primary_bytes, args.facts, assertion)
        print(f"facts {_sha256_bytes(fact_bytes)}")
        return None

    registry = load_source_registry(Path(args.source_registry))
    authorized = authoritative_source_keys_for(registry, kind, args.subject_key)
    if assertion == "present":
        for key in captures:
            if key not in authorized:
                raise EvidenceError(
                    f"capture source is not registered for {kind}:{args.subject_key}: {key}"
                )
        if source_meta["authoritative_source_keys_checked"]:
            raise EvidenceError("a present observation must not check any authority")
    else:
        checked = set(source_meta["authoritative_source_keys_checked"])
        if set(captures) != set(authorized) or checked != set(authorized):
            raise EvidenceError(
                "an absent observation must capture every registered authority, not a subset"
            )

    capture_entries: list[dict[str, str]] = []
    payload_bytes: dict[str, bytes] = {}
    for key in sorted(captures, key=lambda k: (k != primary_key, k)):
        path_name = _capture_payload_path(command, key, primary_key)
        payload_bytes[path_name] = captures[key]
        capture_entries.append({"source_url_key": key, "path": path_name})

    payloads_list: list[dict[str, str]] = []
    if assertion == "present":
        normalized_path, normalized_bytes = _normalized_fact(
            command, kind, primary_bytes, args.facts, assertion
        )
        payload_bytes[normalized_path] = normalized_bytes
        payloads_list.append({"path": normalized_path, "sha256": _sha256_bytes(normalized_bytes)})
    else:
        # Validate the owner's negative facts shape; a negative record
        # carries no normalized-fact payload of its own.
        _normalized_fact(command, kind, primary_bytes, args.facts, assertion)

    registry_bytes = Path(args.source_registry).read_bytes()
    registry_raw = json.loads(registry_bytes.decode("utf-8"))
    payload_bytes["authority-registry.json"] = registry_bytes
    payloads_list.append({"path": "authority-registry.json", "sha256": _sha256_bytes(registry_bytes)})
    for entry in capture_entries:
        payloads_list.append(
            {"path": entry["path"], "sha256": _sha256_bytes(captures[entry["source_url_key"]])}
        )

    source_field = {
        "source_url_key": primary_key,
        "capture_method": source_meta["capture_method"],
        "available_at_utc": source_meta["available_at_utc"],
        "published_at_utc": source_meta["published_at_utc"],
        "retrieved_at_utc": source_meta["retrieved_at_utc"],
    }
    observation_field = {
        "assertion": assertion,
        "observed_at_utc": source_meta["observed_at_utc"],
        "supported_through_utc": source_meta["supported_through_utc"],
        "captures": capture_entries,
        "authoritative_source_keys_checked": list(source_meta["authoritative_source_keys_checked"]),
        "diagnostic_reason": None,
    }
    authority_registry_field = {
        "schema": "ti26.evidence-authority-binding.v1",
        "path": "authority-registry.json",
        "sha256": _sha256_bytes(registry_bytes),
        "effective_at_utc": registry_raw["effective_at_utc"],
    }
    supersedes = sorted(set(args.supersedes))
    if len(supersedes) != len(args.supersedes):
        raise EvidenceError("--supersedes must not repeat an evidence id")

    manifest: dict[str, object] = {
        "schema": "ti26.evidence-manifest.v1",
        "evidence_id": "",
        "kind": kind,
        "event_id": args.event_id,
        "subject_key": args.subject_key,
        "source": source_field,
        "observation": observation_field,
        "attestation": source_meta["attestation"],
        "authority_registry": authority_registry_field,
        "construction": source_meta["construction"],
        "payloads": payloads_list,
        "supersedes": supersedes,
        "producer_revision": "0" * 40,
    }
    manifest["producer_revision"] = clean_head_revision(Path.cwd())
    manifest["evidence_id"] = evidence_id_for_manifest(manifest)
    evidence_id = manifest["evidence_id"]
    root = Path(args.root)

    existing = validate_existing_exact(root, kind, evidence_id, manifest, payload_bytes)
    if existing is not None:
        return existing

    destination = evidence_record_path(root, kind, evidence_id)
    candidate = validate_evidence_manifest(destination, manifest, verify_payloads=False)
    validate_record_sources(candidate, registry)

    catalog = load_evidence_catalog(root, registry)
    current_tips = _current_tip_ids(catalog, kind, args.subject_key)
    if set(supersedes) != current_tips:
        raise EvidenceError(
            "--supersedes must name every current same-subject tip: "
            f"expected {sorted(current_tips)}, got {supersedes}"
        )

    return write_evidence_record(root, manifest, payload_bytes)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        record = _run_command(args)
    except (EvidenceError, EvidenceExistsError, OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2  # pragma: no cover -- parser.error already raises SystemExit
    if record is not None:
        print(record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
