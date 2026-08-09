"""Run every producer from a pinned snapshot into one hash-bound run bundle.

This is the command that makes a published number checkable. It rebuilds the
SQLite store from committed raw chunks, runs the gate, card and diagnostic
producers into a single directory, and writes a manifest binding every output's
SHA-256 to the source revision, the input snapshot, the rebuilt store's logical
digest, and every configuration file consulted.

It decides nothing. Gate verdicts are whatever the registered gates return -- a
failing gate's non-zero exit is expected evidence here, recorded and carried
into the artifact, never retried with different arguments. D4 is a diagnostic
and its output reaches no selection.

The run id is derived from the descriptor before any output exists, which is
what lets each generated report carry it on line one while the manifest still
hashes the finished file.
"""

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from ti26.data.snapshot import sha256_file, validate_snapshot
from ti26.gate_artifacts import write_frozen_gate_artifact
from ti26.provenance import (
    RUN_MANIFEST_SCHEMA_VERSION,
    logical_store_digest,
    render_report_prefix,
    write_run_manifest,
)

# EVERY configuration file in `config/`, hashed into the manifest so a report
# cannot be traced to a config that has since changed. `tests/test_cli_release.py`
# asserts this list equals `config/*.yaml` exactly, so adding a config without
# adding it here fails the suite.
#
# The invariant is deliberately "every config", not "every config a producer
# below reads". Those differ -- `ti2025_external_cards.yaml` feeds a diagnostic
# that is not yet a bundle producer -- and the stricter rule is the useful one:
# the manifest then records the repository's whole configuration state at run
# time, so a reader comparing two bundles can tell what changed between them
# without knowing which producer consumed what.
# The registered gates. A non-zero exit from one of these is its verdict, not a
# build failure, and the driver records it and carries on.
GATE_PRODUCERS = frozenset({"d2", "d3", "d3b"})

CONFIG_INPUTS = (
    "config/d2_gate.yaml",
    "config/team_aliases.yaml",
    "config/ti2026_rules.yaml",
    "config/ti2026_teams.yaml",
    "config/ti2025_backtest.yaml",
    "config/ti2025_external_cards.yaml",
    "pyproject.toml",
)


def declared_inputs(snapshot_manifest_path: str, groups: str | None) -> list[str]:
    """Every file whose BYTES the manifest binds this run to.

    The group draw belongs here in exactly the sense the snapshot does: it is an
    external fact the forecast is conditioned on, not a setting we chose. The
    producer list already records that `--groups <path>` was passed, but a path
    is not its contents -- without this, two bundles conditioned on different
    draws are indistinguishable, and `verify-run` cannot fail closed when the
    draw changes under a finished bundle.

    Hashed wherever it lives rather than required to sit in `config/`, because
    `CONFIG_INPUTS` is asserted to equal `config/*.yaml` exactly. Dropping a
    draw file there on lock day would turn the suite red at step 9, in the
    middle of the regeneration, for a file that is data rather than
    configuration.
    """
    return [
        snapshot_manifest_path,
        *CONFIG_INPUTS,
        *([groups] if groups else []),
    ]


def build_producers(args, store_path: Path) -> list[list[str]]:
    """Every command the bundle runs, in order, as `python -m` argument lists.

    The list IS the run id: it goes into the descriptor, and the id is derived
    from the descriptor before any output exists. Adding a producer therefore
    moves the run id, which is correct -- a bundle containing different outputs
    is a different bundle.
    """
    store = str(store_path)
    min_train = str(args.min_train)
    return [
        ["ti26.cli_d2", "--store", store, "--min-train", min_train],
        ["ti26.cli_d3", "--store", store, "--min-train", min_train],
        ["ti26.cli_d3b", "--store", store, "--min-train", min_train],
        # --groups reaches the CARD only. D4 backtests TI 2025, whose groups
        # were its own; handing it TI 2026's draw would be a leak, not a fix.
        ["ti26.cli_card", "--store", store, "--min-train", min_train,
         "--card-sims", str(args.card_sims), "--card-seed", str(args.card_seed),
         *(["--groups", args.groups] if args.groups else [])],
        ["ti26.cli_d4", "--store", store, "--min-train", min_train,
         "--card-sims", str(args.card_sims), "--card-seed", str(args.card_seed),
         "--sweep-sims", args.sweep_sims, "--sweep-seeds", args.sweep_seeds,
         "--random-samples", str(args.random_samples), "--random-seed", str(args.random_seed)],
        # Neither of these two scores the model. They state what the card was
        # built from and what a card score can prove, and both belong in the
        # bundle for the same reason the manifest exists: a number that ships
        # beside the card should be as traceable as the card. `external_cards`
        # reads no store -- it scores published cards against a frozen truth --
        # so it takes the same inputs in every run and lands here as a constant.
        ["ti26.cli_data_health", "--store", store],
        ["ti26.cli_external_cards"],
    ]


