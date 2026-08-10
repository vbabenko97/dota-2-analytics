import dataclasses
import json
from pathlib import Path

import pytest
import yaml

from ti26.evidence import (
    RELEASE_SUBJECTS,
    EvidenceError,
    EvidenceExistsError,  # noqa: F401 -- imported per Step 2's RED-import assertion
    EvidenceManifest,
    ReconciliationError,
    canonical_evidence_json_bytes,
    evidence_id_for_manifest,
    evidence_is_admissible,
    extract_ti2026_published_format,
    extract_ti2026_rules,
    load_release_evidence,
    load_source_registry,
    reconcile_draw,
    reconcile_participants,
    reconcile_release_evidence,
    reconcile_rosters,
    reconcile_rules_facts,
    reconcile_rules_format_facts,
    select_current_evidence,
    validate_evidence_manifest,
    validate_kind_payload,
    validate_record_sources,
    write_evidence_record,
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


def _source_registry(
    tmp_path,
    *,
    subject_key: str = "rules:ti2026:valve:group-stage",
    additional_authority: str | None = None,
):
    """Write and load a synthetic source registry authorizing the primary key.

    `additional_authority`, when given, is authorized for the same subject so
    a test can prove a negative observation must check every registered
    authority, not a subset.
    """
    sources = [
        {
            "source_url_key": "valve-ti-group-stage-rules",
            "authorizations": [
                {"event_id": "ti2026", "kind": "rules", "subject_key": subject_key}
            ],
        }
    ]
    if additional_authority is not None:
        sources.append(
            {
                "source_url_key": additional_authority,
                "authorizations": [
                    {"event_id": "ti2026", "kind": "rules", "subject_key": subject_key}
                ],
            }
        )
    value = {
        "schema": "ti26.evidence-source-registry.v1",
        "effective_at_utc": "2025-12-31T00:00:00Z",
        "sources": sources,
    }
    path = tmp_path / "source-registry.json"
    path.write_bytes(canonical_evidence_json_bytes(value) + b"\n")
    return load_source_registry(path)


def _negative_manifest(*, checked: list[str]) -> dict[str, object]:
    """Build a manifest-valid absent-observation payload checking exactly `checked`."""
    payload = _manifest()
    payloads = [{"path": "authority-registry.json", "sha256": _sha(_bound_registry())}]
    captures = []
    for key in checked:
        path = "rendered.txt" if key == "valve-ti-group-stage-rules" else f"captures/{key}.bin"
        payloads.append({"path": path, "sha256": _sha(f"synthetic-{key}".encode())})
        captures.append({"source_url_key": key, "path": path})
    payload["payloads"] = payloads
    payload["attestation"] = None
    payload["observation"] = {
        "assertion": "absent",
        "observed_at_utc": "2026-01-01T00:00:01Z",
        "supported_through_utc": "2026-01-01T00:00:01Z",
        "captures": captures,
        "authoritative_source_keys_checked": list(checked),
        "diagnostic_reason": None,
    }
    payload["evidence_id"] = ""
    payload["evidence_id"] = evidence_id_for_manifest(payload)
    return payload


def _negative_record_with_payload_bytes(
    *, checked: list[str] | None = None
) -> tuple[dict[str, object], dict[str, bytes]]:
    """Build a manifest-valid absent-observation payload plus its exact payload bytes.

    In the style of `_negative_manifest`, but every declared digest is derived
    from real bytes returned alongside the manifest, so the result can be
    handed to `write_evidence_record` -- not merely shape-validated.
    """
    checked = checked if checked is not None else ["valve-ti-group-stage-rules"]
    registry_bytes = _bound_registry()
    payload_bytes: dict[str, bytes] = {"authority-registry.json": registry_bytes}
    payloads = [{"path": "authority-registry.json", "sha256": _sha(registry_bytes)}]
    captures = []
    for key in checked:
        path = "rendered.txt" if key == "valve-ti-group-stage-rules" else f"captures/{key}.bin"
        data = f"synthetic-{key}".encode()
        payload_bytes[path] = data
        payloads.append({"path": path, "sha256": _sha(data)})
        captures.append({"source_url_key": key, "path": path})
    payload = _manifest()
    payload["payloads"] = payloads
    payload["attestation"] = None
    payload["observation"] = {
        "assertion": "absent",
        "observed_at_utc": "2026-01-01T00:00:01Z",
        "supported_through_utc": "2026-01-01T00:00:01Z",
        "captures": captures,
        "authoritative_source_keys_checked": list(checked),
        "diagnostic_reason": None,
    }
    payload["evidence_id"] = ""
    payload["evidence_id"] = evidence_id_for_manifest(payload)
    return payload, payload_bytes


def _record(
    tmp_path,
    marker,
    available,
    supersedes=(),
    subject="rules:ti2026:valve:group-stage",
    *,
    assertion="present",
    construction="contemporaneous",
):
    payload = _manifest()
    payload.update({"evidence_id": "", "subject_key": subject, "supersedes": list(supersedes)})
    payload["source"]["capture_method"] = f"synthetic-{marker}"
    payload["source"]["available_at_utc"] = available
    payload["source"]["retrieved_at_utc"] = available
    payload["observation"]["assertion"] = assertion
    payload["observation"]["observed_at_utc"] = available
    payload["observation"]["supported_through_utc"] = available
    payload["construction"] = construction
    if assertion == "absent":
        payload["attestation"] = None
        payload["observation"]["authoritative_source_keys_checked"] = ["valve-ti-group-stage-rules"]
    payload["evidence_id"] = evidence_id_for_manifest(payload)
    return validate_evidence_manifest(tmp_path, payload, verify_payloads=False)


def _cyclic_records(tmp_path):
    """Build two internally consistent records, then corrupt their supersedes edges into a cycle.

    Honest content-addressed publication cannot produce this: `supersedes` is
    part of the content digest, so a real publisher cannot retarget an
    existing record's predecessors without changing its own identity. This
    models a corrupt manifest handed directly to the pure selector, which
    must still fail closed.
    """
    first = _record(tmp_path, "cycle-first", "2026-01-01T00:00:00Z")
    second = _record(tmp_path, "cycle-second", "2026-01-01T00:00:01Z", (first.evidence_id,))
    corrupted_first = dataclasses.replace(first, supersedes=(second.evidence_id,))
    return [corrupted_first, second]


def _negative_record_observed_later(tmp_path, ancestor, *, available, observed):
    """Build an absent-observation record whose observation trails its availability.

    Unlike `_record`, `available_at_utc` and `observed_at_utc` differ, so its
    graph-applicability timestamp (`max` of the two) can fall after a cutoff
    even though the source itself became available earlier.
    """
    payload = _manifest()
    payload.update(
        {
            "evidence_id": "",
            "subject_key": ancestor.subject_key,
            "supersedes": [ancestor.evidence_id],
        }
    )
    payload["source"]["capture_method"] = "synthetic-negative-observed-later"
    payload["source"]["available_at_utc"] = available
    payload["source"]["retrieved_at_utc"] = observed
    payload["observation"]["assertion"] = "absent"
    payload["observation"]["observed_at_utc"] = observed
    payload["observation"]["supported_through_utc"] = observed
    payload["observation"]["authoritative_source_keys_checked"] = ["valve-ti-group-stage-rules"]
    payload["attestation"] = None
    payload["evidence_id"] = evidence_id_for_manifest(payload)
    return validate_evidence_manifest(tmp_path, payload, verify_payloads=False)


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


def test_roster_payload_requires_one_exact_five_account_set_per_team():
    """Kills mutation: accept a roster evidence entry with fewer than five unique accounts."""
    with pytest.raises(EvidenceError, match="five"):
        validate_kind_payload(
            "rosters",
            {
                "schema": "ti26.rosters.v1",
                "rosters": [{"team_id": 101, "account_ids": [1, 2, 3, 4]}],
            },
            assertion="present",
        )


def test_draw_unpublished_requires_negative_observation_and_forbids_a_value():
    """Kills mutation: represent unpublished groups with a value or positive observation."""
    with pytest.raises(EvidenceError, match="unpublished"):
        validate_kind_payload(
            "draws",
            {
                "schema": "ti26.draw-fact.v1",
                "component": "groups",
                "publication_state": "unpublished",
                "value": {"a": [101]},
            },
            assertion="present",
        )


def test_draw_payload_represents_only_one_publication_component():
    """Kills mutation: combine groups and Round 1 under one publication state."""
    with pytest.raises(EvidenceError, match="unsupported or missing"):
        validate_kind_payload(
            "draws",
            {
                "schema": "ti26.draw-fact.v1",
                "component": "groups",
                "publication_state": "published",
                "value": {"a": [101]},
                "round_one": [[101, 102]],
            },
            assertion="present",
        )


def test_participant_reconciler_reports_missing_and_unexpected_team_keys():
    """Kills mutation: reconcile participant facts by display name and ignore field membership."""
    with pytest.raises(ReconciliationError, match="team_id"):
        reconcile_participants({101}, {102})


def test_roster_reconciler_does_not_accept_an_organisation_name_as_identity():
    """Kills mutation: reconcile roster evidence by display name rather than exact account ids."""
    with pytest.raises(ReconciliationError, match="account_ids"):
        reconcile_rosters({101: [1, 2, 3, 4, 5]}, {101: [1, 2, 3, 4, 6]})


def test_draw_reconciler_compares_groups_and_round_one_independently():
    """Kills mutation: treat matching group membership as proof of matching Round 1 pairings."""
    with pytest.raises(ReconciliationError, match="round_one"):
        reconcile_draw(
            {"groups": {"a": [101, 102]}, "round_one": [[101, 102]]},
            {"groups": {"a": [101, 102]}, "round_one": [[102, 101]]},
        )


def test_source_registry_rejects_an_unregistered_authority(tmp_path):
    """Kills mutation: accept a source key that is not registered for the evidence subject."""
    registry = _source_registry(tmp_path, subject_key="rules:ti2026:owner:other-slot")
    record = validate_evidence_manifest(tmp_path, _manifest(), verify_payloads=False)
    with pytest.raises(EvidenceError, match="not registered"):
        validate_record_sources(record, registry)


def test_negative_observation_cannot_omit_a_registered_authority(tmp_path):
    """Kills mutation: allow an owner to check only a subset of exact-pair authorities."""
    registry = _source_registry(tmp_path, additional_authority="valve-ti-series-page")
    record = validate_evidence_manifest(
        tmp_path,
        _negative_manifest(checked=["valve-ti-group-stage-rules"]),
        verify_payloads=False,
    )
    with pytest.raises(EvidenceError, match="complete authority set"):
        validate_record_sources(record, registry)


def test_write_evidence_record_binds_written_bytes_and_writes_manifest_last(tmp_path, monkeypatch):
    """Kills mutation: create manifest.json before validating every payload digest."""
    seen_manifest = []
    original = Path.open

    def observing_open(path, mode="r", *args, **kwargs):
        if Path(path).name == "manifest.json" and "x" in mode:
            assert (Path(path).parent / "authority-registry.json").is_file()
            assert (Path(path).parent / "rendered.txt").is_file()
            assert (Path(path).parent / "extracted.json").is_file()
            seen_manifest.append(True)
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observing_open)
    record = write_evidence_record(
        tmp_path, _manifest(),
        {"authority-registry.json": _bound_registry(), "rendered.txt": b"Group Stage Rules\n", "extracted.json": canonical_json_bytes({"schema": "ti26.rules-extracted.v1", "facts": {}}) + b"\n"},
    )
    assert seen_manifest == [True]
    assert validate_evidence_manifest(record, json.loads((record / "manifest.json").read_text()))


