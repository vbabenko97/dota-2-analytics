# Evidence Import and Rules Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create immutable, offline-imported external evidence records for rules, participants, exact-five rosters, and the independently published draw components, then use their normalized TI 2026 facts to fail closed on shipping-input mismatches without changing predictive behavior.

**Architecture:** A new dependency-minimal `ti26.evidence` module owns exact, subject-dispatched schemas for rules, participants, exact-five account rosters, and one independently published draw component per record; safe artifact paths; semantic content addressing; exclusive payload/manifest publication; evidence verification; and pure current-at-cutoff reconciliation. `cli_evidence_import` reads only owner-supplied local capture, normalized fact, metadata, and authority-registry files, resolves clean actual `HEAD` for a real import, derives the record identifier, and writes a new evidence directory with `manifest.json` last. Its audited production import graph contains no transport module or network call. This slice commits only the current rendered group-stage-rules record because the published-format, participant, roster, and draw facts require fresh owner captures, but it implements and tests every import subcommand — six capture-import modes plus `migrate-v1`, per the amended Task 6 contract — and the evidence-only adapter that Plan 3 consumes.

**Tech Stack:** Python 3.12 standard library (`dataclasses`, `datetime`, `hashlib`, `json`, `pathlib`), existing PyYAML, pytest, Ruff, committed data artifacts, and `.venv/bin/python`.

**Test-helper convention:** some RED-test listings reference small fixture helpers (`_negative_record_observed_later`, `_release_catalog`, `_release_inputs`, `_draw_yaml`, `_current_fork`, `_expected_import_path`, `_complete_rules_text`, `_source_metadata`, `_write_json`, and similar underscore-prefixed names) without printing their bodies. Implement each in the same test file, in the style of the fully specified `_manifest`/`_bound_registry` helpers: build the minimal record or file the referencing test names, declare exactly the payload paths written, and derive every digest from the actual bytes. A helper never relaxes a schema rule to make its test pass.

---

## Scope and non-goals

This is pre-TI hardening plan 2 from the approved design at `docs/superpowers/specs/2026-08-09-three-plane-forecasting-system-design.md:990-1010`.

- It imports and verifies all release evidence kinds offline, chooses each unique current record at a cutoff, extracts and reconciles rules facts, binds the existing Valve capture, adds the superseded banner, and removes unbound empirical prose from touched rules comments.
- It does not alter `Rules`, `TIEBREAK_ORDER`, pairing, elimination choice policy, duration fitting, simulation, card assignment, gates, `cli_release`, checkout preflight, or run-bundle declared inputs. Those changes belong to plan 3.
- It does not fetch Valve, participant, roster, draw, or patch sources. The owner supplies locally captured bytes and source metadata; the importer must reject any option or implementation that contacts a host.
- The artifact source metadata must contain the actual RFC 3339 availability and retrieval times supplied by the owner. Do not fabricate an availability timestamp from the prose archive: a date-only archive cannot establish a precise availability time.

## File structure

- Create: `src/ti26/evidence.py` — generic exact evidence schemas, semantic descriptor/content addressing, safe file handling, canonical manifests, validation, supersession graph selection, and pure reconcilers.
- Create: `src/ti26/cli_evidence_import.py` — offline owner-capture importer with the seven subcommands of Task 6's authoritative table (`rules`, `rules-format`, `prediction-shape`, `participants`, `rosters`, `draw`, `migrate-v1`) and an audited transport-free production dependency graph.
- Create: `data/evidence/source-registry.json` — exact owner-reviewed stable source-key registry used by import and release verification; it contains no mutable URLs.
- Create: `tests/test_evidence.py` — unit tests for schemas, content addressing, manifest-last/exclusive behavior, observation validity, graph selection, and reconciliation.
- Create: `tests/test_cli_evidence_import.py` — black-box offline import and no-network tests.
- Modify: `src/ti26/rules.py` — `shipping_rules_facts(path: str) -> dict[str, object]`; it reads YAML only and exposes no model-facing behavior.
- Modify: `tests/test_rules.py` — prove configuration fact projection and reconciler agreement without changing the existing rule engine assertions.
- Create: `data/evidence/imports/valve-group-stage-rendered.txt` — owner-supplied exact rendered capture used as the local import source.
- Create: `data/evidence/imports/valve-group-stage-source.json` — owner-supplied exact source metadata used as the local import source.
- Create: the generated lowercase-digest directory beneath `data/evidence/rules/` — immutable rules evidence record containing `rendered.txt`, `extracted.json`, and `manifest.json`, after the owner has supplied precise source metadata. The implementation and generated manifest, never this plan, determine the directory name.
- Modify: `docs/ti26/2026-08-08-ti2026-rules-fetched.md` — replace its non-immutable-input framing with a short pointer to the generated evidence manifest; retain the archived body exactly.
- Modify: `docs/ti26/2026-08-08-published-format-rules.md` — prepend a superseded notice for the morning TI 2026 transcription, link the later evidence record, and do not alter the historical transcription body.
- Modify: `config/ti2026_rules.yaml` — remove empirical quantities and comparisons from duration-model and tiebreak/pairing-provenance comments; leave YAML keys, parsed values, provenance tags, and every predictive setting semantically unchanged.
- Modify: `docs/ti26/near-lock-runbook.md` — replace the manual archive/diff instruction with owner capture plus offline import and reconciliation commands, preserving owner stop authority.

The new manifest schemas use string identifiers rather than an integer schema field:

```python
EVIDENCE_MANIFEST_SCHEMA_V1 = "ti26.evidence-manifest.v1"
EVIDENCE_MANIFEST_SCHEMA_V2 = "ti26.evidence-manifest.v2"
EVIDENCE_MANIFEST_WRITE_SCHEMA = EVIDENCE_MANIFEST_SCHEMA_V2
RULES_EXTRACTED_SCHEMA = "ti26.rules-extracted.v1"
```

**Amended 2026-08-11 — read this before implementing anything below.** Both manifest versions are live: v1 is read-only legacy with a required singular `source`, v2 is what every writer emits and carries a required `sources` map instead. The two exact key sets are separate constants and `validate_evidence_manifest` dispatches on the exact `schema` value; no record straddles versions. Task 1's snippets and fixtures in the sections that follow are the **v1** contract, and they remain correct for reading historical records — but a worker implementing them as the write path would produce v1 records, which is wrong. The v2 contract, the multi-source import metadata document, the prediction-shape producer, and the executable v1→v2 migration are specified in the published-format section and its neighbours later in this plan. Read those before writing the writer.

All evidence JSON producer output is `canonical_evidence_json_bytes(value) + b"\n"`, implemented locally with the same `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)` contract as `ti26.provenance.canonical_json_bytes`; a test proves byte equality without making the production evidence module import the much wider run-provenance graph. Paths stored in manifests are POSIX-relative to the evidence-record directory, must name regular files, and may not contain a symlink, `.` component, `..` component, backslash, or absolute prefix. `evidence_id` is never an owner input: `evidence_descriptor(manifest_without_id)` returns the semantic descriptor containing all manifest fields except `evidence_id`, with every set-like field canonical-sorted; `evidence_id = sha256(canonical_evidence_json_bytes(descriptor)).hexdigest()`. The descriptor binds each payload digest, every capture mapping, and the record-local authority-registry digest/version. The producer first canonicalizes all payload bytes in memory, computes their digests, derives the descriptor and destination `data/evidence/<kind>/<evidence_id>/`, then exclusive-creates payload files, revalidates their on-disk digests, and exclusive-creates `manifest.json` last. The manifest repeats the derived identifier and is the completeness marker. A directory without it is incomplete and requires explicit owner recovery; identical inputs cannot honestly choose a different content identifier.

### Task 1: Define exact evidence and extraction contracts

**Files:**

- Create: `src/ti26/evidence.py`
- Create: `tests/test_evidence.py`

- [ ] **Step 1: Write RED schema and path-validation tests**

Add the following fixture helpers and tests. Every test in this plan contains the mutation it kills in its docstring; preserve that text.

```python
from datetime import datetime

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
```

- [ ] **Step 2: Run RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_evidence.py -q
```

Expected: collection error because `ti26.evidence` and its public validator do not exist.

- [ ] **Step 3: Implement the pure exact-schema validator**

Add `EvidenceError(ValueError)`, immutable `EvidenceManifest`/`PayloadDigest` dataclasses, and these public functions. `EvidenceManifest.root` is the validated record directory supplied by the loader; it is runtime location metadata, never part of the semantic descriptor or `evidence_id`:

```python
def parse_utc(value: object, label: str) -> datetime: ...
def evidence_id_for_manifest(payload: dict[str, object]) -> str: ...
def safe_relative_file(root: Path, value: object, label: str) -> tuple[str, Path]: ...
def validate_evidence_manifest(root: Path, payload: object, *, verify_payloads: bool = True) -> EvidenceManifest: ...
```

`evidence_id_for_manifest` first requires exact key shape except that `evidence_id` may be an empty string, removes `evidence_id`, canonicalizes the semantic descriptor, and returns its lower-case SHA-256. `validate_evidence_manifest` requires a non-empty identifier equal to that derived result; caller-authored labels must fail. Require exactly these manifest keys:

```python
{"schema", "evidence_id", "kind", "event_id", "subject_key", "source",
 "observation", "attestation", "authority_registry", "construction", "payloads",
 "supersedes", "producer_revision"}
