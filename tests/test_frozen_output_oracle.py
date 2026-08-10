import json
from pathlib import Path, PurePosixPath

import pytest

from ti26 import frozen_output_oracle as oracle
from ti26.frozen_output_oracle import (
    BASELINE_ROOT,
    BASELINE_RUN_KIND,
    FrozenOutputOracleError,
    load_current_baseline,
    registered_baseline_bundle,
    registered_baseline_invocation,
)


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
