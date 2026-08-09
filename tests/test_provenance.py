import hashlib
import json
import re
from dataclasses import replace

import pytest

from ti26 import provenance
from ti26.cli_provenance import card_diff
from ti26.cli_provenance import main as provenance_main
from ti26.data.queries import MAP_QUERY
from ti26.data.schema import MapRow
from ti26.data.snapshot import (
    SnapshotIntegrityError,
    read_snapshot,
    sha256_file,
    validate_snapshot,
    write_snapshot,
)
from ti26.data.store import STORE_COLUMNS, insert_rows, open_store
from ti26.provenance import (
    RunManifestError,
    canonical_json_bytes,
    logical_store_digest,
    render_report_prefix,
    verify_run_bundle,
    write_run_manifest,
)


def _row(match_id: int, start_time: int, radiant_win: bool) -> MapRow:
    return MapRow(
        match_id=match_id,
        start_time=start_time,
        duration=100,
        radiant_win=radiant_win,
        league_id=1,
        tier="pro",
        radiant_team_id=10,
        dire_team_id=20,
        series_id=None,
        series_type=0,
        patch="x",
        radiant_accounts=(1, 2, 3, 4, 5),
        dire_accounts=(6, 7, 8, 9, 10),
        radiant_heroes=(1, 2, 3, 4, 5),
        dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False,
        has_bad_roster=False,
    )


def test_logical_store_digest_is_independent_of_insert_order(tmp_path):
    """Kills mutation: hash rows in unordered SQLite scan order.

    `reverse_unordered_selects` makes an omitted ORDER BY deterministically
    return the second connection's rows in the opposite order.
    """
    first = open_store(tmp_path / "first.sqlite")
    second = open_store(tmp_path / "second.sqlite")
    try:
        rows = [_row(2, 20, False), _row(1, 10, True)]
        insert_rows(first, rows)
        insert_rows(second, list(reversed(rows)))
        second.execute("pragma reverse_unordered_selects = on")

        assert logical_store_digest(first) == logical_store_digest(second)
    finally:
        first.close()
        second.close()


def test_logical_store_digest_changes_when_a_stored_value_changes(tmp_path):
    """Kills mutation: hash only match_id and omit other stored values."""
    original = open_store(tmp_path / "original.sqlite")
    changed = open_store(tmp_path / "changed.sqlite")
    try:
        insert_rows(original, [_row(1, 10, True)])
        insert_rows(changed, [_row(1, 10, False)])

        assert logical_store_digest(original)["sha256"] != logical_store_digest(changed)["sha256"]
    finally:
        original.close()
        changed.close()


def test_logical_store_digest_changes_when_live_schema_changes(tmp_path):
    """Kills mutation: hash source SCHEMA instead of the live SQLite schema."""
    conn = open_store(tmp_path / "store.sqlite")
    try:
        before = logical_store_digest(conn)
        conn.execute("alter table maps add column provenance_note text")

        assert logical_store_digest(conn)["sha256"] != before["sha256"]
    finally:
        conn.close()


def test_logical_store_digest_covers_partial_index_predicates(tmp_path):
    """Kills mutation: describe indexes with PRAGMA metadata but omit their DDL predicates."""
    first = open_store(tmp_path / "first.sqlite")
    second = open_store(tmp_path / "second.sqlite")
    try:
        first.execute("create index maps_duration_partial on maps(duration) where duration > 0")
        second.execute("create index maps_duration_partial on maps(duration) where duration > 1")

        assert logical_store_digest(first)["sha256"] != logical_store_digest(second)["sha256"]
    finally:
        first.close()
        second.close()


def test_logical_store_digest_covers_the_declared_store_schema(tmp_path, monkeypatch):
    """Kills mutation: omit the declared SCHEMA text from the digest header."""
    conn = open_store(tmp_path / "store.sqlite")
    try:
        before = logical_store_digest(conn)
        monkeypatch.setattr(provenance, "SCHEMA", provenance.SCHEMA + "\n-- schema revision")

        assert logical_store_digest(conn)["sha256"] != before["sha256"]
    finally:
        conn.close()


