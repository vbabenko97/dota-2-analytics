import ast
import contextlib
import hashlib
import io
import json
import socket
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from ti26.cli_evidence_import import clean_head_revision, main
from ti26.evidence import (
    EvidenceError,
    canonical_evidence_json_bytes,
    evidence_id_for_manifest,
    extract_ti2026_rules,
    validate_evidence_manifest,
    validate_kind_payload,
    write_evidence_record,
)
from ti26.provenance import canonical_json_bytes

_PRIMARY_SOURCE_KEY = "valve-ti-group-stage-rules"
_KIND_BY_COMMAND = {
    "rules": "rules",
    "rules-format": "rules",
    "participants": "participants",
    "rosters": "rosters",
    "draw": "draws",
}
_DEFAULT_SUBJECT = {
    "rules": "rules:ti2026:owner:field",
    "rules-format": "rules:ti2026:valve:published-format",
    "participants": "participants:ti2026:owner:field",
    "rosters": "rosters:ti2026:owner:field",
    "draw": "draws:ti2026:owner:field",
}
_DEFAULT_FACTS = {
    "participants": {
        "schema": "ti26.participants.v1",
        "participants": [{"team_id": 101, "display_name": "Alpha"}],
    },
    "rosters": {
        "schema": "ti26.rosters.v1",
        "rosters": [{"team_id": 101, "account_ids": [1, 2, 3, 4, 5]}],
    },
    "draw": {
        "schema": "ti26.draw-fact.v1",
        "component": "groups",
        "publication_state": "published",
        "value": {"a": [101]},
    },
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: object) -> Path:
    """Write `value` as an owner would type it -- readable, not pre-canonicalized.

    Default `json.dumps` spacing (`", "`/`": "`) differs from
    `canonical_evidence_json_bytes`'s compact separators, so a test comparing
    an imported record's normalized payload against the canonical form of
    the same Python value actually exercises the importer's own
    canonicalization step rather than merely echoing already-canonical bytes.
    """
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def _complete_rules_text() -> bytes:
    return (
        b"Number of Matches Won\nNumber of Matches Lost\n"
        b"Total Number of Matches Won by Opponents Played\nPercentage of Games Won\n"
        b"Average Percentage of Games Won by Opponents Played\n"
        b"Average Game Duration (Shorter is Better)\nCoin Toss\n"
        b"Round 2\nTeams are only matched against other members of their initial group\n"
        b"Round 3\nTeams are only matched against other members of their initial group\n"
        b"Round 4\nTeams are only matched against members of the other group\n"
        b"Round 5\nFor matches where the loser is eliminated, maximize the distance in "
        b"ranking between the teams\n"
        b"Elimination Round\nStarting with the best 3-2 team, they will choose any of the "
        b"five 2-3 teams as their opponent.\n"
    )


def _source_metadata(
    *,
    assertion: str = "present",
    checked: list[str] | None = None,
    source_url_key: str = _PRIMARY_SOURCE_KEY,
    attestation: dict[str, object] | None = None,
    available_at_utc: str = "2026-01-01T00:00:00Z",
    observed_at_utc: str = "2026-01-01T00:00:01Z",
    construction: str = "contemporaneous",
) -> dict[str, object]:
    """Build one owner-supplied source-metadata JSON object -- never a fetched value.

    Every field is a synthetic literal supplied by the test, in the style of
    `tests/test_evidence.py`'s `_manifest`. `attestation` is `None` unless the
    caller (usually `_run_import`, which knows the real computed digests)
    supplies one; a negative-observation manifest never carries one.
    """
    return {
        "source_url_key": source_url_key,
        "capture_method": "owner-supplied-rendered-text",
        "available_at_utc": available_at_utc,
        "published_at_utc": None,
        "retrieved_at_utc": observed_at_utc,
        "assertion": assertion,
        "observed_at_utc": observed_at_utc,
        "supported_through_utc": observed_at_utc,
        "authoritative_source_keys_checked": list(checked) if checked else [],
        "attestation": attestation,
        "construction": construction,
    }


def _source_registry(
    workdir: Path, *, kind: str, subject_key: str, source_keys: list[str]
) -> Path:
    """Write and return the path to a synthetic owner-reviewed source registry.

    Authorizes exactly `source_keys` for `(kind, subject_key)` -- the exact
    generic contract `ti26.evidence.load_source_registry` requires.
    """
    sources = [
        {
            "source_url_key": key,
            "authorizations": [{"event_id": "ti2026", "kind": kind, "subject_key": subject_key}],
        }
        for key in sorted(set(source_keys))
    ]
    value = {
        "schema": "ti26.evidence-source-registry.v1",
        "effective_at_utc": "2025-12-31T00:00:00Z",
        "sources": sources,
    }
    return _write_json(workdir / "registry.json", value)


