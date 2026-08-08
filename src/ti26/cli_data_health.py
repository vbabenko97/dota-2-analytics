"""What the training corpus actually contains, measured rather than assumed.

Every other producer here asks whether the MODEL is any good. This one asks
whether the DATA underneath it can support the question being put to it, which
is a different failure and an invisible one: a rating fit succeeds, reports a
number for all sixteen teams and says nothing about the fact that one of them
has twenty-seven maps behind it and another has three hundred and seventy-six.

It exists because the weaknesses documentation needed these numbers and the
project's own rule forbids publishing a number no producer emits. Prose that
says "most of the corpus is low tier" rots silently against a re-ingest; a
table regenerated from the store does not.

Four questions, each with a way of being wrong that the gates cannot see:

  TIER MIX      The event being forecast is `premium`. If the corpus is mostly
                `excluded` and `professional`, the model is calibrated on a
                different population than the one it is asked about, and no
                amount of out-of-sample rigour inside that population detects
                it -- the backtest folds inherit the same mix.
  PATCH MIX     Dota is not a stationary game. Rows from a superseded patch
                describe a game that no longer exists, and nothing in the
                rating models consults `patch`, so they are pooled as if it
                did.
  RECENCY       Teams stop playing publicly before a major. The evidence that
                matters most is therefore the thinnest, and Glicko answers
                idleness by inflating RD -- which `strengths()` discards.
  PER-TEAM      Roster-level volume, RD and idleness for the configured field.
                An unequal field is not a bug, but a point estimate presented
                with equal authority for a 27-map roster and a 376-map one is.

DIAGNOSTIC. No threshold, gates nothing, cannot alter the shipping card.
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from ti26.data.schema import MapRow
from ti26.data.store import load_rows, open_store
from ti26.ratings.glicko import GlickoModel
from ti26.roster import RosterIndex, load_aliases, roster_version_id
from ti26.teams import load_teams, resolve_rosters

SCHEMA = "ti26.data-health.v1"
STATUS = "DIAGNOSTIC -- no threshold, gates nothing, cannot alter the card"

# The tier the forecast target is played at. Named once so the share below is
# derived from it rather than from a literal repeated in the report.
TARGET_TIER = "premium"

# Windows for the recency table. The shortest one matters most and is usually
# the emptiest, which is the point of showing them together.
RECENCY_WINDOWS_DAYS = (30, 60, 90, 180, 365)

DAY_SECONDS = 86400


def _share(part: int, whole: int) -> float:
    """Zero rather than ZeroDivisionError: an empty store is a reportable state."""
    return part / whole if whole else 0.0


def corpus_facts(rows: Sequence[MapRow]) -> dict:
    """Tier, patch, recency and exclusion mix over the whole store."""
    total = len(rows)
    last = max((r.start_time for r in rows), default=0)
    first = min((r.start_time for r in rows), default=0)

    tiers: dict[str, int] = {}
    patches: dict[str, dict] = {}
    # How many DISTINCT events supply the target tier, not just how many maps.
    # A tier share is easy to misread as breadth: 144 maps sounds like thin
    # coverage of several events, and is in fact total coverage of one.
    target_leagues: dict[object, dict] = {}
    for row in rows:
        tier = row.tier or "unknown"
        tiers[tier] = tiers.get(tier, 0) + 1
        patch = row.patch or "unknown"
        seen = patches.setdefault(patch, {"maps": 0, "last_start_time": 0})
        seen["maps"] += 1
        seen["last_start_time"] = max(seen["last_start_time"], row.start_time)
        if tier == TARGET_TIER:
            league = target_leagues.setdefault(
                row.league_id, {"maps": 0, "first_start_time": row.start_time, "last_start_time": 0}
            )
            league["maps"] += 1
            league["first_start_time"] = min(league["first_start_time"], row.start_time)
            league["last_start_time"] = max(league["last_start_time"], row.start_time)

    return {
        "rows": total,
        "first_start_time": first,
        "last_start_time": last,
        "span_days": round((last - first) / DAY_SECONDS, 1),
        "tier_mix": [
            {"tier": tier, "maps": maps, "share": _share(maps, total)}
            for tier, maps in sorted(tiers.items(), key=lambda kv: -kv[1])
        ],
        "patch_mix": [
            {
                "patch": patch,
                "maps": seen["maps"],
                "share": _share(seen["maps"], total),
                "last_start_time": seen["last_start_time"],
            }
            for patch, seen in sorted(
                patches.items(), key=lambda kv: -kv[1]["last_start_time"]
            )
        ],
        "recency": [
            {
                "window_days": days,
                "maps": (n := sum(1 for r in rows if r.start_time > last - days * DAY_SECONDS)),
                "share": _share(n, total),
            }
            for days in RECENCY_WINDOWS_DAYS
        ],
        "target_tier_leagues": [
            {
                "league_id": league_id,
                "maps": seen["maps"],
                "first_start_time": seen["first_start_time"],
                "last_start_time": seen["last_start_time"],
            }
            for league_id, seen in sorted(target_leagues.items(), key=lambda kv: -kv[1]["maps"])
        ],
        "unrateable": {
            "null_team": (nt := sum(1 for r in rows if r.has_null_team)),
            "bad_roster": (br := sum(1 for r in rows if r.has_bad_roster)),
            "share_null_team": _share(nt, total),
            "share_bad_roster": _share(br, total),
        },
    }


def field_facts(rows: Sequence[MapRow], teams_path: str, aliases_path: str, tau: float) -> dict:
    """Per-team volume, RD, strength and idleness for the CURRENT roster.

    Keyed on `roster_version_id`, not on `team_id`, because that is the
    identity the rating model itself uses. Counting by organisation would
    credit a roster with maps its current five never played, which is the
    specific error the roster-continuity design exists to avoid.
    """
    aliases = load_aliases(aliases_path)
    teams = load_teams(teams_path)

    model = GlickoModel(tau=tau, roster_index=RosterIndex(aliases))
    for row in rows:
        model.update(row)
    model.flush()

    strengths = model.strengths()
    activity = {entry["roster_version_id"]: entry for entry in model.activity_report()}
    resolved = resolve_rosters(rows, teams, aliases)
    last_overall = max((r.start_time for r in rows), default=0)

    # One pass over the store per side, rather than a query per team: the
    # roster ids are hashes, so this cannot be pushed into SQL.
    last_seen: dict[str, int] = {}
    tier_counts: dict[str, dict[str, int]] = {}
    wanted = set(resolved.values())
    for row in rows:
        for accounts in (row.radiant_accounts, row.dire_accounts):
            rvid = roster_version_id(accounts)
            if rvid not in wanted:
                continue
            last_seen[rvid] = max(last_seen.get(rvid, 0), row.start_time)
            by_tier = tier_counts.setdefault(rvid, {})
            tier = row.tier or "unknown"
            by_tier[tier] = by_tier.get(tier, 0) + 1

    entries = []
    for name, rvid in sorted(resolved.items()):
        seen = activity.get(rvid, {})
        by_tier = tier_counts.get(rvid, {})
        entries.append(
            {
                "team": name,
                "roster_version_id": rvid,
                "roster_maps": seen.get("total_maps", 0),
                "rd": seen.get("rd"),
                "raw_strength": strengths.get(rvid, 0.0),
                "target_tier_maps": by_tier.get(TARGET_TIER, 0),
                "days_since_last_map": (
                    round((last_overall - last_seen[rvid]) / DAY_SECONDS, 1)
                    if rvid in last_seen
                    else None
                ),
            }
        )
    return {"teams": entries}


def headline(corpus: dict, field: dict, thin_roster_maps: int) -> dict:
    """The comparisons a reader would otherwise have to do by hand.

    `thin_roster_maps` is a reporting cut only. It selects which rows get
    counted into `teams_below_thin_threshold`; it gates nothing and no
    downstream code branches on it.
    """
    volumes = [t["roster_maps"] for t in field["teams"]]
    rds = [t["rd"] for t in field["teams"] if t["rd"] is not None]
    tier_share = {row["tier"]: row["share"] for row in corpus["tier_mix"]}
    newest_patch = corpus["patch_mix"][0] if corpus["patch_mix"] else None

    return {
        "target_tier": TARGET_TIER,
        "target_tier_share": tier_share.get(TARGET_TIER, 0.0),
        "target_tier_events": len(corpus["target_tier_leagues"]),
        "newest_patch": newest_patch["patch"] if newest_patch else None,
        "newest_patch_share": newest_patch["share"] if newest_patch else 0.0,
        "roster_maps_min": min(volumes, default=0),
        "roster_maps_max": max(volumes, default=0),
        "roster_maps_ratio": (
            max(volumes) / min(volumes) if volumes and min(volumes) else None
        ),
        "rd_min": min(rds, default=None),
        "rd_max": max(rds, default=None),
        "rd_ratio": (max(rds) / min(rds) if rds and min(rds) else None),
        "thin_roster_threshold_maps": thin_roster_maps,
        "teams_below_thin_threshold": sum(1 for v in volumes if v < thin_roster_maps),
        "teams_with_no_target_tier_maps": sum(
            1 for t in field["teams"] if t["target_tier_maps"] == 0
        ),
    }


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def render_markdown(payload: dict) -> str:
    corpus, field, head = payload["corpus"], payload["field"], payload["headline"]
    lines: list[str] = []
    add = lines.append

    add("# Data health")
    add("")
    add(f"**{payload['status']}**")
    add("")
    add(f"Store: `{payload['store']}`, {corpus['rows']} maps over {corpus['span_days']} days.")
    add("")
    add("## Headline")
    add("")
    league_ids = ", ".join(str(row["league_id"]) for row in corpus["target_tier_leagues"])
    add(
        f"- Maps at the forecast target's own tier (`{head['target_tier']}`): "
        f"**{_pct(head['target_tier_share'])}** of the corpus, from "
        f"**{head['target_tier_events']} distinct event(s)** (league ids: {league_ids})."
    )
    add(
        f"- Maps on the newest patch (`{head['newest_patch']}`): "
        f"**{_pct(head['newest_patch_share'])}** of the corpus."
    )
    # A field can legitimately be empty here -- `corpus_facts` is useful on its
    # own, and the store may predate a qualifier. Report that rather than
    # formatting `None`.
    if field["teams"]:
        spread = (
            f", a {head['roster_maps_ratio']:.1f}x spread." if head["roster_maps_ratio"] else "."
        )
        add(
            f"- Current-roster volume across the field: "
            f"**{head['roster_maps_min']} to {head['roster_maps_max']} maps**{spread}"
        )
        rd_spread = f", a {head['rd_ratio']:.2f}x spread." if head["rd_ratio"] else "."
        rd_range = (
            f"**{head['rd_min']:.1f} to {head['rd_max']:.1f}**"
            if head["rd_min"] is not None
            else "**not rated**"
        )
        add(f"- Rating deviation across the field: {rd_range}{rd_spread}")
        add(
            f"- Teams under {head['thin_roster_threshold_maps']} maps on their current "
            f"roster: **{head['teams_below_thin_threshold']}**."
        )
        add(
            f"- Teams with zero `{head['target_tier']}` maps on their current roster: "
            f"**{head['teams_with_no_target_tier_maps']}**."
        )
    else:
        add("- No configured field resolved against this store.")

    add("")
    add("## Tier mix")
    add("")
    add("| tier | maps | share |")
    add("|---|---|---|")
    for row in corpus["tier_mix"]:
        add(f"| {row['tier']} | {row['maps']} | {_pct(row['share'])} |")

    add("")
    add("## Patch mix (most recent first)")
    add("")
    add("| patch | maps | share |")
    add("|---|---|---|")
    for row in corpus["patch_mix"]:
        add(f"| {row['patch']} | {row['maps']} | {_pct(row['share'])} |")

    add("")
    add("## Recency")
    add("")
    add("| window | maps | share of corpus |")
    add("|---|---|---|")
    for row in corpus["recency"]:
        add(f"| last {row['window_days']} days | {row['maps']} | {_pct(row['share'])} |")

    add("")
    add("## Rows the model declines to rate")
    add("")
    unrateable = corpus["unrateable"]
    add(f"- `null_team`: {unrateable['null_team']} ({_pct(unrateable['share_null_team'])})")
    add(f"- `bad_roster`: {unrateable['bad_roster']} ({_pct(unrateable['share_bad_roster'])})")

    add("")
    add("## The field, by current roster")
    add("")
    add(
        "Sorted by volume, thinnest first. `raw_strength` is pre-calibration and "
        "zero-centred over every roster in the store, not over these sixteen."
    )
    add("")
    add(f"| team | roster maps | RD | raw strength | `{head['target_tier']}` maps | days idle |")
    add("|---|---|---|---|---|---|")
    for team in sorted(field["teams"], key=lambda t: t["roster_maps"]):
        rd = f"{team['rd']:.1f}" if team["rd"] is not None else "--"
        idle = "--" if team["days_since_last_map"] is None else f"{team['days_since_last_map']:.1f}"
        add(
            f"| {team['team']} | {team['roster_maps']} | {rd} | "
            f"{team['raw_strength']:.3f} | {team['target_tier_maps']} | {idle} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default="data/processed/d2.sqlite")
    parser.add_argument("--teams", default="config/ti2026_teams.yaml")
    parser.add_argument("--aliases", default="config/team_aliases.yaml")
    parser.add_argument("--tau", type=float, default=0.5)
    parser.add_argument("--thin-roster-maps", type=int, default=50)
    parser.add_argument("--out", default="reports/data_health")
    args = parser.parse_args(argv)

    connection = open_store(args.store)
    try:
        rows = load_rows(connection)
    finally:
        connection.close()
    if not rows:
        raise SystemExit(f"{args.store} is empty; run `python -m ti26.cli_ingest` first")

    corpus = corpus_facts(rows)
    field = field_facts(rows, args.teams, args.aliases, args.tau)
    payload = {
        "schema": SCHEMA,
        "status": STATUS,
        "store": args.store,
        "corpus": corpus,
        "field": field,
        "headline": headline(corpus, field, args.thin_roster_maps),
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "data_health.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (out / "data_health.md").write_text(render_markdown(payload), encoding="utf-8")
    print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