def test_logical_store_digest_rejects_an_open_transaction(tmp_path):
    """Kills mutation: identify rows visible only in an uncommitted transaction."""
    conn = open_store(tmp_path / "store.sqlite")
    try:
        insert_rows(conn, [_row(1, 10, True)])
        conn.execute("begin")
        conn.execute("update maps set radiant_win = 0 where match_id = 1")

        with pytest.raises(ValueError, match="transaction"):
            logical_store_digest(conn)
    finally:
        conn.rollback()
        conn.close()


def test_logical_store_digest_reads_schema_and_rows_from_one_snapshot(tmp_path):
    """Kills mutation: omit the digest's internal read transaction."""
    store = tmp_path / "store.sqlite"
    reader = open_store(store)
    writer = open_store(store)
    try:
        reader.execute("pragma journal_mode = wal").fetchone()
        insert_rows(reader, [_row(1, 10, True)])
        before = logical_store_digest(reader)
        committed = False

        def commit_after_schema_read(statement):
            nonlocal committed
            if not committed and "from maps order by match_id" in statement.lower():
                writer.execute("update maps set radiant_win = 0 where match_id = 1")
                writer.commit()
                committed = True

        reader.set_trace_callback(commit_after_schema_read)
        assert logical_store_digest(reader) == before
        assert committed
    finally:
        reader.set_trace_callback(None)
        reader.close()
        writer.close()


@pytest.mark.parametrize(
    ("column", "changes"),
    [
        ("match_id", {"match_id": 2}),
        ("start_time", {"start_time": 11}),
        ("duration", {"duration": 101}),
        ("radiant_win", {"radiant_win": False}),
        ("league_id", {"league_id": 2}),
        ("tier", {"tier": "amateur"}),
        ("radiant_team_id", {"radiant_team_id": 11}),
        ("dire_team_id", {"dire_team_id": 21}),
        ("series_id", {"series_id": 1}),
        ("series_type", {"series_type": 1}),
        ("patch", {"patch": "y"}),
        ("radiant_accounts", {"radiant_accounts": (11, 2, 3, 4, 5)}),
        ("dire_accounts", {"dire_accounts": (16, 7, 8, 9, 10)}),
        ("radiant_heroes", {"radiant_heroes": (11, 2, 3, 4, 5)}),
        ("dire_heroes", {"dire_heroes": (16, 7, 8, 9, 10)}),
        ("has_null_team", {"has_null_team": True}),
        ("has_bad_roster", {"has_bad_roster": True}),
    ],
    ids=STORE_COLUMNS,
)
def test_logical_store_digest_covers_every_stored_column(tmp_path, column, changes):
    """Kills mutation: hash only a partial prefix of STORE_COLUMNS."""
    original = open_store(tmp_path / f"original-{column}.sqlite")
    changed = open_store(tmp_path / f"changed-{column}.sqlite")
    try:
        base = _row(1, 10, True)
        insert_rows(original, [base])
        insert_rows(changed, [replace(base, **changes)])

        assert logical_store_digest(original)["sha256"] != logical_store_digest(changed)["sha256"]
    finally:
        original.close()
        changed.close()


def test_logical_store_digest_normalizes_json_array_whitespace(tmp_path):
    """Kills mutation: hash JSON-array text instead of decoded JSON arrays."""
    first = open_store(tmp_path / "first.sqlite")
    second = open_store(tmp_path / "second.sqlite")
    try:
        row = _row(1, 10, True)
        insert_rows(first, [row])
        insert_rows(second, [row])
        with second:
            second.execute(
                """update maps set radiant_accounts = ?, dire_accounts = ?,
                   radiant_heroes = ?, dire_heroes = ? where match_id = 1""",
                ("[1,2,3,4,5]", "[6,7,8,9,10]", "[1,2,3,4,5]", "[6,7,8,9,10]"),
            )

        assert logical_store_digest(first) == logical_store_digest(second)
    finally:
        first.close()
        second.close()