def _registry_bytes_for(kind: str, subject_key: str) -> bytes:
    """Return canonical bytes for a registry authorizing the primary key only.

    Used only as the embedded `authority-registry.json` *payload* of a
    directly-written synthetic catalog record (`_current_fork`); it is not
    the live `--source-registry` file a later import consults.
    """
    value = {
        "schema": "ti26.evidence-source-registry.v1",
        "effective_at_utc": "2025-12-31T00:00:00Z",
        "sources": [
            {
                "source_url_key": _PRIMARY_SOURCE_KEY,
                "authorizations": [
                    {"event_id": "ti2026", "kind": kind, "subject_key": subject_key}
                ],
            }
        ],
    }
    return canonical_evidence_json_bytes(value) + b"\n"


def _current_fork(tmp_path: Path, kind: str, subject_key: str):
    """Write two already-published, unsuperseded records for one subject.

    Every helper in this module writes through `write_evidence_record`, in
    the style of Task 7's stated convention -- no test hand-authors a
    trusted manifest for the catalog an importer will read. The two records
    differ only in their rendered capture bytes, so they get distinct
    content-addressed evidence ids while remaining an honest, unresolved
    fork: neither supersedes the other.
    """
    registry_bytes = _registry_bytes_for(kind, subject_key)
    extracted = canonical_evidence_json_bytes(
        {"schema": "ti26.rules-extracted.v1", "facts": {}}
    ) + b"\n"

    def build(label: str):
        rendered = f"Group Stage Rules ({label})\n".encode()
        payloads = [
            {"path": "authority-registry.json", "sha256": _sha(registry_bytes)},
            {"path": "rendered.txt", "sha256": _sha(rendered)},
            {"path": "extracted.json", "sha256": _sha(extracted)},
        ]
        manifest = {
            "schema": "ti26.evidence-manifest.v1",
            "evidence_id": "",
            "kind": kind,
            "event_id": "ti2026",
            "subject_key": subject_key,
            "source": {
                "source_url_key": _PRIMARY_SOURCE_KEY,
                "capture_method": f"synthetic-{label}",
                "available_at_utc": "2026-01-01T00:00:00Z",
                "published_at_utc": None,
                "retrieved_at_utc": "2026-01-01T00:00:01Z",
            },
            "observation": {
                "assertion": "present",
                "observed_at_utc": "2026-01-01T00:00:01Z",
                "supported_through_utc": "2026-01-01T00:00:01Z",
                "captures": [{"source_url_key": _PRIMARY_SOURCE_KEY, "path": "rendered.txt"}],
                "authoritative_source_keys_checked": [],
                "diagnostic_reason": None,
            },
            "attestation": {
                "fact_payload_sha256": _sha(extracted),
                "capture_sha256s": [_sha(rendered)],
            },
            "authority_registry": {
                "schema": "ti26.evidence-authority-binding.v1",
                "path": "authority-registry.json",
                "sha256": _sha(registry_bytes),
                "effective_at_utc": "2025-12-31T00:00:00Z",
            },
            "construction": "contemporaneous",
            "payloads": payloads,
            "supersedes": [],
            "producer_revision": "a" * 40,
        }
        manifest["evidence_id"] = evidence_id_for_manifest(manifest)
        record_path = write_evidence_record(
            tmp_path,
            manifest,
            {
                "authority-registry.json": registry_bytes,
                "rendered.txt": rendered,
                "extracted.json": extracted,
            },
        )
        return validate_evidence_manifest(record_path, manifest, verify_payloads=True)

    return build("first"), build("second")