def test_write_evidence_record_reuses_only_an_identical_complete_record(tmp_path):
    """Kills mutation: reject an identical complete content-addressed retry or overwrite different bytes."""
    payloads = {"authority-registry.json": _bound_registry(), "rendered.txt": b"Group Stage Rules\n", "extracted.json": canonical_json_bytes({"schema": "ti26.rules-extracted.v1", "facts": {}}) + b"\n"}
    write_evidence_record(tmp_path, _manifest(), payloads)
    assert write_evidence_record(tmp_path, _manifest(), payloads) == tmp_path / "rules" / _manifest()["evidence_id"]


def test_write_evidence_record_rejects_caller_digest_that_does_not_describe_bytes(tmp_path):
    """Kills mutation: trust a caller-supplied payload digest instead of hashing bytes written."""
    payload, payload_bytes = _negative_record_with_payload_bytes()
    corrupted = next(entry for entry in payload["payloads"] if entry["path"] != "authority-registry.json")
    corrupted["sha256"] = "0" * 64
    payload["evidence_id"] = ""
    payload["evidence_id"] = evidence_id_for_manifest(payload)
    with pytest.raises(EvidenceError, match="sha256"):
        write_evidence_record(tmp_path, payload, payload_bytes)


def test_present_evidence_requires_availability_no_later_than_cutoff(tmp_path):
    """Kills mutation: admit a positive fact based only on retrieval time."""
    record = validate_evidence_manifest(tmp_path, _manifest(), verify_payloads=False)
    assert evidence_is_admissible(record, "2026-01-01T00:00:00Z") is True
    assert evidence_is_admissible(record, "2025-12-31T23:59:59Z") is False