```

Require exactly the source keys `source_url_key`, `capture_method`, `available_at_utc`, `published_at_utc`, and `retrieved_at_utc`; `source_url_key` is a registered stable string and the manifest never carries a mutable raw URL. Accept `published_at_utc` only as `None` or a canonical UTC timestamp. Require exact observation keys `assertion`, `observed_at_utc`, `supported_through_utc`, `captures`, `authoritative_source_keys_checked`, and `diagnostic_reason` (a string or `None`; the fixtures and Task 3's observation literals carry it). `assertion` is precisely `present` or `absent`. Every `captures` entry has the exact keys `source_url_key` and `path`; paths are duplicate-free payload paths and source keys are registered stable keys. For `present`, require at least one capture and require its source key to equal `source.source_url_key`; the checked-source list is empty. For `absent`, require its checked and capture source-key sets to equal the complete registry-derived authority set for this exact `(kind, subject_key)`, so owner input cannot select a subset or let an unrelated capture stand in for an authority. `attestation` is `None` only for negative records; a positive record requires exact keys `fact_payload_sha256` and `capture_sha256s`, where the former equals the normalized fact payload digest and the latter is the duplicate-free sorted digest list for its referenced captures. It is an owner attestation, not an automated semantic claim. `authority_registry` is required with exact keys `schema`, `path`, `sha256`, and `effective_at_utc`: `schema` is exactly `ti26.evidence-authority-binding.v1`; `path` must equal one declared payload path; `sha256` must equal that payload's declared digest; `effective_at_utc` is a canonical UTC timestamp; and with `verify_payloads=True` the bound registry bytes are re-hashed like any payload, so a tampered `authority-registry.json` fails with an error matching `authority.registry`. Require lower-case 64-hex SHA-256 digests, non-empty strings for ids/kind/event/subject/source-key/method, `construction` in exactly `contemporaneous`, `reconstructed_verified`, or `reconstructed_unknown`, a duplicate-free list of predecessor **evidence IDs** for `supersedes`, and a lower-case 40-hex producer revision. The ordering from strongest to weakest is the order just listed. The evidence ID is the content digest and the sole evidence-record identity used for directory, banner, and supersession references. Reject timestamps that are not round-trip RFC 3339 UTC strings ending in `Z`; require `published_at_utc <= available_at_utc <= observed_at_utc <= retrieved_at_utc` when publication time is present, and `available_at_utc <= observed_at_utc <= retrieved_at_utc` otherwise. Require `observed_at_utc <= supported_through_utc`. The approved architecture permits a separately registered freshness allowance, but this pre-TI schema intentionally defines none; therefore require `supported_through_utc == observed_at_utc`. Any later allowance needs a new registered schema field and tests rather than an unbound timestamp extension. For `absent`, cutoff admissibility must be bounded on both sides by the observation interval.

**Schema version (amended 2026-08-11).** Everything above is the exact `ti26.evidence-manifest.v1` contract and stays valid for reading historical records forever. `ti26.evidence-manifest.v2` differs in exactly one place in this key set: `source` is replaced by the required `sources` map specified in the published-format section below, whose per-entry keys are exactly the nine `capture_path`, `capture_sha256`, `capture_method`, `published_at_utc`, `available_at_utc`, `observed_at_utc`, `supported_through_utc`, `retrieved_at_utc`, and `construction`. Every other key, timestamp ordering rule, digest rule, and path rule is unchanged, and the same ordering constraints apply within each source entry. The writer emits v2 only; `validate_evidence_manifest` dispatches on the exact `schema` value and applies the matching key set, with no version-straddling record accepted.

**v2 keeps `observation` and `construction`, so they become assertions, not second truths.** v2 retains the v1 `observation` object and the top-level `construction` key, which means a record can carry both a stored `observation.observed_at_utc`, `observation.supported_through_utc`, and `construction` **and** the composites derived from `sources`. Validation requires **exact equality** between each stored value and its recomputed composite and rejects the record otherwise, so the stored fields are compatibility assertions that can only ever restate the derivation. `test_v2_composite_times_are_recomputed_not_read` must mutate each stored value in turn — observation time, support time, construction — and observe rejection.

**Version-neutral record properties.** Nothing outside the validator reads `source` or `sources` for timing. `EvidenceManifest` exposes `available_at_utc`, `observed_at_utc`, `supported_through_utc`, `retrieved_at_utc`, and `construction` as typed record-level properties: for v1 they return the stored values directly, for v2 the derived composites. Selection, admissibility, supersession-graph applicability, and the release adapter consume only these; the singular-source compatibility accessor is for identity, never for timing, and must never appear in a timing path.

**Required v2 mutation tests**, each observed RED then restored GREEN: `test_v2_manifest_rejects_a_singular_source_key` (`Kills mutation: accept a v2 record that also stores source.`), `test_v1_manifest_rejects_a_sources_key` (`Kills mutation: accept an optional sources map under v1.`), `test_v2_sources_entry_must_match_its_observation_capture` (`Kills mutation: accept a sources entry whose capture_path or capture_sha256 differs from the declared capture.`), `test_v2_composite_times_are_recomputed_not_read` (`Kills mutation: accept owner-authored composite availability, observation, support, or construction.`), and `test_write_evidence_record_rejects_v1_new_write` (`Kills mutation: permit creation of a new legacy-v1 evidence record.`).

`safe_relative_file` and the catalog loader must use `lstat` on every component from their declared root through the final manifest/payload; reject every symlink, including a symlinked root/kind/record/manifest redirect, before opening or hashing it. `validate_evidence_manifest` performs all schema, identifier, timestamp, and path-shape validation before any filesystem lookup. With `verify_payloads=True`, it then recomputes every digest with a small streaming SHA-256 helper implemented locally in `ti26.evidence` (same chunked-read contract as the digest helpers already in `ti26.provenance` and `ti26.data.snapshot`; do not import from `ti26.data`, which would couple the evidence module to the network-seam package); with `False`, it validates shape only for pre-write construction. Positive capture sources must each be exact-pair registry-authorized, not merely the primary. Canonical serialization sorts every set-like list, including `supersedes`, capture-digest lists, authority keys, participant IDs, roster account IDs, and group member IDs; semantic source, group-label, and Round-1 order remains preserved.

Define the generic `kind` payload contracts now: `rules` requires source capture payloads plus normalized `extracted.json`; `participants` requires a source capture plus `participants.json` with unique numeric `team_id` entries, nonempty display names, and canonical ascending `team_id` order; `rosters` requires a source capture plus `rosters.json` with one unique numeric `team_id` entry per participant, each canonical ascending five-account tuple of unique positive IDs; `draws` requires source captures plus `draw.json` for exactly one `component` (`groups` or `round_one`) with exact `publication_state` of `published` or `unpublished` and a `value`. Published groups cover every participant exactly once with nonempty group labels; published Round 1 covers every participant exactly once in ordered two-member pairs, with no self pair, duplicate team, reversed duplicate, or reordered pair permitted. Canonicalize every set-like field before hashing (participant IDs, roster account IDs, authority keys, and group member IDs); preserve source order, group-label ordering, and Round-1 pair/member ordering where they are semantic. A `published` component requires a non-null value and a `present` manifest observation; `unpublished` forbids a value and requires an `absent` observation. `unknown` is not an evidence assertion: the release adapter uses it only when no adequate current positive or negative tip exists, and final shipping rejects it. Separate records and `subject_key` values carry group and Round-1 publication state independently; a payload never contains its own evidence ID. Use pure `validate_kind_payload(kind, payload, *, assertion)` and `reconcile_participants`, `reconcile_rosters`, and `reconcile_draw` functions with explicit caller-provided expected facts. They perform no I/O, selection, network call, or predictive action. Add tests for every contract before Plan 3 consumes them.

Add immutable `EvidenceSource`/`EvidenceSourceRegistry` types plus `load_source_registry(path)`, `authoritative_source_keys_for(registry, kind, subject_key)`, `validate_record_sources(record, registry)`, and `load_evidence_catalog(root, registry)`. `source-registry.json` has exact schema `ti26.evidence-source-registry.v1`; each entry has one safe stable `source_url_key` and duplicate-free exact `authorizations`, each `{event_id, kind, subject_key}`. It grants no wildcard, event-only, or kind-only authority.

**Amended 2026-08-11 — the authorization triple is three fields, and the lookup must use all three.** This paragraph previously described the authorization as `{kind, subject_key}` while `_bound_registry()` and the committed `data/evidence/source-registry.json` both carry `event_id`, and the shipped `authoritative_source_keys_for(registry, kind, subject_key)` filters on kind and subject only — so an authorization registered for a different event currently matches. The registry schema is **not** changed; it already has the right shape, and changing it now would create a migration for no benefit. Instead the signature becomes `authoritative_source_keys_for(registry, event_id, kind, subject_key)` and returns the complete sorted authority set for one exact triple, with `validate_record_sources` and every import and release call site passing the record's `event_id`. Add `test_authorization_for_another_event_does_not_authorize` (`Kills mutation: match an authorization on kind and subject while ignoring event_id.`); observe RED, restore GREEN. Import and release loading require the primary source to be authorized for that exact pair; a negative record's checked and captured source-key sets must equal—not merely be subsets of—that derived set. The owner cannot choose a subset. The registry carries no raw URL and is itself a declared release input in Plan 3. `load_evidence_catalog` lstat-validates, loads, and source-validates every existing immutable record for importer preflight. Synthetic tests build a local registry; Task 8 adds the owner-reviewed current Valve entry rather than inventing future participant, roster, or draw authorities.

**Implementation errata (binding).** Everywhere in this section and the next, the signature is `authoritative_source_keys_for(registry, event_id, kind, subject_key)` and the authorization is the exact **triple**; wherever the surrounding prose says "exact pair", read "exact triple". Wherever it says "primary source", that is v1 vocabulary only — v2 has none.

Under v2 there is no `source.source_url_key` and no primary source: the phrase "primary source" in this section and the next is v1 vocabulary, and a v2 record's authorization is checked over every entry in `sources`, which the capture-anchored invariant already equates with the observation's capture keys. `validate_record_sources` must authorize every positive capture source for the exact `(kind, subject_key)`, not only `source.source_url_key`; add `test_positive_capture_rejects_an_unregistered_secondary_source` with docstring `Kills mutation: authorize only the primary capture source.` Mutate the per-capture registry loop out, observe that node fail, restore, and rerun GREEN.

Graph applicability is `available_at_utc` for present assertions and `max(available_at_utc, observed_at_utc)` for absent assertions; use it in both maximal-tip filtering and importer boundary checks. The new negative-before-observation test must fail when this function is mutated to use availability alone.

- [ ] **Step 4: Run GREEN and mutation proof**

Run:

```bash
.venv/bin/python -m pytest tests/test_evidence.py -q
.venv/bin/python -m ruff check src/ti26/evidence.py tests/test_evidence.py
```

Expected: PASS. Then temporarily replace the top-level `set(payload) != _MANIFEST_KEYS` check with a subset check and run `test_validate_evidence_manifest_requires_exact_top_level_keys`; it must FAIL. Temporarily return `root / value` before validating `PurePosixPath` and run `test_validate_evidence_manifest_rejects_unsafe_payload_path`; it must FAIL. Temporarily accept any scalar in `parse_utc` and run `test_validate_evidence_manifest_rejects_a_boolean_where_a_timestamp_is_required`; it must FAIL. Temporarily weaken the no-policy equality to `observed_at_utc <= supported_through_utc` and run `test_validate_evidence_manifest_rejects_unregistered_freshness_extension`; it must FAIL. Restore each mutation and rerun the file.

- [ ] **Step 5: Commit**

```bash
git add src/ti26/evidence.py tests/test_evidence.py
git commit -m "feat: validate immutable evidence manifests"
```

### Task 1a: Freeze generic Plan 3 fact schemas and pure reconcilers

**Files:**

- Modify: `src/ti26/evidence.py`
- Modify: `tests/test_evidence.py`

- [ ] **Step 1: Write RED generic-contract tests**

```python
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
    record = validate_evidence_manifest(tmp_path, _negative_manifest(checked=["valve-ti-group-stage-rules"]), verify_payloads=False)
    with pytest.raises(EvidenceError, match="complete authority set"):
        validate_record_sources(record, registry)
```

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_evidence.py -q
```

Expected: collection error for generic validators and reconcilers.

- [ ] **Step 3: Implement exact generic schemas and pure reconcilers**

Implement `validate_kind_payload(kind: str, payload: object, *, assertion: str) -> dict[str, object]`, `reconcile_participants(expected: set[int], observed: set[int]) -> None`, `reconcile_rosters(expected: dict[int, list[int]], observed: dict[int, list[int]]) -> None`, and `reconcile_draw(expected: dict[str, object], observed: dict[str, object]) -> None`. Use exact key sets and canonical JSON equality. Reject duplicate participant IDs, duplicate roster team IDs/accounts, duplicate group members, duplicate round-one participants/pairs, and noncanonical set-like ordering; require complete participant coverage and exactly one group membership or Round-1 pairing per participant. Participant display names are presentation fields and never identity. Roster identity is exactly the sorted five-account set attached to a configured numeric team ID. A draw evidence payload represents only one component; the release adapter later joins independently selected `groups` and `round_one` tips into the combined structure accepted by `reconcile_draw`. Preserve group-label order and Round-1 pair/member order. Reconcile functions raise `ReconciliationError` with stable dotted mismatch paths and write nothing. Implement the exact source-registry loader and record-source validator described in Task 1; reject duplicate keys, unsafe keys, unknown kinds, unregistered primary sources, and any negative checked/captured set not equal to the registry-derived complete authority set for the exact subject.

- [ ] **Step 4: Run GREEN and mutations**

Run the eight nodeids; expected PASS. Temporarily replace the roster cardinality check with `len(set(ids)) >= 1` and observe the roster-schema test FAIL. Temporarily allow an `unpublished` value, accept extra draw keys, permit duplicate/noncanonical participant-roster-draw entries, compare participant display names, compare roster team IDs only, compare draw groups only, skip the registry subject check, and accept an authority subset; observe the corresponding named test FAIL after each mutation. Restore all mutations, run the full evidence tests, then Ruff.

- [ ] **Step 5: Commit**

```bash
git add src/ti26/evidence.py tests/test_evidence.py
git commit -m "feat: define generic evidence fact contracts"
```

### Task 2: Write content-addressed evidence records exclusively and manifest-last

**Files:**

- Modify: `src/ti26/evidence.py`
- Modify: `tests/test_evidence.py`

- [ ] **Step 1: Write RED publication tests**

```python
from ti26.evidence import EvidenceExistsError, write_evidence_record


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
        tmp_path, _manifest_v2(),
        {"authority-registry.json": _bound_registry(), "rendered.txt": b"Group Stage Rules\n", "extracted.json": canonical_json_bytes({"schema": "ti26.rules-extracted.v1", "facts": {}}) + b"\n"},
    )
    assert seen_manifest == [True]
    assert validate_evidence_manifest(record, json.loads((record / "manifest.json").read_text()))


def test_write_evidence_record_reuses_only_an_identical_complete_record(tmp_path):
    """Kills mutation: reject an identical complete content-addressed retry or overwrite different bytes."""
    payloads = {"authority-registry.json": _bound_registry(), "rendered.txt": b"Group Stage Rules\n", "extracted.json": canonical_json_bytes({"schema": "ti26.rules-extracted.v1", "facts": {}}) + b"\n"}
    write_evidence_record(tmp_path, _manifest_v2(), payloads)
    assert write_evidence_record(tmp_path, _manifest_v2(), payloads) == tmp_path / "rules" / _manifest_v2()["evidence_id"]


def test_write_evidence_record_rejects_caller_digest_that_does_not_describe_bytes(tmp_path):
    """Kills mutation: trust a caller-supplied payload digest instead of hashing bytes written."""
    payload, payload_bytes = _negative_record_with_payload_bytes()
    corrupted = next(entry for entry in payload["payloads"] if entry["path"] != "authority-registry.json")
    corrupted["sha256"] = "0" * 64
    payload["evidence_id"] = ""
    payload["evidence_id"] = evidence_id_for_manifest(payload)
    with pytest.raises(EvidenceError, match="sha256"):
        write_evidence_record(tmp_path, payload, payload_bytes)
```