def _expected_import_path(
    tmp_path: Path, command: str, *, capture: bytes, subject_key: str
) -> Path:
    """Predict the destination `write_evidence_record` will use for one import.

    Rebuilds the same candidate manifest `_run_import` would construct for a
    fresh, un-superseded, present-observation import of `capture`, purely to
    derive its content-addressed `evidence_id` ahead of running the CLI --
    never to bypass it. The registry bytes are written through
    `_source_registry` (the same helper `_run_import` itself uses), not
    `_registry_bytes_for`'s pre-canonicalized form, so the digest matches
    exactly what the real import will read off disk.
    """
    kind = _KIND_BY_COMMAND[command]
    extracted = extract_ti2026_rules(capture.decode("utf-8"))
    fact_bytes = canonical_evidence_json_bytes(extracted) + b"\n"
    registry_workdir = Path(tempfile.mkdtemp(dir=tmp_path))
    registry_path = _source_registry(
        registry_workdir, kind=kind, subject_key=subject_key, source_keys=[_PRIMARY_SOURCE_KEY]
    )
    registry_bytes = registry_path.read_bytes()
    manifest = {
        "schema": "ti26.evidence-manifest.v1",
        "evidence_id": "",
        "kind": kind,
        "event_id": "ti2026",
        "subject_key": subject_key,
        "source": {
            "source_url_key": _PRIMARY_SOURCE_KEY,
            "capture_method": "owner-supplied-rendered-text",
            "available_at_utc": "2026-01-01T00:00:00Z",
            "published_at_utc": None,
            "retrieved_at_utc": "2026-01-01T00:00:01Z",
        },
        "observation": {
            "assertion": "present",
            "observed_at_utc": "2026-01-01T00:00:01Z",
            "supported_through_utc": "2026-01-01T00:00:01Z",
            "captures": [{"source_url_key": _PRIMARY_SOURCE_KEY, "path": "rendered.txt"}],
            "authoritative_source_keys_checked": [],
            "diagnostic_reason": None,
        },
        "attestation": {
            "fact_payload_sha256": _sha(fact_bytes),
            "capture_sha256s": [_sha(capture)],
        },
        "authority_registry": {
            "schema": "ti26.evidence-authority-binding.v1",
            "path": "authority-registry.json",
            "sha256": _sha(registry_bytes),
            "effective_at_utc": "2025-12-31T00:00:00Z",
        },
        "construction": "contemporaneous",
        # Matches `_run_command`'s own append order exactly: the payloads list
        # is not among the canonically-sorted set-like fields, so its order is
        # part of the content digest.
        "payloads": [
            {"path": "extracted.json", "sha256": _sha(fact_bytes)},
            {"path": "authority-registry.json", "sha256": _sha(registry_bytes)},
            {"path": "rendered.txt", "sha256": _sha(capture)},
        ],
        "supersedes": [],
        "producer_revision": "a" * 40,
    }
    manifest["evidence_id"] = evidence_id_for_manifest(manifest)
    return tmp_path / kind / manifest["evidence_id"]


@pytest.fixture
def clean_import_head(monkeypatch):
    """Provide a clean synthetic checkout only to tests exercising import behavior."""
    monkeypatch.setattr("ti26.cli_evidence_import.clean_head_revision", lambda _root: "a" * 40)


