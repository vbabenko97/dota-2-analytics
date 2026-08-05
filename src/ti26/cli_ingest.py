"""Snapshot the explorer, then load the snapshot into the store.

Fetch and load are separate phases on purpose: the snapshot is immutable and
re-loadable, so a schema change never costs another 18 months of API calls.
"""

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ti26.data.opendota import MAP_QUERY, explorer_query, http_transport, month_windows
from ti26.data.schema import normalize_all
from ti26.data.snapshot import (
    sha256_file,
    snapshot_id,
    validate_snapshot,
    write_manifest,
    write_snapshot,
)
from ti26.data.store import insert_rows, open_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest pro maps from OpenDota /explorer")
    parser.add_argument("--months", type=int, default=18)
    parser.add_argument("--raw", default="data/raw")
    parser.add_argument("--store", default="data/processed/d2.sqlite")
    parser.add_argument("--snapshot", default=None, help="reload an existing snapshot id")
    args = parser.parse_args(argv)

    raw_root = Path(args.raw)
    if args.snapshot:
        sid = args.snapshot
        chunks = validate_snapshot(raw_root, sid)
    else:
        now = datetime.now(UTC)
        sid = snapshot_id(now)
        start = now - timedelta(days=30 * args.months)
        entries = []
        for start_epoch, end_epoch in month_windows(start, now):
            sql = MAP_QUERY.format(start=start_epoch, end=end_epoch)
            rows = explorer_query(sql, http_transport)
            name = datetime.fromtimestamp(start_epoch, UTC).strftime("%Y-%m")
            path = write_snapshot(raw_root, sid, name, rows)
            entries.append(
                {
                    "name": name,
                    "rows": len(rows),
                    "start": start_epoch,
                    "end": end_epoch,
                    "query": sql,
                    "sha256": sha256_file(path),
                }
            )
            print(f"{name}: {len(rows)} maps")
        write_manifest(raw_root, sid, entries, retrieved_at=now.isoformat().replace("+00:00", "Z"))
        chunks = validate_snapshot(raw_root, sid)

    store_path = Path(args.store)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    conn = open_store(store_path)

    total, tally = 0, {}
    for chunk in chunks:
        rows, chunk_tally = normalize_all(chunk.rows)
        total += insert_rows(conn, rows)
        for key, count in chunk_tally.items():
            tally[key] = tally.get(key, 0) + count

    print(f"snapshot {sid}: loaded {total} maps into {store_path}")
    if tally:
        print(f"rejected: {tally}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