def test_absent_evidence_expires_after_supported_through(tmp_path):
    """Kills mutation: treat an old negative observation as absence forever."""
    record = validate_evidence_manifest(
        tmp_path,
        _manifest(
            observation={
                "assertion": "absent",
                "observed_at_utc": "2026-01-01T00:00:01Z",
                "supported_through_utc": "2026-01-01T00:00:01Z",
                "captures": [
                    {
                        "source_url_key": "valve-ti-group-stage-rules",
                        "path": "rendered.txt",
                    }
                ],
                "authoritative_source_keys_checked": [
                    "valve-ti-group-stage-rules"
                ],
                "diagnostic_reason": None,
            }
        ),
        verify_payloads=False,
    )
    assert evidence_is_admissible(record, "2026-01-01T00:00:00Z") is False
    assert evidence_is_admissible(record, "2026-01-01T00:00:01Z") is True
    assert evidence_is_admissible(record, "2026-01-01T00:00:02Z") is False


def test_present_evidence_without_a_bound_capture_is_rejected(tmp_path):
    """Kills mutation: allow a positive assertion with no source bytes."""
    payload = _manifest()
    payload["observation"]["captures"] = []
    with pytest.raises(EvidenceError, match="capture"):
        validate_evidence_manifest(tmp_path, payload, verify_payloads=False)


def test_negative_evidence_binds_one_capture_for_every_checked_authority(tmp_path):
    """Kills mutation: let one captured page prove absence across multiple authorities."""
    payload = _manifest()
    payload["observation"] = {
        "assertion": "absent",
        "observed_at_utc": "2026-01-01T00:00:01Z",
        "supported_through_utc": "2026-01-01T00:00:01Z",
        "captures": [
            {
                "source_url_key": "valve-ti-group-stage-rules",
                "path": "rendered.txt",
            }
        ],
        "authoritative_source_keys_checked": [
            "valve-ti-group-stage-rules",
            "valve-ti-series-page",
        ],
        "diagnostic_reason": None,
    }
    payload["evidence_id"] = evidence_id_for_manifest(payload)
    with pytest.raises(EvidenceError, match="every checked authority"):
        validate_evidence_manifest(tmp_path, payload, verify_payloads=False)


def test_positive_attestation_rejects_facts_swapped_between_captures(tmp_path):
    """Kills mutation: accept positive facts whose owner attestation names another payload digest."""
    payload = _manifest()
    payload["attestation"]["fact_payload_sha256"] = "0" * 64
    payload["evidence_id"] = evidence_id_for_manifest(payload)
    with pytest.raises(EvidenceError, match="fact_payload_sha256"):
        validate_evidence_manifest(tmp_path, payload, verify_payloads=False)


