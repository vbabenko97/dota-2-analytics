"""Exact, content-addressed evidence manifests for offline TI 2026 release facts.

This module owns the immutable evidence-manifest schema: canonical JSON
encoding, the content-addressed `evidence_id`, safe on-disk paths, and the
pure validator that turns a JSON object into a trusted `EvidenceManifest`.
It performs no I/O beyond reading the bytes a manifest already declares, and
it never imports a network-capable module.
"""

import hashlib
import json
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
