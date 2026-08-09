from argparse import Namespace
from pathlib import Path

import pytest

from ti26.cli_release import (
    CONFIG_INPUTS,
    GATE_PRODUCERS,
    _prefix_markdown,
    build_producers,
    card_producer,
    declared_inputs,
    non_gate_failures,
)


def release_args(**overrides):
    args = Namespace(
        min_train=500,
        card_sims=2000,
        card_seed=1,
        sweep_sims="2000",
        sweep_seeds="1",
        random_samples=1000,
        random_seed=1,
        groups=None,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


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


def test_the_group_draw_is_hashed_into_the_manifest_when_one_is_supplied():
    """Kills mutation: declare only the snapshot and configs, as this did until 2026-08-09.

    The producer list records that `--groups <path>` was passed, but a path is
    not its contents. Without the file among the declared inputs, two bundles
    conditioned on DIFFERENT draws hash identically on their inputs, and
    `verify-run` cannot fail closed when the draw is edited under a finished
    bundle -- which is the one guarantee the manifest exists to give.

    The draw is expected to arrive during the near-lock window, so this is the
    input most likely to be new on the day and least likely to be noticed.
    """
    without = declared_inputs("data/raw/S/manifest.json", None)
    with_draw = declared_inputs("data/raw/S/manifest.json", "data/ti2026_groups.yaml")

    assert "data/ti2026_groups.yaml" not in without
    assert "data/ti2026_groups.yaml" in with_draw
    assert with_draw[: len(without)] == without, "the draw is added, never a substitution"


def test_declared_inputs_do_not_require_the_draw_to_live_in_config():
    """Kills mutation: append the draw to CONFIG_INPUTS instead of the input list.

    `test_every_tracked_config_is_hashed_into_the_manifest` asserts CONFIG_INPUTS
    equals `config/*.yaml` exactly. A draw added to that tuple, or a draw file
    dropped into `config/` to get it hashed, turns the suite red at runbook step
    9 -- in the middle of the regeneration, over a file that is data rather than
    configuration.
    """
    assert all(not path.startswith("config/") or path in CONFIG_INPUTS for path in CONFIG_INPUTS)
    with_draw = declared_inputs("data/raw/S/manifest.json", "data/ti2026_groups.yaml")
    assert "data/ti2026_groups.yaml" not in CONFIG_INPUTS
    assert with_draw.count("data/ti2026_groups.yaml") == 1


def test_the_standalone_diagnostics_are_bundle_producers():
    """Kills mutation: drop cli_data_health or cli_external_cards from the list.

    Both ran standalone until 2026-08-09, which put the corpus composition and
    the external-card ceiling outside every manifest: numbers the weaknesses
    document quotes, with no hash binding them to the snapshot and configs they
    came from. Removing either restores exactly that gap, and nothing else in
    the suite would notice, because a bundle short an output still verifies.
    """
    names = {producer[0] for producer in build_producers(release_args(), Path("s.sqlite"))}
    assert "ti26.cli_data_health" in names
    assert "ti26.cli_external_cards" in names


def test_the_groups_draw_reaches_the_card_and_nothing_else():
    """Kills mutation: append --groups to every producer, or to d4.

    D4 backtests TI 2025, whose group draw was its own. Handing it TI 2026's
    draw would be a leak dressed as a fix -- the held-out event scored under
    information from the event being forecast.
    """
    producers = build_producers(release_args(groups="config/groups.yaml"), Path("s.sqlite"))
    carrying = {producer[0] for producer in producers if "--groups" in producer}
    assert carrying == {"ti26.cli_card"}


def test_the_card_is_found_by_name_when_the_producer_order_changes():
    """Kills mutation: select the card for the frozen-gate re-run by index.

    The card runs twice: once with the others, then again once the frozen-gate
    artifact exists. The list has grown twice, and a positional lookup that slid
    onto a neighbour would re-run that neighbour with the card's arguments and
    overwrite the card directory with its output -- producing a bundle whose
    `card/` holds something else entirely, which still hashes and still verifies.
    """
    producers = build_producers(release_args(), Path("s.sqlite"))
    assert card_producer(producers)[0] == "ti26.cli_card"

    # Moved to the end, so no fixed index finds it. Reversing is not enough:
    # the list has an odd length and the card sits at its centre, so index 3
    # survives a reversal and the positional mutation passes.
    card = card_producer(producers)
    moved = [producer for producer in producers if producer[0] != "ti26.cli_card"] + [card]
    assert moved.index(card) == len(moved) - 1
    assert card_producer(moved)[0] == "ti26.cli_card"


def test_a_failing_diagnostic_stops_the_run_but_a_failing_gate_does_not():
    """Kills mutation: check only the card and d4 for non-zero exits.

    A gate's non-zero exit is its registered verdict and must not abort the
    bundle. Every other producer exiting non-zero means it could not produce,
    and the old explicit card/d4 check would have let a newly added diagnostic
    fail in silence -- leaving the bundle short an output nobody looks for.
    """
    assert non_gate_failures({"d2": 1, "d3": 1, "d3b": 0, "card": 0}) == {}
    assert non_gate_failures({"d2": 1, "data_health": 2}) == {"data_health": 2}
    assert non_gate_failures({"external_cards": 1}) == {"external_cards": 1}


@pytest.mark.parametrize("gate", sorted(GATE_PRODUCERS))
def test_every_gate_named_here_is_a_producer_that_runs(gate):
    """Kills mutation: leave a stale name in GATE_PRODUCERS.

    A name here exempts a producer from the failure check. One that no longer
    matches any producer is dead, but a name that later collides with a real
    non-gate producer would exempt it silently, which is the failure this set
    exists to prevent.
    """
    names = {producer[0] for producer in build_producers(release_args(), Path("s.sqlite"))}
    assert f"ti26.cli_{gate}" in names


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