def test_reconstructed_unknown_is_diagnostic_only_by_default(tmp_path):
    """Kills mutation: admit reconstructed-unknown evidence into release selection by default."""
    payload = _manifest()
    payload["construction"] = "reconstructed_unknown"
    payload["evidence_id"] = evidence_id_for_manifest(payload)
    record = validate_evidence_manifest(tmp_path, payload, verify_payloads=False)
    assert evidence_is_admissible(record, "2026-01-01T00:00:00Z") is False
    assert evidence_is_admissible(
        record,
        "2026-01-01T00:00:00Z",
        allow_reconstructed_unknown=True,
    ) is True


def test_current_selection_rejects_an_available_fork(tmp_path):
    """Kills mutation: choose an arbitrary current tip when incomparable tips exist."""
    records = [_record(tmp_path, "first", "2026-01-01T00:00:00Z"), _record(tmp_path, "second", "2026-01-01T00:00:00Z")]
    with pytest.raises(ReconciliationError, match="incomparable"):
        select_current_evidence(records, "rules", "rules:ti2026:valve:group-stage", "2026-01-01T00:00:00Z")


def test_current_selection_rejects_a_cycle(tmp_path):
    """Kills mutation: traverse supersedes edges without cycle detection."""
    records = _cyclic_records(tmp_path)
    with pytest.raises(ReconciliationError, match="cycle"):
        select_current_evidence(records, "rules", "rules:ti2026:valve:group-stage", "2026-01-01T00:00:00Z")


def test_current_selection_keeps_a_later_descendant_out_of_an_earlier_cutoff(tmp_path):
    """Kills mutation: let a post-cutoff supersession rewrite earlier knowledge."""
    ancestor = _record(tmp_path, "ancestor", "2026-01-01T00:00:00Z")
    descendant = _record(tmp_path, "descendant", "2026-01-01T00:00:02Z", (ancestor.evidence_id,))
    selected = select_current_evidence([ancestor, descendant], "rules", ancestor.subject_key, "2026-01-01T00:00:01Z")
    assert selected.selected.evidence_id == ancestor.evidence_id
    assert selected.rejected[descendant.evidence_id] == "available_after_cutoff"


def test_current_selection_rejects_cross_subject_supersession(tmp_path):
    """Kills mutation: follow a supersedes edge without enforcing subject identity."""
    first = _record(tmp_path, "first", "2026-01-01T00:00:00Z")
    second = _record(tmp_path, "second", "2026-01-01T00:00:01Z", (first.evidence_id,), "rules:ti2026:owner:other-slot")
    with pytest.raises(ReconciliationError, match="cross-subject"):
        select_current_evidence([first, second], "rules", first.subject_key, "2026-01-01T00:00:02Z")


def test_expired_negative_descendant_blocks_its_ancestor(tmp_path):
    """Kills mutation: revive an ancestor after its temporally applicable negative descendant expires."""
    ancestor = _record(tmp_path, "ancestor", "2026-01-01T00:00:00Z")
    negative = _record(tmp_path, "negative", "2026-01-01T00:00:01Z", (ancestor.evidence_id,), assertion="absent")
    with pytest.raises(ReconciliationError, match="negative_observation_expired"):
        select_current_evidence([ancestor, negative], "rules", ancestor.subject_key, "2026-01-01T00:00:02Z")


def test_reconstructed_unknown_descendant_blocks_its_ancestor(tmp_path):
    """Kills mutation: revive an ancestor when the current descendant is reconstructed-unknown."""
    ancestor = _record(tmp_path, "ancestor", "2026-01-01T00:00:00Z")
    unknown = _record(tmp_path, "unknown", "2026-01-01T00:00:01Z", (ancestor.evidence_id,), construction="reconstructed_unknown")
    with pytest.raises(ReconciliationError, match="reconstructed_unknown"):
        select_current_evidence([ancestor, unknown], "rules", ancestor.subject_key, "2026-01-01T00:00:02Z")


def test_negative_descendant_is_not_graph_applicable_before_observation(tmp_path):
    """Kills mutation: let negative availability supersede an ancestor before observation time."""
    ancestor = _record(tmp_path, "ancestor", "2026-01-01T00:00:00Z")
    negative = _negative_record_observed_later(tmp_path, ancestor, available="2026-01-01T00:00:01Z", observed="2026-01-01T00:00:03Z")
    selected = select_current_evidence([ancestor, negative], "rules", ancestor.subject_key, "2026-01-01T00:00:02Z")
    assert selected.selected.evidence_id == ancestor.evidence_id


def test_rules_extractor_binds_each_fact_to_its_exact_rendered_span():
    """Kills mutation: emit normalized rules facts without a supporting text-span digest."""
    rendered = (
        "Number of Matches Won\nNumber of Matches Lost\n"
        "Total Number of Matches Won by Opponents Played\nPercentage of Games Won\n"
        "Average Percentage of Games Won by Opponents Played\n"
        "Average Game Duration (Shorter is Better)\nCoin Toss\n"
        "Round 2\nTeams are only matched against other members of their initial group\n"
        "Round 3\nTeams are only matched against other members of their initial group\n"
        "Round 4\nTeams are only matched against members of the other group\n"
        "Round 5\nFor matches where the loser is eliminated, maximize the distance in ranking between the teams\n"
        "Elimination Round\nStarting with the best 3-2 team, they will choose any of the five 2-3 teams as their opponent.\n"
    )
    extracted = extract_ti2026_rules(rendered)
    assert extracted["schema"] == "ti26.rules-extracted.v1"
    assert all(value["span_sha256"] for value in extracted["facts"].values())


