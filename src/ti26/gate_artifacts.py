"""Frozen gate results as a versioned artifact, so reports stop copying them.

Every card report used to restate D2's, D3's and D3b's metrics from string
literals pasted into `cli_card`. Those literals were true when written and had
no way of staying true: nothing recomputed them, nothing checked them, and a
re-ingest that moved a gate's numbers would have left the card report quoting
the old ones indefinitely.

The gate CLIs now serialise the result objects they already computed. This
module validates those files and combines them into one artifact that the card
report reads. It performs no gate evaluation of its own and holds no threshold:
a gate's verdict is whatever its own registered, unchanged computation returned.
"""

import json
from pathlib import Path
from typing import Any

GATE_RESULT_SCHEMA = "ti26.gate-result.v1"
GATE_ARTIFACT_SCHEMA = "ti26.frozen-gates.v1"
EXPECTED_GATES = frozenset({"d2", "d3", "d3b"})


def gate_result_payload(
    *,
    gate: str,
    verdict: str,
    exit_code: int,
    registration: str,
    conditions: dict[str, dict[str, Any]],
    method: str,
    n_maps: int,
    excluded: dict[str, int],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build one gate's machine-readable result from values it already computed.

    `conditions` carries each registered condition's measured value, the
    threshold it was tested against, and whether it passed -- so a reader can
    see the test, not just its verdict.
    """
    return {
        "schema": GATE_RESULT_SCHEMA,
        "gate": gate,
        "verdict": verdict,
        "exit_code": exit_code,
        "registration": registration,
        "conditions": conditions,
        "method": method,
        "n_maps": n_maps,
        "excluded": excluded,
        "config": config,
    }


def write_gate_result(path: Path, payload: dict[str, Any]) -> None:
    if payload.get("schema") != GATE_RESULT_SCHEMA:
        raise ValueError(f"refusing to write a gate result with schema {payload.get('schema')!r}")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _validate_gate_result(result: object, expected_gate: str) -> dict[str, Any]:
    if not isinstance(result, dict):
        # Validating untrusted JSON: a malformed document is bad data
        # (ValueError), not a caller type error.
        raise ValueError(  # noqa: TRY004
            f"{expected_gate} gate result must be a JSON object"
        )
    if result.get("schema") != GATE_RESULT_SCHEMA:
        raise ValueError(f"{expected_gate} gate result has an unexpected schema")
    if result.get("gate") != expected_gate:
        raise ValueError(
            f"expected a {expected_gate} gate result, found {result.get('gate')!r}"
        )
    if result.get("verdict") not in {"PASS", "FAIL"}:
        raise ValueError(f"{expected_gate} verdict must be PASS or FAIL")
    # A PASS that exited non-zero, or a FAIL that exited zero, means the report
    # and the process disagreed about what happened. Refuse to combine either.
    if (result["verdict"] == "PASS") != (result.get("exit_code") == 0):
        raise ValueError(f"{expected_gate} verdict and exit_code disagree")
    conditions = result.get("conditions")
    if not isinstance(conditions, dict) or not conditions:
        raise ValueError(f"{expected_gate} gate result has no conditions")
    for name, condition in conditions.items():
        if not isinstance(condition, dict) or "value" not in condition:
            raise ValueError(f"{expected_gate} condition {name!r} has no measured value")
        if not isinstance(condition.get("passed"), bool):
            raise ValueError(  # noqa: TRY004 -- malformed input data, not a caller type error
                f"{expected_gate} condition {name!r} has no pass/fail flag"
            )
    return result


def write_frozen_gate_artifact(
    paths: dict[str, Path], destination: Path, *, source_revision: str
) -> dict[str, Any]:
    """Validate the three registered gate results and combine them."""
    if set(paths) != EXPECTED_GATES:
        raise ValueError(
            f"expected results for {sorted(EXPECTED_GATES)}, got {sorted(paths)}"
        )
    if not isinstance(source_revision, str) or len(source_revision) != 40:
        raise ValueError("source_revision must be a 40-character Git SHA")
    gates = {
        name: _validate_gate_result(json.loads(Path(path).read_text()), name)
        for name, path in sorted(paths.items())
    }
    artifact = {
        "schema": GATE_ARTIFACT_SCHEMA,
        "source_revision": source_revision,
        "gates": gates,
    }
    Path(destination).write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    return artifact


def load_frozen_gate_artifact(path: str | Path) -> dict[str, Any]:
    """Reject a missing, wrong-schema, incomplete or inconsistent artifact."""
    try:
        artifact = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable frozen gate artifact: {path}") from exc
    if not isinstance(artifact, dict) or artifact.get("schema") != GATE_ARTIFACT_SCHEMA:
        raise ValueError(f"unexpected frozen gate artifact schema: {path}")
    gates = artifact.get("gates")
    if not isinstance(gates, dict) or set(gates) != EXPECTED_GATES:
        raise ValueError(f"frozen gate artifact must carry {sorted(EXPECTED_GATES)}")
    for name in sorted(EXPECTED_GATES):
        _validate_gate_result(gates[name], name)
    return artifact


def _format_condition(name: str, condition: dict[str, Any]) -> str:
    value = condition["value"]
    rendered = (
        "[" + ", ".join(f"{v:.5f}" for v in value) + "]"
        if isinstance(value, list)
        else f"{value:.5f}"
    )
    against = ""
    if "threshold" in condition:
        against = f" against {condition['threshold']}"
    elif "band" in condition:
        against = f" against band {condition['band']}"
    elif "excludes" in condition:
        against = f", must exclude {condition['excludes']}"
    flag = "PASS" if condition["passed"] else "FAIL"
    return f"{name} {rendered}{against}: {flag}"


def format_gate_lineage(artifact: dict[str, Any]) -> list[str]:
    """Render the gate lineage entirely from the artifact's own fields.

    Nothing here is written by hand. If a gate's numbers change, the next
    artifact changes and so does every report that reads it.
    """
    lines = []
    for name in ("d2", "d3", "d3b"):
        gate = artifact["gates"][name]
        conditions = "; ".join(
            _format_condition(condition_name, condition)
            for condition_name, condition in sorted(gate["conditions"].items())
        )
        lines.append(
            f"- **{name.upper()} {gate['verdict']}** ({conditions}). "
            f"Maps compared: {gate['n_maps']}, interval method: {gate['method']}. "
            f"Registered: {gate['registration']}."
        )
    return lines
