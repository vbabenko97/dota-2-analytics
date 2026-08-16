"""Pin one Valve announcement from the Steam News API as a raw capture.

Fetch and import are separate phases, exactly as `cli_ingest` separates
snapshotting from loading. This command only writes bytes under `data/raw/`;
turning those bytes into an evidence record is `cli_evidence_import`'s job and
still requires the owner to attest the digests printed here.

Selecting by `gid` rather than by title or feed position is what makes a re-run
reproducible: the feed reorders every time Valve posts.
"""

import argparse
import hashlib
import json
from pathlib import Path

from ti26.data.opendota import http_transport
from ti26.data.steam_news import DOTA_2_APP_ID, announcement_by_gid, steam_news_query


def render_capture(item: dict) -> bytes:
    """Serialize one announcement to the exact bytes that get pinned.

    Sorted keys and a trailing newline so that re-fetching unchanged content
    reproduces the file byte-for-byte, which is what makes a digest mismatch
    mean "Valve edited the post" rather than "Python reordered a dict".
    """
    return (json.dumps(item, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pin one Steam announcement under data/raw")
    parser.add_argument("--gid", required=True, help="Steam announcement gid")
    parser.add_argument("--out", default="data/raw/steam-news")
    parser.add_argument("--app-id", type=int, default=DOTA_2_APP_ID)
    parser.add_argument("--count", type=int, default=100)
    args = parser.parse_args(argv)

    newsitems = steam_news_query(http_transport, app_id=args.app_id, count=args.count)
    item = announcement_by_gid(newsitems, args.gid)
    payload = render_capture(item)
    digest = hashlib.sha256(payload).hexdigest()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{args.gid}.json"

    if path.exists():
        existing = path.read_bytes()
        if existing == payload:
            print(f"unchanged: {path}")
            print(f"sha256: {digest}")
            return 0
        # A pinned capture is evidence. Overwriting it here would destroy the
        # record of what the source said when it was attested, so the divergence
        # is reported and left for the owner to resolve.
        print(f"CHANGED: {path} already holds different bytes for gid {args.gid}")
        print(f"  pinned:  {hashlib.sha256(existing).hexdigest()}")
        print(f"  fetched: {digest}")
        return 1

    path.write_bytes(payload)
    print(f"pinned: {path} ({len(payload)} bytes)")
    print(f"sha256: {digest}")
    print(f"title: {item.get('title')!r} date: {item.get('date')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