def _run_import(
    root: Path,
    command: str,
    *,
    capture: bytes | None = None,
    captures: dict[str, bytes] | None = None,
    facts: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
    registry_subject: str | None = None,
    subject_key: str | None = None,
    supersedes: list[str] | None = None,
) -> Path:
    """Write synthetic owner-capture inputs, then invoke the real CLI parser.

    Every input file is a fresh, uniquely-named synthetic fixture -- never a
    copied measurement. Returns the sole path `main` printed on success;
    `main`'s own `SystemExit` (argparse or `parser.error`) propagates
    unchanged, so a caller wanting a parser rejection uses
    `pytest.raises(SystemExit)` around this call rather than around a raw
    `main` invocation.
    """
    kind = _KIND_BY_COMMAND[command]
    used_subject_key = subject_key or _DEFAULT_SUBJECT[command]
    workdir = Path(tempfile.mkdtemp(dir=root))

    if capture is None and captures is None:
        capture = _complete_rules_text() if command in ("rules", "rules-format") else b"synthetic-capture-bytes"
    capture_map = dict(captures) if captures is not None else {_PRIMARY_SOURCE_KEY: capture}

    capture_args: list[str] = []
    for key in sorted(capture_map):
        capture_path = workdir / f"capture-{key}.bin"
        capture_path.write_bytes(capture_map[key])
        capture_args += ["--capture", f"{key}={capture_path}"]

    if command not in ("rules", "rules-format") and facts is None:
        facts = _DEFAULT_FACTS[command]

    if metadata is None:
        primary_bytes = capture_map[_PRIMARY_SOURCE_KEY]
        if command == "rules":
            fact_bytes = canonical_evidence_json_bytes(
                extract_ti2026_rules(primary_bytes.decode("utf-8"))
            ) + b"\n"
        else:
            from ti26.evidence import extract_ti2026_published_format

            if command == "rules-format":
                fact_bytes = canonical_evidence_json_bytes(
                    extract_ti2026_published_format(primary_bytes.decode("utf-8"))
                ) + b"\n"
            else:
                validated = validate_kind_payload(kind, facts, assertion="present")
                fact_bytes = canonical_evidence_json_bytes(validated) + b"\n"
        attestation = {
            "fact_payload_sha256": _sha(fact_bytes),
            "capture_sha256s": sorted({_sha(primary_bytes)}),
        }
        metadata = _source_metadata(assertion="present", attestation=attestation)

    checked_keys = metadata.get("authoritative_source_keys_checked") or []
    authorized_keys = sorted(set(capture_map) | set(checked_keys) | {metadata["source_url_key"]})
    registry_path = _source_registry(
        workdir,
        kind=kind,
        subject_key=registry_subject or used_subject_key,
        source_keys=authorized_keys,
    )
    metadata_path = _write_json(workdir / "source.json", metadata)

    argv = [
        command,
        "--root", str(root),
        "--event-id", "ti2026",
        "--subject-key", used_subject_key,
        "--source-registry", str(registry_path),
        "--source", str(metadata_path),
        *capture_args,
    ]
    if command not in ("rules", "rules-format"):
        facts_path = _write_json(workdir / "facts.json", facts)
        argv += ["--facts", str(facts_path)]
    for evidence_id in supersedes or []:
        argv += ["--supersedes", evidence_id]

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        main(argv)
    return Path(out.getvalue().strip())


def test_clean_head_revision_rejects_an_untracked_file(monkeypatch, tmp_path):
    """Kills mutation: omit untracked files from the importer's clean-checkout boundary."""
    responses = iter(
        [SimpleNamespace(stdout="?? owner-capture.txt\n"), SimpleNamespace(stdout="a" * 40 + "\n")]
    )
    monkeypatch.setattr(
        "ti26.cli_evidence_import.subprocess.run", lambda *args, **kwargs: next(responses)
    )
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
        (
            "participants",
            {"schema": "ti26.participants.v1", "participants": [{"team_id": 101, "display_name": "Alpha"}]},
            "participants.json",
        ),
        (
            "rosters",
            {"schema": "ti26.rosters.v1", "rosters": [{"team_id": 101, "account_ids": [1, 2, 3, 4, 5]}]},
            "rosters.json",
        ),
        (
            "draw",
            {"schema": "ti26.draw-fact.v1", "component": "groups", "publication_state": "published", "value": {"a": [101]}},
            "draw.json",
        ),
    ],
)
def test_fact_imports_canonicalize_owner_facts_and_keep_capture_bytes(
    tmp_path, clean_import_head, kind, facts, normalized_name
):
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
            facts={
                "schema": "ti26.draw-fact.v1",
                "component": "round_one",
                "publication_state": "unpublished",
                "value": None,
            },
            metadata=_source_metadata(
                assertion="absent", checked=["blast-series", "valve-event"]
            ),
            captures={"blast-series": b"not published"},
        )


def test_negative_draw_import_writes_a_distinct_file_per_checked_capture(tmp_path, clean_import_head):
    """Kills mutation: collapse every keyed secondary capture onto one shared file path."""
    record = _run_import(
        tmp_path,
        "draw",
        facts={
            "schema": "ti26.draw-fact.v1",
            "component": "round_one",
            "publication_state": "unpublished",
            "value": None,
        },
        metadata=_source_metadata(
            assertion="absent",
            checked=["blast-series", "valve-event"],
            source_url_key="blast-series",
        ),
        captures={"blast-series": b"blast series says no draw yet", "valve-event": b"valve event page is blank"},
    )
    assert (record / "captures" / "blast-series.bin").read_bytes() == b"blast series says no draw yet"
    assert (record / "captures" / "valve-event.bin").read_bytes() == b"valve event page is blank"


def test_import_rejects_attestation_swapped_from_the_actual_bytes(tmp_path, clean_import_head):
    """Kills mutation: silently substitute a self-computed attestation for the owner's claim."""
    wrong_attestation = {
        "fact_payload_sha256": "0" * 64,
        "capture_sha256s": [_sha(_complete_rules_text())],
    }
    with pytest.raises(SystemExit):
        _run_import(
            tmp_path,
            "rules",
            capture=_complete_rules_text(),
            metadata=_source_metadata(assertion="present", attestation=wrong_attestation),
        )


