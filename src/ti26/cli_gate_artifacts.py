"""Combine three registered gate results into one frozen artifact.

This command runs no gate and evaluates no condition. It reads the machine-
readable results the gate CLIs already wrote, checks they are internally
consistent and complete, and writes the artifact the card report reads.
"""

import argparse
from pathlib import Path

from ti26.gate_artifacts import write_frozen_gate_artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--d2", required=True, help="path to d2_gate.json")
    parser.add_argument("--d3", required=True, help="path to d3_gate.json")
    parser.add_argument("--d3b", required=True, help="path to d3b_gate.json")
    parser.add_argument(
        "--source-revision",
        required=True,
        help="the 40-character commit these results were produced from",
    )
    parser.add_argument("--out", required=True, help="destination artifact path")
    args = parser.parse_args(argv)

    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_frozen_gate_artifact(
        {"d2": Path(args.d2), "d3": Path(args.d3), "d3b": Path(args.d3b)},
        destination,
        source_revision=args.source_revision,
    )
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
