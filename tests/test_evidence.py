import pytest

from ti26.evidence import (
    EvidenceError,
    canonical_evidence_json_bytes,
    evidence_id_for_manifest,
    validate_evidence_manifest,
)
from ti26.provenance import canonical_json_bytes


def _sha(payload: bytes) -> str:
    import hashlib
    return hashlib.sha256(payload).hexdigest()


def _bound_registry() -> bytes:
    value = {
        "schema": "ti26.evidence-source-registry.v1",
        "effective_at_utc": "2025-12-31T00:00:00Z",
        "sources": [
            {
                "source_url_key": "valve-ti-group-stage-rules",
                "authorizations": [
                    {
                        "event_id": "ti2026",
                        "kind": "rules",
                        "subject_key": "rules:ti2026:valve:group-stage",
                    }
                ],
            }
        ],
    }
    return canonical_evidence_json_bytes(value) + b"\n"


def _manifest(*, observation: dict[str, object] | None = None) -> dict[str, object]:
    rendered = b"Group Stage Rules\n"
    extracted = canonical_evidence_json_bytes(
        {"schema": "ti26.rules-extracted.v1", "facts": {}}
    ) + b"\n"
    registry = _bound_registry()
    resolved_observation = observation or {
        "assertion": "present",
        "observed_at_utc": "2026-01-01T00:00:01Z",
        "supported_through_utc": "2026-01-01T00:00:01Z",
        "captures": [
            {
                "source_url_key": "valve-ti-group-stage-rules",
                "path": "rendered.txt",
            }
        ],
        "authoritative_source_keys_checked": [],
        "diagnostic_reason": None,
    }
    is_positive = resolved_observation["assertion"] == "present"
    payloads = [
        {"path": "authority-registry.json", "sha256": _sha(registry)},
        {"path": "rendered.txt", "sha256": _sha(rendered)},
    ]
    if is_positive:
        payloads.append({"path": "extracted.json", "sha256": _sha(extracted)})
    payload = {
        "schema": "ti26.evidence-manifest.v1",
        "evidence_id": "",
        "kind": "rules",
        "event_id": "ti2026",
        "subject_key": "rules:ti2026:valve:group-stage",
        "source": {
            "source_url_key": "valve-ti-group-stage-rules",
            "capture_method": "owner-supplied-rendered-text",
            "available_at_utc": "2026-01-01T00:00:00Z",
            "published_at_utc": None,
            "retrieved_at_utc": "2026-01-01T00:00:01Z",
        },
        "observation": resolved_observation,
        "attestation": {
            "fact_payload_sha256": _sha(extracted),
            "capture_sha256s": [_sha(rendered)],
        } if is_positive else None,
        "authority_registry": {
            "schema": "ti26.evidence-authority-binding.v1",
            "path": "authority-registry.json",
            "sha256": _sha(registry),
            "effective_at_utc": "2025-12-31T00:00:00Z",
        },
        "construction": "contemporaneous",
        "payloads": payloads,
        "supersedes": [],
        "producer_revision": "a" * 40,
    }
    payload["evidence_id"] = evidence_id_for_manifest(payload)
    return payload


def test_evidence_json_encoding_matches_run_provenance_encoding():
    """Kills mutation: use a different canonical JSON separator in evidence IDs."""
    value = {"z": [2, 1], "a": "text"}
    assert canonical_evidence_json_bytes(value) == canonical_json_bytes(value)


def test_validate_evidence_manifest_requires_exact_top_level_keys(tmp_path):
    """Kills mutation: accept an evidence manifest with an unrecognized key."""
    payload = _manifest()
    payload["outcome_path"] = "outcomes/result.json"
    with pytest.raises(EvidenceError, match="unsupported or missing"):
        validate_evidence_manifest(tmp_path, payload)


def test_validate_evidence_manifest_rejects_unsafe_payload_path(tmp_path):
    """Kills mutation: join manifest payload paths without rejecting traversal."""
    payload = _manifest()
    payload["payloads"][0]["path"] = "../rendered.txt"
    with pytest.raises(EvidenceError, match="POSIX-relative"):
        validate_evidence_manifest(tmp_path, payload)


def test_validate_evidence_manifest_rejects_a_boolean_where_a_timestamp_is_required(tmp_path):
    """Kills mutation: treat bool as an acceptable timestamp-like scalar."""
    payload = _manifest()
    payload["source"]["available_at_utc"] = True
    with pytest.raises(EvidenceError, match="available_at_utc"):
        validate_evidence_manifest(tmp_path, payload)


def test_validate_evidence_manifest_rejects_unregistered_freshness_extension(tmp_path):
    """Kills mutation: let supported-through extend beyond the bound observation without a policy."""
    payload = _manifest()
    payload["observation"]["supported_through_utc"] = "2026-01-01T00:00:02Z"
    payload["evidence_id"] = evidence_id_for_manifest(payload)
    with pytest.raises(EvidenceError, match="supported_through_utc"):
        validate_evidence_manifest(tmp_path, payload, verify_payloads=False)


def test_validate_evidence_manifest_rejects_changed_bound_registry_bytes(tmp_path):
    """Kills mutation: trust the authority-registry digest without hashing its bound bytes."""
    record = tmp_path / "rules" / _manifest()["evidence_id"]
    record.mkdir(parents=True)
    (record / "authority-registry.json").write_bytes(_bound_registry() + b" ")
    with pytest.raises(EvidenceError, match="authority.registry"):
        validate_evidence_manifest(record, _manifest(), verify_payloads=True)