def test_negative_draw_import_rejects_a_checked_authority_subset_of_the_registry(
    tmp_path, clean_import_head
):
    """Kills mutation: accept a checked/captured set that omits a registered authority."""
    workdir = Path(tempfile.mkdtemp(dir=tmp_path))
    blast_capture = workdir / "blast.bin"
    blast_capture.write_bytes(b"blast series says no draw yet")
    valve_capture = workdir / "valve.bin"
    valve_capture.write_bytes(b"valve event page is blank")

    metadata = _source_metadata(
        assertion="absent", checked=["blast-series", "valve-event"], source_url_key="blast-series"
    )
    metadata_path = _write_json(workdir / "source.json", metadata)
    subject_key = _DEFAULT_SUBJECT["draw"]
    # The registry authorizes a THIRD source ("reddit-thread") for this exact
    # subject that the owner's checked/captured set never mentions -- checked
    # matching captured is not enough; both must equal the complete registry
    # authority set.
    registry_path = _source_registry(
        workdir,
        kind="draws",
        subject_key=subject_key,
        source_keys=["blast-series", "valve-event", "reddit-thread"],
    )
    argv = [
        "draw",
        "--root", str(tmp_path),
        "--event-id", "ti2026",
        "--subject-key", subject_key,
        "--source-registry", str(registry_path),
        "--source", str(metadata_path),
        "--capture", f"blast-series={blast_capture}",
        "--capture", f"valve-event={valve_capture}",
        "--facts", str(_write_json(
            workdir / "facts.json",
            {
                "schema": "ti26.draw-fact.v1",
                "component": "round_one",
                "publication_state": "unpublished",
                "value": None,
            },
        )),
    ]
    with pytest.raises(SystemExit):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            main(argv)


def test_import_rejects_a_source_not_registered_for_the_subject(tmp_path, clean_import_head):
    """Kills mutation: trust a source key without checking its registered kind and subject."""
    with pytest.raises(SystemExit):
        _run_import(tmp_path, "participants", registry_subject="participants:ti2026:other")


def test_import_requires_every_current_same_subject_tip_in_supersedes(tmp_path, clean_import_head):
    """Kills mutation: permit an import that supersedes only one tip of a current fork."""
    first, second = _current_fork(tmp_path, "rules", "rules:ti2026:owner:field")  # noqa: RUF059 -- verbatim plan test; `second` documents the fork's other tip
    with pytest.raises(SystemExit):
        _run_import(tmp_path, "rules", capture=_complete_rules_text(), supersedes=[first.evidence_id])


def test_import_reuses_complete_identical_content_and_rejects_incomplete_destination(
    tmp_path, clean_import_head
):
    """Kills mutation: create a new record over an incomplete destination or reject a verified retry."""
    first = _run_import(tmp_path, "rules", capture=_complete_rules_text())
    assert _run_import(tmp_path, "rules", capture=_complete_rules_text()) == first
    _expected_import_path(
        tmp_path, "rules", capture=_complete_rules_text(), subject_key="rules:ti2026:owner:incomplete"
    ).mkdir(parents=True)
    with pytest.raises(SystemExit):
        _run_import(
            tmp_path, "rules", capture=_complete_rules_text(), subject_key="rules:ti2026:owner:incomplete"
        )


def test_import_module_has_no_network_or_opendota_dependency():
    """Kills mutation: add a network-capable import to the offline evidence command."""
    tree = ast.parse(Path("src/ti26/cli_evidence_import.py").read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported.update(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))
    assert not {name for name in imported if name.startswith(("urllib", "requests", "httpx", "ti26.data.opendota"))}


def test_importer_uses_only_fixed_git_subprocess_vectors():
    """Kills mutation: construct an arbitrary subprocess command from importer input."""
    tree = ast.parse(Path("src/ti26/cli_evidence_import.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run"
    ]
    assert calls
    assert all(
        isinstance(call.args[0], ast.List)
        and all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in call.args[0].elts)
        for call in calls
    )
    assert {tuple(item.value for item in call.args[0].elts) for call in calls} == {
        ("git", "status", "--porcelain=v1", "--untracked-files=all"),
        ("git", "rev-parse", "HEAD"),
    }


