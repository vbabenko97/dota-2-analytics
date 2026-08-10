"""Exact, content-addressed evidence manifests for offline TI 2026 release facts.

This module owns the immutable evidence-manifest schema: canonical JSON
encoding, the content-addressed `evidence_id`, safe on-disk paths, and the
pure validator that turns a JSON object into a trusted `EvidenceManifest`.
It performs no I/O beyond reading the bytes a manifest already declares, and
it never imports a network-capable module.
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

_CHUNK_SIZE = 1024 * 1024

EVIDENCE_MANIFEST_SCHEMA = "ti26.evidence-manifest.v1"
_AUTHORITY_BINDING_SCHEMA = "ti26.evidence-authority-binding.v1"

_MANIFEST_KEYS = frozenset(
    {
        "schema",
        "evidence_id",
        "kind",
        "event_id",
        "subject_key",
        "source",
        "observation",
        "attestation",
        "authority_registry",
        "construction",
        "payloads",
        "supersedes",
        "producer_revision",
    }
)
_SOURCE_KEYS = frozenset(
    {"source_url_key", "capture_method", "available_at_utc", "published_at_utc", "retrieved_at_utc"}
)
_OBSERVATION_KEYS = frozenset(
    {
        "assertion",
        "observed_at_utc",
        "supported_through_utc",
        "captures",
        "authoritative_source_keys_checked",
        "diagnostic_reason",
    }
)
_CAPTURE_KEYS = frozenset({"source_url_key", "path"})
_ATTESTATION_KEYS = frozenset({"fact_payload_sha256", "capture_sha256s"})
_AUTHORITY_REGISTRY_KEYS = frozenset({"schema", "path", "sha256", "effective_at_utc"})
_PAYLOAD_ENTRY_KEYS = frozenset({"path", "sha256"})

_CONSTRUCTIONS = ("contemporaneous", "reconstructed_verified", "reconstructed_unknown")
_ASSERTIONS = ("present", "absent")


class EvidenceError(ValueError):
    """An evidence manifest, payload, or path violates its exact contract."""


@dataclass(frozen=True)
class PayloadDigest:
    path: str
    sha256: str


@dataclass(frozen=True)
class EvidenceCapture:
    source_url_key: str
    path: str


@dataclass(frozen=True)
class EvidenceSource:
    source_url_key: str
    capture_method: str
    available_at_utc: datetime
    published_at_utc: datetime | None
    retrieved_at_utc: datetime


@dataclass(frozen=True)
class EvidenceObservation:
    assertion: str
    observed_at_utc: datetime
    supported_through_utc: datetime
    captures: tuple[EvidenceCapture, ...]
    authoritative_source_keys_checked: tuple[str, ...]
    diagnostic_reason: str | None


@dataclass(frozen=True)
class EvidenceAttestation:
    fact_payload_sha256: str
    capture_sha256s: tuple[str, ...]


@dataclass(frozen=True)
class AuthorityRegistryBinding:
    schema: str
    path: str
    sha256: str
    effective_at_utc: datetime


@dataclass(frozen=True)
class EvidenceManifest:
    """A fully validated evidence record. `root` is runtime location metadata;

    it is never part of the semantic descriptor or the `evidence_id`.
    """

    root: Path
    schema: str
    evidence_id: str
    kind: str
    event_id: str
    subject_key: str
    source: EvidenceSource
    observation: EvidenceObservation
    attestation: EvidenceAttestation | None
    authority_registry: AuthorityRegistryBinding
    construction: str
    payloads: tuple[PayloadDigest, ...]
    supersedes: tuple[str, ...]
    producer_revision: str


def canonical_evidence_json_bytes(value: object) -> bytes:
    """Encode JSON values in the project's deterministic representation."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _require_nonempty_str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvidenceError(f"{label} must be a non-empty string")
    return value