def card_producer(producers: list[list[str]]) -> list[str]:
    """The card's argument list, found by name rather than by position.

    The card is run twice: once with the others, then again once the frozen-gate
    artifact exists so its report can cite the gate lineage. The second call has
    to reach the same producer, and the list above has grown twice. A positional
    lookup that slid onto a neighbour would re-run that neighbour with the card's
    arguments and overwrite the card directory with its output.
    """
    return next(producer for producer in producers if producer[0] == "ti26.cli_card")


def non_gate_failures(exits: dict[str, int]) -> dict[str, int]:
    """Producers that failed and were not entitled to.

    A registered gate's non-zero exit is its verdict and expected evidence.
    Everything else that exits non-zero could not produce at all. Naming the
    gates rather than the non-gates means a producer added later is must-succeed
    by default, which is the safe direction: a diagnostic that failed silently
    leaves the bundle short an output nobody notices is missing.
    """
    return {
        name: code
        for name, code in exits.items()
        if code != 0 and name not in GATE_PRODUCERS
    }


def _run(argv: list[str], repo_root: Path) -> int:
    """Run one producer as a subprocess and return its exit code.

    A gate that fails returns non-zero. That is a result, not an error, so the
    exit code is captured and reported rather than raised.
    """
    print(f"  $ {' '.join(argv)}", flush=True)
    completed = subprocess.run(
        [sys.executable, "-m", *argv], cwd=repo_root, check=False
    )
    return completed.returncode


def _runtime() -> dict[str, str]:
    versions = {"python": platform.python_version(), "platform": platform.platform()}
    for name in ("numpy", "scipy", "yaml"):
        try:
            versions[name] = __import__(name).__version__
        except (ImportError, AttributeError):  # pragma: no cover -- declared deps
            versions[name] = "unavailable"
    return versions


def _prefix_markdown(path: Path, prefix: str) -> None:
    """Stamp the run reference onto a generated report's first line.

    The producers write their own Markdown and know nothing about bundles. The
    reference is bundle metadata, not a claim about the run's contents, so
    adding it here keeps the producers unaware of where their output lands.
    """
    body = path.read_text(encoding="utf-8")
    path.write_text(f"{prefix}\n{body}", encoding="utf-8")