def test_import_rejects_unregistered_positive_secondary_capture(tmp_path, clean_import_head):
    """Kills mutation: authorize only the primary capture source for a positive import."""
    workdir = Path(tempfile.mkdtemp(dir=tmp_path))
    primary_capture = workdir / "capture-primary.bin"
    primary_capture.write_bytes(_complete_rules_text())
    secondary_capture = workdir / "capture-secondary.bin"
    secondary_capture.write_bytes(b"secondary corroborating capture")

    fact_bytes = canonical_evidence_json_bytes(
        extract_ti2026_rules(_complete_rules_text().decode("utf-8"))
    ) + b"\n"
    attestation = {
        "fact_payload_sha256": _sha(fact_bytes),
        "capture_sha256s": sorted({_sha(_complete_rules_text()), _sha(b"secondary corroborating capture")}),
    }
    metadata = _source_metadata(assertion="present", attestation=attestation)
    metadata_path = _write_json(workdir / "source.json", metadata)

    subject_key = _DEFAULT_SUBJECT["rules"]
    # Registry authorizes only the primary key -- "unregistered-secondary" is
    # never granted an authorization for this (kind, subject_key) pair.
    registry_path = _source_registry(
        workdir, kind="rules", subject_key=subject_key, source_keys=[_PRIMARY_SOURCE_KEY]
    )

    argv = [
        "rules",
        "--root", str(tmp_path),
        "--event-id", "ti2026",
        "--subject-key", subject_key,
        "--source-registry", str(registry_path),
        "--source", str(metadata_path),
        "--capture", f"{_PRIMARY_SOURCE_KEY}={primary_capture}",
        "--capture", f"unregistered-secondary={secondary_capture}",
    ]
    with pytest.raises(SystemExit):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            main(argv)


def test_identical_retry_precedes_supersession_validation(tmp_path, clean_import_head):
    """Kills mutation: check supersedes before returning an identical complete record."""
    text_a = _complete_rules_text()
    text_b = _complete_rules_text() + b"\n"  # distinct bytes -> distinct evidence id
    subject = "rules:ti2026:owner:retry-precedence"

    record_a = _run_import(tmp_path, "rules", capture=text_a, subject_key=subject)
    record_b = _run_import(
        tmp_path, "rules", capture=text_b, subject_key=subject, supersedes=[_record_id(record_a)]
    )
    assert record_b != record_a

    # A now has a superseding descendant (B); a naive re-check of "does this
    # candidate's --supersedes cover every current tip" would see {B} and
    # reject a bare retry of A (whose own supersedes is still `[]`). The
    # identical-content short-circuit must return A unconditionally instead.
    assert _run_import(tmp_path, "rules", capture=text_a, subject_key=subject) == record_a


def test_import_rejects_backdated_fork(tmp_path, clean_import_head):
    """Kills mutation: validate only tips at the incoming timestamp."""
    subject = "rules:ti2026:owner:backdate"
    later = _run_import(tmp_path, "rules", capture=_complete_rules_text(), subject_key=subject)
    assert later.is_dir()

    backdated_metadata = _source_metadata(
        assertion="present",
        available_at_utc="2020-01-01T00:00:00Z",
        observed_at_utc="2020-01-01T00:00:01Z",
        attestation={
            "fact_payload_sha256": _sha(
                canonical_evidence_json_bytes(
                    extract_ti2026_rules((_complete_rules_text() + b"\nextra\n").decode("utf-8"))
                )
                + b"\n"
            ),
            "capture_sha256s": [_sha(_complete_rules_text() + b"\nextra\n")],
        },
    )
    with pytest.raises(SystemExit):
        _run_import(
            tmp_path,
            "rules",
            capture=_complete_rules_text() + b"\nextra\n",
            subject_key=subject,
            metadata=backdated_metadata,
        )


def test_import_runtime_denies_socket_and_non_git_subprocess(tmp_path, clean_import_head, monkeypatch):
    """Kills mutation: permit runtime network or arbitrary subprocess capability."""

    def denied(*args, **kwargs):
        raise AssertionError("forbidden runtime network or subprocess call")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(subprocess, "run", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)

    record = _run_import(tmp_path, "rules", capture=_complete_rules_text())
    assert record.is_dir()


def _record_id(record_path: Path) -> str:
    manifest = json.loads((record_path / "manifest.json").read_text(encoding="utf-8"))
    return manifest["evidence_id"]
