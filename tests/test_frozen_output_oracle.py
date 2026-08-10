import json
import subprocess
from copy import deepcopy
from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest

from ti26 import frozen_output_oracle as oracle
from ti26.data.snapshot import sha256_file
from ti26.frozen_output_oracle import (
    BASELINE_ROOT,
    BASELINE_RUN_KIND,
    CANDIDATE_RUN_KIND,
    FrozenBaselineInvocation,
    FrozenOutput,
    FrozenOutputOracleError,
    assert_matches_frozen_output,
    load_current_baseline,
    load_frozen_output,
    load_staged_frozen_output,
    registered_baseline_bundle,
    registered_baseline_invocation,
    replay_current_frozen_output,
)
from ti26.gate_artifacts import (
    gate_result_payload,
    write_frozen_gate_artifact,
    write_gate_result,
)
from ti26.provenance import write_run_manifest


def test_registered_baseline_is_the_sole_runtime_named_bundle():
    """Kills mutation: resolve registration from the generic reports/runs root."""
    repo_root = Path.cwd()
    bundle = registered_baseline_bundle(repo_root=repo_root)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))

    assert bundle.parent == repo_root / BASELINE_ROOT
    assert bundle.name == manifest["run_id"]
    assert manifest["run_kind"] == BASELINE_RUN_KIND


def test_registration_rejects_any_second_immediate_child(tmp_path, monkeypatch):
    """Kills mutation: count only child manifest files and ignore extra children."""
    registration = tmp_path / "registration"
    (registration / "manifest-child").mkdir(parents=True)
    (registration / "manifest-child" / "manifest.json").write_text("{}\n")
    (registration / "extra-child").mkdir()
    monkeypatch.setattr(oracle, "BASELINE_ROOT", registration)

    with pytest.raises(FrozenOutputOracleError, match="one child bundle"):
        registered_baseline_bundle(repo_root=tmp_path)


def test_registered_baseline_invocation_is_derived_from_manifest(monkeypatch):
    """Kills mutation: replay with cli_release defaults instead of manifest values."""
    repo_root = Path.cwd()
    bundle = registered_baseline_bundle(repo_root=repo_root)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    for key in (
        "card_sims",
        "card_seed",
        "min_train",
        "sweep_sims",
        "sweep_seeds",
        "random_samples",
        "random_seed",
    ):
        value = manifest["invocation"][key]
        manifest["invocation"][key] = (
            value + 1 if isinstance(value, int) else f"{value},synthetic"
        )
    monkeypatch.setattr(
        oracle,
        "verify_run_bundle_at_source_revision",
        lambda *_, **__: manifest,
    )
    baseline = registered_baseline_invocation(repo_root=repo_root)
    args = dict(zip(baseline.release_args[::2], baseline.release_args[1::2]))

    assert baseline.snapshot_id == manifest["snapshot"]["snapshot_id"]
    assert args["--snapshot"] == baseline.snapshot_id
    assert args["--raw"] == PurePosixPath(
        manifest["snapshot"]["manifest_path"]
    ).parent.parent.as_posix()
    for option, key in (
        ("--card-sims", "card_sims"),
        ("--card-seed", "card_seed"),
        ("--min-train", "min_train"),
        ("--sweep-sims", "sweep_sims"),
        ("--sweep-seeds", "sweep_seeds"),
        ("--random-samples", "random_samples"),
        ("--random-seed", "random_seed"),
    ):
        assert args[option] == str(manifest["invocation"][key])


def test_current_baseline_loads_complete_manifest_declared_gate_and_card_objects():
    """Kills mutation: reconstruct predictive output from selected JSON members."""
    repo_root = Path.cwd()
    bundle = registered_baseline_bundle(repo_root=repo_root)
    output = load_current_baseline(repo_root=repo_root)
    frozen = json.loads(
        (bundle / "frozen_gate_results.json").read_text(encoding="utf-8")
    )

    assert output.gates == frozen["gates"]
    for gate in ("d2", "d3", "d3b"):
        individual = json.loads(
            (bundle / gate / f"{gate}_gate.json").read_text(encoding="utf-8")
        )
        assert output.gates[gate] == individual
    assert output.card == json.loads(
        (bundle / "card" / "recommended_card.json").read_text(encoding="utf-8")
    )


def _git_text(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )
    return completed.stdout.decode("utf-8").strip()


def _synthetic_gate(gate: str) -> dict[str, object]:
    return gate_result_payload(
        gate=gate,
        verdict="PASS",
        exit_code=0,
        registration="synthetic",
        conditions={"synthetic": {"value": "synthetic", "passed": True}},
        method="synthetic",
        n_maps=0,
        excluded={},
        config={},
    )


