"""Tests for the retrospective postmortem replay attestation."""

import json
from pathlib import Path

import pytest

from ti26.cli_replay_postmortems import (
    ReplayAttestationError,
    _normalise_store_path,
    load_and_verify_manifest,
    replay,
)


def test_playoff_normalization_rejects_a_non_unique_rendered_store_path(tmp_path):
    """Kills mutation: replace every rendered store path without checking its count.

    The one permitted difference is the producer's single `Store:` line. A global
    replacement with no count check could hide a second path-dependent line, which
    would turn a substantive output change into a passing replay.
    """
    store = tmp_path / "fresh.sqlite"
    rendered = f"Store: `{store}`\nAgain: `{store}`\n"

    with pytest.raises(ReplayAttestationError, match="expected one rendered store path, found 2"):
        _normalise_store_path(rendered, store, "data/processed/ti2026-postgroup.sqlite")


def test_replay_refuses_an_existing_store_before_reading_manifests(tmp_path):
    """Kills mutation: allow an existing store to be re-ingested.

    Replaying into a prior database would accept duplicate rows and could hide a
    different starting state. The command must require a path that did not exist
    when the replay began, even if its manifests are unavailable.
    """
    store = tmp_path / "already-there.sqlite"
    store.write_text("not a new store")

    with pytest.raises(ReplayAttestationError, match="refusing to overwrite store"):
        replay(
            repo_root=tmp_path,
            raw=tmp_path / "raw",
            snapshot="20260816T115509Z",
            store=store,
            manifests=(tmp_path / "group.json", tmp_path / "playoff.json"),
        )


def test_manifest_rejects_a_changed_bound_input(tmp_path):
    """Kills mutation: skip the current-byte check for a manifest input digest.

    A replay must fail before a changed config or raw snapshot can be treated as
    the frozen experiment. This changes a copied manifest's recorded input hash
    while leaving every repository file untouched.
    """
    repo_root = Path(__file__).parents[1]
    manifest = json.loads(
        (repo_root / "reports/postmortems/group-replay.manifest.json").read_text()
    )
    manifest["inputs"][0]["sha256"] = "0" * 64
    changed = tmp_path / "group-replay.manifest.json"
    changed.write_text(json.dumps(manifest))

    with pytest.raises(ReplayAttestationError, match="input sha256 mismatch"):
        load_and_verify_manifest(changed, repo_root)


@pytest.mark.parametrize("kind", ["group", "playoff"])
def test_committed_replay_manifests_match_the_tree(kind):
    """Kills mutation: edit a replay-bound file (reformat teams.py, touch pyproject.toml).

    The postmortem manifests bind producer sources, replay tooling and inputs by
    their current bytes. CI does not run the replay itself, so without this check a
    formatting pass or a lock bump would silently break the documented recipe.
    """
    repo_root = Path(__file__).parents[1]
    load_and_verify_manifest(
        repo_root / f"reports/postmortems/{kind}-replay.manifest.json", repo_root
    )