`_negative_record_with_payload_bytes` is a test-helper-convention fixture: it builds a negative-observation manifest (in the style of `_negative_manifest`) together with the exact payload-byte map its declared paths require, all digests derived from the actual bytes. The corrupted entry is deliberately a capture payload on a negative record — the one digest no attestation or authority-registry cross-check references — so removing the write-time recompute is the only thing that can let it through, which is exactly the mutation this test kills. Do not corrupt the `authority-registry.json` entry here: Task 1's binding cross-check already rejects that during pre-write shape validation, before the write-time check runs.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_evidence.py -q
```

Expected: import error for `EvidenceExistsError` and `write_evidence_record`.

- [ ] **Step 3: Implement exclusive record publication**

Implement:

```python
class EvidenceExistsError(FileExistsError): ...

def evidence_record_path(root: Path, kind: str, evidence_id: str) -> Path: ...
def write_evidence_record(root: Path, manifest: dict[str, object], payloads: dict[str, bytes]) -> Path: ...
```

The destination is `root / kind / evidence_id`; validate both ids as one safe path component. If an existing destination is complete, lstat/validate every component, manifest, and payload; return it only when the canonical manifest and every byte exactly equal the requested record, otherwise raise `EvidenceExistsError` without overwriting. Any incomplete directory or existing non-directory raises `EvidenceExistsError` and requires explicit owner recovery. Payload-map keys must exactly equal the manifest payload paths. Create a new directory only after shape validation. Write payloads in sorted path order via `open("xb")`; recompute digests from the written regular files; reject a digest mismatch before manifest creation. Re-read and validate the manifest with payload verification after exclusive `manifest.json` creation. On an exception before the manifest, leave an identifiable incomplete directory and never delete it. Identical semantic inputs derive the same identifier and are idempotent only after complete verification; a retry must never invent a different identifier.

Before every `mkdir`, `open("xb")`, hash, and manifest open, lstat every ancestor from root through the nested capture parent and revalidate it remains a regular non-symlink directory; create missing nested capture parents one safe component at a time with exclusive semantics. This closes parent-symlink races as well as final-file redirects.

**Write-side fixtures are v2 (amended 2026-08-11).** The `_manifest()` fixture used by this task's write tests is the **v1** shape, and passing it to `write_evidence_record` contradicts the registered rule that new writers emit v2 only. Replace every write-side use with `_manifest_v2()`; keep `_manifest()` for parser, historical-read, supersession, and migration tests, which is exactly what v1 is still for. `write_evidence_record` must itself refuse a v1 payload, proved by `test_write_evidence_record_rejects_v1_new_write` (`Kills mutation: permit creation of a new legacy-v1 evidence record.`) — the sole exception being the `migrate-v1` route, which writes a v2 record and only *reads* v1.

Per-capture registry authorization for positive assertions belongs to the importer, not to `write_evidence_record`: `test_import_rejects_unregistered_positive_secondary_capture` and its mutation live in Task 6, which owns the `--capture` interface. Task 2 adds no such test.

- [ ] **Step 4: Run GREEN and every mutation**

Run the focused file and Ruff; expected PASS. Then (1) move manifest write ahead of the payload-digest loop and observe `test_write_evidence_record_binds_written_bytes_and_writes_manifest_last` FAIL, (2) reject the verified identical-retry branch or allow mismatched existing bytes and observe `test_write_evidence_record_reuses_only_an_identical_complete_record` FAIL, and (3) remove written-file digest comparison and observe `test_write_evidence_record_rejects_caller_digest_that_does_not_describe_bytes` FAIL. Restore and rerun:

```bash
.venv/bin/python -m pytest tests/test_evidence.py -q
.venv/bin/python -m ruff check src/ti26/evidence.py tests/test_evidence.py
```

- [ ] **Step 5: Commit**

```bash
git add src/ti26/evidence.py tests/test_evidence.py
git commit -m "feat: write evidence records manifest-last"
```

### Task 3: Enforce positive and negative observation validity at a cutoff

**Files:**

- Modify: `src/ti26/evidence.py`
- Modify: `tests/test_evidence.py`

- [ ] **Step 1: Write RED observation tests**

```python
from ti26.evidence import evidence_is_admissible


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
```

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_evidence.py -q
```

Expected: import error for `evidence_is_admissible`.

- [ ] **Step 3: Implement availability semantics**

Implement `evidence_is_admissible(record: EvidenceManifest, cutoff_utc: str, *, allow_reconstructed_unknown: bool = False) -> bool`. It returns false when the parsed cutoff precedes `record.available_at_utc` — the version-neutral record property registered in Task 1, **not** `record.source.available_at_utc`, which a multi-source v2 record does not have; for an `absent` observation it requires `max(available_at_utc, observed_at_utc) <= cutoff <= supported_through_utc`, and it returns false for `construction == "reconstructed_unknown"` unless a diagnostic caller opts in explicitly. It does not back-project a later negative observation to an earlier cutoff, infer absence from a missing extracted field, or invent a freshness policy. This is a pure predicate; graph selection supplies the separate current-tip condition.

- [ ] **Step 4: Run GREEN and mutations**

Run the nodeids above; expected PASS. Temporarily compare cutoff to `retrieved_at_utc`, omit the lower `observed_at_utc` bound, omit the upper `supported_through_utc` bound, permit an empty capture list, compare only whether the checked-source list is non-empty, accept a swapped attested fact digest, and default `allow_reconstructed_unknown` to true; observe the corresponding test FAIL after each mutation. Restore and run the whole evidence test file plus Ruff.

- [ ] **Step 5: Commit**

```bash
git add src/ti26/evidence.py tests/test_evidence.py
git commit -m "feat: enforce evidence observation validity"
```

### Task 4: Select a unique current evidence tip and record rejection reasons

**Files:**

- Modify: `src/ti26/evidence.py`
- Modify: `tests/test_evidence.py`

- [ ] **Step 1: Write RED supersession tests**

```python
from ti26.evidence import ReconciliationError, select_current_evidence


def _record(tmp_path, marker, available, supersedes=(), subject="rules:ti2026:valve:group-stage", *, assertion="present", construction="contemporaneous"):
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
```

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_evidence.py -q
```

Expected: import error for the selector.

- [ ] **Step 3: Implement graph validation and selection**

Implement immutable `CurrentEvidence(selected: EvidenceManifest, rejected: dict[str, str])`, `ReconciliationError(ValueError)`, and:

```python
def select_current_evidence(
    records: Iterable[EvidenceManifest],
    kind: str,
    subject_key: str,
    cutoff_utc: str,
    *,
    allow_reconstructed_unknown: bool = False,
) -> CurrentEvidence: ...
```

Add the test-only `_cyclic_records(tmp_path)` constructor which builds `EvidenceManifest` objects with internally consistent fields then replaces their evidence-id references through `dataclasses.replace`; it deliberately models a malformed graph that cannot arise from honest content-addressed publication but must still fail closed if a validator is handed corrupt manifests. Materialize the complete supplied collection first and validate global identifier uniqueness plus every edge before filtering for the requested kind/subject: every predecessor exists; predecessor kind and subject match descendant; no self edge; graph traversal detects a cycle. Define graph applicability as `available_at_utc` for a present record and `max(available_at_utc, observed_at_utc)` for an absent record. First form the unique maximal-tip set only from matching records whose graph-applicability timestamp is no later than cutoff, regardless of later assertion freshness or construction. A temporally applicable descendant always removes its ancestor. Then validate that sole tip with `evidence_is_admissible`: an expired negative or `reconstructed_unknown` tip is an error and blocks selection, never revives an ancestor. Mark records unavailable at cutoff as `available_after_cutoff`; report a rejected invalid maximal tip as `negative_observation_expired` or `reconstructed_unknown`. Require exactly one maximal tip before testing assertion validity. Fail closed for no tip, a fork, a cycle, a missing predecessor, a cross-subject edge anywhere in the supplied graph, or two records that have the same subject and availability but neither supersedes the other. The return value explains each rejected matching id as `superseded_by:<evidence-id>`, `available_after_cutoff`, `negative_observation_expired`, or `reconstructed_unknown`; do not select by record-id ordering. Only diagnostic callers may set `allow_reconstructed_unknown=True`.

- [ ] **Step 4: Run GREEN and mutation proof**

Run all six nodeids; expected PASS. Temporarily return `sorted(tips)[0]` for multiple tips and observe the fork test FAIL. Temporarily remove DFS grey-set tracking and observe the cycle test FAIL. Temporarily include descendants independent of availability and observe the earlier-cutoff test FAIL. Temporarily remove predecessor subject comparison and observe cross-subject test FAIL. Temporarily filter expired-negative or reconstructed-unknown descendants before computing tips and observe the respective descendant test FAIL. Restore, then run:

```bash
.venv/bin/python -m pytest tests/test_evidence.py -q
.venv/bin/python -m ruff check src/ti26/evidence.py tests/test_evidence.py
```

- [ ] **Step 5: Commit**

```bash
git add src/ti26/evidence.py tests/test_evidence.py
git commit -m "feat: reconcile current evidence tips"
```

### Task 5: Extract normalized rules facts and reconcile configuration

**Files:**

- Modify: `src/ti26/evidence.py`
- Modify: `src/ti26/rules.py`
- Modify: `tests/test_evidence.py`
- Modify: `tests/test_rules.py`

- [ ] **Step 1: Write RED extraction and reconciliation tests**

```python
from ti26.evidence import extract_ti2026_rules, reconcile_rules_facts
from ti26.rules import shipping_rules_facts


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


```

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_evidence.py tests/test_rules.py -q
```

Expected: import error for extract/reconcile/projection functions.

- [ ] **Step 3: Implement one factual vocabulary, not a second rules engine**

`extract_ti2026_rules(rendered: str) -> dict[str, object]` must produce canonical JSON-ready data with exact keys `schema` and `facts`. `facts` has exactly:

```python
{
    "tiebreak_order": {"value": ["series_wins", "series_losses", "opponent_series_wins", "game_win_pct", "opponent_game_win_pct", "avg_duration", "coin_toss"], "span_sha256": "..."},
    "rounds": {"value": {"within_group": [2, 3], "cross_group": [4], "max_distance_when_loser_eliminated": [5]}, "span_sha256": "..."},
    "elimination_selection_order": {"value": "best_3_2_sequential_choice", "span_sha256": "..."},
}
```

The extractor is intentionally narrow and uses exact required text fragments from the captured rendering. It raises `EvidenceError` if a required fragment is absent, duplicated in an ambiguous way, or reordered. A span digest is SHA-256 of the exact UTF-8 substring that supports the fact; it must not be a digest of the entire page. These are all approved normalized rules facts supported by the group-stage page: tiebreak order, within/cross-group round constraints, loser-elimination distance rule, and sequential 3-2 elimination chooser. The published format is a separate subject with its own captures and schema, specified below. Do not extract `elimination_choice_policy`, duration distribution fields, capacities, or other model assumptions.

**Absence and duplication are distinct defects (amended 2026-08-11).** The fragment helper must not collapse "zero matches" and "more than one match" into one message. Raise `required {label} fragment is absent: {fragment!r}` when no line matches and `required {label} fragment is duplicated {n} times: {fragment!r}` when more than one does, and return the sole index otherwise. Add one mutation test per branch — an absent-fragment capture and a duplicated-fragment capture — so neither state can be accepted by a helper that only counts.

**Structural headings may legitimately repeat (amended 2026-08-11).** `Elimination Round` is a section heading, and a real published page carries it more than once (once for the chooser rule, once for the advancement summary). Anchoring a fact on the global uniqueness of a generic heading rejects a valid capture. The elimination-selection fact must anchor on its ordered factual sentences — `Starting with the best 3-2 team`, `The next best 3-2 team`, `Repeat the above until all teams have chosen an opponent.` — and require that ordered sequence to be unique, while permitting the heading above it to repeat. Add a regression fixture containing two `Elimination Round` headings and one valid chooser sequence; the extractor accepts it. Two chooser sequences remain an error.