def test_logical_store_digest_result_has_the_declared_shape(tmp_path):
    """Kills mutation: return an unversioned, malformed digest result."""
    conn = open_store(tmp_path / "store.sqlite")
    try:
        insert_rows(conn, [_row(1, 10, True)])
        digest = logical_store_digest(conn)

        assert digest.keys() == {"algorithm", "schema_version", "row_count", "sha256"}
        assert digest["algorithm"] == "sha256"
        assert digest["schema_version"] == 1
        assert digest["row_count"] == 1
        assert re.fullmatch(r"[0-9a-f]{64}", digest["sha256"])
    finally:
        conn.close()


def test_canonical_json_bytes_matches_the_exact_vector():
    """Kills mutation: change JSON key order, separators, or ASCII escaping."""
    assert canonical_json_bytes({"z": "café", "a": [True, None, {"b": 1}]}) == (
        b'{"a":[true,null,{"b":1}],"z":"caf\\u00e9"}'
    )


def test_logical_store_digest_matches_the_known_complete_vector(tmp_path):
    """Kills mutation: replace SHA-256 with a different digest algorithm or padding."""
    conn = open_store(tmp_path / "store.sqlite")
    try:
        insert_rows(conn, [_row(1, 10, True)])

        assert logical_store_digest(conn)["sha256"] == (
            "8b38c0b8ef1e822d17ba11f55e3d49d8063b4b044c0ce4048a3ab3c5ca6324ad"
        )
    finally:
        conn.close()


def _descriptor(tmp_path):
    source = tmp_path / "input.yaml"
    source.write_text("seed: 1\n")
    return {
        "schema_version": 1,
        "run_kind": "example",
        "source_revision": "a" * 40,
        "invocation": {"argv": ["example", "--seed", "1"], "seeds": [1]},
        "snapshot": {
            "snapshot_id": "example",
            "manifest_path": "input.yaml",
            "manifest_sha256": sha256_file(source),
        },
        "store": {"algorithm": "sha256", "schema_version": 1, "row_count": 0, "sha256": "b" * 64},
        "inputs": [{"path": "input.yaml", "sha256": sha256_file(source)}],
        "runtime": {"python": "test"},
    }


def test_verify_run_bundle_rejects_a_bundle_built_at_another_revision(tmp_path):
    """Kills mutation: accept `against_revision` and never compare it.

    Every other check here is internal -- it proves a bundle still describes
    the bytes it was built from, which stays true forever no matter what the
    source tree does. A rating-model correction moved every published number
    while this function went on exiting 0 on the superseded bundle. Passing a
    revision has to be able to FAIL, or the argument is decoration.
    """
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    descriptor = _descriptor(tmp_path)
    (bundle / "report.md").write_text(f"{render_report_prefix(descriptor)}\nbody\n")
    write_run_manifest(bundle, descriptor, ["report.md"])

    assert verify_run_bundle(bundle, repo_root=tmp_path, against_revision="a" * 40)
    assert verify_run_bundle(bundle, repo_root=tmp_path)

    with pytest.raises(RunManifestError, match="does not describe this tree"):
        verify_run_bundle(bundle, repo_root=tmp_path, against_revision="c" * 40)


def test_verify_run_bundle_rejects_a_changed_report(tmp_path):
    """Kills mutation: skip SHA-256 validation for outputs ending in .md."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    descriptor = _descriptor(tmp_path)
    report = bundle / "report.md"
    report.write_text(f"{render_report_prefix(descriptor)}\noriginal\n")
    manifest_path = write_run_manifest(bundle, descriptor, ["report.md"])
    manifest = json.loads(manifest_path.read_text())
    report.write_text(f"<!-- ti26-run: {manifest['run_id']} manifest.json -->\ntampered\n")

    with pytest.raises(RunManifestError, match="report.md"):
        verify_run_bundle(bundle, repo_root=tmp_path)


def test_verify_run_bundle_rejects_a_report_with_the_wrong_run_reference(tmp_path):
    """Kills mutation: verify report hashes but never bind report text to manifest run_id."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "report.md").write_text("<!-- ti26-run: wrong manifest.json -->\nbody\n")
    write_run_manifest(bundle, _descriptor(tmp_path), ["report.md"])

    with pytest.raises(RunManifestError, match="run reference"):
        verify_run_bundle(bundle, repo_root=tmp_path)


