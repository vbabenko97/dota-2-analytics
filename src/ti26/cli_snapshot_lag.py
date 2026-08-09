"""Is the thin recent tail a real slowdown, or rows that had not arrived yet?

`cli_data_health` reports 13.9 maps/day across the last 30 days against 76/day
over the corpus. That single number has two incompatible readings and they call
for opposite responses:

  REAL SLOWDOWN   Teams stop playing publicly before a major. The evidence that
                  matters most is genuinely the thinnest, and the response is to
                  widen uncertainty on recent form.
  INGEST LAG      Every snapshot's newest days are incomplete, because results
                  reach OpenDota after the match. The response is to snapshot as
                  late as possible on lock day and to stop reading the final days
                  as evidence of anything.

`cli_data_health` cannot tell them apart, and the reason is structural rather
than an oversight: its recency windows are measured from each store's own last
map, so running it against two snapshots compares two different windows.

This producer compares the SAME calendar window across two snapshots taken days
apart. A match present in the newer snapshot, absent from the older one, and
dated inside the range the older one already claimed to cover, is a row that
arrived late -- lag, measured rather than argued. What survives after that
correction is the real rate.

Both snapshots must already be committed; nothing here touches the network.

DIAGNOSTIC. No threshold, gates nothing, cannot alter the shipping card.
"""

import argparse
import json
from pathlib import Path

from ti26.data.schema import normalize_all
from ti26.data.snapshot import validate_snapshot

SCHEMA = "ti26.snapshot-lag.v1"
STATUS = "DIAGNOSTIC -- no threshold, gates nothing, cannot alter the card"

DAY_SECONDS = 86400


def _rate(maps: int, days: float) -> float:
    """Zero rather than ZeroDivisionError: a zero-day window is reportable."""
    return maps / days if days else 0.0