Add `shipping_rules_facts(path: str) -> dict[str, object]` in `rules.py`. It must `yaml.safe_load` the existing YAML and return only `tiebreak_order`, `rounds.within_group`, `rounds.cross_group`, `rounds.max_distance_when_loser_eliminated`, and derived `elimination_selection_order: "best_3_2_sequential_choice"`. The last value represents the existing sequential chooser invariant already exercised by `tests/test_elimination.py::test_choosers_act_in_ranking_order`; this plan adds no second policy switch and does not edit elimination behavior. It must never call `load_rules`, mutate YAML, or affect `Rules`.

`reconcile_rules_facts(configured, extracted) -> list[str]` accepts the complete extracted object with exact top-level keys `schema` and `facts`, validates its schema, exact fact keys, lower-case span digests, and value types, then performs recursive exact equality between `configured` and each fact's `value`. It returns `[]` only on equality. On mismatch it raises `ReconciliationError` with deterministic dotted field paths and canonical expected/observed JSON. Neither function changes configuration values or rewrites evidence.

Implement the separate import mode `rules-format`: it accepts one or more owner captures and writes a `rules` record for the published-format subject, containing `format-rendered.txt` per capture and canonical `format-extracted.json`. `shipping_rules_format_facts` maps the corresponding shipping format fields into the same normalized object; `reconcile_rules_format_facts` validates exact schema/value/span and compares each field recursively with deterministic dotted paths. Add `test_rules_format_extractor_requires_its_supporting_span` (`Kills mutation: derive published-format facts from the group-stage extractor.`) and `test_reconcile_rules_format_facts_reports_each_field` (`Kills mutation: compare only a format schema or one scalar.`); remove the independent extractor and the field recursion in turn, observe RED, restore GREEN.

#### Published-format subject and schema (amended 2026-08-11)

**Status: plan text only.** This section is a registered amendment awaiting review. No production code implements it yet, and the shipped `v1` extractor, the old subject key in `RELEASE_SUBJECTS`, and `shipping_rules_format_facts`'s current field set all still reflect the superseded contract. Implementing it is a separate authorized unit.

The first real capture falsified the original contract, and this section replaces it. The implemented `v1` extractor required four labeled lines — `Number of Teams: `, `Total Rounds: `, `Advance at Wins: `, `Eliminate at Losses: ` — that this plan never registered and that no published source emits. They were an implementation invention, so replacing them is repair, not criterion shopping. The replacement must be validated against real captured source text, never against a second invented mini-language.

**Subject.** The subject is renamed from `rules:ti2026:valve:published-format` to the source-neutral `rules:ti2026:event-format:group-stage`. The old key asserted Valve authorship in the subject namespace, which would make a non-Valve capture structurally valid while semantically false. A record's field-level support, not its subject key, names which source establishes each fact.

**Source keys.** The subject accepts multiple bound captures under separately registered, honestly named source keys — for example `valve-steam-news-<gid>`, `valve-ti-group-stage-rules`, `liquipedia-ti2026-format`, `compendium-ui-ti2026`. Each must be registered and owner-approved before use, exactly as `valve-ti-group-stage-rules` was.

**Correction 2026-08-11: two source keys named here were fabricated.** An earlier revision of this section listed `valve-ti2026-announcement-2026-02-11` and `valve-ti2026-invitations-2026-05-25` as the Valve sources carrying the format facts, and the paragraph on excluded fields below asserted what the May announcement says. Both came from a reviewer assertion that this plan's author wrote down without retrieving either page — the failure the [correction register](../../audits/2026-08-04-correction-register.md) exists to catch, committed in a planning document rather than a report.

Retrieval on 2026-08-11 established:

- **No February 2026 Dota 2 announcement exists.** The Steam announcement feed for `appid=570` contains no entry from that month.
- **The 2026-05-25 announcement does not state the format.** `The International 2026 Invitations and Qualifiers` (posted `1779766203`) covers direct invitations and regional qualifier slots. It states neither the round count nor the elimination-round structure; `n_teams` is only derivable from it as seven invitations plus nine qualifier slots.
- **The format facts are published by a later announcement.** `The International: Streams, Secret Shop, and More` (posted `1786494519`) states them in prose.

No claim about a source's content belongs in this plan again unless it is quoted from a retrieved capture.

`event-format` is the logical namespace of an observable fact slot. It is not a claim that every source in it carries equal authority. The registered authority policy for this subject:

- Valve sources may provide primary support for any field.
- Compendium UI evidence may support prediction-shape facts, labelled by its actual capture quality rather than promoted to a publisher claim.
- Liquipedia may corroborate a field under its own source key.
- **Liquipedia may never override a conflicting Valve fact.** A conflict between current Valve evidence and current community evidence fails closed and is an owner decision, not a precedence rule the importer resolves.
- Absence of a fact from Liquipedia does not prove its absence from Valve, and the converse also does not hold.

**Per-source time provenance is required (this is the blocking part).** A field-level `source_url_key` names which capture supports a fact; it does not tell current-at-cutoff selection *when that fact set became available*. The manifest's singular `source` object carries one `available_at_utc`, `published_at_utc`, `retrieved_at_utc`, `capture_method`, and `construction`, and a format record assembled from a February announcement, a May announcement, and a compendium capture has no single honest value for any of them. Attaching one timestamp to a multi-source fact set would be a false record, so this subject adopts **Option A: one composite record carrying per-source metadata.**

**Owner ruling 2026-08-11: the manifest is versioned, and `sources` is required in v2.** The umbrella spec now defines both versions; this plan implements them.

`ti26.evidence-manifest.v2` replaces the singular `source` with a required `sources` map keyed by `source_url_key`, each entry carrying `capture_path`, `capture_sha256`, `capture_method`, `published_at_utc`, `available_at_utc`, `observed_at_utc`, `supported_through_utc`, `retrieved_at_utc`, and `construction`. **v2 carries no singular `source` field at all**; two independently supplied truths would only invite disagreement between them. Code needing one source uses a derived accessor on the parsed record that returns the sole entry for a one-source record and raises for a multi-source one, rather than nominating a winner.

The generic invariant is capture-anchored, exactly as the umbrella spec now defines it: `sources.keys` equals the observation's capture source-key set, each entry's `capture_path` equals that capture's path, and each `capture_sha256` equals that path's declared payload digest. Field-level `source_url_key` references are required only of payload schemas that carry them (`rules-format-extracted.v2`, `prediction-shape-extracted.v1`); a release-authoritative multi-source positive composite additionally requires every entry to support at least one mandatory fact; a negative record requires `sources.keys` to equal both its capture source keys and its `authoritative_source_keys_checked`. A one-source positive record's sole source implicitly supports its whole normalized payload, and no fictional fact reference is invented to satisfy a rule.

Five record-level values are **derived by validation and recomputed on every read**, never accepted as written, over a support set that depends on the assertion — the sources supporting mandatory facts for a positive record, every checked authoritative capture source for a negative one:

```text
available_at_utc      = max(support-set available_at_utc)
observed_at_utc       = max(support-set observed_at_utc)
retrieved_at_utc      = max(support-set retrieved_at_utc)
supported_through_utc = min(support-set supported_through_utc)
construction          = weakest(support-set construction)
require observed_at_utc <= supported_through_utc
```

A record is not current at a cutoff earlier than its last required source; support ends where its earliest-lapsing source's does; and one `reconstructed_unknown` source makes the whole record `reconstructed_unknown`. Because this schema registers no freshness allowance, a negative record whose authorities were observed at different times fails the final check and is unusable — so the authorities behind one negative record are observed together, and widening that interval requires a registered allowance with its own field and tests.

**v1 stays valid; it is not invalidated.** The earlier draft of this section wrongly said the committed record "no longer validates". Immutable history remains valid under the schema that created it, and complete records are never overwritten. So: keep the v1 validator for historical records, make the writer emit only v2, and reject an optional `sources` under v1 outright — one schema version with two structural meanings is exactly the ambiguity being removed.

**Migration of the existing rules record.** `data/evidence/rules/b46dd664…` remains a valid v1 record and keeps its identifier. Release authority moves to a new v2 record for the same subject that supersedes it by ID. The migration is mechanical and its inputs are exactly the already-attested bytes.

**Fresh attestation is not required for a mechanical migration.** The owner's existing attestation already approves those exact capture and fact digests, and re-attesting identical hashes adds ceremony without evidence. The migration may reuse it only when all five hold, each proved by a test that breaks the migration when violated:

1. the v2 record uses exactly the already-attested capture bytes;
2. the normalized fact payload bytes are exactly unchanged;
3. the original `capture_sha256s` and `fact_payload_sha256` still match;
4. every `sources` entry is mechanically lifted from the corresponding v1 `source` and `observation` metadata;
5. no source metadata is newly asserted rather than lifted.

Fresh attestation **is** required whenever a capture changes, the normalized facts change, a source is added, or any source metadata is newly asserted.

**The migration needs an executable step, not only a policy.** Register `migrate_v1_record_to_v2(...)` in `ti26.evidence` and importer subcommand `cli_evidence_import migrate-v1`. It takes the existing v1 record as its **only** evidence source and accepts **no replacement capture, metadata, timestamp, or attestation arguments** — that argument-level refusal is what makes it a migration rather than a re-import wearing convenient new metadata. It reconstructs the single `sources` entry mechanically from the v1 `source` and `observation` fields, reuses the existing attestation only after verifying all five conditions, sets `supersedes` to the v1 evidence ID, and writes the v2 record through the same exclusive `write_evidence_record` path with `manifest.json` last.

**Single-source precondition.** `migrate-v1` migrates only a v1 record whose capture-source set is exactly its one `source`. v1 carries no independent per-source method or timing metadata for secondary captures, so a multi-capture v1 record cannot be migrated mechanically — inventing the missing per-source fields is precisely what "mechanical" excludes. Any such record requires a fresh v2 import with owner-supplied per-source metadata and a new attestation. Add `test_migration_rejects_a_multi_capture_v1_record` (`Kills mutation: synthesize per-source metadata for a v1 secondary capture.`).

**Every payload byte carries unchanged**, including the bound `authority-registry.json` and its `authority_registry` binding. `producer_revision` is naturally new, since a new record is produced by the current checkout; the evidence bytes and the authority binding are not, and a migration that rewrites either is not a migration.

**Migration obeys the same graph admission as any other write.** `migrate-v1` requires its source v1 record to be the unique current tip for its `(kind, subject_key)`, or to have an already-existing byte-identical migration, which it returns. Without that, an obsolete v1 ancestor could be migrated later and fork the subject — precisely the state the generic importer treats as failure. Migration reuses that rule rather than bypassing it, and `supersedes` names the v1 tip it migrated.

Named tests, one per condition plus the argument surface and the tip rule, each observed RED then restored GREEN: `test_migration_rejects_a_non_tip_v1_ancestor` (`Kills mutation: migrate any v1 record regardless of its position in the supersession graph.`), `test_migration_rejects_any_replacement_capture_or_metadata_argument` (`Kills mutation: accept --capture or --source on the migrate route.`), `test_migration_requires_identical_capture_bytes` (`Kills mutation: migrate a record whose capture bytes changed.`), `test_migration_requires_identical_normalized_facts` (`Kills mutation: re-extract facts during migration instead of carrying them.`), `test_migration_requires_the_original_attestation_digests_to_match` (`Kills mutation: reuse an attestation whose digests no longer match the payloads.`), `test_migration_lifts_every_source_field_mechanically` (`Kills mutation: assert a source field during migration instead of lifting it.`), and `test_migration_supersedes_the_v1_record_id` (`Kills mutation: write the v2 record with an empty supersedes list.`).

Option B — one ordinary record per source plus a manifest-bound composition artifact — was considered and not chosen. Under Plan 2's model each `(kind, subject)` resolves to exactly one current tip, so several non-superseding records under one subject are a fork and are rejected; Option B would therefore need either one subject per source or a composition record that owns no captures of its own, both of which add more contract than the versioned manifest.

**Corroboration stays out of the release-authoritative composite.** A later community capture of a field Valve already establishes adds no mandatory support but does move the composite's derived `available_at_utc` and `retrieved_at_utc`, complicating historical cutoff semantics for no shipping benefit. Corroborating captures that establish no mandatory fact belong in their own corroboration record, or outside the release path entirely. Liquipedia enters the authoritative composite only if it is genuinely the sole source establishing a mandatory field — and never as an override of conflicting Valve evidence.