def test_run_id_changes_when_invocation_input_changes(tmp_path):
    """Kills mutation: derive run_id from run_kind alone and ignore invocation metadata."""
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    first_descriptor = _descriptor(tmp_path)
    second_descriptor = _descriptor(tmp_path)
    (one / "report.md").write_text(f"{render_report_prefix(first_descriptor)}\n")
    second_descriptor["invocation"]["seeds"] = [2]
    (two / "report.md").write_text(f"{render_report_prefix(second_descriptor)}\n")
    first = write_run_manifest(one, first_descriptor, ["report.md"])
    second = write_run_manifest(two, second_descriptor, ["report.md"])

    assert json.loads(first.read_text())["run_id"] != json.loads(second.read_text())["run_id"]


def test_verify_run_bundle_rejects_a_changed_declared_input(tmp_path):
    """Kills mutation: validate outputs but not manifest-declared input digests."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    descriptor = _descriptor(tmp_path)
    (bundle / "report.md").write_text(f"{render_report_prefix(descriptor)}\nbody\n")
    write_run_manifest(bundle, descriptor, ["report.md"])
    (tmp_path / "input.yaml").write_text("seed: 2\n")

    with pytest.raises(RunManifestError, match="input.yaml"):
        verify_run_bundle(bundle, repo_root=tmp_path)


@pytest.mark.parametrize("path", ["../input.yaml", "/input.yaml"])
def test_verify_run_bundle_rejects_an_input_path_escape(tmp_path, path):
    """Kills mutation: resolve manifest input paths without containment validation."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    descriptor = _descriptor(tmp_path)
    source = tmp_path.parent / "input.yaml" if path.startswith("..") else tmp_path / "input.yaml"
    source.write_text("outside: true\n")
    descriptor["inputs"] = [
        {"path": path if path.startswith("..") else str(source), "sha256": sha256_file(source)}
    ]
    (bundle / "report.md").write_text(f"{render_report_prefix(descriptor)}\nbody\n")
    write_run_manifest(bundle, descriptor, ["report.md"])

    with pytest.raises(RunManifestError, match="path"):
        verify_run_bundle(bundle, repo_root=tmp_path)