def synthetic_oracle_bundle(
    tmp_path: Path,
    *,
    omit_file: str | None = None,
    omit_manifest_output: str | None = None,
    card_bytes: bytes = b"{}\n",
    frozen_gate_bytes: bytes | None = None,
    replace_gate: str | None = None,
) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git_text(repo_root, "init", "--quiet")
    _git_text(repo_root, "config", "user.name", "Oracle Test")
    _git_text(repo_root, "config", "user.email", "oracle@example.invalid")
    source = repo_root / "input.txt"
    source.write_text("synthetic input\n", encoding="utf-8")
    _git_text(repo_root, "add", "input.txt")
    _git_text(repo_root, "commit", "--quiet", "-m", "synthetic oracle input")
    revision = _git_text(repo_root, "rev-parse", "HEAD")

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    paths: dict[str, Path] = {}
    for gate in ("d2", "d3", "d3b"):
        path = bundle / gate / f"{gate}_gate.json"
        path.parent.mkdir()
        write_gate_result(path, _synthetic_gate(gate))
        paths[gate] = path
    frozen_gate_path = bundle / "frozen_gate_results.json"
    write_frozen_gate_artifact(
        paths, frozen_gate_path, source_revision=revision
    )
    if frozen_gate_bytes is not None:
        frozen_gate_path.write_bytes(frozen_gate_bytes)
    card_path = bundle / "card" / "recommended_card.json"
    card_path.parent.mkdir()
    card_path.write_bytes(card_bytes)
    if replace_gate is not None:
        changed = _synthetic_gate(replace_gate)
        changed["registration"] = "changed synthetic registration"
        write_gate_result(paths[replace_gate], changed)
    if omit_file is not None:
        (bundle / omit_file).unlink()

    descriptor = {
        "schema_version": 1,
        "run_kind": "synthetic-oracle",
        "source_revision": revision,
        "invocation": {},
        "snapshot": {
            "snapshot_id": "synthetic",
            "manifest_path": "input.txt",
            "manifest_sha256": sha256_file(source),
        },
        "store": {},
        "inputs": [{"path": "input.txt", "sha256": sha256_file(source)}],
        "runtime": {},
    }
    outputs = sorted(
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if (
            path.is_file()
            and path.relative_to(bundle).as_posix() != omit_manifest_output
        )
    )
    write_run_manifest(bundle, descriptor, outputs)
    return bundle, repo_root


def test_reader_rejects_required_output_not_declared_by_manifest(tmp_path):
    """Kills mutation: read conventional paths without requiring manifest membership."""
    bundle, repo_root = synthetic_oracle_bundle(
        tmp_path, omit_manifest_output="d3/d3_gate.json"
    )

    with pytest.raises(FrozenOutputOracleError, match="d3/d3_gate.json"):
        load_frozen_output(bundle, repo_root=repo_root)


def test_staged_reader_loads_manifestless_complete_objects(tmp_path):
    """Kills mutation: require provenance verification in the staged reader."""
    bundle, _ = synthetic_oracle_bundle(tmp_path)
    frozen = json.loads(
        (bundle / "frozen_gate_results.json").read_text(encoding="utf-8")
    )
    card = json.loads(
        (bundle / "card" / "recommended_card.json").read_text(encoding="utf-8")
    )
    (bundle / "manifest.json").unlink()

    output = load_staged_frozen_output(bundle)

    assert output == FrozenOutput(gates=frozen["gates"], card=card)


def test_staged_reader_rejects_missing_required_file(tmp_path):
    """Kills mutation: skip required-file checks without a run manifest."""
    bundle, _ = synthetic_oracle_bundle(
        tmp_path, omit_file="d3/d3_gate.json"
    )
    (bundle / "manifest.json").unlink()

    with pytest.raises(FrozenOutputOracleError, match="d3/d3_gate.json"):
        load_staged_frozen_output(bundle)


def test_reader_rejects_card_json_that_is_not_an_object(tmp_path):
    """Kills mutation: accept a JSON array as complete card machine output."""
    bundle, repo_root = synthetic_oracle_bundle(tmp_path, card_bytes=b"[]\n")

    with pytest.raises(FrozenOutputOracleError, match="JSON object"):
        load_frozen_output(bundle, repo_root=repo_root)