**Schema.** `ti26.rules-format-extracted.v1` is replaced by `ti26.rules-format-extracted.v2`, which carries per-field support instead of one coarse `facts.format` object:

```json
{
  "schema": "ti26.rules-format-extracted.v2",
  "facts": {
    "n_teams":                         {"value": 16,     "source_url_key": "...", "span_sha256": "..."},
    "total_rounds":                    {"value": 5,      "source_url_key": "...", "span_sha256": "..."},
    "main_event_slots":                {"value": 8,      "source_url_key": "...", "span_sha256": "..."},
    "elimination_matches":             {"value": 5,      "source_url_key": "...", "span_sha256": "..."},
    "series_type":                     {"value": "bo3",  "source_url_key": "...", "span_sha256": "..."},
    "direct_advance_count":            {"value": 3,      "source_url_key": "...", "span_sha256": "..."},
    "elimination_round_rank_range":    {"value": [4, 13],"source_url_key": "...", "span_sha256": "..."},
    "elimination_round_advance_count": {"value": 5,      "source_url_key": "...", "span_sha256": "..."}
  }
}
```

No value in that example is an input. Every value must be parsed from an exact span in a bound capture, and every `source_url_key` must name a capture present in the same record. A plan-stated value never substitutes for a parsed one, and no field acquires support because another field logically implies it.

**Excluded from the direct projection — REVERSED 2026-08-11.** An earlier revision removed `advance_at_wins` and `eliminate_at_losses` from the published-format vocabulary on the stated ground that "no 2026 format source states them", and reclassified their provenance from published to compendium-derived. Retrieval falsified that ground: Valve states both, in one sentence, in `The International: Streams, Secret Shop, and More`. Both fields stay in the direct projection and keep their published-format provenance class. They remain unchanged in `config/ti2026_rules.yaml` either way — only the claimed provenance class was wrong, and it is now corrected back.

`total_rounds` also stays in the direct projection, but **not for the reason previously given here**. The claim that the 2026-05-25 announcement "describes a five-round Swiss bracket followed by five elimination matches" was fabricated; that announcement says nothing about rounds. No retrieved source states the round count as a number. Its support is the already-captured Valve rules page, which enumerates per-round pairing modifications through `Round 5`, and it must cite that span rather than a sentence no source contains.

**The grammar this implies.** Every published number is written as an English word — `Sixteen`, `eight`, `fourth`, `three`, `five` — inside flowing prose, with two distinct facts sharing one sentence. A labeled-line vocabulary cannot read this source in either its original or its replacement form. The extractor must anchor on exact whole sentences from a bound capture, and every pattern must be demonstrated against the captured bytes before it is committed.

**The 2026-08-11 Liquipedia paste is not evidence.** A chat-transported Liquipedia paste was moved outside the repository. It is not evidence, is not a byte-exact page capture, and must not be referenced by digest or reused for import. Any future Liquipedia record requires a new owner-approved capture, metadata, dry run, and attestation.

**Threshold derivation.** The two thresholds are established by a separate, explicit, tested derivation from compendium prediction-shape evidence rather than by the format extractor:

```python
def derive_swiss_thresholds(prediction_categories: set[str]) -> dict[str, int]:
    required = {"4-0", "4-1", "1-4", "0-4"}
    if not required <= prediction_categories:
        raise ReconciliationError("prediction categories do not establish thresholds")
    return {"advance_at_wins": 4, "eliminate_at_losses": 4}
```

Three provenance classes stay distinct and are never merged: directly published format structure; compendium prediction-shape evidence carrying the categories and capacities; and derived configuration facts, which is where the two thresholds live. `shipping_rules_format_facts` projects only the direct published vocabulary, so it must stop emitting `advance_at_wins` and `eliminate_at_losses`.

**Dropping them from that projection must not drop them from reconciliation.** Removing the thresholds from `shipping_rules_format_facts` without replacing their check would leave two load-bearing shipping values outside the evidence boundary entirely — a new hole, opened by a repair. Release reconciliation therefore requires **both** halves, and fails closed on either:

1. the directly published format facts, reconciled as above; and
2. bound compendium prediction-shape evidence, followed by deterministic threshold derivation whose output is compared against the unchanged shipping configuration.

`RELEASE_SUBJECTS` gains a seventh entry for that evidence, `prediction_shape: "rules:ti2026:event-format:prediction-shape"`, kind `rules`, requiring a `present` observation and carrying the captured category set with its own span support. `reconcile_release_evidence` then calls `derive_swiss_thresholds` on the **captured** categories — never on a set written into this plan — and compares the result field by field against `config/ti2026_rules.yaml`. Absent prediction-shape evidence, a category missing from the captured set, or a derived threshold that differs from the shipping value each fail preflight. The shipping values themselves are never rewritten to match, and no value in this plan's examples may be copied into production output.

The illustrative shape of the reconciled result, values included only to show the field layout:

```json
{
  "published_format": {"n_teams": 16, "total_rounds": 5, "main_event_slots": 8, "elimination_matches": 5},
  "prediction_shape": {"categories": ["4-0", "4-1", "ER_WINNER", "ER_LOSER", "1-4", "0-4"]},
  "derived_config": {"derivation": "derive_swiss_thresholds.v1", "advance_at_wins": 4, "eliminate_at_losses": 4}
}
```

**The prediction-shape subject needs a producer, or it is the old blocker with a new name.** Making it a required release subject without an extractor, schema, importer route, or capture representation would replace one unsatisfiable subject with another, and Plan 3 would hard-stop forever on the new one. Register all of it:

- Schema `ti26.prediction-shape-extracted.v1`, one fact per category with `value`, `source_url_key`, and `span_sha256`, plus the complete `categories` set as an ordered fact carrying its own span. The `rules` importer cannot produce it (it runs the group-stage extraction) and `rules-format` is constrained to the other subject, so add importer subcommand `prediction-shape`, accepting subject `rules:ti2026:event-format:prediction-shape` only and calling `extract_ti2026_prediction_shape`.
- `extract_ti2026_prediction_shape(rendered)` follows the same rules as the other extractors: exact required whole-line fragments, absence and duplication distinguished, ordered, and every span digest over the exact supporting substring rather than the page.
- `reconcile_release_evidence` then calls `derive_swiss_thresholds` on the **captured** category set and compares against `config/ti2026_rules.yaml`, as specified above.
- Tests: `test_prediction_shape_extractor_requires_every_category_span` (`Kills mutation: emit a category fact with no supporting span.`), `test_prediction_shape_import_rejects_the_rules_subject` (`Kills mutation: let the prediction-shape mode write the group-stage subject.`), and `test_release_reconciliation_derives_thresholds_from_captured_categories` (`Kills mutation: compare thresholds against a plan-stated category set instead of the captured one.`). Observe RED on each, restore GREEN.

**Capture representation: a textual UI capture is required for this tranche.** The compendium card this evidence describes was supplied as a screenshot, and **an image has no UTF-8 span** — a span digest over image bytes would be a category error dressed as provenance. The earlier draft of this section admitted a screenshot-plus-owner-transcription path, and the schema cannot express it: a v2 `sources` entry has exactly one `capture_path` and one `capture_sha256`, a field-level fact carries only `source_url_key` and `span_sha256` with no field naming which payload the span lies in, and `capture_sha256s` is defined over captures. Supporting it would require a per-fact `support_path` and an attestation model that binds non-capture support payloads separately — a schema evolution, not a footnote, and not one this pre-TI tranche takes on.

So: **prediction-shape release evidence requires a textual UI capture.** Spans are computed over it, `construction` is `contemporaneous`, and it is the record's sole payload class. If no textual representation of the compendium surface can be captured, that is a hard stop and an owner decision — not a licence to hash an image and describe a transcription as its capture. Screenshot-plus-transcription remains a possible future amendment; until it is registered with `support_path` and an extended attestation, `capture_sha256s` means captures and nothing else.

**Redundant claims get a consistency check, not independence.** Several of these fields constrain each other — `main_event_slots` is the sum of the direct advancers and the elimination-round advancers, and `elimination_round_rank_range` spans exactly the teams the elimination matches consume. Where both a total and its components are retained, reconciliation asserts their arithmetic relationship explicitly and fails closed on violation, rather than recording them as unrelated observations that happen to agree.

- [ ] **Step 4: Run GREEN and mutations**

Run focused tests plus `tests/test_elimination.py::test_choosers_act_in_ranking_order`; expected PASS. Temporarily replace each fact's `span_sha256` with an empty string and observe the span test FAIL. Temporarily make `reconcile_rules_facts` compare only keys and observe the divergence test FAIL. Temporarily omit `max_distance_when_loser_eliminated` from `shipping_rules_facts` and observe the divergence test FAIL after expanding its expected object to include that field. Restore and run the focused files plus Ruff.

- [ ] **Step 5: Commit**

```bash
git add src/ti26/evidence.py src/ti26/rules.py tests/test_evidence.py tests/test_rules.py
git commit -m "feat: reconcile normalized rules evidence"
```

### Task 6: Provide one generic offline importer with no network capability

**Files:**

- Create: `src/ti26/cli_evidence_import.py`
- Create: `tests/test_cli_evidence_import.py`

- [ ] **Step 1: Write RED CLI tests for every import mode**

Create synthetic helpers `_complete_rules_text()`, `_source_metadata(assertion="present")`, `_source_registry(...)`, and `_write_json(path, value)`. Values are synthetic test inputs, never copied measurements. Add:

```python
from ti26.cli_evidence_import import clean_head_revision, main


@pytest.fixture
def clean_import_head(monkeypatch):
    """Provide a clean synthetic checkout only to tests exercising import behavior."""
    monkeypatch.setattr("ti26.cli_evidence_import.clean_head_revision", lambda _root: "a" * 40)


def test_clean_head_revision_rejects_an_untracked_file(monkeypatch, tmp_path):
    """Kills mutation: omit untracked files from the importer's clean-checkout boundary."""
    responses = iter([SimpleNamespace(stdout="?? owner-capture.txt\n"), SimpleNamespace(stdout="a" * 40 + "\n")])
    monkeypatch.setattr("ti26.cli_evidence_import.subprocess.run", lambda *args, **kwargs: next(responses))
    with pytest.raises(EvidenceError, match="clean"):
        clean_head_revision(tmp_path)


def test_rules_import_creates_capture_extraction_and_manifest(tmp_path, clean_import_head):
    """Kills mutation: publish rules evidence without its normalized extraction."""
    record = _run_import(tmp_path, "rules", capture=_complete_rules_text())
    assert (record / "rendered.txt").is_file()
    assert (record / "extracted.json").is_file()
    assert (record / "manifest.json").is_file()


@pytest.mark.parametrize(
    ("kind", "facts", "normalized_name"),
    [
        ("participants", {"schema": "ti26.participants.v1", "participants": [{"team_id": 101, "display_name": "Alpha"}]}, "participants.json"),
        ("rosters", {"schema": "ti26.rosters.v1", "rosters": [{"team_id": 101, "account_ids": [1, 2, 3, 4, 5]}]}, "rosters.json"),
        ("draw", {"schema": "ti26.draw-fact.v1", "component": "groups", "publication_state": "published", "value": {"a": [101]}}, "draw.json"),
    ],
)
def test_fact_imports_canonicalize_owner_facts_and_keep_capture_bytes(tmp_path, clean_import_head, kind, facts, normalized_name):
    """Kills mutation: copy generic fact JSON without validating and canonicalizing it."""
    record = _run_import(tmp_path, kind, facts=facts, capture=b"owner capture")
    assert (record / normalized_name).read_bytes() == canonical_json_bytes(facts) + b"\n"
    assert next((record / "captures").iterdir()).read_bytes() == b"owner capture"


def test_negative_draw_import_requires_one_keyed_capture_per_checked_source(tmp_path, clean_import_head):
    """Kills mutation: let one local page support absence across multiple authorities."""
    with pytest.raises(SystemExit):
        _run_import(
            tmp_path,
            "draw",
            facts={"schema": "ti26.draw-fact.v1", "component": "round_one", "publication_state": "unpublished", "value": None},
            metadata=_source_metadata(assertion="absent", checked=["blast-series", "valve-event"]),
            captures={"blast-series": b"not published"},
        )


def test_import_rejects_a_source_not_registered_for_the_subject(tmp_path, clean_import_head):
    """Kills mutation: trust a source key without checking its registered kind and subject."""
    with pytest.raises(SystemExit):
        _run_import(tmp_path, "participants", registry_subject="participants:ti2026:other")


def test_import_requires_every_current_same_subject_tip_in_supersedes(tmp_path, clean_import_head):
    """Kills mutation: permit an import that supersedes only one tip of a current fork."""
    first, second = _current_fork(tmp_path, "rules", "rules:ti2026:owner:field")
    with pytest.raises(SystemExit):
        _run_import(tmp_path, "rules", capture=_complete_rules_text(), supersedes=[first.evidence_id])


def test_import_reuses_complete_identical_content_and_rejects_incomplete_destination(tmp_path, clean_import_head):
    """Kills mutation: create a new record over an incomplete destination or reject a verified retry."""
    first = _run_import(tmp_path, "rules", capture=_complete_rules_text())
    assert _run_import(tmp_path, "rules", capture=_complete_rules_text()) == first
    _expected_import_path(tmp_path, "rules", capture=_complete_rules_text(), subject_key="rules:ti2026:owner:incomplete").mkdir(parents=True)
    with pytest.raises(SystemExit):
        _run_import(tmp_path, "rules", capture=_complete_rules_text(), subject_key="rules:ti2026:owner:incomplete")


def test_import_module_has_no_network_or_opendota_dependency():
    """Kills mutation: add a network-capable import to the offline evidence command."""
    tree = ast.parse(Path("src/ti26/cli_evidence_import.py").read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported.update(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))
    assert not {name for name in imported if name.startswith(("urllib", "requests", "httpx", "ti26.data.opendota"))}


def test_importer_uses_only_fixed_git_subprocess_vectors():
    """Kills mutation: construct an arbitrary subprocess command from importer input."""
    tree = ast.parse(Path("src/ti26/cli_evidence_import.py").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run"]
    assert calls
    assert all(isinstance(call.args[0], ast.List) and all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in call.args[0].elts) for call in calls)
    assert {tuple(item.value for item in call.args[0].elts) for call in calls} == {
        ("git", "status", "--porcelain=v1", "--untracked-files=all"),
        ("git", "rev-parse", "HEAD"),
    }
```