def test_reconcile_rules_facts_reports_the_field_that_diverges():
    """Kills mutation: compare only provenance tags and ignore factual values."""
    expected = {
        "tiebreak_order": ["series_wins"],
        "rounds": {"within_group": [2], "cross_group": [4], "max_distance_when_loser_eliminated": [5]},
        "elimination_selection_order": "best_3_2_sequential_choice",
    }
    observed = {
        "schema": "ti26.rules-extracted.v1",
        "facts": {
            "tiebreak_order": {"value": ["series_losses"], "span_sha256": "a" * 64},
            "rounds": {"value": expected["rounds"], "span_sha256": "b" * 64},
            "elimination_selection_order": {
                "value": expected["elimination_selection_order"],
                "span_sha256": "c" * 64,
            },
        },
    }
    with pytest.raises(ReconciliationError, match="tiebreak_order"):
        reconcile_rules_facts(expected, observed)


def test_rules_format_extractor_requires_its_supporting_span():
    """Kills mutation: derive published-format facts from the group-stage extractor."""
    rendered = (
        "Format\n"
        "Number of Teams: 16\n"
        "Total Rounds: 5\n"
        "Advance at Wins: 4\n"
        "Eliminate at Losses: 4\n"
    )
    extracted = extract_ti2026_published_format(rendered)
    assert extracted["schema"] == "ti26.rules-format-extracted.v1"
    assert extracted["facts"]["format"]["span_sha256"]
    assert extracted["facts"]["format"]["value"] == {
        "n_teams": 16,
        "total_rounds": 5,
        "advance_at_wins": 4,
        "eliminate_at_losses": 4,
    }
    with pytest.raises(EvidenceError, match="format"):
        extract_ti2026_published_format("Some unrelated published text with no format fragment.\n")


def test_reconcile_rules_format_facts_reports_each_field():
    """Kills mutation: compare only a format schema or one scalar."""
    expected = {
        "format": {
            "n_teams": 16,
            "total_rounds": 5,
            "advance_at_wins": 4,
            "eliminate_at_losses": 4,
        }
    }
    observed = {
        "schema": "ti26.rules-format-extracted.v1",
        "facts": {
            "format": {
                "value": {
                    "n_teams": 16,
                    "total_rounds": 5,
                    "advance_at_wins": 4,
                    "eliminate_at_losses": 5,
                },
                "span_sha256": "d" * 64,
            }
        },
    }
    with pytest.raises(ReconciliationError, match=r"format\.eliminate_at_losses"):
        reconcile_rules_format_facts(expected, observed)


# --- Task 7: release-evidence catalog and reconciliation fixtures -----------
#
# Every fixture below writes through `write_evidence_record` (in the style of
# `_current_fork` in `tests/test_cli_evidence_import.py`), so no test here
# hand-authors a trusted manifest; `load_release_evidence` does the real
# verification. All four teams and their ids are a synthetic fixture field,
# never a real TI 2026 participant.

_RELEASE_SOURCE_KEY = "owner-capture"
_RELEASE_AVAILABLE = "2026-01-01T00:00:00Z"
_RELEASE_OBSERVED = "2026-01-01T00:00:01Z"
_RELEASE_CUTOFF = "2026-01-01T00:00:01Z"
_RELEASE_KIND_BY_NAME = {
    "rules": "rules",
    "published_format": "rules",
    "participants": "participants",
    "rosters": "rosters",
    "groups": "draws",
    "round_one": "draws",
}
_TEAM_NAMES = {101: "Alpha", 102: "Beta", 103: "Gamma", 104: "Delta"}
_RULES_FACTS_VALUE = {
    "tiebreak_order": [
        "series_wins",
        "series_losses",
        "opponent_series_wins",
        "game_win_pct",
        "opponent_game_win_pct",
        "avg_duration",
        "coin_toss",
    ],
    "rounds": {
        "within_group": [2, 3],
        "cross_group": [4],
        "max_distance_when_loser_eliminated": [5],
    },
    "elimination_selection_order": "best_3_2_sequential_choice",
}
_FORMAT_FACTS_VALUE = {"n_teams": 4, "total_rounds": 5, "advance_at_wins": 4, "eliminate_at_losses": 4}
_DEFAULT_GROUPS_VALUE = {"A": [101, 102], "B": [103, 104]}
_DEFAULT_ROUND_ONE_VALUE = [[101, 102], [103, 104]]


def _release_registry_value() -> dict[str, object]:
    return {
        "schema": "ti26.evidence-source-registry.v1",
        "effective_at_utc": "2025-12-31T00:00:00Z",
        "sources": [
            {
                "source_url_key": _RELEASE_SOURCE_KEY,
                "authorizations": [
                    {
                        "event_id": "ti2026",
                        "kind": _RELEASE_KIND_BY_NAME[name],
                        "subject_key": subject_key,
                    }
                    for name, subject_key in RELEASE_SUBJECTS.items()
                ],
            }
        ],
    }


def _release_registry_bytes() -> bytes:
    return canonical_evidence_json_bytes(_release_registry_value()) + b"\n"