def test_reader_translates_invalid_frozen_gate_artifact_error(tmp_path):
    """Kills mutation: leak gate-artifact ValueError outside the oracle API."""
    bundle, repo_root = synthetic_oracle_bundle(
        tmp_path, frozen_gate_bytes=b"[]\n"
    )

    with pytest.raises(FrozenOutputOracleError, match="invalid frozen gate artifact"):
        load_frozen_output(bundle, repo_root=repo_root)


def test_reader_rejects_gate_disagreeing_with_frozen_aggregate(tmp_path):
    """Kills mutation: trust the aggregate without cross-checking individual gates."""
    bundle, repo_root = synthetic_oracle_bundle(tmp_path, replace_gate="d3")

    with pytest.raises(FrozenOutputOracleError, match="d3/d3_gate.json"):
        load_frozen_output(bundle, repo_root=repo_root)


def replace_gate_member_without_known_measurement(
    output: FrozenOutput, gate: str
) -> FrozenOutput:
    gates = deepcopy(output.gates)
    registration = gates[gate]["registration"]
    assert isinstance(registration, str)
    gates[gate]["registration"] = f"{registration} [oracle test mutation]"
    return replace(output, gates=gates)


def replace_non_assignment_card_member_without_known_measurement(
    output: FrozenOutput,
) -> FrozenOutput:
    card = deepcopy(output.card)
    note = card["note"]
    assert isinstance(note, str)
    card["note"] = f"{note} [oracle test mutation]"
    return replace(output, card=card)


def rename_one_card_display_name_without_changing_team_id(
    output: FrozenOutput,
) -> FrozenOutput:
    card = deepcopy(output.card)
    assignments = card["assignments"]
    team_ids = card["team_ids"]
    assert isinstance(assignments, dict) and isinstance(team_ids, dict)
    name = next(iter(assignments))
    renamed = f"{name} [oracle test rename]"
    while renamed in assignments:
        renamed = f"{renamed}_"
    card["assignments"] = {
        renamed if key == name else key: value
        for key, value in assignments.items()
    }
    card["team_ids"] = {
        renamed if key == name else key: value
        for key, value in team_ids.items()
    }
    return replace(output, card=card)


def move_one_assignment_to_another_existing_category(
    output: FrozenOutput,
) -> FrozenOutput:
    card = deepcopy(output.card)
    assignments = card["assignments"]
    assert isinstance(assignments, dict)
    name = next(iter(assignments))
    current_category = assignments[name]
    alternate_category = next(
        category
        for category in assignments.values()
        if category != current_category
    )
    assignments[name] = alternate_category
    return replace(output, card=card)


def test_comparator_rejects_change_anywhere_in_complete_gate_result():
    """Kills mutation: compare only gate verdicts and ignore other result members."""
    baseline = load_current_baseline(repo_root=Path.cwd())
    candidate = replace_gate_member_without_known_measurement(baseline, "d2")

    with pytest.raises(FrozenOutputOracleError, match="d2"):
        assert_matches_frozen_output(baseline, candidate)


def test_comparator_rejects_changed_non_assignment_card_member():
    """Kills mutation: compare assignments but ignore other card JSON members."""
    baseline = load_current_baseline(repo_root=Path.cwd())
    candidate = replace_non_assignment_card_member_without_known_measurement(
        baseline
    )

    with pytest.raises(FrozenOutputOracleError, match="non-assignment"):
        assert_matches_frozen_output(baseline, candidate)


def test_comparator_keys_assignments_by_stable_team_id_not_display_name():
    """Kills mutation: compare assignment dictionaries by display-name keys."""
    baseline = load_current_baseline(repo_root=Path.cwd())
    renamed = rename_one_card_display_name_without_changing_team_id(baseline)

    assert_matches_frozen_output(baseline, renamed)


def test_comparator_rejects_category_change_for_same_stable_team_id():
    """Kills mutation: compare only stable-ID membership and ignore its category."""
    baseline = load_current_baseline(repo_root=Path.cwd())
    changed = move_one_assignment_to_another_existing_category(baseline)

    with pytest.raises(FrozenOutputOracleError, match="team_id"):
        assert_matches_frozen_output(baseline, changed)


def test_oracle_cli_invokes_complete_comparator(monkeypatch, tmp_path):
    """Kills mutation: return CLI success without calling the output comparator."""
    baseline = load_current_baseline(repo_root=Path.cwd())
    changed = replace_non_assignment_card_member_without_known_measurement(
        baseline
    )
    monkeypatch.setattr(oracle, "load_current_baseline", lambda **_: baseline)
    monkeypatch.setattr(oracle, "load_frozen_output", lambda *_, **__: changed)

    with pytest.raises(FrozenOutputOracleError, match="non-assignment"):
        oracle.main(
            ["--candidate", str(tmp_path / "candidate"), "--repo-root", "."]
        )