`_run_import` must invoke the real parser with `--root`, `--event-id`, `--subject-key`, `--source-registry`, `--source`, and one repeated `--capture SOURCE_URL_KEY=PATH` per capture. It adds `--facts PATH` for non-rules modes. It returns the sole complete generated record and inspects captured stderr for parser failures; do not use `pytest.raises(SystemExit, match=...)` because `SystemExit` carries the exit code rather than argparse's stderr text.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_cli_evidence_import.py -q
```

Expected: collection error because the CLI module does not exist.

- [ ] **Step 3: Implement the generic importer**

Implement `clean_head_revision(repo_root: Path) -> str` as the only local-Git boundary. Run `git status --porcelain=v1 --untracked-files=all` with `cwd=repo_root`, reject any output, then resolve `git rev-parse HEAD` and require lower-case 40-hex. No caller may provide the revision.

`main(argv)` has **exactly seven** subcommands in three argument classes:

| class | subcommands | manifest kind | `--facts` | `--capture` | `--source` |
|---|---|---|---|---|---|
| extracting capture import | `rules`, `rules-format`, `prediction-shape` | `rules` | forbidden | one or more | v2 document |
| owner-fact capture import | `participants`, `rosters`, `draw` | `participants`, `rosters`, `draws` | required | one or more | v2 document |
| migration | `migrate-v1` | as the migrated record | forbidden | forbidden | forbidden |

The six capture-import commands each require `--root`, `--event-id`, `--subject-key`, `--source-registry`, `--source`, and at least one repeated `--capture SOURCE_URL_KEY=PATH`; repeated `--supersedes` is optional only when it names every current same-subject tip. `rules` derives from one primary capture; `rules-format` and `prediction-shape` accept one or more captures, since their fields may be supported by different sources, and each extracted field names the capture that supports it. `rules-format` accepts only subject `rules:ti2026:event-format:group-stage` and calls `extract_ti2026_published_format`; `prediction-shape` accepts only subject `rules:ti2026:event-format:prediction-shape`, calls `extract_ti2026_prediction_shape`, and is an extracting mode, never a generic `--facts` mode.

**Capture cardinality follows the support model, not the table's "one or more".** Only `rules-format` and `prediction-shape` payloads carry field-level `source_url_key`; every other positive record relies on the one-source implicit-support rule, so it cannot say what an extra capture supports. Enforce exactly:

```text
rules            present      -> exactly 1 capture
participants     present      -> exactly 1 capture
rosters          present      -> exactly 1 capture
draw             published    -> exactly 1 capture
draw             unpublished  -> exactly one capture per registered authoritative source
rules-format     present      -> 1 or more; every used source supports >= 1 mandatory field
prediction-shape present      -> 1 or more textual captures; every used source supports >= 1 mandatory field
migrate-v1                    -> no capture arguments
```

A positive record whose normalized schema cannot express what a capture supports must reject the extra capture rather than carry it as unexplained corroboration.

`migrate-v1` takes the existing v1 record as its only evidence source, under the preconditions registered in the migration section: unique current tip, single-source, byte-identical payloads. Its parser surface is deliberately narrow: it identifies the existing v1 record plus the evidence root and registry needed to validate it, and **`--event-id`, `--subject-key`, `--source`, timestamps, attestation, `--capture`, `--supersedes`, and `--dry-run` are not caller inputs**. Event, subject, source material, attestation, and the supersession edge all come from the validated source record. Because it writes a new record carrying a current `producer_revision`, it still requires the ordinary clean-HEAD admission.

Parse `SOURCE_URL_KEY=PATH` without shell interpretation, reject duplicate keys, read bytes locally, and map them deterministically:

- rules primary capture: `rendered.txt`;
- every other capture: `captures/<safe-source-url-key>.bin`;
- normalized facts: `extracted.json` for `rules`, `format-extracted.json` for `rules-format`, `prediction-shape-extracted.json` for `prediction-shape`, and `participants.json`, `rosters.json`, or `draw.json` for other modes.

**DO NOT IMPLEMENT the following sentence's v1 metadata document.** It describes the superseded singular source JSON and is retained only to show what the v2 document replaced. The six live capture-import commands consume `ti26.evidence-import-metadata.v2` exclusively, and `migrate-v1` consumes no metadata document at all. Every other rule in this paragraph — registry authorization, present/absent capture requirements, per-kind assertion limits, `--facts` handling, attestation equality, supersession-tip equality, and the single `write_evidence_record` call — remains binding, read against the v2 document.

~~Parse source JSON with exactly `source_url_key`, `capture_method`, `available_at_utc`, `published_at_utc`, `retrieved_at_utc`, `assertion`, `observed_at_utc`, `supported_through_utc`, `authoritative_source_keys_checked`, `attestation`, and `construction`.~~ Load the source registry and require the primary and every checked key to authorize this exact kind/subject. For `present`, require the primary capture and no checked-source list. For `absent`, require keyed captures exactly equal to the registry-derived complete authority set, not a user subset. Participants and rosters accept only `present`; draw accepts `present/published` or `absent/unpublished`; rules accepts only `present`. Non-rules `--facts` is parsed as exact JSON, validated with `validate_kind_payload`, then re-serialized canonically before hashing. Positive normalized facts require an owner attestation in the source JSON whose fact payload digest and sorted referenced capture digests equal the computed bytes; reject swapped facts/captures. Before any write, call `load_evidence_catalog(root, registry)`, calculate all same-kind/subject maximal current tips at the incoming available time, and require `set(--supersedes)` to equal that entire set (empty only for a new subject). A catalog fork therefore requires superseding every tip; a stale/incomplete predecessor set fails. Derive the manifest and content ID in memory and call `write_evidence_record` once. Its verified identical-complete branch returns the old path; an immutable fork or incomplete destination fails.

For a present observation, validate every `--capture SOURCE_URL_KEY` against the exact `(kind, subject_key)` registry authorization, including secondary captures; no primary-only shortcut is allowed. `test_import_rejects_unregistered_positive_secondary_capture` must remove that per-capture check, observe RED, restore GREEN.

**Multi-source import metadata (amended 2026-08-11).** The paragraph above describes the v1 singular metadata document, and it cannot express a v2 record: `--capture` repeats but `--source` does not, so there is nowhere to supply February metadata and May metadata independently. Rather than inventing "primary source" semantics, `--source` accepts a v2 document whose per-source map mirrors the capture arguments:

```json
{
  "schema": "ti26.evidence-import-metadata.v2",
  "assertion": "present",
  "authoritative_source_keys_checked": [],
  "diagnostic_reason": null,
  "attestation": {"fact_payload_sha256": "...", "capture_sha256s": ["..."]},
  "sources": {
    "<source-key>": {
      "capture_method": "...",
      "published_at_utc": "...",
      "available_at_utc": "...",
      "observed_at_utc": "...",
      "supported_through_utc": "...",
      "retrieved_at_utc": "...",
      "construction": "..."
    }
  }
}
```

`capture_path` and `capture_sha256` are **derived by the importer** from the `--capture` arguments and never typed into a second place, so the owner cannot desynchronize a digest from its file. The document's exact top-level keys are the **six** shown — `schema`, `assertion`, `authoritative_source_keys_checked`, `diagnostic_reason`, `attestation`, and `sources` — and each source entry's keys are exactly the **seven** shown. Neither count is to be reconciled by inventing a key. The importer enforces one equality that makes a missing or surplus source impossible:

```text
metadata.sources.keys == the set of --capture SOURCE_URL_KEY arguments
```

Add `test_import_metadata_sources_must_equal_capture_keys` (`Kills mutation: accept metadata describing a source the command did not capture.`) covering both directions — a metadata source with no capture, and a capture with no metadata — and `test_importer_derives_capture_paths_and_digests` (`Kills mutation: read capture_path or capture_sha256 from owner metadata instead of the captured file.`). Observe RED on each, restore GREEN. **Every import mode requires this v2 document, and the v1 importer-metadata format has no live CLI consumer at all** — `migrate-v1` derives everything from the existing v1 evidence record and accepts no metadata document, so nothing reads the old format. Historical v1 *manifests* remain readable; the old *import* format does not.

Before new-content supersession validation, derive the candidate content ID and call pure `validate_existing_exact(root, kind, evidence_id, canonical_manifest, payloads)`: it lstat-validates an existing destination and returns only a complete byte-identical record; if absent it returns `None`, and if incomplete/different it raises. Return a verified existing path immediately; only an absent candidate proceeds to supersession validation and then calls `write_evidence_record` once. For genuinely new content, validate the full graph at every existing and candidate graph-applicability boundary: each exact subject has one maximal tip, or the candidate supersedes every globally current maximal tip. This prevents a backdated fork, not merely a fork at the incoming timestamp. Add `test_identical_retry_precedes_supersession_validation` (`Kills mutation: check supersedes before returning an identical complete record.`) and `test_import_rejects_backdated_fork` (`Kills mutation: validate only tips at the incoming timestamp.`); bypass `validate_existing_exact` or the global-boundary check in turn, observe each node RED, restore, then GREEN.

The **six capture-import** subcommands accept `--dry-run`; `migrate-v1` does not, because it asserts nothing new and there is no fresh attestation for the owner to preview. A dry run performs the complete parsing, registry-authorization, capture-read, extraction, canonicalization, and digest pipeline, but: the source JSON's `attestation` may be `null` and is not compared (the printed digests are what the owner attests to — requiring the attestation first would be circular); `clean_head_revision` is not called; nothing is written. It prints each capture path with its canonical SHA-256 and the computed normalized-fact payload SHA-256, and exits zero. Task 8's `test_dry_run_emits_digests_without_writing` covers the no-write half; the null-attestation exception is part of this parser contract, not a Task 8 afterthought.

Print only the created digest path. `clean_head_revision` is the only subprocess user: it invokes only the two literal Git argv vectors in the AST test, with no shell, no interpolated command string, and no other subprocess API. Enforce an importer source-module allowlist of `argparse`, `ast`, `hashlib`, `json`, `pathlib`, `subprocess`, and `ti26.evidence`; install a test-only runtime guard that makes `socket.socket`, `socket.create_connection`, and every subprocess entry point except the two fixed Git calls raise. The guard lives in the test file, never in production code, and is installed exclusively through pytest's `monkeypatch` fixture around each in-process `main()` invocation, so it is reverted automatically per test and cannot leak broken `socket`/`subprocess` state into unrelated tests in the same pytest process. Add `test_import_runtime_denies_socket_and_non_git_subprocess` (`Kills mutation: permit runtime network or arbitrary subprocess capability.`), mutate out each guard, observe RED, restore GREEN. Convert `EvidenceError`, `EvidenceExistsError`, JSON errors, duplicate captures, and local file errors to `parser.error`. Import no network-capable module and never call the OpenDota seam. The test fixture stubs only the Git boundary; all schema, source-registration, digest, and filesystem behavior remains real.

- [ ] **Step 4: Run GREEN and every mutation**

Run the CLI test file and Ruff; expected PASS. Apply each named mutation separately: omit `--untracked-files=all`; skip normalized rules payload; write generic fact bytes without canonical validation; collapse keyed captures to one file; accept an authority subset; accept swapped attested facts; omit one current fork tip from `--supersedes`; reuse an incomplete destination; skip source-registry subject validation; add an import of `urllib.request`; construct `subprocess.run(["git", user_value])`. Observe the corresponding test FAIL, restore, and rerun:

```bash
.venv/bin/python -m pytest tests/test_cli_evidence_import.py -q
.venv/bin/python -m ruff check src/ti26/cli_evidence_import.py tests/test_cli_evidence_import.py
```

- [ ] **Step 5: Commit**

```bash
git add src/ti26/cli_evidence_import.py tests/test_cli_evidence_import.py
git commit -m "feat: import release evidence offline"
```

### Task 7: Expose one validated release-evidence catalog and reconciliation result

**Files:**

- Modify: `src/ti26/evidence.py`
- Modify: `tests/test_evidence.py`

- [ ] **Step 1: Write RED catalog and release-reconciliation tests**

Use synthetic manifest-valid catalogs. Every helper writes through `write_evidence_record`; no test hand-authors a trusted manifest. Add:

```python
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
    catalog = _release_catalog(tmp_path, groups_state="published", round_one_state="published", evidence_round_one=[[101, 999]])
    with pytest.raises(ReconciliationError, match="round_one"):
        reconcile_release_evidence(catalog, **_release_inputs(tmp_path, groups_path=draw_path))