def _write_release_record(
    root: Path,
    *,
    kind: str,
    subject_key: str,
    assertion: str,
    normalized_path: str,
    normalized_value: dict[str, object],
    capture_path: str,
    capture_bytes: bytes,
    construction: str = "contemporaneous",
    supersedes: tuple[str, ...] = (),
    available_at_utc: str = _RELEASE_AVAILABLE,
    observed_at_utc: str = _RELEASE_OBSERVED,
) -> EvidenceManifest:
    """Build and write one manifest-valid release-evidence record.

    Every declared digest is derived from the actual bytes handed to
    `write_evidence_record`, per the plan's test-helper convention. `assertion`
    picks the observation shape: `"present"` binds a positive attestation to
    `normalized_path`; `"absent"` checks (and captures) exactly the one
    registered authority, `_RELEASE_SOURCE_KEY`, and carries no attestation.
    """
    registry_bytes = _release_registry_bytes()
    normalized_bytes = canonical_evidence_json_bytes(normalized_value) + b"\n"
    payloads = [
        {"path": "authority-registry.json", "sha256": _sha(registry_bytes)},
        {"path": capture_path, "sha256": _sha(capture_bytes)},
        {"path": normalized_path, "sha256": _sha(normalized_bytes)},
    ]
    payload_bytes = {
        "authority-registry.json": registry_bytes,
        capture_path: capture_bytes,
        normalized_path: normalized_bytes,
    }
    captures = [{"source_url_key": _RELEASE_SOURCE_KEY, "path": capture_path}]
    if assertion == "present":
        observation = {
            "assertion": "present",
            "observed_at_utc": observed_at_utc,
            "supported_through_utc": observed_at_utc,
            "captures": captures,
            "authoritative_source_keys_checked": [],
            "diagnostic_reason": None,
        }
        attestation = {
            "fact_payload_sha256": _sha(normalized_bytes),
            "capture_sha256s": [_sha(capture_bytes)],
        }
    else:
        observation = {
            "assertion": "absent",
            "observed_at_utc": observed_at_utc,
            "supported_through_utc": observed_at_utc,
            "captures": captures,
            "authoritative_source_keys_checked": [_RELEASE_SOURCE_KEY],
            "diagnostic_reason": None,
        }
        attestation = None

    manifest = {
        "schema": "ti26.evidence-manifest.v1",
        "evidence_id": "",
        "kind": kind,
        "event_id": "ti2026",
        "subject_key": subject_key,
        "source": {
            "source_url_key": _RELEASE_SOURCE_KEY,
            "capture_method": "owner-supplied-capture",
            "available_at_utc": available_at_utc,
            "published_at_utc": None,
            "retrieved_at_utc": observed_at_utc,
        },
        "observation": observation,
        "attestation": attestation,
        "authority_registry": {
            "schema": "ti26.evidence-authority-binding.v1",
            "path": "authority-registry.json",
            "sha256": _sha(registry_bytes),
            "effective_at_utc": "2025-12-31T00:00:00Z",
        },
        "construction": construction,
        "payloads": payloads,
        "supersedes": list(supersedes),
        "producer_revision": "a" * 40,
    }
    manifest["evidence_id"] = evidence_id_for_manifest(manifest)
    record_path = write_evidence_record(root, manifest, payload_bytes)
    return validate_evidence_manifest(record_path, manifest, verify_payloads=True)


def _extracted_rules_value() -> dict[str, object]:
    return {
        "schema": "ti26.rules-extracted.v1",
        "facts": {
            key: {"value": value, "span_sha256": _sha(f"span:{key}".encode())}
            for key, value in _RULES_FACTS_VALUE.items()
        },
    }


def _extracted_format_value(value: dict[str, int]) -> dict[str, object]:
    return {
        "schema": "ti26.rules-format-extracted.v1",
        "facts": {"format": {"value": value, "span_sha256": _sha(b"span:format")}},
    }


def _roster_accounts_for(team_id: int) -> list[int]:
    base = (team_id - 101) * 5 + 1
    return list(range(base, base + 5))


