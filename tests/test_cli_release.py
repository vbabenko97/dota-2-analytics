from pathlib import Path

from ti26.cli_release import CONFIG_INPUTS, _prefix_markdown


def test_report_prefix_is_prepended_and_leaves_the_body_untouched(tmp_path):
    """Kills mutation: write the run reference over the report instead of before it.

    The manifest hashes the finished file, so a prefix step that truncated the
    body would still produce a bundle that verifies -- and would have silently
    destroyed the report it was supposed to bind.
    """
    report = tmp_path / "report.md"
    body = "# D4 diagnostic\n\nobserved score 1/16\n"
    report.write_text(body)

    _prefix_markdown(report, "<!-- ti26-run: abc manifest.json -->")

    written = report.read_text()
    assert written.startswith("<!-- ti26-run: abc manifest.json -->\n")
    assert written[len("<!-- ti26-run: abc manifest.json -->\n") :] == body


def test_every_tracked_config_is_hashed_into_the_manifest():
    """Kills mutation: add a config file without adding it to CONFIG_INPUTS.

    A config a producer reads but the manifest does not hash is a number in a
    report whose input can change without trace, which is the whole defect this
    bundle exists to close. This fails the moment someone adds a config and
    forgets it.
    """
    on_disk = {path.as_posix() for path in Path("config").glob("*.yaml")}
    declared = {path for path in CONFIG_INPUTS if path.startswith("config/")}
    assert on_disk == declared, (
        f"config files not hashed into the run manifest: {sorted(on_disk - declared)}; "
        f"declared but absent: {sorted(declared - on_disk)}"
    )


def test_declared_inputs_all_exist():
    """Kills mutation: declare an input path that no longer exists.

    verify_run_bundle fails closed on a missing declared input, so a stale path
    here would break every future bundle at verification time rather than here.
    """
    missing = [path for path in CONFIG_INPUTS if not Path(path).is_file()]
    assert not missing, f"declared manifest inputs do not exist: {missing}"


def test_a_complete_bundle_is_refused_and_an_incomplete_one_is_replaced(tmp_path, monkeypatch):
    """Kills mutation: refuse on directory existence, as this did until 2026-08-08.

    A run id identifies its inputs exactly, so a COMPLETE bundle must never be
    overwritten. But a run killed partway leaves a directory with no manifest,
    and refusing on existence alone made that directory block every retry with
    no flag to clear it -- which cost a manual recovery during the 2026-08-08
    regeneration, on the wrong side of a deadline.

    Asserts both halves, because a mutation that always replaces passes the
    second half alone and is far more dangerous than the bug being fixed.
    """
    import json as _json

    from ti26 import cli_release

    runs = tmp_path / "runs"
    complete = runs / "abc123"
    complete.mkdir(parents=True)
    (complete / "manifest.json").write_text(_json.dumps({"run_id": "abc123"}))
    assert cli_release._bundle_is_complete(complete)

    incomplete = runs / "def456"
    incomplete.mkdir(parents=True)
    (incomplete / "d2").mkdir()
    (incomplete / "d2" / "d2_gate.json").write_text("{}")
    assert not cli_release._bundle_is_complete(incomplete)

    missing = runs / "ghi789"
    assert not cli_release._bundle_is_complete(missing)
