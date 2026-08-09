# Snapshot lag

**DIAGNOSTIC -- no threshold, gates nothing, cannot alter the card**

Older snapshot `20260802T165535Z` retrieved 2026-08-02T16:55:35Z; newer `20260807T182355Z` retrieved 2026-08-07T18:23:55.987711Z.

Both counted over the same 540.0 days of overlapping coverage, with a 30-day tail.

## Headline

- Of the newer snapshot's 421 maps in the tail, **0.7%** were absent from the older one: rows that had not arrived yet.
- Tail rate on the newer snapshot: **14.0 maps/day** against 76.2/day over the whole window — a ratio of **0.18**. Lag is already corrected for here, so this part is real.
- Maps present in the older snapshot and missing from the newer: **0**. Anything but zero means the source rewrote history and the rest of this report is not safe to read as lag.

The two snapshots are **5.1 days** apart, which is the longest backfill this comparison can see. A row arriving later than that is counted here as no lag at all.

## Whole window

| snapshot | maps |
|---|---|
| older | 41140 |
| newer | 41143 |
| added | 3 |

## The last 30 days, by day

Day 0 is the last day both snapshots claim to cover.

| days before window end | older | newer | added |
|---|---|---|---|
| 0 | 22 | 25 | 3 |
| 1 | 42 | 42 | 0 |
| 2 | 37 | 37 | 0 |
| 3 | 28 | 28 | 0 |
| 4 | 15 | 15 | 0 |
| 5 | 23 | 23 | 0 |
| 6 | 8 | 8 | 0 |
| 7 | 11 | 11 | 0 |
| 8 | 10 | 10 | 0 |
| 9 | 15 | 15 | 0 |
| 10 | 14 | 14 | 0 |
| 11 | 11 | 11 | 0 |
| 12 | 11 | 11 | 0 |
| 13 | 9 | 9 | 0 |
| 14 | 5 | 5 | 0 |
| 15 | 5 | 5 | 0 |
| 16 | 4 | 4 | 0 |
| 17 | 5 | 5 | 0 |
| 18 | 10 | 10 | 0 |
| 19 | 7 | 7 | 0 |
| 20 | 0 | 0 | 0 |
| 21 | 12 | 12 | 0 |
| 22 | 18 | 18 | 0 |
| 23 | 24 | 24 | 0 |
| 24 | 25 | 25 | 0 |
| 25 | 27 | 27 | 0 |
| 26 | 17 | 17 | 0 |
| 27 | 0 | 0 | 0 |
| 28 | 0 | 0 | 0 |
| 29 | 3 | 3 | 0 |
