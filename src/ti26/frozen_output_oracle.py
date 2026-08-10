from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ti26.gate_artifacts import load_frozen_gate_artifact
from ti26.provenance import verify_run_bundle_at_source_revision

BASELINE_ROOT = Path("reports/runs/frozen-output-oracle-baseline")
BASELINE_RUN_KIND = "ti2026-frozen-output-oracle-baseline"
_GATE_OUTPUTS = {
    gate: f"{gate}/{gate}_gate.json" for gate in ("d2", "d3", "d3b")
}
_FROZEN_GATES_OUTPUT = "frozen_gate_results.json"
_CARD_OUTPUT = "card/recommended_card.json"


class FrozenOutputOracleError(ValueError):
    """A bundle cannot substantiate or match the frozen predictive output."""


@dataclass(frozen=True)
class FrozenOutput:
    gates: dict[str, dict[str, object]]
    card: dict[str, object]


@dataclass(frozen=True)
class FrozenBaselineInvocation:
    snapshot_id: str
    release_args: tuple[str, ...]


def registered_baseline_bundle(*, repo_root: Path) -> Path:
    root = repo_root / BASELINE_ROOT
    try:
        children = sorted(root.iterdir())
    except OSError as exc:
        raise FrozenOutputOracleError(
            f"cannot read baseline registration root: {root}"
        ) from exc
    if (
        len(children) != 1
        or children[0].is_symlink()
        or not children[0].is_dir()
    ):
        raise FrozenOutputOracleError(
            "baseline registration requires exactly one child bundle"
        )
    bundle = children[0]
    try:
        manifest = verify_run_bundle_at_source_revision(
            bundle, repo_root=repo_root
        )
    except ValueError as exc:
        raise FrozenOutputOracleError(f"invalid registered baseline: {bundle}") from exc
    if manifest["run_kind"] != BASELINE_RUN_KIND:
        raise FrozenOutputOracleError("registered baseline has the wrong run_kind")
    if manifest["run_id"] != bundle.name:
        raise FrozenOutputOracleError("registered baseline directory is not its run_id")
    return bundle


def registered_baseline_invocation(
    *, repo_root: Path
) -> FrozenBaselineInvocation:
    bundle = registered_baseline_bundle(repo_root=repo_root)
    manifest = verify_run_bundle_at_source_revision(bundle, repo_root=repo_root)
    snapshot = manifest.get("snapshot")
    invocation = manifest.get("invocation")
    if not isinstance(snapshot, dict) or not isinstance(invocation, dict):
        raise FrozenOutputOracleError("baseline invocation metadata is invalid")
    snapshot_id = snapshot.get("snapshot_id")
    manifest_path = snapshot.get("manifest_path")
    if not isinstance(snapshot_id, str) or not isinstance(manifest_path, str):
        raise FrozenOutputOracleError("baseline snapshot metadata is invalid")
    snapshot_manifest = PurePosixPath(manifest_path)
    if (
        snapshot_manifest.name != "manifest.json"
        or snapshot_manifest.parent.name != snapshot_id
    ):
        raise FrozenOutputOracleError("baseline snapshot path is inconsistent")
    release_args = [
        "--snapshot", snapshot_id,
        "--raw", snapshot_manifest.parent.parent.as_posix(),
    ]
    for option, key in (
        ("--card-sims", "card_sims"),
        ("--card-seed", "card_seed"),
        ("--min-train", "min_train"),
        ("--sweep-sims", "sweep_sims"),
        ("--sweep-seeds", "sweep_seeds"),
        ("--random-samples", "random_samples"),
        ("--random-seed", "random_seed"),
    ):
        value = invocation.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise FrozenOutputOracleError(
                f"baseline invocation value is invalid: {key}"
            )
        release_args.extend((option, str(value)))
    producers = invocation.get("producers")
    if not isinstance(producers, list):
        raise FrozenOutputOracleError("baseline producer invocation is invalid")
    card_commands = [
        command
        for command in producers
        if isinstance(command, list) and command and command[0] == "ti26.cli_card"
    ]
    if len(card_commands) != 1:
        raise FrozenOutputOracleError("baseline card invocation is invalid")
    card_command = card_commands[0]
    group_positions = [
        index for index, value in enumerate(card_command) if value == "--groups"
    ]
    if group_positions:
        if len(group_positions) != 1 or group_positions[0] + 1 >= len(card_command):
            raise FrozenOutputOracleError("baseline group invocation is invalid")
        group_path = card_command[group_positions[0] + 1]
        if not isinstance(group_path, str):
            raise FrozenOutputOracleError("baseline group path is invalid")
        release_args.extend(("--groups", group_path))
    return FrozenBaselineInvocation(snapshot_id, tuple(release_args))


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrozenOutputOracleError(f"unreadable oracle JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FrozenOutputOracleError(f"oracle JSON object required: {path}")
    return value


def _staged_root(staging: Path) -> Path:
    try:
        if staging.is_symlink() or not staging.is_dir():
            raise FrozenOutputOracleError(
                "staged output must be a directory, not a symlink"
            )
        return staging.resolve(strict=True)
    except OSError as exc:
        raise FrozenOutputOracleError(f"invalid staged output: {staging}") from exc


def _required_staged_files(staging: Path) -> tuple[Path, dict[str, Path]]:
    root = _staged_root(staging)
    paths: dict[str, Path] = {}
    required = {*_GATE_OUTPUTS.values(), _FROZEN_GATES_OUTPUT, _CARD_OUTPUT}
    for relative in sorted(required):
        path = root
        for part in PurePosixPath(relative).parts:
            path /= part
            if path.is_symlink():
                raise FrozenOutputOracleError(
                    f"staged oracle path must not use a symlink: {relative}"
                )
        if not path.is_file():
            raise FrozenOutputOracleError(
                f"staged oracle requires a regular file: {relative}"
            )
        paths[relative] = path
    return root, paths


def load_staged_frozen_output(staging: Path) -> FrozenOutput:
    """Validate internal output agreement without asserting provenance."""
    _, paths = _required_staged_files(staging)
    try:
        artifact = load_frozen_gate_artifact(paths[_FROZEN_GATES_OUTPUT])
    except ValueError as exc:
        raise FrozenOutputOracleError(
            f"invalid frozen gate artifact: {paths[_FROZEN_GATES_OUTPUT]}"
        ) from exc
    gates = artifact["gates"]
    for gate, output in _GATE_OUTPUTS.items():
        if _load_json_object(paths[output]) != gates[gate]:
            raise FrozenOutputOracleError(
                f"frozen gate artifact disagrees with {output}"
            )
    return FrozenOutput(
        gates=gates,
        card=_load_json_object(paths[_CARD_OUTPUT]),
    )


def load_frozen_output(bundle: Path, *, repo_root: Path) -> FrozenOutput:
    try:
        manifest = verify_run_bundle_at_source_revision(bundle, repo_root=repo_root)
    except ValueError as exc:
        raise FrozenOutputOracleError(f"invalid oracle bundle: {bundle}") from exc
    declared = {entry["path"] for entry in manifest["outputs"]}
    required = {*_GATE_OUTPUTS.values(), _FROZEN_GATES_OUTPUT, _CARD_OUTPUT}
    missing = sorted(required - declared)
    if missing:
        raise FrozenOutputOracleError(f"bundle lacks oracle output(s): {missing}")
    return load_staged_frozen_output(bundle)


def load_current_baseline(*, repo_root: Path) -> FrozenOutput:
    return load_frozen_output(
        registered_baseline_bundle(repo_root=repo_root), repo_root=repo_root
    )