def snapshot_facts(raw_root: Path, sid: str) -> dict:
    """Every match id in a snapshot, plus the range its queries claimed to cover.

    Coverage comes from the manifest's query windows, not from the earliest and
    latest row observed. The distinction is the whole measurement: a snapshot
    whose newest day is empty still CLAIMED that day, and calling it uncovered
    would define the lag away.
    """
    chunks = validate_snapshot(raw_root, sid)
    manifest = json.loads((raw_root / sid / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest["entries"]

    matches: dict[int, int] = {}
    for chunk in chunks:
        rows, _ = normalize_all(list(chunk.rows))
        for row in rows:
            matches[row.match_id] = row.start_time

    return {
        "snapshot_id": sid,
        "retrieved_at": manifest["retrieved_at"],
        "covered_start": min(entry["start"] for entry in entries),
        "covered_end": max(entry["end"] for entry in entries),
        "matches": matches,
    }


def compare(older: dict, newer: dict, tail_days: int) -> dict:
    """Count the same calendar window in both snapshots, then again in its tail.

    Restricted to the overlap of the two coverage ranges. The snapshots are
    taken days apart over a rolling window, so their far ends differ by that
    much; counting outside the overlap would report a query-window difference
    as if it were data.
    """
    start = max(older["covered_start"], newer["covered_start"])
    end = min(older["covered_end"], newer["covered_end"])

    def within(facts: dict, since: int) -> set[int]:
        return {
            match_id
            for match_id, start_time in facts["matches"].items()
            if since <= start_time <= end
        }

    older_ids, newer_ids = within(older, start), within(newer, start)
    tail_since = end - tail_days * DAY_SECONDS
    older_tail, newer_tail = within(older, tail_since), within(newer, tail_since)

    overlap_days = (end - start) / DAY_SECONDS
    # Per-day counts across the tail, so a reader can see whether the added rows
    # pile up against the newest days (lag) or spread evenly (something else).
    daily = []
    for index in range(tail_days):
        day_end = end - index * DAY_SECONDS
        day_start = day_end - DAY_SECONDS
        in_day = {
            name: sum(
                1
                for match_id in ids
                if day_start < facts["matches"][match_id] <= day_end
            )
            for name, facts, ids in (
                ("older", older, older_tail),
                ("newer", newer, newer_tail),
            )
        }
        daily.append(
            {
                "days_before_window_end": index,
                "older_maps": in_day["older"],
                "newer_maps": in_day["newer"],
                "added_maps": in_day["newer"] - in_day["older"],
            }
        )

    return {
        "window": {
            "start": start,
            "end": end,
            "days": round(overlap_days, 1),
            "tail_days": tail_days,
        },
        "whole_window": {
            "older_maps": len(older_ids),
            "newer_maps": len(newer_ids),
            "added_maps": len(newer_ids - older_ids),
            # Never expected to be non-zero. A match the newer snapshot has
            # dropped would mean the source rewrote history, which is a bigger
            # problem than lag and must not be silently absorbed into a delta.
            "dropped_maps": len(older_ids - newer_ids),
        },
        "tail": {
            "older_maps": len(older_tail),
            "newer_maps": len(newer_tail),
            "added_maps": len(newer_tail - older_tail),
            "older_maps_per_day": _rate(len(older_tail), tail_days),
            "newer_maps_per_day": _rate(len(newer_tail), tail_days),
        },
        "baseline": {
            "newer_maps_per_day": _rate(len(newer_ids), overlap_days),
        },
        "daily": daily,
    }


def _observation_horizon_days(older: dict, newer: dict) -> float:
    """How long a backfill this comparison could have seen at all.

    The newer snapshot was taken a fixed time after the older one, so a row
    arriving later than that gap is invisible here and would be scored as
    "no lag". Reporting the gap turns that blind spot into a stated bound
    rather than an unstated assumption.
    """
    return round((newer["covered_end"] - older["covered_end"]) / DAY_SECONDS, 1)


def headline(comparison: dict, older: dict, newer: dict) -> dict:
    """The two ratios the question actually turns on, and what bounds them.

    `tail_backfill_share` is how much of the newer snapshot's tail had not
    arrived when the older one was taken -- the size of the lag. `tail_rate_ratio`
    is the tail's rate against the whole window's, measured on the NEWER
    snapshot, so lag is already corrected for: whatever thinness survives here
    is real.
    """
    tail, baseline = comparison["tail"], comparison["baseline"]
    return {
        "tail_backfill_share": (
            tail["added_maps"] / tail["newer_maps"] if tail["newer_maps"] else 0.0
        ),
        "tail_rate_ratio": (
            tail["newer_maps_per_day"] / baseline["newer_maps_per_day"]
            if baseline["newer_maps_per_day"]
            else 0.0
        ),
        "dropped_maps": comparison["whole_window"]["dropped_maps"],
        "observation_horizon_days": _observation_horizon_days(older, newer),
    }


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def render_markdown(payload: dict) -> str:
    comparison, head = payload["comparison"], payload["headline"]
    window, tail = comparison["window"], comparison["tail"]
    older, newer = payload["older"], payload["newer"]
    lines: list[str] = []
    add = lines.append

    add("# Snapshot lag")
    add("")
    add(f"**{payload['status']}**")
    add("")
    add(
        f"Older snapshot `{older['snapshot_id']}` retrieved {older['retrieved_at']}; "
        f"newer `{newer['snapshot_id']}` retrieved {newer['retrieved_at']}."
    )
    add("")
    add(
        f"Both counted over the same {window['days']} days of overlapping coverage, "
        f"with a {window['tail_days']}-day tail."
    )
    add("")
    add("## Headline")
    add("")
    add(
        f"- Of the newer snapshot's {tail['newer_maps']} maps in the tail, "
        f"**{_pct(head['tail_backfill_share'])}** were absent from the older one: "
        f"rows that had not arrived yet."
    )
    add(
        f"- Tail rate on the newer snapshot: **{tail['newer_maps_per_day']:.1f} maps/day** "
        f"against {comparison['baseline']['newer_maps_per_day']:.1f}/day over the whole "
        f"window — a ratio of **{head['tail_rate_ratio']:.2f}**. Lag is already "
        f"corrected for here, so this part is real."
    )
    add(
        f"- Maps present in the older snapshot and missing from the newer: "
        f"**{head['dropped_maps']}**. Anything but zero means the source rewrote "
        f"history and the rest of this report is not safe to read as lag."
    )
    add("")
    add(
        f"The two snapshots are **{head['observation_horizon_days']} days** apart, "
        f"which is the longest backfill this comparison can see. A row arriving "
        f"later than that is counted here as no lag at all."
    )

    add("")
    add("## Whole window")
    add("")
    add("| snapshot | maps |")
    add("|---|---|")
    add(f"| older | {comparison['whole_window']['older_maps']} |")
    add(f"| newer | {comparison['whole_window']['newer_maps']} |")
    add(f"| added | {comparison['whole_window']['added_maps']} |")

    add("")
    add(f"## The last {window['tail_days']} days, by day")
    add("")
    add("Day 0 is the last day both snapshots claim to cover.")
    add("")
    add("| days before window end | older | newer | added |")
    add("|---|---|---|---|")
    for row in comparison["daily"]:
        add(
            f"| {row['days_before_window_end']} | {row['older_maps']} | "
            f"{row['newer_maps']} | {row['added_maps']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", default="data/raw")
    parser.add_argument("--older", required=True, help="the earlier snapshot id")
    parser.add_argument("--newer", required=True, help="the later snapshot id")
    parser.add_argument("--tail-days", type=int, default=30)
    parser.add_argument("--out", default="reports/snapshot_lag")
    args = parser.parse_args(argv)

    raw_root = Path(args.raw)
    older = snapshot_facts(raw_root, args.older)
    newer = snapshot_facts(raw_root, args.newer)
    if older["retrieved_at"] >= newer["retrieved_at"]:
        raise SystemExit(
            f"--older ({older['retrieved_at']}) must have been retrieved before "
            f"--newer ({newer['retrieved_at']})"
        )

    comparison = compare(older, newer, args.tail_days)
    payload = {
        "schema": SCHEMA,
        "status": STATUS,
        "older": {key: older[key] for key in ("snapshot_id", "retrieved_at")},
        "newer": {key: newer[key] for key in ("snapshot_id", "retrieved_at")},
        "comparison": comparison,
        "headline": headline(comparison, older, newer),
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "snapshot_lag.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (out / "snapshot_lag.md").write_text(render_markdown(payload), encoding="utf-8")
    print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
