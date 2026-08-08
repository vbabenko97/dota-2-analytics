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

# Every configuration file a producer below reads. Hashed into the manifest so a
# report cannot be traced to a config that has since changed.
CONFIG_INPUTS = (
    "config/d2_gate.yaml",
    "config/team_aliases.yaml",
    "config/ti2026_rules.yaml",
    "config/ti2026_teams.yaml",
    "config/ti2025_backtest.yaml",
    "pyproject.toml",
)


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
    producers = [
        ["ti26.cli_d2", "--store", str(store_path), "--min-train", str(args.min_train)],
        ["ti26.cli_d3", "--store", str(store_path), "--min-train", str(args.min_train)],
        ["ti26.cli_d3b", "--store", str(store_path), "--min-train", str(args.min_train)],
        # --groups reaches the CARD only. D4 backtests TI 2025, whose groups
        # were its own; handing it TI 2026's draw would be a leak, not a fix.
        ["ti26.cli_card", "--store", str(store_path), "--min-train", str(args.min_train),
         "--card-sims", str(args.card_sims), "--card-seed", str(args.card_seed),
         *(["--groups", args.groups] if args.groups else [])],
        ["ti26.cli_d4", "--store", str(store_path), "--min-train", str(args.min_train),
         "--card-sims", str(args.card_sims), "--card-seed", str(args.card_seed),
         "--sweep-sims", args.sweep_sims, "--sweep-seeds", args.sweep_seeds,
         "--random-samples", str(args.random_samples), "--random-seed", str(args.random_seed)],
    ]
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
            for path in (snapshot_manifest.as_posix(), *CONFIG_INPUTS)
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

    # A gate's registered failure exit is expected evidence. Only a producer
    # that cannot produce at all is a problem.
    if exits.get("card", 0) != 0 or exits.get("d4", 0) != 0:
        raise SystemExit(f"a non-gate producer failed: {exits}")

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
    card_argv = [*producers[3], "--out", str(bundle / "card"), "--frozen-gates", str(artifact_path)]
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