def _release_catalog(
    tmp_path: Path,
    *,
    omit_subject: str | None = None,
    groups_state: str = "unpublished",
    round_one_state: str = "unpublished",
    evidence_round_one: list[list[int]] | None = None,
    roster_construction: str = "contemporaneous",
    team_ids: list[int] | None = None,
    roster_team_ids: list[int] | None = None,
    format_facts: dict[str, int] | None = None,
    rules_ancestor: bool = False,
):
    """Write a complete, manifest-valid synthetic release catalog under `tmp_path/"evidence"`.

    Defaults to the single-team field `{101: Alpha}` with both draw
    components unpublished. `groups_state`/`round_one_state` of
    `"published"` switch the default field to the four-team fixture
    (`101..104`, two even groups) that `load_group_draw` requires.
    `omit_subject` skips writing exactly the named `RELEASE_SUBJECTS` value,
    simulating evidence that was never captured.
    """
    root = tmp_path / "evidence"
    root.mkdir(parents=True, exist_ok=True)
    (root / "source-registry.json").write_bytes(_release_registry_bytes())

    uses_four_teams = groups_state == "published" or round_one_state == "published"
    default_team_ids = [101, 102, 103, 104] if uses_four_teams else [101]
    resolved_team_ids = team_ids if team_ids is not None else default_team_ids
    resolved_roster_ids = roster_team_ids if roster_team_ids is not None else resolved_team_ids

    def omitted(name: str) -> bool:
        return RELEASE_SUBJECTS[name] == omit_subject

    if not omitted("rules"):
        supersedes: tuple[str, ...] = ()
        if rules_ancestor:
            ancestor = _write_release_record(
                root,
                kind="rules",
                subject_key=RELEASE_SUBJECTS["rules"],
                assertion="present",
                normalized_path="extracted.json",
                normalized_value=_extracted_rules_value(),
                capture_path="rendered.txt",
                capture_bytes=b"Group Stage Rules (ancestor)\n",
                available_at_utc="2025-12-31T00:00:00Z",
                observed_at_utc="2025-12-31T00:00:01Z",
            )
            supersedes = (ancestor.evidence_id,)
        _write_release_record(
            root,
            kind="rules",
            subject_key=RELEASE_SUBJECTS["rules"],
            assertion="present",
            normalized_path="extracted.json",
            normalized_value=_extracted_rules_value(),
            capture_path="rendered.txt",
            capture_bytes=b"Group Stage Rules (current)\n",
            supersedes=supersedes,
        )

    if not omitted("published_format"):
        _write_release_record(
            root,
            kind="rules",
            subject_key=RELEASE_SUBJECTS["published_format"],
            assertion="present",
            normalized_path="format-extracted.json",
            normalized_value=_extracted_format_value(format_facts or _FORMAT_FACTS_VALUE),
            capture_path="format-rendered.txt",
            capture_bytes=b"Format\n",
        )

    if not omitted("participants"):
        participants_value = {
            "schema": "ti26.participants.v1",
            "participants": [
                {"team_id": team_id, "display_name": _TEAM_NAMES[team_id]}
                for team_id in sorted(resolved_team_ids)
            ],
        }
        _write_release_record(
            root,
            kind="participants",
            subject_key=RELEASE_SUBJECTS["participants"],
            assertion="present",
            normalized_path="participants.json",
            normalized_value=participants_value,
            capture_path="source.bin",
            capture_bytes=b"participants capture",
        )

    if not omitted("rosters"):
        rosters_value = {
            "schema": "ti26.rosters.v1",
            "rosters": [
                {"team_id": team_id, "account_ids": _roster_accounts_for(team_id)}
                for team_id in sorted(resolved_roster_ids)
            ],
        }
        _write_release_record(
            root,
            kind="rosters",
            subject_key=RELEASE_SUBJECTS["rosters"],
            assertion="present",
            normalized_path="rosters.json",
            normalized_value=rosters_value,
            capture_path="source.bin",
            capture_bytes=b"rosters capture",
            construction=roster_construction,
        )

    if not omitted("groups"):
        groups_value = _DEFAULT_GROUPS_VALUE if groups_state == "published" else None
        _write_release_record(
            root,
            kind="draws",
            subject_key=RELEASE_SUBJECTS["groups"],
            assertion="present" if groups_state == "published" else "absent",
            normalized_path="draw.json",
            normalized_value={
                "schema": "ti26.draw-fact.v1",
                "component": "groups",
                "publication_state": groups_state,
                "value": groups_value,
            },
            capture_path="captures/owner-capture.bin",
            capture_bytes=b"groups capture",
        )

    if not omitted("round_one"):
        if round_one_state == "published":
            round_one_value = evidence_round_one if evidence_round_one is not None else _DEFAULT_ROUND_ONE_VALUE
        else:
            round_one_value = None
        _write_release_record(
            root,
            kind="draws",
            subject_key=RELEASE_SUBJECTS["round_one"],
            assertion="present" if round_one_state == "published" else "absent",
            normalized_path="draw.json",
            normalized_value={
                "schema": "ti26.draw-fact.v1",
                "component": "round_one",
                "publication_state": round_one_state,
                "value": round_one_value,
            },
            capture_path="captures/owner-capture.bin",
            capture_bytes=b"round one capture",
        )

    return load_release_evidence(root)


def _rules_yaml(tmp_path: Path, *, format_value: dict[str, int]) -> Path:
    value = {
        "tiebreak_order": _RULES_FACTS_VALUE["tiebreak_order"],
        "rounds": _RULES_FACTS_VALUE["rounds"],
        "format": format_value,
    }
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(value), encoding="utf-8")
    return path


def _teams_yaml(tmp_path: Path, team_ids: list[int]) -> Path:
    value = {
        "teams": [
            {"name": _TEAM_NAMES[team_id], "team_id": team_id} for team_id in sorted(team_ids)
        ]
    }
    path = tmp_path / "teams.yaml"
    path.write_text(yaml.safe_dump(value), encoding="utf-8")
    return path


def _release_inputs(
    tmp_path: Path,
    *,
    groups_path: Path | None = None,
    team_ids: list[int] | None = None,
    format_value: dict[str, int] | None = None,
) -> dict[str, object]:
    """Build the keyword arguments `reconcile_release_evidence` expects.

    Defaults to the single-team field, matching `_release_catalog`'s own
    default; a supplied `groups_path` switches the default field to the
    four-team fixture so `load_group_draw` sees a configured name for every
    member of its groups YAML.
    """
    resolved_team_ids = team_ids
    if resolved_team_ids is None:
        resolved_team_ids = [101, 102, 103, 104] if groups_path is not None else [101]
    return {
        "cutoff_utc": _RELEASE_CUTOFF,
        "rules_path": _rules_yaml(tmp_path, format_value=format_value or _FORMAT_FACTS_VALUE),
        "teams_path": _teams_yaml(tmp_path, resolved_team_ids),
        "groups_path": groups_path,
    }


