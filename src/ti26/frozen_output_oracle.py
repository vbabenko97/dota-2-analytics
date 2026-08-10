from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ti26.gate_artifacts import load_frozen_gate_artifact
from ti26.provenance import verify_run_bundle, verify_run_bundle_at_source_revision

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


def assignment_slots_by_team_id(card: dict[str, object]) -> dict[str, str]:
    assignments = card.get("assignments")
    team_ids = card.get("team_ids")
    if not isinstance(assignments, dict) or not isinstance(team_ids, dict):
        raise FrozenOutputOracleError(
            "card requires assignments and configured team_ids objects"
        )
    if set(assignments) != set(team_ids):
        raise FrozenOutputOracleError("card assignment and team_id names disagree")
    slots: dict[str, str] = {}
    for name, category in assignments.items():
        team_id = team_ids[name]
        if (
            not isinstance(team_id, str)
            or not team_id
            or not isinstance(category, str)
            or not category
        ):
            raise FrozenOutputOracleError("card assignment identity is invalid")
        if team_id in slots:
            raise FrozenOutputOracleError(f"duplicate card team_id: {team_id}")
        slots[team_id] = category
    return slots


def _card_without_assignments(card: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in card.items()
        if key not in {"assignments", "team_ids"}
    }


def assert_matches_frozen_output(
    baseline: FrozenOutput, candidate: FrozenOutput
) -> None:
    for gate in ("d2", "d3", "d3b"):
        if candidate.gates.get(gate) != baseline.gates.get(gate):
            raise FrozenOutputOracleError(f"frozen gate output changed: {gate}")
    baseline_slots = assignment_slots_by_team_id(baseline.card)
    candidate_slots = assignment_slots_by_team_id(candidate.card)
    if _card_without_assignments(candidate.card) != _card_without_assignments(
        baseline.card
    ):
        raise FrozenOutputOracleError("frozen card non-assignment JSON changed")
    if candidate_slots != baseline_slots:
        raise FrozenOutputOracleError(
            "frozen card assignment changed by configured team_id"
        )


CANDIDATE_RUN_KIND = "ti2026-frozen-output-oracle-candidate"


def _clean_head_revision(repo_root: Path) -> str:
    status = subprocess.run(
        [
            "git", "-C", str(repo_root), "status", "--porcelain=v1",
            "--untracked-files=all",
        ],
        check=False,
        capture_output=True,
    )
    if status.returncode != 0 or status.stdout:
        raise FrozenOutputOracleError("frozen replay requires a clean Git checkout")
    head = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
    )
    if head.returncode != 0:
        raise FrozenOutputOracleError("cannot resolve replay source revision")
    return head.stdout.decode("ascii").strip()


def _run_release(repo_root: Path, argv: tuple[str, ...]) -> int:
    return subprocess.run(
        [sys.executable, "-m", "ti26.cli_release", *argv],
        cwd=repo_root,
        check=False,
    ).returncode


def _sole_generated_bundle(runs_root: Path) -> Path:
    try:
        children = sorted(runs_root.iterdir())
    except OSError as exc:
        raise FrozenOutputOracleError(
            f"cannot read isolated replay root: {runs_root}"
        ) from exc
    if (
        len(children) != 1
        or children[0].is_symlink()
        or not children[0].is_dir()
    ):
        raise FrozenOutputOracleError(
            "isolated replay must produce exactly one child bundle"
        )
    return children[0]


def replay_current_frozen_output(
    *, repo_root: Path, runs_root: Path, source_revision: str
) -> None:
    try:
        repository = repo_root.resolve(strict=True)
    except OSError as exc:
        raise FrozenOutputOracleError("invalid replay repository root") from exc
    if not runs_root.is_absolute():
        raise FrozenOutputOracleError("isolated replay root must be an absolute path")
    candidate_root = runs_root.resolve(strict=False)
    if candidate_root == repository or repository in candidate_root.parents:
        raise FrozenOutputOracleError("isolated replay root must be outside repository")
    if candidate_root.exists() or candidate_root.is_symlink():
        raise FrozenOutputOracleError("isolated replay root must not already exist")
    if _clean_head_revision(repository) != source_revision:
        raise FrozenOutputOracleError(
            "replay source revision must equal the clean current HEAD"
        )
    invocation = registered_baseline_invocation(repo_root=repository)
    argv = (
        *invocation.release_args,
        "--runs", str(candidate_root),
        "--run-kind", CANDIDATE_RUN_KIND,
        "--source-revision", source_revision,
    )
    if _run_release(repository, argv) != 0:
        raise FrozenOutputOracleError("isolated cli_release replay failed")
    candidate_bundle = _sole_generated_bundle(candidate_root)
    verify_run_bundle(
        candidate_bundle,
        repo_root=repository,
        against_revision=source_revision,
    )
    baseline = load_current_baseline(repo_root=repository)
    candidate = load_frozen_output(candidate_bundle, repo_root=repository)
    assert_matches_frozen_output(baseline, candidate)
    shutil.rmtree(candidate_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare a full release bundle with the frozen output baseline"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--candidate")
    mode.add_argument("--replay-root")
    parser.add_argument("--source-revision")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()

    if args.replay_root is not None:
        if args.source_revision is None:
            parser.error("--replay-root requires --source-revision")
        replay_current_frozen_output(
            repo_root=repo_root,
            runs_root=Path(args.replay_root),
            source_revision=args.source_revision,
        )
        print("frozen output replay: match")
        return 0
    if args.source_revision is not None:
        parser.error("--source-revision is valid only with --replay-root")

    baseline = load_current_baseline(repo_root=repo_root)
    candidate = load_frozen_output(Path(args.candidate), repo_root=repo_root)
    assert_matches_frozen_output(baseline, candidate)
    print("frozen output oracle: match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