def test_verify_run_bundle_rejects_a_symlinked_output(tmp_path):
    """Kills mutation: accept a declared output symlink within the bundle."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    descriptor = _descriptor(tmp_path)
    target = bundle / "report-target.md"
    target.write_text(f"{render_report_prefix(descriptor)}\nbody\n")
    (bundle / "report.md").symlink_to(target)

    with pytest.raises(RunManifestError, match="symlink"):
        write_run_manifest(bundle, descriptor, ["report.md"])


def _legacy_manifest(raw, sid, entries):
    """Write a pre-provenance manifest: no per-chunk query and no digest."""
    (raw / sid).mkdir(parents=True, exist_ok=True)
    (raw / sid / "manifest.json").write_text(
        json.dumps(
            {
                "snapshot_id": sid,
                "source": "opendota /explorer",
                "total_rows": sum(entry["rows"] for entry in entries),
                "entries": entries,
            },
            indent=2,
        )
        + "\n"
    )


def test_snapshot_manifest_command_hashes_the_committed_gzip_bytes(tmp_path):
    """Kills mutation: digest the decoded rows instead of the chunk file's bytes.

    The gzip container carries its own header and compression, so the digest of
    the chunk on disk is a different byte string from the digest of the rows it
    decodes to. Only the former identifies the committed input.
    """
    raw = tmp_path / "raw"
    sid = "20260802T165535Z"
    first = write_snapshot(raw, sid, "2025-02", [{"match_id": 1}, {"match_id": 2}])
    second = write_snapshot(raw, sid, "2025-03", [{"match_id": 3}])
    _legacy_manifest(
        raw,
        sid,
        [
            {"name": "2025-02", "rows": 2, "start": 10, "end": 20},
            {"name": "2025-03", "rows": 1, "start": 20, "end": 30},
        ],
    )

    exit_code = provenance_main(
        ["snapshot-manifest", "--raw", str(raw), "--snapshot", sid, "--replace-existing-manifest"]
    )

    assert exit_code == 0
    manifest = json.loads((raw / sid / "manifest.json").read_text())
    digests = {entry["name"]: entry["sha256"] for entry in manifest["entries"]}
    assert digests == {"2025-02": sha256_file(first), "2025-03": sha256_file(second)}
    assert (
        digests["2025-02"]
        != hashlib.sha256(canonical_json_bytes(read_snapshot(first))).hexdigest()
    )
    assert manifest["total_rows"] == 3
    assert [chunk.path for chunk in validate_snapshot(raw, sid)] == [first, second]


def test_snapshot_manifest_command_derives_the_query_from_the_committed_template(tmp_path):
    """Kills mutation: write one constant query instead of MAP_QUERY.format(start, end)."""
    raw = tmp_path / "raw"
    sid = "20260802T165535Z"
    write_snapshot(raw, sid, "2025-02", [{"match_id": 1}])
    write_snapshot(raw, sid, "2025-03", [{"match_id": 2}])
    _legacy_manifest(
        raw,
        sid,
        [
            {"name": "2025-02", "rows": 1, "start": 10, "end": 20},
            {"name": "2025-03", "rows": 1, "start": 20, "end": 30},
        ],
    )

    provenance_main(
        ["snapshot-manifest", "--raw", str(raw), "--snapshot", sid, "--replace-existing-manifest"]
    )

    entries = json.loads((raw / sid / "manifest.json").read_text())["entries"]
    queries = {entry["name"]: entry["query"] for entry in entries}
    assert queries["2025-02"] == MAP_QUERY.format(start=10, end=20)
    assert queries["2025-03"] == MAP_QUERY.format(start=20, end=30)
    assert queries["2025-02"] != queries["2025-03"]


def test_snapshot_manifest_command_derives_retrieved_at_from_the_snapshot_id(tmp_path):
    """Kills mutation: stamp the current time instead of parsing the snapshot identifier.

    A wall-clock stamp would make the regenerated manifest differ on every run,
    so the pinned input could never be reproduced byte-for-byte.
    """
    raw = tmp_path / "raw"
    sid = "20260802T165535Z"
    write_snapshot(raw, sid, "2025-02", [{"match_id": 1}])
    _legacy_manifest(raw, sid, [{"name": "2025-02", "rows": 1, "start": 10, "end": 20}])

    provenance_main(
        ["snapshot-manifest", "--raw", str(raw), "--snapshot", sid, "--replace-existing-manifest"]
    )

    manifest = json.loads((raw / sid / "manifest.json").read_text())
    assert manifest["retrieved_at"] == "2026-08-02T16:55:35Z"


def test_snapshot_manifest_command_refuses_to_replace_without_the_explicit_flag(tmp_path):
    """Kills mutation: overwrite an existing manifest whether or not the flag was supplied."""
    raw = tmp_path / "raw"
    sid = "20260802T165535Z"
    write_snapshot(raw, sid, "2025-02", [{"match_id": 1}])
    _legacy_manifest(raw, sid, [{"name": "2025-02", "rows": 1, "start": 10, "end": 20}])
    before = (raw / sid / "manifest.json").read_bytes()

    with pytest.raises(SnapshotIntegrityError, match="replace-existing-manifest"):
        provenance_main(["snapshot-manifest", "--raw", str(raw), "--snapshot", sid])

    assert (raw / sid / "manifest.json").read_bytes() == before


def _card(assignments, team_ids, objective=4.0):
    return {
        "assignments": assignments,
        "team_ids": team_ids,
        "optimizer_marginal_objective": objective,
    }


def test_card_diff_keys_on_team_id_so_a_rebrand_is_not_reported_as_a_move():
    """Kills mutation: diff the cards on display name instead of team id.

    Four of the sixteen TI 2026 entrants rebranded between the qualifier and the
    field confirmation. A name-keyed diff reports a renamed team as gone from
    one card and new in the other -- two spurious differences per rebrand -- at
    the moment the operator is deciding whether a fallback card is materially
    different from the one they meant to ship.
    """
    before = _card({"PARIVISION": "4-0", "BetBoom": "0-4"}, {"PARIVISION": "1", "BetBoom": "2"})
    after = _card({"Team Vision": "4-0", "BoomBoys": "0-4"}, {"Team Vision": "1", "BoomBoys": "2"})

    result = card_diff(before, after)

    assert result["teams_compared"] == 2
    assert result["assignments_moved"] == 0
    assert result["only_in_a"] == [] and result["only_in_b"] == []
    assert result["renamed_without_moving"] == 2


def test_card_diff_reports_a_real_move_with_both_slots_and_the_team_id():
    """Kills mutation: count the moves but drop which slots they moved between.

    A bare count cannot be acted on. The operator has to see that a team went
    from `4-1` to `elim_win` to judge whether the fallback card is a different
    forecast or a rounding difference, and the team id is what lets them check
    it against the configured field rather than against a display name.
    """
    ids = {"A": "1", "B": "2"}
    result = card_diff(
        _card({"A": "4-0", "B": "0-4"}, ids), _card({"A": "elim_win", "B": "0-4"}, ids)
    )

    assert result["assignments_moved"] == 1
    assert result["moved"] == [
        {
            "team_id": "1",
            "name_a": "A",
            "name_b": "A",
            "renamed": False,
            "slot_a": "4-0",
            "slot_b": "elim_win",
        }
    ]


def test_card_diff_refuses_to_present_the_two_objectives_as_comparable():
    """Kills mutation: drop the note, or emit a delta between the objectives.

    Each objective is the optimiser's expected score under its OWN marginals, so
    a more extreme strength vector scores higher whether or not it is more
    accurate -- a confidently wrong card beats a cautious one. Emitting
    `objective_b - objective_a` would manufacture exactly the comparison this
    number cannot support, and the rung-3 fallback scores the higher of the two.
    """
    ids = {"A": "1"}
    result = card_diff(_card({"A": "4-0"}, ids, 4.59), _card({"A": "4-0"}, ids, 6.62))

    assert result["objective_a"] == 4.59
    assert result["objective_b"] == 6.62
    assert "NOT comparable" in result["objective_note"]
    assert not any("delta" in key or "improvement" in key for key in result)


def test_card_diff_reports_a_team_present_in_only_one_card():
    """Kills mutation: intersect silently and report only the shared teams.

    A substitution in the field changes which sixteen team ids exist. Comparing
    only the intersection would show a small, reassuring difference while hiding
    that the two cards are not about the same tournament.
    """
    result = card_diff(
        _card({"A": "4-0", "B": "0-4"}, {"A": "1", "B": "2"}),
        _card({"A": "4-0", "C": "0-4"}, {"A": "1", "C": "3"}),
    )

    assert result["teams_compared"] == 1
    assert result["only_in_a"] == ["2"]
    assert result["only_in_b"] == ["3"]


def test_snapshot_manifest_command_rejects_a_row_count_the_chunks_contradict(tmp_path):
    """Kills mutation: recount rows from the decoded chunk instead of carrying the prior count.

    The prior manifest's row counts are the only independent record of what was
    fetched. Recounting them from the chunk would make the check self-satisfying.
    """
    raw = tmp_path / "raw"
    sid = "20260802T165535Z"
    write_snapshot(raw, sid, "2025-02", [{"match_id": 1}, {"match_id": 2}])
    _legacy_manifest(raw, sid, [{"name": "2025-02", "rows": 9, "start": 10, "end": 20}])

    with pytest.raises(SnapshotIntegrityError, match="row count"):
        provenance_main(
            [
                "snapshot-manifest",
                "--raw",
                str(raw),
                "--snapshot",
                sid,
                "--replace-existing-manifest",
            ]
        )
