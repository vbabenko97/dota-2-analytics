"""Does the snapshot-lag comparison measure lag, or define it away?

Every test here builds two synthetic snapshots whose difference is known
exactly, because the producer's whole job is to attribute a difference between
two real snapshots to one of two causes.
"""

import json

import pytest

from ti26.cli_snapshot_lag import compare, headline, main, snapshot_facts
from ti26.data.snapshot import sha256_file, write_manifest, write_snapshot

DAY = 86400
# An arbitrary fixed epoch. Nothing depends on the calendar date; the tests are
# written in offsets from `END` so a reader can see the window structure.
END = 1_786_000_000
RADIANT_SLOTS = [0, 1, 2, 3, 4]
DIRE_SLOTS = [128, 129, 130, 131, 132]


def raw_map(match_id: int, start_time: int) -> dict:
    return {
        "match_id": match_id,
        "start_time": start_time,
        "duration": 2000,
        "radiant_win": True,
        "leagueid": 20009,
        "tier": "professional",
        "radiant_team_id": 1,
        "dire_team_id": 2,
        "series_id": 5,
        "series_type": 1,
        "patch": "7.41",
        "accounts": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "heroes": [11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
        "slots": RADIANT_SLOTS + DIRE_SLOTS,
    }


def build_snapshot(root, sid, rows, *, start, end, retrieved_at):
    """Write one chunk plus its manifest, exactly as `cli_ingest` would."""
    path = write_snapshot(root, sid, "chunk", rows)
    entry = {
        "name": "chunk",
        "rows": len(rows),
        "start": start,
        "end": end,
        "query": "select 1",
        "sha256": sha256_file(path),
    }
    write_manifest(root, sid, [entry], retrieved_at=retrieved_at)
    return sid


def two_snapshots(root, *, older_rows, newer_rows, older_end=END, newer_end=END + 5 * DAY):
    older = build_snapshot(
        root,
        "20260802T000000Z",
        older_rows,
        start=END - 100 * DAY,
        end=older_end,
        retrieved_at="2026-08-02T00:00:00Z",
    )
    newer = build_snapshot(
        root,
        "20260807T000000Z",
        newer_rows,
        start=END - 100 * DAY,
        end=newer_end,
        retrieved_at="2026-08-07T00:00:00Z",
    )
    return snapshot_facts(root, older), snapshot_facts(root, newer)


def test_a_row_the_older_snapshot_lacked_is_counted_as_added_not_dropped(tmp_path):
    """Kills mutation: swap the operands to `added_maps = len(newer - older)`.

    Under the swap the backfilled row scores as `dropped_maps`, which the
    report reads as the source having rewritten history -- the opposite
    conclusion from the same bytes.
    """
    shared = [raw_map(1, END - 10 * DAY), raw_map(2, END - 2 * DAY)]
    older, newer = two_snapshots(
        tmp_path, older_rows=shared, newer_rows=[*shared, raw_map(3, END - DAY // 2)]
    )
    result = compare(older, newer, tail_days=30)
    assert result["whole_window"]["added_maps"] == 1
    assert result["whole_window"]["dropped_maps"] == 0


def test_a_row_missing_from_the_newer_snapshot_is_reported_not_absorbed(tmp_path):
    """Kills mutation: report `dropped_maps` as a constant 0.

    A match that disappears between snapshots means the source rewrote
    history. Netting it against the additions would hide it inside a delta
    that still looks like ordinary lag.
    """
    older, newer = two_snapshots(
        tmp_path,
        older_rows=[raw_map(1, END - 10 * DAY), raw_map(2, END - 2 * DAY)],
        newer_rows=[raw_map(1, END - 10 * DAY)],
    )
    result = compare(older, newer, tail_days=30)
    assert result["whole_window"]["dropped_maps"] == 1
    assert headline(result, older, newer)["dropped_maps"] == 1


def test_counting_is_restricted_to_the_overlap_of_the_two_coverage_ranges(tmp_path):
    """Kills mutation: use the older snapshot's window instead of the overlap.

    The snapshots roll an 18-month window forward, so the newer one starts
    later and ends later. Counting over either snapshot's own range reports a
    query-window difference as data: rows before the newer snapshot's start
    become phantom `dropped_maps`, and rows after the older one's end become
    phantom lag.
    """
    old_row = raw_map(1, END - 90 * DAY)
    newer_only_future = raw_map(9, END + 2 * DAY)
    older = build_snapshot(
        tmp_path,
        "20260802T000000Z",
        [old_row, raw_map(2, END - DAY)],
        start=END - 100 * DAY,
        end=END,
        retrieved_at="2026-08-02T00:00:00Z",
    )
    newer = build_snapshot(
        tmp_path,
        "20260807T000000Z",
        [raw_map(2, END - DAY), newer_only_future],
        start=END - 80 * DAY,
        end=END + 5 * DAY,
        retrieved_at="2026-08-07T00:00:00Z",
    )
    result = compare(snapshot_facts(tmp_path, older), snapshot_facts(tmp_path, newer), 30)

    assert result["window"]["start"] == END - 80 * DAY
    assert result["window"]["end"] == END
    # match 1 predates the newer snapshot's coverage; match 9 postdates the
    # older snapshot's. Neither is evidence about lag.
    assert result["whole_window"]["dropped_maps"] == 0
    assert result["whole_window"]["added_maps"] == 0


def test_coverage_comes_from_the_manifest_not_from_the_last_row_observed(tmp_path):
    """Kills mutation: set `covered_end` to `max(row.start_time)`.

    That mutation defines the lag away. The newest days are exactly the ones a
    snapshot claims and has not yet received; ending the window at the last row
    present means the empty tail is never counted, and a snapshot missing its
    final three days scores as complete.
    """
    sid = build_snapshot(
        tmp_path,
        "20260802T000000Z",
        [raw_map(1, END - 10 * DAY)],
        start=END - 100 * DAY,
        end=END,
        retrieved_at="2026-08-02T00:00:00Z",
    )
    facts = snapshot_facts(tmp_path, sid)
    assert facts["covered_end"] == END
    assert max(facts["matches"].values()) == END - 10 * DAY


def test_the_tail_rate_ratio_is_measured_on_the_newer_snapshot(tmp_path):
    """Kills mutation: compute `tail_rate_ratio` from the older snapshot's tail.

    The ratio's whole purpose is to state the thinness that SURVIVES the lag
    correction. Taking it from the older snapshot re-introduces the lag it was
    built to remove, so a purely lag-driven dip would be reported as real.
    """
    # Dense history, thin tail, and the newer snapshot has backfilled the tail
    # to exactly the same density as the history.
    history = [raw_map(100 + i, END - (40 + i) * DAY) for i in range(20)]
    tail_late = [raw_map(200 + i, END - 5 * DAY) for i in range(20)]
    older, newer = two_snapshots(
        tmp_path, older_rows=history, newer_rows=[*history, *tail_late]
    )
    head = headline(compare(older, newer, tail_days=30), older, newer)
    assert head["tail_backfill_share"] == 1.0
    # 20 maps over 30 tail days against 40 over the 100-day overlap.
    assert head["tail_rate_ratio"] == pytest.approx((20 / 30) / (40 / 100))


def test_the_observation_horizon_is_the_gap_between_the_two_coverage_ends(tmp_path):
    """Kills mutation: derive the horizon from `covered_start` instead.

    The horizon states how long a backfill this comparison could see at all.
    Both snapshots roll the same window, so their starts move together and the
    mutated value stays near zero -- reporting that the measurement can see
    nothing, while the report still draws conclusions from it.
    """
    older, newer = two_snapshots(
        tmp_path,
        older_rows=[raw_map(1, END - DAY)],
        newer_rows=[raw_map(1, END - DAY)],
        newer_end=END + 5 * DAY,
    )
    assert headline(compare(older, newer, 30), older, newer)["observation_horizon_days"] == 5.0


def test_main_refuses_a_pair_given_in_the_wrong_order(tmp_path):
    """Kills mutation: drop the retrieved_at ordering check in `main`.

    Swapping the arguments inverts every difference: the backfilled rows become
    dropped rows, and the report then claims the source rewrote history. The
    ordering is not recoverable from the numbers afterwards, so it has to be
    refused up front.
    """
    shared = [raw_map(1, END - 10 * DAY)]
    two_snapshots(tmp_path, older_rows=shared, newer_rows=[*shared, raw_map(2, END - DAY)])
    with pytest.raises(SystemExit, match="retrieved before"):
        main(
            [
                "--raw", str(tmp_path),
                "--older", "20260807T000000Z",
                "--newer", "20260802T000000Z",
                "--out", str(tmp_path / "out"),
            ]
        )


def test_main_writes_both_artifacts_with_the_diagnostic_status(tmp_path):
    """Kills mutation: drop `status` from the payload.

    A reader who finds this report in a bundle must be able to tell from the
    file alone that it gates nothing. The project's standing rule is that a
    diagnostic says so in its own output.
    """
    shared = [raw_map(1, END - 10 * DAY)]
    two_snapshots(tmp_path, older_rows=shared, newer_rows=[*shared, raw_map(2, END - DAY)])
    out = tmp_path / "out"
    assert (
        main(
            [
                "--raw", str(tmp_path),
                "--older", "20260802T000000Z",
                "--newer", "20260807T000000Z",
                "--out", str(out),
            ]
        )
        == 0
    )
    payload = json.loads((out / "snapshot_lag.json").read_text())
    assert payload["status"].startswith("DIAGNOSTIC")
    assert "DIAGNOSTIC" in (out / "snapshot_lag.md").read_text(encoding="utf-8")
