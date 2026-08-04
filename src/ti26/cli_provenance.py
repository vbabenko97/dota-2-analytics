"""Offline provenance inspection commands."""

import argparse
import sqlite3
from pathlib import Path

from ti26.provenance import canonical_json_bytes, logical_store_digest, verify_run_bundle


def _print_json(value: object) -> None:
    print(canonical_json_bytes(value).decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect offline forecast provenance")
    commands = parser.add_subparsers(dest="command", required=True)
    store_digest = commands.add_parser("store-digest")
    store_digest.add_argument("--store", required=True)
    verify_run = commands.add_parser("verify-run")
    verify_run.add_argument("--bundle", required=True)
    verify_run.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)

    if args.command == "store-digest":
        store = Path(args.store)
        connection = sqlite3.connect(f"file:{store.resolve()}?mode=ro", uri=True)
        try:
            _print_json(logical_store_digest(connection))
        finally:
            connection.close()
    else:
        repo_root = Path(args.repo_root) if args.repo_root is not None else None
        _print_json(verify_run_bundle(Path(args.bundle), repo_root=repo_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