def parse_utc(value: object, label: str) -> datetime:
    """Parse a strict, round-trip RFC 3339 UTC timestamp ending in `Z`."""
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EvidenceError(f"{label} must be a canonical RFC 3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise EvidenceError(f"{label} must be a canonical RFC 3339 UTC timestamp") from exc
    if parsed.tzinfo != UTC or parsed.isoformat().replace("+00:00", "Z") != value:
        raise EvidenceError(f"{label} must be a canonical RFC 3339 UTC timestamp")
    return parsed


def safe_relative_file(root: Path, value: object, label: str) -> tuple[str, Path]:
    """Validate a POSIX-relative path and lstat every component for a symlink."""
    if not isinstance(value, str) or not value or "\\" in value:
        raise EvidenceError(f"{label} must be a non-empty POSIX-relative path")
    relative = PurePosixPath(value)
    if (
        not relative.parts
        or relative.is_absolute()
        or ".." in relative.parts
        or "." in relative.parts
        or relative.as_posix() != value
    ):
        raise EvidenceError(f"{label} must be a non-empty POSIX-relative path")
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise EvidenceError(f"{label} must not use a symlink: {value}")
    return value, path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(_CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_descriptor(payload: dict[str, object]) -> dict[str, object]:
    """Return the semantic descriptor with every set-like field canonical-sorted."""
    descriptor = {key: value for key, value in payload.items() if key != "evidence_id"}
    supersedes = descriptor.get("supersedes")
    if isinstance(supersedes, list):
        descriptor["supersedes"] = sorted(set(supersedes))
    observation = descriptor.get("observation")
    if isinstance(observation, dict):
        checked = observation.get("authoritative_source_keys_checked")
        if isinstance(checked, list):
            descriptor["observation"] = {
                **observation,
                "authoritative_source_keys_checked": sorted(set(checked)),
            }
    attestation = descriptor.get("attestation")
    if isinstance(attestation, dict):
        captures = attestation.get("capture_sha256s")
        if isinstance(captures, list):
            descriptor["attestation"] = {**attestation, "capture_sha256s": sorted(set(captures))}
    return descriptor


def evidence_id_for_manifest(payload: dict[str, object]) -> str:
    """Return the content digest of `payload` without its own `evidence_id`."""
    if not isinstance(payload, dict) or set(payload) != _MANIFEST_KEYS:
        raise EvidenceError("evidence manifest has unsupported or missing keys")
    if not isinstance(payload.get("evidence_id"), str):
        raise EvidenceError("evidence_id must be a string")
    descriptor = _canonical_descriptor(payload)
    try:
        canonical = canonical_evidence_json_bytes(descriptor)
    except (TypeError, ValueError) as exc:
        raise EvidenceError("evidence manifest is not canonical JSON") from exc
    return hashlib.sha256(canonical).hexdigest()


def _validate_source(value: object) -> EvidenceSource:
    if not isinstance(value, dict) or set(value) != _SOURCE_KEYS:
        raise EvidenceError("source has unsupported or missing keys")
    source_url_key = _require_nonempty_str(value["source_url_key"], "source.source_url_key")
    capture_method = _require_nonempty_str(value["capture_method"], "source.capture_method")
    available_at_utc = parse_utc(value["available_at_utc"], "source.available_at_utc")
    retrieved_at_utc = parse_utc(value["retrieved_at_utc"], "source.retrieved_at_utc")
    published_raw = value["published_at_utc"]
    published_at_utc = (
        None if published_raw is None else parse_utc(published_raw, "source.published_at_utc")
    )
    return EvidenceSource(
        source_url_key=source_url_key,
        capture_method=capture_method,
        available_at_utc=available_at_utc,
        published_at_utc=published_at_utc,
        retrieved_at_utc=retrieved_at_utc,
    )


def _validate_payloads_shape(root: Path, value: object) -> tuple[PayloadDigest, ...]:
    if not isinstance(value, list) or not value:
        raise EvidenceError("payloads must be a non-empty list")
    seen_paths: set[str] = set()
    digests: list[PayloadDigest] = []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != _PAYLOAD_ENTRY_KEYS:
            raise EvidenceError("payload entry has unsupported or missing keys")
        path_text, _ = safe_relative_file(root, entry["path"], "payload")
        if path_text in seen_paths:
            raise EvidenceError(f"payload has a duplicate path: {path_text}")
        seen_paths.add(path_text)
        digest = entry["sha256"]
        if not _is_sha256(digest):
            raise EvidenceError(f"payload has an invalid sha256: {path_text}")
        digests.append(PayloadDigest(path=path_text, sha256=digest))
    return tuple(digests)


def _validate_authority_registry_shape(
    value: object, payload_digests: tuple[PayloadDigest, ...]
) -> AuthorityRegistryBinding:
    if not isinstance(value, dict) or set(value) != _AUTHORITY_REGISTRY_KEYS:
        raise EvidenceError("authority_registry has unsupported or missing keys")
    schema = value["schema"]
    if schema != _AUTHORITY_BINDING_SCHEMA:
        raise EvidenceError(f"authority_registry.schema must be {_AUTHORITY_BINDING_SCHEMA!r}")
    payload_by_path = {digest.path: digest for digest in payload_digests}
    path = value["path"]
    if not isinstance(path, str) or path not in payload_by_path:
        raise EvidenceError("authority_registry.path must equal one declared payload path")
    sha256 = value["sha256"]
    if not _is_sha256(sha256) or sha256 != payload_by_path[path].sha256:
        raise EvidenceError("authority_registry.sha256 must match its declared payload digest")
    effective_at_utc = parse_utc(value["effective_at_utc"], "authority_registry.effective_at_utc")
    return AuthorityRegistryBinding(
        schema=schema, path=path, sha256=sha256, effective_at_utc=effective_at_utc
    )


def _validate_observation(
    value: object, source: EvidenceSource, payload_digests: tuple[PayloadDigest, ...]
) -> EvidenceObservation:
    if not isinstance(value, dict) or set(value) != _OBSERVATION_KEYS:
        raise EvidenceError("observation has unsupported or missing keys")
    assertion = value["assertion"]
    if assertion not in _ASSERTIONS:
        raise EvidenceError("observation.assertion must be exactly present or absent")
    observed_at_utc = parse_utc(value["observed_at_utc"], "observation.observed_at_utc")
    supported_through_utc = parse_utc(
        value["supported_through_utc"], "observation.supported_through_utc"
    )
    payload_paths = {digest.path for digest in payload_digests}
    captures_raw = value["captures"]
    if not isinstance(captures_raw, list):
        raise EvidenceError("observation.captures must be a list")
    captures: list[EvidenceCapture] = []
    seen_capture_paths: set[str] = set()
    for entry in captures_raw:
        if not isinstance(entry, dict) or set(entry) != _CAPTURE_KEYS:
            raise EvidenceError("observation capture has unsupported or missing keys")
        capture_source_key = _require_nonempty_str(
            entry["source_url_key"], "observation capture source_url_key"
        )
        capture_path = entry["path"]
        if not isinstance(capture_path, str) or capture_path not in payload_paths:
            raise EvidenceError("observation capture path must reference a declared payload path")
        if capture_path in seen_capture_paths:
            raise EvidenceError(f"observation has a duplicate capture path: {capture_path}")
        seen_capture_paths.add(capture_path)
        captures.append(EvidenceCapture(source_url_key=capture_source_key, path=capture_path))
    checked_raw = value["authoritative_source_keys_checked"]
    if not isinstance(checked_raw, list) or not all(
        isinstance(key, str) and key for key in checked_raw
    ):
        raise EvidenceError(
            "observation.authoritative_source_keys_checked must be a list of non-empty strings"
        )
    if len(set(checked_raw)) != len(checked_raw):
        raise EvidenceError("observation.authoritative_source_keys_checked must not repeat a key")
    diagnostic_reason = value["diagnostic_reason"]
    if diagnostic_reason is not None and not isinstance(diagnostic_reason, str):
        raise EvidenceError("observation.diagnostic_reason must be a string or null")

    if assertion == "present":
        if not captures:
            raise EvidenceError("a present observation requires at least one capture")
        if captures[0].source_url_key != source.source_url_key:
            raise EvidenceError(
                "a present observation's primary capture must match source.source_url_key"
            )
        if checked_raw:
            raise EvidenceError("a present observation must not check any authority")
    else:
        checked_set = set(checked_raw)
        captured_set = {capture.source_url_key for capture in captures}
        if not checked_set:
            raise EvidenceError("an absent observation must check at least one authority")
        if checked_set != captured_set:
            raise EvidenceError(
                "an absent observation must bind one capture for every checked authority"
            )

    return EvidenceObservation(
        assertion=assertion,
        observed_at_utc=observed_at_utc,
        supported_through_utc=supported_through_utc,
        captures=tuple(captures),
        authoritative_source_keys_checked=tuple(sorted(checked_raw)),
        diagnostic_reason=diagnostic_reason,
    )


def _validate_attestation(
    value: object,
    observation: EvidenceObservation,
    payload_digests: tuple[PayloadDigest, ...],
    authority_registry: AuthorityRegistryBinding,
) -> EvidenceAttestation | None:
    if observation.assertion == "absent":
        if value is not None:
            raise EvidenceError("an absent observation must not carry an attestation")
        return None
    if not isinstance(value, dict) or set(value) != _ATTESTATION_KEYS:
        raise EvidenceError("attestation has unsupported or missing keys")
    fact_payload_sha256 = value["fact_payload_sha256"]
    if not _is_sha256(fact_payload_sha256):
        raise EvidenceError("attestation.fact_payload_sha256 must be a sha256 digest")
    capture_sha256s = value["capture_sha256s"]
    if not isinstance(capture_sha256s, list) or not all(_is_sha256(v) for v in capture_sha256s):
        raise EvidenceError("attestation.capture_sha256s must be a list of sha256 digests")
    if capture_sha256s != sorted(set(capture_sha256s)):
        raise EvidenceError("attestation.capture_sha256s must be a duplicate-free sorted digest list")
    capture_paths = {capture.path for capture in observation.captures}
    payload_by_path = {digest.path: digest for digest in payload_digests}
    expected_capture_digests = sorted({payload_by_path[path].sha256 for path in capture_paths})
    if capture_sha256s != expected_capture_digests:
        raise EvidenceError("attestation.capture_sha256s does not match its referenced captures")
    excluded_paths = capture_paths | {authority_registry.path}
    remaining = [digest for digest in payload_digests if digest.path not in excluded_paths]
    if len(remaining) != 1:
        raise EvidenceError("a positive record must declare exactly one normalized fact payload")
    if fact_payload_sha256 != remaining[0].sha256:
        raise EvidenceError(
            "attestation.fact_payload_sha256 does not match the normalized fact payload"
        )
    return EvidenceAttestation(
        fact_payload_sha256=fact_payload_sha256, capture_sha256s=tuple(capture_sha256s)
    )


def _validate_timestamp_ordering(source: EvidenceSource, observation: EvidenceObservation) -> None:
    if source.published_at_utc is not None:
        ordered = (
            source.published_at_utc
            <= source.available_at_utc
            <= observation.observed_at_utc
            <= source.retrieved_at_utc
        )
        if not ordered:
            raise EvidenceError(
                "published_at_utc, available_at_utc, observed_at_utc, and retrieved_at_utc "
                "must be non-decreasing"
            )
    else:
        ordered = (
            source.available_at_utc <= observation.observed_at_utc <= source.retrieved_at_utc
        )
        if not ordered:
            raise EvidenceError(
                "available_at_utc, observed_at_utc, and retrieved_at_utc must be non-decreasing"
            )
    if observation.supported_through_utc != observation.observed_at_utc:
        raise EvidenceError(
            "observation.supported_through_utc must equal observed_at_utc; "
            "no freshness allowance is registered"
        )


def _validate_supersedes(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(_is_sha256(v) for v in value):
        raise EvidenceError("supersedes must be a list of evidence ids")
    if len(set(value)) != len(value):
        raise EvidenceError("supersedes must not repeat an evidence id")
    return tuple(sorted(value))


def _validate_producer_revision(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise EvidenceError("producer_revision must be a lowercase 40-character Git SHA")
    return value


def _verify_authority_registry_bytes(root: Path, authority_registry: AuthorityRegistryBinding) -> None:
    _, path = safe_relative_file(root, authority_registry.path, "authority_registry.path")
    if not path.is_file():
        raise EvidenceError(f"authority_registry payload is missing: {authority_registry.path}")
    if _sha256_file(path) != authority_registry.sha256:
        raise EvidenceError(f"authority_registry sha256 mismatch: {authority_registry.path}")


def _verify_all_payload_bytes(
    root: Path, payload_digests: tuple[PayloadDigest, ...], *, already_verified: str
) -> None:
    for digest in payload_digests:
        if digest.path == already_verified:
            continue
        _, path = safe_relative_file(root, digest.path, "payload")
        if not path.is_file():
            raise EvidenceError(f"payload is missing: {digest.path}")
        if _sha256_file(path) != digest.sha256:
            raise EvidenceError(f"payload sha256 mismatch: {digest.path}")


def validate_evidence_manifest(
    root: Path, payload: object, *, verify_payloads: bool = True
) -> EvidenceManifest:
    """Validate the exact evidence-manifest contract and return a trusted record.

    All schema, identifier, timestamp, and path-shape validation happens
    before any filesystem lookup. With `verify_payloads=True`, every declared
    payload's bytes -- starting with the bound authority registry -- are
    re-hashed against their declared digests.
    """
    if not isinstance(payload, dict):
        raise EvidenceError("evidence manifest must be a JSON object")
    computed_id = evidence_id_for_manifest(payload)

    schema = payload["schema"]
    if schema != EVIDENCE_MANIFEST_SCHEMA:
        raise EvidenceError(f"evidence manifest schema must be {EVIDENCE_MANIFEST_SCHEMA!r}")
    kind = _require_nonempty_str(payload["kind"], "kind")
    event_id = _require_nonempty_str(payload["event_id"], "event_id")
    subject_key = _require_nonempty_str(payload["subject_key"], "subject_key")

    source = _validate_source(payload["source"])
    payload_digests = _validate_payloads_shape(root, payload["payloads"])
    authority_registry = _validate_authority_registry_shape(
        payload["authority_registry"], payload_digests
    )
    observation = _validate_observation(payload["observation"], source, payload_digests)
    attestation = _validate_attestation(
        payload["attestation"], observation, payload_digests, authority_registry
    )

    construction = payload["construction"]
    if construction not in _CONSTRUCTIONS:
        raise EvidenceError(f"construction must be one of {_CONSTRUCTIONS}")
    supersedes = _validate_supersedes(payload["supersedes"])
    producer_revision = _validate_producer_revision(payload["producer_revision"])

    evidence_id = payload["evidence_id"]
    if not _is_sha256(evidence_id) or evidence_id != computed_id:
        raise EvidenceError("evidence_id does not match its derived content descriptor")

    _validate_timestamp_ordering(source, observation)

    if verify_payloads:
        if root.is_symlink() or not root.is_dir():
            raise EvidenceError(f"evidence record root must be a directory, not a symlink: {root}")
        _verify_authority_registry_bytes(root, authority_registry)
        _verify_all_payload_bytes(root, payload_digests, already_verified=authority_registry.path)

    return EvidenceManifest(
        root=root,
        schema=schema,
        evidence_id=evidence_id,
        kind=kind,
        event_id=event_id,
        subject_key=subject_key,
        source=source,
        observation=observation,
        attestation=attestation,
        authority_registry=authority_registry,
        construction=construction,
        payloads=payload_digests,
        supersedes=supersedes,
        producer_revision=producer_revision,
    )


def evidence_is_admissible(
    record: EvidenceManifest, cutoff_utc: str, *, allow_reconstructed_unknown: bool = False
) -> bool:
    """Return whether `record` is a valid observation as of `cutoff_utc`.

    Pure predicate: false when the parsed cutoff precedes
    `source.available_at_utc`; for an `absent` observation it also requires
    `cutoff <= supported_through_utc`, using
    `max(available_at_utc, observed_at_utc)` as the lower bound so a negative
    observation cannot apply before it was actually made. A
    `reconstructed_unknown` record is inadmissible unless a diagnostic caller
    opts in explicitly. This function never back-projects a later negative
    observation to an earlier cutoff and invents no freshness policy beyond
    the bound `supported_through_utc`; current-tip selection is separate.
    """
    cutoff = parse_utc(cutoff_utc, "cutoff_utc")
    if record.construction == "reconstructed_unknown" and not allow_reconstructed_unknown:
        return False
    if record.observation.assertion == "present":
        return cutoff >= record.source.available_at_utc
    lower_bound = max(record.source.available_at_utc, record.observation.observed_at_utc)
    return lower_bound <= cutoff <= record.observation.supported_through_utc


class ReconciliationError(ValueError):
    """A pure fact comparison between expected and observed evidence disagrees."""


PARTICIPANTS_SCHEMA = "ti26.participants.v1"
ROSTERS_SCHEMA = "ti26.rosters.v1"
DRAW_FACT_SCHEMA = "ti26.draw-fact.v1"
SOURCE_REGISTRY_SCHEMA = "ti26.evidence-source-registry.v1"

_PARTICIPANTS_KEYS = frozenset({"schema", "participants"})
_PARTICIPANT_ENTRY_KEYS = frozenset({"team_id", "display_name"})
_ROSTERS_KEYS = frozenset({"schema", "rosters"})
_ROSTER_ENTRY_KEYS = frozenset({"team_id", "account_ids"})
_ROSTER_ACCOUNT_COUNT = 5
_DRAW_KEYS = frozenset({"schema", "component", "publication_state", "value"})
_DRAW_COMPONENTS = ("groups", "round_one")
_PUBLICATION_STATES = ("published", "unpublished")

_SOURCE_REGISTRY_KEYS = frozenset({"schema", "effective_at_utc", "sources"})
_SOURCE_REGISTRY_ENTRY_KEYS = frozenset({"source_url_key", "authorizations"})
_SOURCE_AUTHORIZATION_KEYS = frozenset({"event_id", "kind", "subject_key"})
_EVIDENCE_KINDS = frozenset({"rules", "participants", "rosters", "draws"})
_SAFE_KEY_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")


def _require_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EvidenceError(f"{label} must be a positive integer")
    return value


def _require_safe_source_key(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value[0] == "-"
        or value[-1] == "-"
        or any(char not in _SAFE_KEY_CHARS for char in value)
    ):
        raise EvidenceError(f"{label} must be a safe lowercase hyphenated key")
    return value


def _validate_participants_payload(payload: object, assertion: str) -> dict[str, object]:
    if assertion != "present":
        raise EvidenceError("a participants payload requires a present observation")
    if not isinstance(payload, dict) or set(payload) != _PARTICIPANTS_KEYS:
        raise EvidenceError("participants payload has unsupported or missing keys")
    if payload["schema"] != PARTICIPANTS_SCHEMA:
        raise EvidenceError(f"participants payload schema must be {PARTICIPANTS_SCHEMA!r}")
    entries = payload["participants"]
    if not isinstance(entries, list) or not entries:
        raise EvidenceError("participants must be a non-empty list")
    team_ids: list[int] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _PARTICIPANT_ENTRY_KEYS:
            raise EvidenceError("participant entry has unsupported or missing keys")
        team_ids.append(_require_positive_int(entry["team_id"], "participant.team_id"))
        _require_nonempty_str(entry["display_name"], "participant.display_name")
    if len(set(team_ids)) != len(team_ids):
        raise EvidenceError("participants must not repeat a team_id")
    if team_ids != sorted(team_ids):
        raise EvidenceError("participants must be in canonical ascending team_id order")
    return payload


def _validate_rosters_payload(payload: object, assertion: str) -> dict[str, object]:
    if assertion != "present":
        raise EvidenceError("a rosters payload requires a present observation")
    if not isinstance(payload, dict) or set(payload) != _ROSTERS_KEYS:
        raise EvidenceError("rosters payload has unsupported or missing keys")
    if payload["schema"] != ROSTERS_SCHEMA:
        raise EvidenceError(f"rosters payload schema must be {ROSTERS_SCHEMA!r}")
    entries = payload["rosters"]
    if not isinstance(entries, list) or not entries:
        raise EvidenceError("rosters must be a non-empty list")
    team_ids: list[int] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _ROSTER_ENTRY_KEYS:
            raise EvidenceError("roster entry has unsupported or missing keys")
        team_id = _require_positive_int(entry["team_id"], "roster.team_id")
        team_ids.append(team_id)
        account_ids = entry["account_ids"]
        if not isinstance(account_ids, list) or len(account_ids) != _ROSTER_ACCOUNT_COUNT:
            raise EvidenceError(f"roster {team_id} must declare exactly five account ids")
        parsed_accounts = [
            _require_positive_int(value, "roster.account_ids") for value in account_ids
        ]
        if len(set(parsed_accounts)) != len(parsed_accounts):
            raise EvidenceError(f"roster {team_id} must not repeat an account id")
        if parsed_accounts != sorted(parsed_accounts):
            raise EvidenceError(
                f"roster {team_id} must list account ids in canonical ascending order"
            )
    if len(set(team_ids)) != len(team_ids):
        raise EvidenceError("rosters must not repeat a team_id")
    if team_ids != sorted(team_ids):
        raise EvidenceError("rosters must be in canonical ascending team_id order")
    return payload


def _validate_draw_groups_value(value: object) -> None:
    if not isinstance(value, dict) or not value:
        raise EvidenceError("a published groups value must be a non-empty mapping")
    seen_members: set[int] = set()
    for label, members in value.items():
        if not isinstance(label, str) or not label:
            raise EvidenceError("a group label must be a non-empty string")
        if not isinstance(members, list) or not members:
            raise EvidenceError(f"group {label!r} must list at least one member")
        parsed_members = [_require_positive_int(member, "group member") for member in members]
        if len(set(parsed_members)) != len(parsed_members):
            raise EvidenceError(f"group {label!r} must not repeat a member")
        if seen_members & set(parsed_members):
            raise EvidenceError("published groups must cover each participant exactly once")
        seen_members |= set(parsed_members)


def _validate_draw_round_one_value(value: object) -> None:
    if not isinstance(value, list) or not value:
        raise EvidenceError("a published Round 1 value must be a non-empty list of pairs")
    seen_members: set[int] = set()
    seen_pairs: set[tuple[int, int]] = set()
    for pair in value:
        if not isinstance(pair, list) or len(pair) != 2:
            raise EvidenceError("a Round 1 pair must have exactly two members")
        parsed_pair = [_require_positive_int(member, "round_one member") for member in pair]
        first, second = parsed_pair
        if first == second:
            raise EvidenceError("a Round 1 pair must not pair a team against itself")
        canonical_pair = tuple(sorted((first, second)))
        if canonical_pair in seen_pairs:
            raise EvidenceError("Round 1 must not repeat a pair in duplicate or reversed form")
        seen_pairs.add(canonical_pair)
        if seen_members & {first, second}:
            raise EvidenceError("Round 1 must cover each participant exactly once")
        seen_members |= {first, second}


def _validate_draw_payload(payload: object, assertion: str) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != _DRAW_KEYS:
        raise EvidenceError("draw payload has unsupported or missing keys")
    if payload["schema"] != DRAW_FACT_SCHEMA:
        raise EvidenceError(f"draw payload schema must be {DRAW_FACT_SCHEMA!r}")
    component = payload["component"]
    if component not in _DRAW_COMPONENTS:
        raise EvidenceError("draw payload component must be exactly groups or round_one")
    publication_state = payload["publication_state"]
    if publication_state not in _PUBLICATION_STATES:
        raise EvidenceError(
            "draw payload publication_state must be exactly published or unpublished"
        )
    value = payload["value"]
    if publication_state == "unpublished":
        if value is not None or assertion != "absent":
            raise EvidenceError(
                "an unpublished draw component must have a null value and an absent observation"
            )
        return payload
    if value is None or assertion != "present":
        raise EvidenceError(
            "a published draw component must have a value and a present observation"
        )
    if component == "groups":
        _validate_draw_groups_value(value)
    else:
        _validate_draw_round_one_value(value)
    return payload


def validate_kind_payload(kind: str, payload: object, *, assertion: str) -> dict[str, object]:
    """Validate one generic Plan 3 fact payload against its exact schema.

    Pure shape validation: no I/O, no selection, no network call, and no
    predictive action. Supports the generic `participants`, `rosters`, and
    `draws` kinds; `rules` extraction has its own narrow contract in Task 5.
    """
    if assertion not in _ASSERTIONS:
        raise EvidenceError("assertion must be exactly present or absent")
    if kind == "participants":
        return _validate_participants_payload(payload, assertion)
    if kind == "rosters":
        return _validate_rosters_payload(payload, assertion)
    if kind == "draws":
        return _validate_draw_payload(payload, assertion)
    raise EvidenceError(f"validate_kind_payload does not support kind: {kind!r}")


def reconcile_participants(expected: set[int], observed: set[int]) -> None:
    """Compare participant identity by exact team_id set membership only."""
    if expected != observed:
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        raise ReconciliationError(
            f"participants.team_id mismatch: missing={missing} unexpected={unexpected}"
        )


def reconcile_rosters(expected: dict[int, list[int]], observed: dict[int, list[int]]) -> None:
    """Compare roster identity by exact team_id and its sorted five-account set."""
    expected_ids = set(expected)
    observed_ids = set(observed)
    if expected_ids != observed_ids:
        missing = sorted(expected_ids - observed_ids)
        unexpected = sorted(observed_ids - expected_ids)
        raise ReconciliationError(
            f"rosters.team_id mismatch: missing={missing} unexpected={unexpected}"
        )
    for team_id in sorted(expected_ids):
        expected_accounts = sorted(expected[team_id])
        observed_accounts = sorted(observed[team_id])
        if expected_accounts != observed_accounts:
            raise ReconciliationError(
                f"rosters.{team_id}.account_ids mismatch: "
                f"expected={expected_accounts} observed={observed_accounts}"
            )


def reconcile_draw(expected: dict[str, object], observed: dict[str, object]) -> None:
    """Compare the combined groups/round_one draw facts independently, by canonical JSON."""
    if canonical_evidence_json_bytes(expected.get("groups")) != canonical_evidence_json_bytes(
        observed.get("groups")
    ):
        raise ReconciliationError("draw.groups mismatch between expected and observed facts")
    if canonical_evidence_json_bytes(
        expected.get("round_one")
    ) != canonical_evidence_json_bytes(observed.get("round_one")):
        raise ReconciliationError("draw.round_one mismatch between expected and observed facts")


@dataclass(frozen=True)
class EvidenceSourceAuthorization:
    event_id: str
    kind: str
    subject_key: str


@dataclass(frozen=True)
class EvidenceSourceRegistryEntry:
    source_url_key: str
    authorizations: tuple[EvidenceSourceAuthorization, ...]


@dataclass(frozen=True)
class EvidenceSourceRegistry:
    schema: str
    effective_at_utc: datetime
    entries: tuple[EvidenceSourceRegistryEntry, ...]


def _parse_source_registry(payload: object) -> EvidenceSourceRegistry:
    if not isinstance(payload, dict) or set(payload) != _SOURCE_REGISTRY_KEYS:
        raise EvidenceError("source registry has unsupported or missing keys")
    schema = payload["schema"]
    if schema != SOURCE_REGISTRY_SCHEMA:
        raise EvidenceError(f"source registry schema must be {SOURCE_REGISTRY_SCHEMA!r}")
    effective_at_utc = parse_utc(payload["effective_at_utc"], "source registry effective_at_utc")
    sources_raw = payload["sources"]
    if not isinstance(sources_raw, list) or not sources_raw:
        raise EvidenceError("source registry sources must be a non-empty list")
    seen_keys: set[str] = set()
    entries: list[EvidenceSourceRegistryEntry] = []
    for entry in sources_raw:
        if not isinstance(entry, dict) or set(entry) != _SOURCE_REGISTRY_ENTRY_KEYS:
            raise EvidenceError("source registry entry has unsupported or missing keys")
        source_url_key = _require_safe_source_key(entry["source_url_key"], "source_url_key")
        if source_url_key in seen_keys:
            raise EvidenceError(
                f"source registry has a duplicate source_url_key: {source_url_key}"
            )
        seen_keys.add(source_url_key)
        authorizations_raw = entry["authorizations"]
        if not isinstance(authorizations_raw, list) or not authorizations_raw:
            raise EvidenceError(
                f"source registry entry must declare at least one authorization: {source_url_key}"
            )
        authorizations: list[EvidenceSourceAuthorization] = []
        seen_pairs: set[tuple[str, str, str]] = set()
        for auth in authorizations_raw:
            if not isinstance(auth, dict) or set(auth) != _SOURCE_AUTHORIZATION_KEYS:
                raise EvidenceError(
                    "source registry authorization has unsupported or missing keys"
                )
            event_id = _require_nonempty_str(auth["event_id"], "authorization.event_id")
            kind = auth["kind"]
            if kind not in _EVIDENCE_KINDS:
                raise EvidenceError(
                    f"source registry authorization has an unknown kind: {kind!r}"
                )
            subject_key = _require_nonempty_str(auth["subject_key"], "authorization.subject_key")
            pair = (event_id, kind, subject_key)
            if pair in seen_pairs:
                raise EvidenceError(
                    f"source registry has a duplicate authorization for {source_url_key}: {pair}"
                )
            seen_pairs.add(pair)
            authorizations.append(
                EvidenceSourceAuthorization(event_id=event_id, kind=kind, subject_key=subject_key)
            )
        entries.append(
            EvidenceSourceRegistryEntry(
                source_url_key=source_url_key, authorizations=tuple(authorizations)
            )
        )
    return EvidenceSourceRegistry(
        schema=schema, effective_at_utc=effective_at_utc, entries=tuple(entries)
    )


def load_source_registry(path: Path) -> EvidenceSourceRegistry:
    """Load and validate the exact owner-reviewed stable source-key registry."""
    if path.is_symlink() or not path.is_file():
        raise EvidenceError(f"source registry must be a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"source registry is not valid JSON: {path}") from exc
    return _parse_source_registry(payload)


def authoritative_source_keys_for(
    registry: EvidenceSourceRegistry, kind: str, subject_key: str
) -> tuple[str, ...]:
    """Return the complete sorted authority set for one exact (kind, subject) pair."""
    keys = {
        entry.source_url_key
        for entry in registry.entries
        for authorization in entry.authorizations
        if authorization.kind == kind and authorization.subject_key == subject_key
    }
    return tuple(sorted(keys))


def validate_record_sources(record: EvidenceManifest, registry: EvidenceSourceRegistry) -> None:
    """Require the record's primary source, and every checked authority, to be registered.

    A negative observation's checked set must equal -- not merely be a subset
    of -- the registry-derived complete authority set for the exact
    `(kind, subject_key)` pair; the owner cannot select a subset.
    """
    authorized = authoritative_source_keys_for(registry, record.kind, record.subject_key)
    if record.source.source_url_key not in authorized:
        raise EvidenceError(
            f"source {record.source.source_url_key!r} is not registered for "
            f"{record.kind}:{record.subject_key}"
        )
    if record.observation.assertion == "absent":
        checked = set(record.observation.authoritative_source_keys_checked)
        if checked != set(authorized):
            raise EvidenceError(
                "a negative observation must check the complete authority set for "
                f"{record.kind}:{record.subject_key}"
            )


_EVIDENCE_KIND_DIRS = ("rules", "participants", "rosters", "draws")


def load_evidence_catalog(
    root: Path, registry: EvidenceSourceRegistry
) -> tuple[EvidenceManifest, ...]:
    """Load, verify, and source-validate every existing immutable evidence record.

    Importer preflight: `root` may not yet exist (a brand-new evidence tree),
    in which case the catalog is empty. Every present `<kind>/<evidence_id>/`
    entry is lstat-validated at each component -- root, kind directory, record
    directory, and `manifest.json` -- rejecting a symlink anywhere; loaded
    with full payload verification; and checked with `validate_record_sources`
    against `registry`. It performs no selection and writes nothing.
    """
    if root.is_symlink():
        raise EvidenceError(f"evidence root must not be a symlink: {root}")
    if not root.exists():
        return ()
    if not root.is_dir():
        raise EvidenceError(f"evidence root must be a directory: {root}")
    records: list[EvidenceManifest] = []
    for kind in _EVIDENCE_KIND_DIRS:
        kind_dir = root / kind
        if kind_dir.is_symlink():
            raise EvidenceError(f"evidence kind directory must not be a symlink: {kind_dir}")
        if not kind_dir.exists():
            continue
        if not kind_dir.is_dir():
            raise EvidenceError(f"evidence kind directory must be a directory: {kind_dir}")
        for child in sorted(kind_dir.iterdir()):
            if child.is_symlink():
                raise EvidenceError(f"evidence record directory must not be a symlink: {child}")
            if not child.is_dir():
                raise EvidenceError(f"evidence record entry must be a directory: {child}")
            manifest_path = child / "manifest.json"
            if manifest_path.is_symlink() or not manifest_path.is_file():
                raise EvidenceError(f"evidence record is incomplete: {child}")
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise EvidenceError(f"evidence record manifest is unreadable: {child}") from exc
            record = validate_evidence_manifest(child, payload, verify_payloads=True)
            validate_record_sources(record, registry)
            records.append(record)
    return tuple(records)


class EvidenceExistsError(FileExistsError):
    """An evidence destination already exists and is not a verified-identical retry."""


def _require_safe_path_component(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "/" in value
        or "\\" in value
        or value in (".", "..")
    ):
        raise EvidenceError(f"{label} must be a single safe path component")
    return value


def evidence_record_path(root: Path, kind: str, evidence_id: str) -> Path:
    """Return `root / kind / evidence_id`, validating both as one safe path component."""
    kind_component = _require_safe_path_component(kind, "kind")
    id_component = _require_safe_path_component(evidence_id, "evidence_id")
    if not _is_sha256(id_component):
        raise EvidenceError("evidence_id must be a lower-case 64-hex sha256 digest")
    return root / kind_component / id_component


def _ancestor_chain(base: Path, target: Path) -> tuple[Path, ...]:
    """Return `base`, then every path from `base` down through `target`, inclusive."""
    chain = [base]
    current = base
    for part in target.relative_to(base).parts:
        current = current / part
        chain.append(current)
    return tuple(chain)


def _require_safe_dir(path: Path, label: str) -> None:
    """Raise unless `path` is absent, or an existing non-symlink directory."""
    if path.is_symlink():
        raise EvidenceError(f"{label} must not be a symlink: {path}")
    if path.exists() and not path.is_dir():
        raise EvidenceError(f"{label} must be a directory: {path}")


def _ensure_dir(path: Path, label: str) -> None:
    """lstat-revalidate `path`, then create it with exclusive-create semantics if absent."""
    _require_safe_dir(path, label)
    if not path.exists():
        try:
            path.mkdir()
        except FileExistsError:
            pass
        _require_safe_dir(path, label)
        if not path.is_dir():
            raise EvidenceError(f"{label} must be a directory: {path}")


def _reuse_existing_record(
    record: Path, manifest: dict[str, object], payloads: dict[str, bytes]
) -> Path | None:
    """Return `record` only when it already holds a complete, byte-identical record.

    Any incomplete directory, non-directory, or content mismatch raises
    `EvidenceExistsError` without touching the existing destination.
    """
    if record.is_symlink():
        raise EvidenceExistsError(f"evidence destination must not be a symlink: {record}")
    if not record.exists():
        return None
    if not record.is_dir():
        raise EvidenceExistsError(f"evidence destination exists and is not a directory: {record}")
    manifest_path = record / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise EvidenceExistsError(f"evidence destination is incomplete: {record}")
    try:
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceExistsError(
            f"evidence destination manifest is unreadable: {record}"
        ) from exc
    try:
        validate_evidence_manifest(record, existing_manifest, verify_payloads=True)
    except EvidenceError as exc:
        raise EvidenceExistsError(
            f"evidence destination manifest is invalid: {record}"
        ) from exc
    if canonical_evidence_json_bytes(existing_manifest) != canonical_evidence_json_bytes(manifest):
        raise EvidenceExistsError(
            f"evidence destination content differs from the requested record: {record}"
        )
    for path_text, payload_bytes in payloads.items():
        _, file_path = safe_relative_file(record, path_text, "payload")
        if not file_path.is_file() or file_path.read_bytes() != payload_bytes:
            raise EvidenceExistsError(
                f"evidence destination payload differs from requested bytes: {path_text}"
            )
    return record


def _write_payload_exclusive(record: Path, digest: PayloadDigest, data: bytes) -> None:
    """Exclusively create one payload file, then reject a written-bytes digest mismatch."""
    _, file_path = safe_relative_file(record, digest.path, "payload")
    for ancestor in _ancestor_chain(record, file_path.parent):
        _ensure_dir(ancestor, "evidence capture parent")
    with file_path.open("xb") as file:
        file.write(data)
    written_digest = _sha256_file(file_path)
    if written_digest != digest.sha256:
        raise EvidenceError(
            f"written payload sha256 does not match its declared digest: {digest.path}"
        )


def write_evidence_record(
    root: Path, manifest: dict[str, object], payloads: dict[str, bytes]
) -> Path:
    """Publish one content-addressed evidence record, payloads first and manifest last.

    An absent destination is created from scratch with exclusive `open("xb")`
    writes in sorted payload-path order, each recomputed from the bytes just
    written. `manifest.json` is exclusively created only after every payload
    is bound. An existing destination is returned unmodified only when it is
    complete and byte-identical to the requested record; otherwise
    `EvidenceExistsError` is raised without overwriting. Every
    filesystem-mutating step lstat-revalidates its ancestor directories
    immediately beforehand, closing a symlink substituted after an earlier
    check.
    """
    if not isinstance(manifest, dict):
        raise EvidenceError("evidence manifest must be a JSON object")
    if not isinstance(payloads, dict) or not all(
        isinstance(value, bytes) for value in payloads.values()
    ):
        raise EvidenceError("payloads must be a mapping of payload path to bytes")

    record = evidence_record_path(root, manifest.get("kind"), manifest.get("evidence_id"))
    chain = _ancestor_chain(root, record)
    for ancestor in chain[:-1]:
        _require_safe_dir(ancestor, "evidence path ancestor")

    existing = _reuse_existing_record(record, manifest, payloads)
    if existing is not None:
        return existing

    validated = validate_evidence_manifest(record, manifest, verify_payloads=False)
    declared_paths = {digest.path for digest in validated.payloads}
    if set(payloads) != declared_paths:
        raise EvidenceError("payload map keys must exactly equal the manifest payload paths")

    for ancestor in chain:
        _ensure_dir(ancestor, "evidence path component")

    for digest in sorted(validated.payloads, key=lambda item: item.path):
        _write_payload_exclusive(record, digest, payloads[digest.path])

    for ancestor in chain:
        _require_safe_dir(ancestor, "evidence path component")
    manifest_path = record / "manifest.json"
    if manifest_path.is_symlink():
        raise EvidenceError(f"manifest.json must not be a symlink: {manifest_path}")
    with manifest_path.open("xb") as file:
        file.write(canonical_evidence_json_bytes(manifest) + b"\n")

    written_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_evidence_manifest(record, written_manifest, verify_payloads=True)
    return record


@dataclass(frozen=True)
class CurrentEvidence:
    """The unique current evidence tip for one `(kind, subject_key)` at a cutoff.

    `rejected` maps every other matching evidence id to a stable reason:
    `superseded_by:<evidence-id>`, `available_after_cutoff`,
    `negative_observation_expired`, or `reconstructed_unknown`.
    """

    selected: EvidenceManifest
    rejected: dict[str, str]


def _graph_applicability(record: EvidenceManifest) -> datetime:
    """Return the timestamp at which `record` becomes eligible to compete as a tip.

    `available_at_utc` for a present record; otherwise
    `max(available_at_utc, observed_at_utc)`, so a negative observation cannot
    supersede an ancestor before the negative observation was actually made.
    """
    if record.observation.assertion == "present":
        return record.source.available_at_utc
    return max(record.source.available_at_utc, record.observation.observed_at_utc)


def _detect_supersession_cycle(
    records: tuple[EvidenceManifest, ...], by_id: dict[str, EvidenceManifest]
) -> None:
    """Raise if any `supersedes` chain in `records` revisits a node on its own path."""
    _WHITE, _GREY, _BLACK = 0, 1, 2
    colors: dict[str, int] = {record.evidence_id: _WHITE for record in records}

    def visit(evidence_id: str) -> None:
        colors[evidence_id] = _GREY
        for predecessor_id in by_id[evidence_id].supersedes:
            if colors[predecessor_id] == _GREY:
                raise ReconciliationError(
                    f"evidence graph has a supersession cycle at {predecessor_id}"
                )
            if colors[predecessor_id] == _WHITE:
                visit(predecessor_id)
        colors[evidence_id] = _BLACK

    for record in records:
        if colors[record.evidence_id] == _WHITE:
            visit(record.evidence_id)


def select_current_evidence(
    records: Iterable[EvidenceManifest],
    kind: str,
    subject_key: str,
    cutoff_utc: str,
    *,
    allow_reconstructed_unknown: bool = False,
) -> CurrentEvidence:
    """Select the unique current evidence tip for `(kind, subject_key)` at `cutoff_utc`.

    Validates the complete supplied graph first -- unique identifiers, every
    predecessor exists, predecessor kind/subject match the descendant, no
    self edge, and no cycle -- before filtering to matching records. Among
    matching records whose graph-applicability timestamp
    (`_graph_applicability`) is no later than the cutoff, a temporally
    applicable descendant always removes its ancestor from the maximal-tip
    set, regardless of the descendant's own assertion freshness or
    construction. Exactly one maximal tip must remain; only then is it
    checked with `evidence_is_admissible`, so an expired negative or
    `reconstructed_unknown` tip is a hard error that never revives an
    earlier ancestor.
    """
    materialized = tuple(records)
    cutoff = parse_utc(cutoff_utc, "cutoff_utc")

    by_id: dict[str, EvidenceManifest] = {}
    for record in materialized:
        if record.evidence_id in by_id:
            raise ReconciliationError(
                f"evidence graph has a duplicate evidence id: {record.evidence_id}"
            )
        by_id[record.evidence_id] = record

    for record in materialized:
        for predecessor_id in record.supersedes:
            if predecessor_id == record.evidence_id:
                raise ReconciliationError(f"evidence {record.evidence_id} supersedes itself")
            predecessor = by_id.get(predecessor_id)
            if predecessor is None:
                raise ReconciliationError(
                    f"evidence {record.evidence_id} supersedes a missing predecessor: "
                    f"{predecessor_id}"
                )
            if predecessor.kind != record.kind or predecessor.subject_key != record.subject_key:
                raise ReconciliationError(
                    f"evidence {record.evidence_id} has a cross-subject supersession of "
                    f"{predecessor_id}"
                )

    _detect_supersession_cycle(materialized, by_id)

    matching = tuple(
        record
        for record in materialized
        if record.kind == kind and record.subject_key == subject_key
    )

    rejected: dict[str, str] = {}
    applicable: list[EvidenceManifest] = []
    for record in matching:
        if _graph_applicability(record) <= cutoff:
            applicable.append(record)
        else:
            rejected[record.evidence_id] = "available_after_cutoff"

    superseded_by: dict[str, str] = {
        predecessor_id: record.evidence_id
        for record in applicable
        for predecessor_id in record.supersedes
    }
    tips = [record for record in applicable if record.evidence_id not in superseded_by]
    for record in applicable:
        if record.evidence_id in superseded_by:
            rejected[record.evidence_id] = f"superseded_by:{superseded_by[record.evidence_id]}"

    if not tips:
        raise ReconciliationError(
            f"no current evidence tip exists for {kind}:{subject_key} at {cutoff_utc}"
        )
    if len(tips) > 1:
        tip_ids = sorted(tip.evidence_id for tip in tips)
        raise ReconciliationError(
            f"evidence graph for {kind}:{subject_key} has incomparable current tips: {tip_ids}"
        )

    tip = tips[0]
    if not evidence_is_admissible(
        tip, cutoff_utc, allow_reconstructed_unknown=allow_reconstructed_unknown
    ):
        if tip.construction == "reconstructed_unknown" and not allow_reconstructed_unknown:
            raise ReconciliationError(
                f"current evidence tip is inadmissible (reconstructed_unknown): {tip.evidence_id}"
            )
        raise ReconciliationError(
            "current evidence tip is inadmissible (negative_observation_expired): "
            f"{tip.evidence_id}"
        )

    return CurrentEvidence(selected=tip, rejected=rejected)


RULES_EXTRACTED_SCHEMA = "ti26.rules-extracted.v1"
RULES_FORMAT_EXTRACTED_SCHEMA = "ti26.rules-format-extracted.v1"

_RULES_FACT_KEYS = frozenset({"tiebreak_order", "rounds", "elimination_selection_order"})
_RULES_FORMAT_FACT_KEYS = frozenset({"format"})
_FACT_ENTRY_KEYS = frozenset({"value", "span_sha256"})

_TIEBREAK_FRAGMENTS: tuple[tuple[str, str], ...] = (
    ("Number of Matches Won", "series_wins"),
    ("Number of Matches Lost", "series_losses"),
    ("Total Number of Matches Won by Opponents Played", "opponent_series_wins"),
    ("Percentage of Games Won", "game_win_pct"),
    ("Average Percentage of Games Won by Opponents Played", "opponent_game_win_pct"),
    ("Average Game Duration (Shorter is Better)", "avg_duration"),
    ("Coin Toss", "coin_toss"),
)
_ROUND_MARKERS: tuple[tuple[str, int], ...] = (
    ("Round 2", 2),
    ("Round 3", 3),
    ("Round 4", 4),
    ("Round 5", 5),
)
_WITHIN_GROUP_SENTENCE = "Teams are only matched against other members of their initial group"
_CROSS_GROUP_SENTENCE = "Teams are only matched against members of the other group"
_MAX_DISTANCE_SENTENCE = (
    "For matches where the loser is eliminated, maximize the distance in ranking between the teams"
)
_ELIMINATION_MARKER = "Elimination Round"
_ELIMINATION_SENTENCE = (
    "Starting with the best 3-2 team, they will choose any of the five 2-3 teams as their opponent."
)
_FORMAT_LABELS: tuple[tuple[str, str], ...] = (
    ("Number of Teams: ", "n_teams"),
    ("Total Rounds: ", "total_rounds"),
    ("Advance at Wins: ", "advance_at_wins"),
    ("Eliminate at Losses: ", "eliminate_at_losses"),
)


def _line_spans(rendered: str) -> list[tuple[str, int, int]]:
    """Split `rendered` into `(line_text, start, end)` triples with character offsets.

    `end` excludes the line's own trailing newline, so `rendered[start:end]`
    reproduces the line exactly. Matching whole lines -- rather than raw
    substrings -- is what keeps a short required fragment (e.g. "Number of
    Matches Won") from colliding with a longer line that merely contains it
    (e.g. "Total Number of Matches Won by Opponents Played").
    """
    spans: list[tuple[str, int, int]] = []
    pos = 0
    for line in rendered.split("\n"):
        spans.append((line, pos, pos + len(line)))
        pos += len(line) + 1
    return spans


def _find_line(
    lines: list[tuple[str, int, int]],
    matches,
    cursor: int,
    label: str,
    want: str,
) -> int:
    """Return the index of the first line at or after `cursor` for which `matches` holds.

    Raises `EvidenceError` naming `label` and `want`, distinguishing a
    fragment that is wholly absent from one that exists only before `cursor`
    (out of order).
    """
    for i in range(cursor, len(lines)):
        if matches(lines[i][0]):
            return i
    if any(matches(line) for line, _, _ in lines[:cursor]):
        raise EvidenceError(f"required {label} fragment is out of order: {want!r}")
    raise EvidenceError(f"required {label} fragment is missing: {want!r}")


def _require_unique_line(lines: list[tuple[str, int, int]], matches, label: str, want: str) -> None:
    """Raise unless exactly one line in `lines` satisfies `matches`."""
    if sum(1 for line, _, _ in lines if matches(line)) != 1:
        raise EvidenceError(f"required {label} fragment is ambiguous or duplicated: {want!r}")


def extract_ti2026_rules(rendered: str) -> dict[str, object]:
    """Extract the narrow, span-bound TI 2026 group-stage rules vocabulary.

    Uses exact required whole-line fragments from the captured rendering and
    raises `EvidenceError` if one is absent, ambiguously duplicated, or out
    of order. Every fact's `span_sha256` digests the exact supporting UTF-8
    substring, never the entire page. Extracts only tiebreak order,
    within/cross-group round constraints, the loser-elimination distance
    rule, and the sequential 3-2 elimination chooser -- no model assumption
    such as `elimination_choice_policy`, duration fields, or capacities.
    """
    if not isinstance(rendered, str) or not rendered:
        raise EvidenceError("rendered rules text must be a non-empty string")
    lines = _line_spans(rendered)

    cursor = 0
    tiebreak_start: int | None = None
    order: list[str] = []
    for fragment, name in _TIEBREAK_FRAGMENTS:
        matches = lambda line, fragment=fragment: line == fragment
        _require_unique_line(lines, matches, "tiebreak_order", fragment)
        idx = _find_line(lines, matches, cursor, "tiebreak_order", fragment)
        if tiebreak_start is None:
            tiebreak_start = lines[idx][1]
        cursor = idx + 1
        order.append(name)
    tiebreak_span = rendered[tiebreak_start : lines[cursor - 1][2]]

    rounds_start: int | None = None
    within_group: list[int] = []
    cross_group: list[int] = []
    max_distance: list[int] = []
    for marker, number in _ROUND_MARKERS:
        matches = lambda line, marker=marker: line == marker
        _require_unique_line(lines, matches, "rounds", marker)
        idx = _find_line(lines, matches, cursor, "rounds", marker)
        if rounds_start is None:
            rounds_start = lines[idx][1]
        cursor = idx + 1
        if number in (2, 3):
            sentence, bucket = _WITHIN_GROUP_SENTENCE, within_group
        elif number == 4:
            sentence, bucket = _CROSS_GROUP_SENTENCE, cross_group
        else:
            sentence, bucket = _MAX_DISTANCE_SENTENCE, max_distance
        sentence_matches = lambda line, sentence=sentence: line == sentence
        idx = _find_line(lines, sentence_matches, cursor, "rounds", sentence)
        cursor = idx + 1
        bucket.append(number)
    rounds_span = rendered[rounds_start : lines[cursor - 1][2]]

    elimination_matches = lambda line: line == _ELIMINATION_MARKER
    _require_unique_line(lines, elimination_matches, "elimination_selection_order", _ELIMINATION_MARKER)
    elimination_idx = _find_line(
        lines, elimination_matches, cursor, "elimination_selection_order", _ELIMINATION_MARKER
    )
    elimination_start = lines[elimination_idx][1]
    cursor = elimination_idx + 1
    sentence_matches = lambda line: line == _ELIMINATION_SENTENCE
    sentence_idx = _find_line(
        lines, sentence_matches, cursor, "elimination_selection_order", _ELIMINATION_SENTENCE
    )
    elimination_span = rendered[elimination_start : lines[sentence_idx][2]]

    return {
        "schema": RULES_EXTRACTED_SCHEMA,
        "facts": {
            "tiebreak_order": {
                "value": order,
                "span_sha256": hashlib.sha256(tiebreak_span.encode("utf-8")).hexdigest(),
            },
            "rounds": {
                "value": {
                    "within_group": within_group,
                    "cross_group": cross_group,
                    "max_distance_when_loser_eliminated": max_distance,
                },
                "span_sha256": hashlib.sha256(rounds_span.encode("utf-8")).hexdigest(),
            },
            "elimination_selection_order": {
                "value": "best_3_2_sequential_choice",
                "span_sha256": hashlib.sha256(elimination_span.encode("utf-8")).hexdigest(),
            },
        },
    }


def _parse_trailing_int(text: str, label: str) -> int:
    """Return the leading run of digits in `text`, or raise `EvidenceError`."""
    digits = ""
    for char in text:
        if char.isdigit():
            digits += char
        elif digits:
            break
    if not digits:
        raise EvidenceError(f"required format fragment has no numeric value: {label!r}")
    return int(digits)


def extract_ti2026_published_format(rendered: str) -> dict[str, object]:
    """Extract the narrow, span-bound TI 2026 published-format vocabulary.

    Owns its own exact required labeled line-prefix fragments -- distinct
    from `extract_ti2026_rules`'s tiebreak/round/elimination fragments -- and
    raises `EvidenceError` if one is absent, ambiguously duplicated, or out
    of order. The single `format` fact's `span_sha256` digests the exact
    supporting UTF-8 substring, never the entire page.
    """
    if not isinstance(rendered, str) or not rendered:
        raise EvidenceError("rendered published-format text must be a non-empty string")
    lines = _line_spans(rendered)

    cursor = 0
    span_start: int | None = None
    value: dict[str, int] = {}
    for prefix, key in _FORMAT_LABELS:
        matches = lambda line, prefix=prefix: line.startswith(prefix)
        _require_unique_line(lines, matches, "format", prefix)
        idx = _find_line(lines, matches, cursor, "format", prefix)
        if span_start is None:
            span_start = lines[idx][1]
        line_text, _, line_end = lines[idx]
        value[key] = _parse_trailing_int(line_text[len(prefix) :], prefix)
        cursor = idx + 1

    span = rendered[span_start:line_end]
    return {
        "schema": RULES_FORMAT_EXTRACTED_SCHEMA,
        "facts": {
            "format": {
                "value": value,
                "span_sha256": hashlib.sha256(span.encode("utf-8")).hexdigest(),
            }
        },
    }


def _reconcile_value(path: str, expected: object, observed: object) -> None:
    """Recursively compare `expected` against `observed`, raising on first divergence.

    A dict pair with matching key sets recurses key by key so the raised
    path names the exact diverging field; anything else -- including a dict
    pair whose key sets differ -- is compared by canonical JSON bytes at the
    current path.
    """
    if (
        isinstance(expected, dict)
        and isinstance(observed, dict)
        and set(expected) == set(observed)
    ):
        for key in sorted(expected):
            _reconcile_value(f"{path}.{key}", expected[key], observed[key])
        return
    if canonical_evidence_json_bytes(expected) != canonical_evidence_json_bytes(observed):
        raise ReconciliationError(
            f"{path} mismatch: expected={canonical_evidence_json_bytes(expected).decode('utf-8')} "
            f"observed={canonical_evidence_json_bytes(observed).decode('utf-8')}"
        )


def reconcile_rules_facts(configured: dict[str, object], extracted: dict[str, object]) -> list[str]:
    """Compare shipping-configured rules facts against a validated extracted object.

    Requires `extracted`'s exact schema and exact fact vocabulary -- matching
    `configured`'s keys -- with a valid lower-case span digest on every fact,
    then performs recursive exact equality between `configured` and each
    fact's `value`. Returns `[]` only on equality; raises
    `ReconciliationError` with a deterministic dotted field path and
    canonical expected/observed JSON on the first mismatch. Neither this nor
    its caller changes configuration values or evidence.
    """
    if not isinstance(configured, dict) or set(configured) != _RULES_FACT_KEYS:
        raise EvidenceError("configured rules facts have unsupported or missing keys")
    if not isinstance(extracted, dict) or set(extracted) != {"schema", "facts"}:
        raise EvidenceError("extracted rules object has unsupported or missing keys")
    if extracted["schema"] != RULES_EXTRACTED_SCHEMA:
        raise EvidenceError(f"extracted rules schema must be {RULES_EXTRACTED_SCHEMA!r}")
    facts = extracted["facts"]
    if not isinstance(facts, dict) or set(facts) != _RULES_FACT_KEYS:
        raise EvidenceError("extracted rules facts do not match the configured fact vocabulary")
    for key, entry in facts.items():
        if not isinstance(entry, dict) or set(entry) != _FACT_ENTRY_KEYS:
            raise EvidenceError(f"extracted rules fact {key!r} has unsupported or missing keys")
        if not _is_sha256(entry["span_sha256"]):
            raise EvidenceError(f"extracted rules fact {key!r} has an invalid span_sha256")
    for key in sorted(configured):
        _reconcile_value(key, configured[key], facts[key]["value"])
    return []


def reconcile_rules_format_facts(
    configured: dict[str, object], extracted: dict[str, object]
) -> list[str]:
    """Compare shipping-configured published-format facts against a validated extracted object.

    Mirrors `reconcile_rules_facts` for the distinct `rules-format` subject:
    exact schema, the exact single `format` fact key, a valid span digest,
    then recursive exact equality with deterministic dotted field paths.
    Returns `[]` only on equality; performs no I/O and changes nothing.
    """
    if not isinstance(configured, dict) or set(configured) != _RULES_FORMAT_FACT_KEYS:
        raise EvidenceError("configured published-format facts have unsupported or missing keys")
    if not isinstance(extracted, dict) or set(extracted) != {"schema", "facts"}:
        raise EvidenceError("extracted published-format object has unsupported or missing keys")
    if extracted["schema"] != RULES_FORMAT_EXTRACTED_SCHEMA:
        raise EvidenceError(
            f"extracted published-format schema must be {RULES_FORMAT_EXTRACTED_SCHEMA!r}"
        )
    facts = extracted["facts"]
    if not isinstance(facts, dict) or set(facts) != _RULES_FORMAT_FACT_KEYS:
        raise EvidenceError(
            "extracted published-format facts do not match the configured fact vocabulary"
        )
    entry = facts["format"]
    if not isinstance(entry, dict) or set(entry) != _FACT_ENTRY_KEYS:
        raise EvidenceError("extracted published-format fact has unsupported or missing keys")
    if not _is_sha256(entry["span_sha256"]):
        raise EvidenceError("extracted published-format fact has an invalid span_sha256")
    _reconcile_value("format", configured["format"], entry["value"])
    return []