def test_release_reconciliation_rejects_reconstructed_unknown_even_if_a_tip_exists(tmp_path):
    """Kills mutation: opt release selection into diagnostic reconstructed-unknown evidence."""
    catalog = _release_catalog(tmp_path, roster_construction="reconstructed_unknown")
    with pytest.raises(ReconciliationError, match="reconstructed_unknown"):
        reconcile_release_evidence(catalog, **_release_inputs(tmp_path))
```

Synthetic release fixtures use exact subject constants defined below, a tiny rules YAML matching a complete extracted record, a teams YAML with numeric IDs and names, and an existing-format draw YAML. `_release_catalog` also writes `source-registry.json` authorizing each synthetic source for its exact subject.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_evidence.py -k 'release_loader or release_reconciliation' -q
```

Expected: import errors for the catalog and release adapter.

- [ ] **Step 3: Implement the exact Plan 3 API**

**Amended 2026-08-11 — this step owns the threshold derivation, restated here rather than carried forward from Task 5.** `reconcile_release_evidence` must, for the `prediction_shape` subject, call `derive_swiss_thresholds` on the **captured** category set from the selected record's normalized payload and compare its `advance_at_wins` and `eliminate_at_losses` against `config/ti2026_rules.yaml` field by field. Absent prediction-shape evidence, a category missing from the captured set, or a derived threshold differing from the shipping value each fail closed; the shipping configuration is never rewritten to agree, and no category set written into this plan may substitute for the captured one. All seven subjects below are mandatory.

Define registered subject constants; observed values never appear in them:

```python
RELEASE_SUBJECTS = {
    "rules": "rules:ti2026:valve:group-stage",
    "published_format": "rules:ti2026:event-format:group-stage",
    "prediction_shape": "rules:ti2026:event-format:prediction-shape",
    "participants": "participants:ti2026:event-authority:field",
    "rosters": "rosters:ti2026:event-authority:registered-lineups",
    "groups": "draws:ti2026:event-authority:groups",
    "round_one": "draws:ti2026:event-authority:round-one",
}

@dataclass(frozen=True)
class EvidenceCatalog:
    root: Path
    registry_path: Path
    records: tuple[EvidenceManifest, ...]

@dataclass(frozen=True)
class ReleaseEvidence:
    selected: dict[str, CurrentEvidence]
    input_paths: tuple[Path, ...]
    participant_ids: frozenset[int]
    roster_accounts: dict[int, tuple[int, ...]]
    rules_facts: dict[str, object]
    draw_states: dict[str, str]
    groups: dict[int, str] | None
    round_one: tuple[tuple[int, int], ...] | None

def load_release_evidence(root: Path) -> EvidenceCatalog: ...
def reconcile_release_evidence(
    catalog: EvidenceCatalog,
    *,
    cutoff_utc: str,
    rules_path: Path,
    teams_path: Path,
    groups_path: Path | None,
) -> ReleaseEvidence: ...
```

`load_release_evidence` loads `root/source-registry.json`. At the evidence-root level it permits exactly that regular non-symlink file, the owner-input staging directory `imports/`, and the registered kind directories `rules`, `participants`, `rosters`, and `draws`; any other entry fails closed. If present, `imports/` must itself be a non-symlink directory; its contents are never searched for records and never enter the catalog. Inside each kind directory, every child must be a non-symlink lowercase-64-hex directory with `manifest.json`; an incomplete or unexpected child fails closed. Validate every manifest, every payload digest, its path kind/ID, and its source registration. Require globally unique evidence IDs and pass the complete collection—not a prefiltered subset—to current-tip selection. Sort records by `(kind, subject_key, evidence_id)` for deterministic output.

`groups` uses numeric configured team IDs as keys and group labels as values, matching the name-to-label shape returned by `load_group_draw` after names are translated to IDs. `round_one` preserves the existing YAML's pair order and orientation after the same translation.

`reconcile_release_evidence` selects the unique current tip for each `RELEASE_SUBJECTS` entry with `allow_reconstructed_unknown=False`. Rules, participants, rosters, published format, and prediction shape require `present`; participant IDs must exactly equal `load_teams(teams_path)` IDs; roster keys must exactly equal those participant IDs; group-stage rules call `reconcile_rules_facts(shipping_rules_facts(rules_path), complete_extracted_object)`, and the distinct format subject's own exact normalized format payload is reconciled the same way, by calling `reconcile_rules_format_facts(shipping_rules_format_facts(rules_path), complete_format_extracted_object)` — Task 5 defines both functions for exactly this call site, and no other place in this slice reconciles the published format (the index forbids Plan 3 from reimplementing evidence reconciliation). Missing format evidence is a hard owner-input stop, never a claim inferred from the group-stage capture. Per the 2026-08-11 amendment, that reconciliation compares only the direct published-format vocabulary: `shipping_rules_format_facts` no longer projects `advance_at_wins` or `eliminate_at_losses`, and the format record does not assert them. Extract normalized payloads only from the selected validated records. Add `test_release_reconciliation_reconciles_published_format_facts` (`Kills mutation: gate the format subject on existence without reconciling its facts against shipping config.`); remove the `reconcile_rules_format_facts` call, observe RED, restore GREEN.

Draw selection remains independent even though the existing shipping input is one optional YAML file. If `groups_path` is absent, both selected draw facts must be `unpublished` with negative observations admissible through the cutoff. If it is supplied, use existing `load_group_draw(groups_path, configured_names)`, translate names to configured numeric team IDs, and compare `groups` against the published groups tip. Compare the optional `round_one` field separately: a present field requires a matching published Round-1 tip; an absent field requires a current unpublished Round-1 tip. A published Round 1 without published groups, `unknown`, missing tip, stale negative observation, mismatched names/IDs/order, or local/evidence publication-state disagreement fails closed. No draw state is inferred from a missing record.

Return `input_paths` as a duplicate-free sorted tuple containing `source-registry.json` plus every selected manifest and every selected payload, including all negative-observation captures and every temporally applicable ancestor/competing-tip manifest and payload inspected to validate the selected lineage/graph. Exclude only records unavailable after the cutoff and not traversed for applicable-graph validation. Release reconciliation, not intrinsic roster schema validation, requires roster keys to exactly cover the authoritative participant ID set. Add `test_release_inputs_bind_applicable_lineage` (`Kills mutation: bind only the selected tip while using unbound ancestors or competing tips for graph selection.`) and `test_release_reconciliation_rejects_roster_coverage_gap` (`Kills mutation: omit authoritative participant coverage from release reconciliation.`); remove lineage collection/coverage comparison in turn, observe RED, restore GREEN. Plan 3 adds the optional local draw path and snapshot/config paths before digesting the complete input set.

- [ ] **Step 4: Run GREEN and every mutation**

Run focused tests and Ruff; expected PASS. Apply each mutation separately: ignore manifestless directories; omit the Round-1 selection; exclude negative captures from `input_paths`; compare roster keys only; reuse the groups comparison for Round 1; pass `allow_reconstructed_unknown=True`; drop the `reconcile_rules_format_facts` call. Observe the corresponding named test FAIL, restore, and rerun:

```bash
.venv/bin/python -m pytest tests/test_evidence.py -q
.venv/bin/python -m ruff check src/ti26/evidence.py tests/test_evidence.py
```

- [ ] **Step 5: Commit**

```bash
git add src/ti26/evidence.py tests/test_evidence.py
git commit -m "feat: reconcile complete release evidence"
```

### Task 8: Bind the current Valve capture and preserve the superseded morning transcript

> **HISTORICAL — COMPLETED 2026-08-10, DO NOT RERUN.** This task already executed and produced the committed v1 record and the archive/transcript banners. Its capture, metadata, and dry-run steps describe the original import and are kept as the record of what was done. **Do not obtain new metadata or re-import the Valve rules capture**: the repair path is `migrate-v1`, which carries those exact attested bytes into a v2 record mechanically, and re-importing would contradict that decision and produce a second lineage. The only live instructions here are its two repository-artifact tests, whose cutoff expression now uses the version-neutral `record.available_at_utc`.

**Files:**

- Create: `data/evidence/source-registry.json` with the owner-reviewed Valve rules source registration.
- Create: the computed `data/evidence/rules/<evidence_id>/` record printed by the importer, containing `rendered.txt`, `extracted.json`, and `manifest.json`.
- Modify: `docs/ti26/2026-08-08-ti2026-rules-fetched.md`
- Modify: `docs/ti26/2026-08-08-published-format-rules.md`
- Modify: `tests/test_evidence.py`
- Modify: `tests/test_rules.py`

- [ ] **Step 1: Add RED repository-artifact tests**

```python
def test_committed_valve_rules_evidence_is_complete_and_reconciles_with_shipping_config():
    """Kills mutation: commit a rendered rules archive without a validated manifest-bound extraction."""
    catalog = load_release_evidence(Path("data/evidence"))
    rules_records = [record for record in catalog.records if record.subject_key == RELEASE_SUBJECTS["rules"]]
    assert rules_records
    cutoff = max(record.available_at_utc for record in rules_records)
    current = select_current_evidence(
        catalog.records,
        "rules",
        RELEASE_SUBJECTS["rules"],
        cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    extracted = json.loads((current.selected.root / "extracted.json").read_text(encoding="utf-8"))
    assert reconcile_rules_facts(shipping_rules_facts("config/ti2026_rules.yaml"), extracted) == []


def test_morning_rules_transcript_has_a_superseded_banner_and_preserves_its_body():
    """Kills mutation: silently replace the earlier owner transcript instead of retaining superseded evidence."""
    text = Path("docs/ti26/2026-08-08-published-format-rules.md").read_text(encoding="utf-8")
    assert any("Superseded" in line for line in text.splitlines()[:8])
    assert "## TI 2025" in text
    assert "## TI 2026, as published on 2026-08-08" in text
    catalog = load_release_evidence(Path("data/evidence"))
    linked = [record for record in catalog.records if record.subject_key == RELEASE_SUBJECTS["rules"]]
    assert any(str(record.root / "manifest.json") in text for record in linked)
```

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_evidence.py tests/test_rules.py -q
```

Expected: FAIL because the evidence record and superseded banner are absent.

- [ ] **Step 3: Obtain source metadata, import exact source bytes, and update archival docs**

Before writing committed data, obtain one owner-authored local source metadata JSON that contains the stable `source_url_key`, capture method, evidence-backed availability time, claimed publication time when available, retrieval time, observation assertion/times, authoritative-source keys checked, and construction class for the already captured Valve page. Save the unmodified rendered bytes at `data/evidence/imports/valve-group-stage-rendered.txt` and the metadata JSON at `data/evidence/imports/valve-group-stage-source.json`; do not derive a time from prose or retain a mutable raw URL. Create `data/evidence/source-registry.json` with exactly that stable key authorized for kind `rules` and `RELEASE_SUBJECTS["rules"]`. Do not pre-register guessed future participant, roster, or draw sources; the owner adds those exact authority entries with their near-lock captures before importing them.

Run `ti26.cli_evidence_import rules --dry-run` first against the local capture and metadata skeleton. It writes no record and prints canonical capture SHA-256 values plus the computed normalized-fact payload SHA-256. The owner approves those exact printed digests and supplies them as the positive attestation; only then may the clean import resolve its actual `HEAD` and write immutable evidence. Add `test_dry_run_emits_digests_without_writing` (`Kills mutation: write evidence before owner attestation approval.`); mutate dry-run to invoke the writer, observe RED, restore GREEN.

**Owner-input stop gate:** if the owner cannot provide the exact capture plus metadata establishing its availability/observation time and stable source key, stop before creating a committed current rules record, changing the transcript banner, or reconciling configuration. Do not infer dates from prose or manufacture metadata. A `reconstructed_unknown` record may be retained only as a diagnostic and is ineligible for this current-source reconciliation.

With adequate input, commit the owner input files and source registry first, leaving a clean checkout:

```bash
git add data/evidence/imports/valve-group-stage-rendered.txt data/evidence/imports/valve-group-stage-source.json data/evidence/source-registry.json
git commit -m "chore: add Valve rules import inputs"
```

Then validate them with the CLI, which resolves and records the actual `HEAD` revision itself:

```bash
.venv/bin/python -m ti26.cli_evidence_import rules \
  --root data/evidence \
  --event-id ti2026 \
  --subject-key rules:ti2026:valve:group-stage \
  --source-registry data/evidence/source-registry.json \
  --capture valve-ti-group-stage-rules=data/evidence/imports/valve-group-stage-rendered.txt \
  --source data/evidence/imports/valve-group-stage-source.json