def test_isolated_replay_uses_registered_args_and_live_verifies_before_compare(
    tmp_path, monkeypatch
):
    """Kills mutation: compare the candidate before live manifest verification."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    runs_root = tmp_path / "candidate-root"
    revision = "a" * 40
    invocation = FrozenBaselineInvocation(
        snapshot_id="synthetic",
        release_args=("--snapshot", "synthetic"),
    )
    baseline = FrozenOutput(gates={}, card={})
    candidate = FrozenOutput(gates={}, card={})
    events: list[object] = []
    monkeypatch.setattr(oracle, "_clean_head_revision", lambda _: revision)
    monkeypatch.setattr(
        oracle,
        "registered_baseline_invocation",
        lambda **_: invocation,
    )

    def fake_release(root, argv):
        events.append(("release", tuple(argv)))
        (runs_root / "runtime-derived").mkdir(parents=True)
        return 0

    monkeypatch.setattr(oracle, "_run_release", fake_release)
    monkeypatch.setattr(
        oracle,
        "verify_run_bundle",
        lambda *_, **__: events.append("live-verify") or {},
    )
    monkeypatch.setattr(
        oracle,
        "load_current_baseline",
        lambda **_: events.append("baseline") or baseline,
    )
    monkeypatch.setattr(
        oracle,
        "load_frozen_output",
        lambda *_, **__: events.append("candidate") or candidate,
    )
    monkeypatch.setattr(
        oracle,
        "assert_matches_frozen_output",
        lambda *args: events.append("compare"),
    )

    replay_current_frozen_output(
        repo_root=repo_root,
        runs_root=runs_root,
        source_revision=revision,
    )

    release = events[0]
    assert release[0] == "release"
    assert release[1] == (
        *invocation.release_args,
        "--runs", str(runs_root),
        "--run-kind", CANDIDATE_RUN_KIND,
        "--source-revision", revision,
    )
    assert events[1:] == ["live-verify", "baseline", "candidate", "compare"]
    assert not runs_root.exists()


def test_isolated_replay_failure_preserves_its_temp_bundle(
    tmp_path, monkeypatch
):
    """Kills mutation: delete the replay root in a finally block after failure."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    runs_root = tmp_path / "candidate-root"
    revision = "a" * 40
    monkeypatch.setattr(oracle, "_clean_head_revision", lambda _: revision)
    monkeypatch.setattr(
        oracle,
        "registered_baseline_invocation",
        lambda **_: FrozenBaselineInvocation(
            snapshot_id="synthetic",
            release_args=("--snapshot", "synthetic"),
        ),
    )

    def fake_release(root, argv):
        (runs_root / "runtime-derived").mkdir(parents=True)
        return 0

    monkeypatch.setattr(oracle, "_run_release", fake_release)
    monkeypatch.setattr(oracle, "verify_run_bundle", lambda *_, **__: {})
    monkeypatch.setattr(
        oracle, "load_current_baseline", lambda **_: FrozenOutput({}, {})
    )
    monkeypatch.setattr(
        oracle, "load_frozen_output", lambda *_, **__: FrozenOutput({}, {})
    )

    def fail_comparison(*_):
        raise FrozenOutputOracleError("drift")

    monkeypatch.setattr(
        oracle, "assert_matches_frozen_output", fail_comparison
    )

    with pytest.raises(FrozenOutputOracleError, match="drift"):
        replay_current_frozen_output(
            repo_root=repo_root,
            runs_root=runs_root,
            source_revision=revision,
        )

    assert runs_root.is_dir()
    assert not (repo_root / "reports" / "forecast_registry").exists()


def test_replay_cli_routes_to_isolated_helper(tmp_path, monkeypatch, capsys):
    """Kills mutation: parse replay flags but return without invoking the helper."""
    revision = "a" * 40
    calls = []
    monkeypatch.setattr(
        oracle,
        "replay_current_frozen_output",
        lambda **kwargs: calls.append(kwargs),
    )

    exit_code = oracle.main(
        [
            "--replay-root", str(tmp_path / "candidate-root"),
            "--source-revision", revision,
            "--repo-root", str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert calls == [
        {
            "repo_root": tmp_path.resolve(),
            "runs_root": tmp_path / "candidate-root",
            "source_revision": revision,
        }
    ]
    assert capsys.readouterr().out == "frozen output replay: match\n"