def _draw_yaml(tmp_path: Path, *, round_one: list[list[str]] | None = None) -> Path:
    """Write an existing-format draw YAML for the default four-team fixture field.

    Group A: Alpha, Beta. Group B: Gamma, Delta. `round_one`, when given,
    overrides only the pairs it names by group; any group not mentioned
    keeps its default in-group pairing, so the result always satisfies
    `load_group_draw`'s full-coverage requirement.
    """
    label_of = {"Alpha": "A", "Beta": "A", "Gamma": "B", "Delta": "B"}
    pairs = {"A": ["Alpha", "Beta"], "B": ["Gamma", "Delta"]}
    if round_one is not None:
        for pair in round_one:
            pairs[label_of[pair[0]]] = list(pair)
    value = {
        "groups": {"A": ["Alpha", "Beta"], "B": ["Gamma", "Delta"]},
        "round_one": [pairs["A"], pairs["B"]],
    }
    path = tmp_path / "draw.yaml"
    path.write_text(yaml.safe_dump(value), encoding="utf-8")
    return path


def test_release_loader_rejects_an_incomplete_record_directory(tmp_path):
    """Kills mutation: skip an evidence directory merely because manifest.json is absent."""
    incomplete = tmp_path / "evidence" / "rosters" / ("a" * 64)
    incomplete.mkdir(parents=True)
    (incomplete / "rosters.json").write_text("{}", encoding="utf-8")
    with pytest.raises(EvidenceError, match="incomplete"):
        load_release_evidence(tmp_path / "evidence")


def test_release_reconciliation_requires_current_rules_field_rosters_and_both_draw_components(tmp_path):
    """Kills mutation: treat a missing Round-1 observation as unpublished evidence."""
    catalog = _release_catalog(tmp_path, omit_subject="draws:ti2026:event-authority:round-one")
    with pytest.raises(ReconciliationError, match="round.one"):
        reconcile_release_evidence(catalog, **_release_inputs(tmp_path))


def test_release_reconciliation_binds_negative_draw_captures_and_exact_rosters(tmp_path):
    """Kills mutation: return only positive evidence paths or compare rosters by organisation ID."""
    catalog = _release_catalog(tmp_path, groups_state="unpublished", round_one_state="unpublished")
    result = reconcile_release_evidence(catalog, **_release_inputs(tmp_path, groups_path=None))
    assert result.roster_accounts == {101: (1, 2, 3, 4, 5)}
    assert result.draw_states == {"groups": "unpublished", "round_one": "unpublished"}
    assert any("captures" in path.parts for path in result.input_paths)


def test_release_reconciliation_compares_published_groups_and_round_one_independently(tmp_path):
    """Kills mutation: accept matching groups as proof that supplied Round 1 also matches."""
    draw_path = _draw_yaml(tmp_path, round_one=[["Alpha", "Beta"]])
    catalog = _release_catalog(
        tmp_path, groups_state="published", round_one_state="published", evidence_round_one=[[101, 999]]
    )
    with pytest.raises(ReconciliationError, match="round_one"):
        reconcile_release_evidence(catalog, **_release_inputs(tmp_path, groups_path=draw_path))


def test_release_reconciliation_rejects_reconstructed_unknown_even_if_a_tip_exists(tmp_path):
    """Kills mutation: opt release selection into diagnostic reconstructed-unknown evidence."""
    catalog = _release_catalog(tmp_path, roster_construction="reconstructed_unknown")
    with pytest.raises(ReconciliationError, match="reconstructed_unknown"):
        reconcile_release_evidence(catalog, **_release_inputs(tmp_path))


def test_release_reconciliation_reconciles_published_format_facts(tmp_path):
    """Kills mutation: gate the format subject on existence without reconciling its facts against shipping config."""
    mismatched = dict(_FORMAT_FACTS_VALUE)
    mismatched["eliminate_at_losses"] = _FORMAT_FACTS_VALUE["eliminate_at_losses"] + 1
    catalog = _release_catalog(tmp_path, format_facts=mismatched)
    with pytest.raises(ReconciliationError, match="format"):
        reconcile_release_evidence(catalog, **_release_inputs(tmp_path))


def test_release_inputs_bind_applicable_lineage(tmp_path):
    """Kills mutation: bind only the selected tip while using unbound ancestors or competing tips for graph selection."""
    catalog = _release_catalog(tmp_path, rules_ancestor=True)
    rules_records = [
        record for record in catalog.records if record.subject_key == RELEASE_SUBJECTS["rules"]
    ]
    assert len(rules_records) == 2
    ancestor = next(record for record in rules_records if record.supersedes == ())
    result = reconcile_release_evidence(catalog, **_release_inputs(tmp_path))
    assert (ancestor.root / "manifest.json") in result.input_paths
    assert (ancestor.root / "rendered.txt") in result.input_paths


def test_release_reconciliation_rejects_roster_coverage_gap(tmp_path):
    """Kills mutation: omit authoritative participant coverage from release reconciliation."""
    catalog = _release_catalog(tmp_path, team_ids=[101, 102], roster_team_ids=[101])
    with pytest.raises(ReconciliationError, match="coverage"):
        reconcile_release_evidence(catalog, **_release_inputs(tmp_path, team_ids=[101, 102]))