def _bundle_is_complete(bundle: Path) -> bool:
    """A bundle counts as complete once it carries the manifest binding it.

    Anything else under that path is wreckage from an interrupted run: the
    manifest is written last, so its absence means the producers did not all
    finish and nothing there is evidence of anything.
    """
    return (bundle / "manifest.json").exists()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--raw", default="data/raw")
    parser.add_argument("--runs", default="reports/runs")
    parser.add_argument("--run-kind", default="historical")
    parser.add_argument("--card-sims", type=int, default=250_000)
    parser.add_argument("--card-seed", type=int, default=1)
    parser.add_argument("--min-train", type=int, default=500)
    parser.add_argument("--sweep-sims", default="2000,20000,250000")
    parser.add_argument("--sweep-seeds", default="1,2,3")
    parser.add_argument("--random-samples", type=int, default=200_000)
    parser.add_argument("--random-seed", type=int, default=1)
    parser.add_argument(
        "--groups",
        default=None,
        help="YAML with the organiser's group draw; forwarded to the card only",
    )
    args = parser.parse_args(argv)

    repo_root = Path.cwd().resolve()
    raw_root = Path(args.raw)
    sid = args.snapshot

    # --- 1. The pinned input, validated before anything reads a row ----------
    chunks = validate_snapshot(raw_root, sid)
    snapshot_manifest = raw_root / sid / "manifest.json"
    print(f"snapshot {sid}: {len(chunks)} chunks validated", flush=True)

    # --- 2. Rebuild the store from those bytes -------------------------------
    store_path = Path("data/processed") / f"release-{sid}.sqlite"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    if _run(
        ["ti26.cli_ingest", "--raw", str(raw_root), "--snapshot", sid, "--store", str(store_path)],
        repo_root,
    ):
        raise SystemExit("store rebuild failed")

    import sqlite3

    connection = sqlite3.connect(f"file:{store_path.resolve()}?mode=ro", uri=True)
    try:
        store_digest = logical_store_digest(connection)
    finally:
        connection.close()
    print(f"store digest: {store_digest['sha256']} over {store_digest['row_count']} rows", flush=True)

    # --- 3. The descriptor, and therefore the run id, before any output ------
    producers = build_producers(args, store_path)
    descriptor = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "run_kind": args.run_kind,
        "source_revision": args.source_revision,
        "invocation": {
            "producers": producers,
            "card_seed": args.card_seed,
            "card_sims": args.card_sims,
            "sweep_sims": args.sweep_sims,
            "sweep_seeds": args.sweep_seeds,
            "random_seed": args.random_seed,
            "random_samples": args.random_samples,
            "min_train": args.min_train,
        },
        "snapshot": {
            "snapshot_id": sid,
            "manifest_path": snapshot_manifest.as_posix(),
            "manifest_sha256": sha256_file(snapshot_manifest),
        },
        "store": store_digest,
        "inputs": [
            {"path": path, "sha256": sha256_file(Path(path))}
            for path in declared_inputs(snapshot_manifest.as_posix(), args.groups)
        ],
        "runtime": _runtime(),
    }
    prefix = render_report_prefix(descriptor)
    run_id = prefix.split()[2]
    bundle = Path(args.runs) / run_id
    # A run id identifies its inputs exactly, so a COMPLETE bundle must never be
    # silently overwritten. An INCOMPLETE one is different: a run killed partway
    # leaves a directory that then blocks every retry, with nothing to clear it.
    # That happened during the 2026-08-08 regeneration and had to be undone by
    # hand, which is exactly the wrong thing to be doing under a deadline. A
    # bundle counts as complete when it has the manifest that binds its outputs;
    # anything else is wreckage from an interrupted run and is replaced.
    if _bundle_is_complete(bundle):
        raise SystemExit(f"{bundle} already exists; a run id identifies its inputs exactly")
    if bundle.exists():
        print(
            f"replacing an incomplete bundle at {bundle} "
            "(no manifest.json, so a previous run did not finish)",
            flush=True,
        )
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)
    print(f"run id: {run_id}", flush=True)

    # --- 4. Producers, each into its own directory ---------------------------
    exits = {}
    for producer in producers:
        name = producer[0].removeprefix("ti26.cli_")
        exits[name] = _run([*producer, "--out", str(bundle / name)], repo_root)
        print(f"  {name} exited {exits[name]}", flush=True)

    failed = non_gate_failures(exits)
    if failed:
        raise SystemExit(f"a non-gate producer failed: {failed}")

    # --- 5. The frozen gate artifact, from those three results ---------------
    artifact_path = bundle / "frozen_gate_results.json"
    write_frozen_gate_artifact(
        {
            "d2": bundle / "d2" / "d2_gate.json",
            "d3": bundle / "d3" / "d3_gate.json",
            "d3b": bundle / "d3b" / "d3b_gate.json",
        },
        artifact_path,
        source_revision=args.source_revision,
    )

    # The card report's gate lineage must come from that artifact, so the card
    # is rendered again now that it exists. The card itself is unchanged: same
    # store, same seed, same sim count, same strengths.
    card_argv = [
        *card_producer(producers),
        "--out", str(bundle / "card"),
        "--frozen-gates", str(artifact_path),
    ]
    for stale in (bundle / "card").glob("*"):
        stale.unlink()
    exits["card"] = _run(card_argv, repo_root)
    if exits["card"] != 0:
        raise SystemExit("card regeneration with the frozen-gate artifact failed")

    (bundle / "producer_exits.json").write_text(json.dumps(exits, indent=2, sort_keys=True) + "\n")

    # --- 6. Stamp the reports, then hash everything --------------------------
    outputs = sorted(
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    )
    for output in outputs:
        if output.endswith(".md"):
            _prefix_markdown(bundle / output, prefix)
    manifest_path = write_run_manifest(bundle, descriptor, outputs)
    print(f"manifest: {manifest_path}", flush=True)
    print(f"outputs: {len(outputs)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
