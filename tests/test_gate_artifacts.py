import json

import pytest

from ti26.gate_artifacts import (
    GATE_ARTIFACT_SCHEMA,
    format_gate_lineage,
    gate_result_payload,
    load_frozen_gate_artifact,
    write_frozen_gate_artifact,
    write_gate_result,
)

REVISION = "a" * 40


def _payload(gate: str, *, verdict: str = "FAIL", slope: float = 0.5) -> dict:
    """One gate result built through the public constructor, never by hand."""
    return gate_result_payload(
        gate=gate,
        verdict=verdict,
        exit_code=0 if verdict == "PASS" else 1,
        registration=f"spec section {gate}",
        conditions={
            "margin": {"value": 0.00671, "threshold": 0.003, "passed": True},
            "ci": {"value": [0.0023, 0.01301], "excludes": 0.0, "passed": True},
            "slope": {"value": slope, "band": [0.9, 1.1], "passed": verdict == "PASS"},
        },
        method="clustered bootstrap",
        n_maps=26830,
        excluded={"unrated": 3},
        config={"bootstrap_ci": 0.975},
    )


def _result_files(tmp_path, **overrides) -> dict:
    paths = {}
    for gate in ("d2", "d3", "d3b"):
        path = tmp_path / f"{gate}_gate.json"
        write_gate_result(path, overrides.get(gate) or _payload(gate))
        paths[gate] = path
    return paths


def test_combined_artifact_rejects_a_verdict_that_disagrees_with_its_exit_code(tmp_path):
    """Kills mutation: accept a result whose verdict and exit_code disagree.

    A FAIL that exited zero means the report and the process said different
    things about the same run. Combining it would publish whichever the reader
    happened to look at.
    """
    paths = _result_files(tmp_path)
    payload = json.loads(paths["d3"].read_text())
    payload["exit_code"] = 0
    paths["d3"].write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="exit_code"):
        write_frozen_gate_artifact(
            paths, tmp_path / "frozen.json", source_revision=REVISION
        )


def test_combined_artifact_requires_every_registered_gate(tmp_path):
    """Kills mutation: combine whichever gate results were supplied.

    Silently omitting D3b would produce a lineage that reads as complete while
    leaving out the only gate that passed.
    """
    paths = _result_files(tmp_path)
    del paths["d3b"]

    with pytest.raises(ValueError, match="d3b"):
        write_frozen_gate_artifact(
            paths, tmp_path / "frozen.json", source_revision=REVISION
        )


def test_combined_artifact_rejects_a_result_filed_under_the_wrong_gate(tmp_path):
    """Kills mutation: trust the filename instead of the result's own gate field."""
    paths = _result_files(tmp_path)
    paths["d3b"].write_text(json.dumps(_payload("d3")))

    with pytest.raises(ValueError, match="d3b"):
        write_frozen_gate_artifact(
            paths, tmp_path / "frozen.json", source_revision=REVISION
        )


def test_loading_rejects_a_condition_with_no_pass_flag(tmp_path):
    """Kills mutation: accept a condition carrying a value but no pass/fail flag.

    A condition without its flag renders as a measurement with no test, which
    is exactly the shape the frozen gates must not degrade into.
    """
    destination = tmp_path / "frozen.json"
    write_frozen_gate_artifact(_result_files(tmp_path), destination, source_revision=REVISION)
    artifact = json.loads(destination.read_text())
    del artifact["gates"]["d2"]["conditions"]["slope"]["passed"]
    destination.write_text(json.dumps(artifact))

    with pytest.raises(ValueError, match="pass/fail"):
        load_frozen_gate_artifact(destination)


def test_lineage_is_rendered_from_the_artifact_not_from_a_literal(tmp_path):
    """Kills mutation: return a fixed lineage string instead of reading the artifact.

    The slope below is a value no real run produced. If it does not appear in
    the rendered lineage, the renderer is not reading its input.
    """
    destination = tmp_path / "frozen.json"
    write_frozen_gate_artifact(
        _result_files(tmp_path, d3b=_payload("d3b", verdict="PASS", slope=0.98765)),
        destination,
        source_revision=REVISION,
    )

    lines = format_gate_lineage(load_frozen_gate_artifact(destination))

    assert len(lines) == 3
    assert any("0.98765" in line for line in lines), lines
    assert any("D3B PASS" in line for line in lines), lines
    assert any("D2 FAIL" in line for line in lines), lines
    assert not any("0.9049" in line for line in lines), (
        "the historical literal must not survive anywhere in the renderer"
    )


def test_artifact_round_trips_through_its_own_schema(tmp_path):
    destination = tmp_path / "frozen.json"
    written = write_frozen_gate_artifact(
        _result_files(tmp_path), destination, source_revision=REVISION
    )
    assert written["schema"] == GATE_ARTIFACT_SCHEMA
    assert load_frozen_gate_artifact(destination) == written