```

The only non-generated file content in the evidence directory is the owner capture supplied to the command; `extracted.json` and `manifest.json` are CLI outputs. The CLI prints the computed immutable record path. Verify that manifest with `validate_evidence_manifest`, then update `docs/ti26/2026-08-08-ti2026-rules-fetched.md` to state that its archival prose is superseded as a release input by the linked immutable evidence record, without changing its quoted capture. Prepend a nonnumeric `Superseded as a current TI 2026 rules source` banner to `docs/ti26/2026-08-08-published-format-rules.md`; it retains the morning transcript as historical evidence and links to the repository-relative `manifest.json` path printed by that command. Do not insert a guessed path or a fixed evidence identifier.

Do not delete or reword the transcript body. The known difference between its morning state and later capture is exactly why it remains.

- [ ] **Step 4: Run GREEN and mutations**

Run the Task 8 nodeids; expected PASS. Temporarily change one byte in `rendered.txt` without regenerating the manifest and observe the committed-evidence test FAIL on SHA-256. Restore the byte. Temporarily remove the banner line and observe the transcript test FAIL. Restore and run:

```bash
.venv/bin/python -m pytest tests/test_evidence.py tests/test_rules.py -q
.venv/bin/python -m ruff check src/ti26/evidence.py src/ti26/rules.py tests/test_evidence.py tests/test_rules.py
```

- [ ] **Step 5: Commit**

```bash
git add data/evidence/source-registry.json data/evidence/rules docs/ti26/2026-08-08-ti2026-rules-fetched.md docs/ti26/2026-08-08-published-format-rules.md tests/test_evidence.py tests/test_rules.py
git commit -m "docs: bind Valve rules evidence"
```

### Task 9: Audit unbound empirical-number prose without changing behavior

**Files:**

- Modify: `config/ti2026_rules.yaml`
- Modify: `tests/test_rules.py`
- Modify: `docs/ti26/near-lock-runbook.md`
- Create: `tests/fixtures/ti2026_rules_predictive_pre_comment_audit.yaml`

- [ ] **Step 1: Write RED comment-audit test**

```python
def test_rules_config_comments_do_not_restate_empirical_measurements():
    """Kills mutation: reintroduce a hand-written measured quantity into shipping rules comments."""
    text = Path(RULES_PATH).read_text(encoding="utf-8")
    comments = "\n".join(line for line in text.splitlines() if line.lstrip().startswith("#"))
    prohibited = (
        "Fitted in",
        "MARGINAL",
        "rating-gap coefficient",
        "Signal-to-noise",
        "marginals by",
        "standard error",
    )
    assert not [fragment for fragment in prohibited if fragment in comments]
    before = yaml.safe_load(Path("tests/fixtures/ti2026_rules_predictive_pre_comment_audit.yaml").read_text(encoding="utf-8"))
    after = yaml.safe_load(text)
    assert predictive_config_projection(after) == predictive_config_projection(before)
```

`predictive_config_projection` returns the complete parsed configuration including provenance; YAML comments are excluded by parsing, not by a field whitelist. Before changing comments, create the fixture by copying the current configuration unchanged, then commit it with the audit change; it is the named pre-edit input, not a hand-authored restatement. The comparison preserves all predictive configuration values and provenance tags, including nested values not exercised by a two-scalar test. This is a deliberately narrow audit for the exact listed legacy fragments, not a claimed general detector of every empirical number. Do not add any numeric prose to this test’s docstring beyond the mutation description.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_rules.py::test_rules_config_comments_do_not_restate_empirical_measurements -q
```

Expected: FAIL on the existing measurement fragments.

- [ ] **Step 3: Replace prose with bound references or nonnumeric statements**

In `config/ti2026_rules.yaml`, retain all keys and scalar values exactly. Remove the map-count, duration conversion, numerical sensitivity comparison, and performance-ratio prose under `duration_model`, `base_pairing_preference`, and `max_distance_when_loser_eliminated_preference`. Replace them with the first template below under `duration_model`, and the second template verbatim under each of the two pairing keys:

```yaml
  # Derived duration-fit outputs are bound by the release bundle that generated
  # them. This configuration stores the chosen model inputs; it does not restate
  # measurements.
```

and:

```yaml
  # The historical pairing diagnostic is manifest-bound producer output.
  # This provenance label records its qualitative status, not a measurement.
```

Do not change `fitted_from_n_maps`, duration values, provenance labels, or the rule-engine code. `fitted_from_n_maps` is a configuration scalar already consumed by existing behavior; this plan does not remove or reinterpret it. The audit removes only duplicated prose measurements and comments which no manifest presently binds.

In `docs/ti26/near-lock-runbook.md` section 3b, replace the re-archive instruction with owner capture, offline import, and a hard stop on import/reconciliation failure. The command must use `ti26.cli_evidence_import rules`, a local capture path, a local source-metadata path, and the importer-resolved clean `HEAD`; it must not accept a caller-authored revision. Do not supply copied result figures in the new prose.

- [ ] **Step 4: Run GREEN and mutation proof**

Run the audit nodeid and the existing rules suite; expected PASS. Temporarily add a comment containing `Signal-to-noise` beneath either pairing provenance label and observe the audit test FAIL. Temporarily alter any parsed predictive scalar or list in the post-audit config and observe the complete projection comparison FAIL. Restore, then run:

```bash
.venv/bin/python -m pytest tests/test_rules.py -q
.venv/bin/python -m ruff check src/ti26/rules.py tests/test_rules.py
```

- [ ] **Step 5: Commit**

```bash
git add config/ti2026_rules.yaml docs/ti26/near-lock-runbook.md tests/fixtures/ti2026_rules_predictive_pre_comment_audit.yaml tests/test_rules.py
git commit -m "docs: remove unbound rules measurements"
```

### Task 10: Focused and full verification

**Files:**

- Modify only if a verification failure identifies an in-scope defect: files owned by Tasks 1–9.

- [ ] **Step 1: Prove complete evidence lineage and reconciliation**

Run:

```bash
.venv/bin/python -m pytest tests/test_evidence.py tests/test_cli_evidence_import.py tests/test_groups.py tests/test_rules.py -q
.venv/bin/python -m ruff check src/ti26/evidence.py src/ti26/cli_evidence_import.py src/ti26/rules.py tests/test_evidence.py tests/test_cli_evidence_import.py tests/test_groups.py tests/test_rules.py
```

Expected: PASS. The test set verifies exact schemas, traversal-safe content addressing, exclusive/manifest-last publication, positive and negative observations, current-at-cutoff selection, extraction span binding, factual reconciliation, the offline import boundary, the committed Valve record, transcript supersession, and prose audit.

- [ ] **Step 2: Generate and verify a post-Plan-2 candidate against Plan 1's real oracle**

After every Task 1–9 commit is present, require a clean checkout and use the actual output of `git rev-parse HEAD` as the candidate execution provenance. Require an absent outside-repository replay root, then invoke Plan 1's exact non-publishing interface `replay_current_frozen_output(*, repo_root: Path, runs_root: Path, source_revision: str) -> None` through its CLI. The helper itself verifies the manifest-bound baseline against the baseline manifest's own `source_revision`, rebuilds the candidate from the registered baseline invocation and snapshot, loads the completed candidate through Plan 1's manifest-bound reader (`load_frozen_output`; the manifestless staged reader is reserved for Plan 3's pre-manifest use), and calls the frozen-output comparator; Plan 2 must not duplicate any of those calls. On success it removes the replay root; on failure it preserves that root for diagnosis. It publishes no registered run or forecast link, but may rebuild the ignored derived `data/processed/release-{snapshot_id}.sqlite`. Do not claim or invoke Plan 3 staging or `cli_release` behavior before Plan 3 exists.

```bash
git rev-parse HEAD
test ! -e /private/tmp/ti26-plan2-frozen-replay
git rev-parse HEAD | xargs .venv/bin/python -m ti26.frozen_output_oracle --replay-root /private/tmp/ti26-plan2-frozen-replay --repo-root . --source-revision
```

```bash
.venv/bin/python -m pytest tests/test_cli_release.py tests/test_cli_card.py tests/test_rules.py -q
```

Expected: PASS, removal of `/private/tmp/ti26-plan2-frozen-replay`, and a successful baseline-manifest-revision verification plus replay-candidate comparison produced after the Plan-2 commit. No registered run or forecast link is created; the ignored derived processed SQLite file may be rebuilt. If the historical-Git verifier or comparison reveals a changed predictive artifact, stop; do not update the oracle, gates, configuration values, simulation, card, or baseline revision to make it pass. This slice has no authority for predictive changes.

- [ ] **Step 3: Run required complete verification**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

Expected: both PASS on the post-change tree. This is the completion oracle required by the committed `CLAUDE.md` ("Verification before any completion claim"; the untracked local `AGENTS.md` mirrors it but is gitignored, so it cannot be cited by a committed plan); no filtered run substitutes for it.

- [ ] **Step 4: Commit final verification fixes only when needed**

If a focused or full check required in-scope fixes, stage only the relevant task files and commit with a message that describes the correction without repeating generated empirical values. If all verification passes without further edits, do not create an empty commit.

## Self-review report

Spec coverage:

- Offline owner-byte import, no network, exact schemas, safe paths, SHA-256 payload binding, exclusive creation, and manifest-last publication: Tasks 1, 2, and 6.
- Present/absent observation requirements and cutoff freshness: Task 3.
- Acyclic same-subject supersession, unique current tips, stale descendants, and deterministic rejection reasons: Task 4.
- Normalized factual extraction with supporting span digests, configuration projection, and fail-closed reconciliation: Task 5.
- Validated release catalog and one typed rules/field/rosters/groups/Round-1 reconciliation result: Task 7.
- Existing rendered Valve evidence import and unchanged historical transcript with superseded banner: Task 8.
- Empirical-number comment audit and nonnumeric runbook update: Task 9.
- No predictive behavior and release wiring deferred to plan 3: Scope section and Task 10 oracle check.

Type consistency checked: importer writes `EvidenceManifest` payloads consumed by `validate_evidence_manifest`; `extract_ti2026_rules` produces the complete extracted object accepted by `reconcile_rules_facts`; `shipping_rules_facts` produces the same vocabulary; `select_current_evidence` accepts validated manifests and returns `CurrentEvidence`; `load_release_evidence` returns `EvidenceCatalog`, and `reconcile_release_evidence` returns the `ReleaseEvidence` consumed by Plan 3.

Placeholder scan: this plan contains no deferred implementation markers. Owner-supplied source metadata is an explicit external authority prerequisite, not a fabricated local value; the implementation must reject its absence rather than fill it.

Verification evidence required before completion: every added test has a named temporary mutation and focused failure procedure in its task, followed by restoration and GREEN commands; Task 10 requires the unfiltered suite and Ruff on the final tree.
