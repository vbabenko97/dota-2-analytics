"""Resolve the 16 configured Swiss-stage teams to rosters and strengths.

D1's card generator takes a strength per team name. This is the bridge from
rating-space (keyed by roster hash) to card-space (keyed by the names a human
types into Valve's form).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from ti26.data.schema import MapRow
from ti26.roster import canonical_team_id, roster_version_id


@dataclass(frozen=True)
class TeamEntry:
    name: str
    team_id: int


class UnresolvedTeamError(ValueError):
    """A configured team could not be tied to any roster in the store."""


def load_teams(path: str | Path) -> list[TeamEntry]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    entries = data.get("teams") or []
    teams = [TeamEntry(name=str(e["name"]), team_id=int(e["team_id"])) for e in entries]
    names = [t.name for t in teams]
    if len(set(names)) != len(names):
        raise UnresolvedTeamError(f"duplicate team names in {path}: {names}")
    ids = [t.team_id for t in teams]
    if len(set(ids)) != len(ids):
        raise UnresolvedTeamError(f"duplicate team_ids in {path}: {ids}")
    return teams


def _latest_roster_accounts(
    rows: Sequence[MapRow], aliases: Mapping[int, int]
) -> dict[int, tuple[int, tuple[int, ...]]]:
    """Most recently fielded (start_time, accounts) per canonical team id.

    Shared by `latest_rosters` (which only needs the hash) and
    `check_roster_staleness` (which needs the actual accounts to compute
    overlap with a candidate migration target).
    """
    latest: dict[int, tuple[int, tuple[int, ...]]] = {}
    for row in sorted(rows, key=lambda r: (r.start_time, r.match_id)):
        for team_id, accounts in (
            (row.radiant_team_id, row.radiant_accounts),
            (row.dire_team_id, row.dire_accounts),
        ):
            canonical = canonical_team_id(team_id, dict(aliases))
            if canonical is None:
                continue
            latest[canonical] = (row.start_time, tuple(accounts))
    return latest


def latest_rosters(
    rows: Sequence[MapRow], aliases: Mapping[int, int]
) -> dict[int, str]:
    """Most recently fielded roster per canonical team id."""
    return {
        team_id: roster_version_id(accounts)
        for team_id, (_, accounts) in _latest_roster_accounts(rows, aliases).items()
    }


def resolve_rosters(
    rows: Sequence[MapRow], teams: Sequence[TeamEntry], aliases: Mapping[int, int]
) -> dict[str, str]:
    """Map each configured team name to its current roster_version_id.

    Raises listing EVERY unresolved team at once. Resolving fifteen of sixteen
    and silently defaulting the last would put a prior-driven team on the card
    with no indication it was guessed.
    """
    current = latest_rosters(rows, aliases)
    resolved, missing = {}, []
    for team in teams:
        canonical = canonical_team_id(team.team_id, dict(aliases))
        if canonical is None or canonical not in current:
            missing.append(f"{team.name} (team_id={team.team_id})")
            continue
        resolved[team.name] = current[canonical]
    if missing:
        raise UnresolvedTeamError(
            f"{len(missing)} of {len(teams)} teams have no maps in the store: "
            + "; ".join(missing)
        )
    return resolved


def team_strengths(
    resolved: Mapping[str, str], strengths: Mapping[str, float]
) -> tuple[dict[str, float], list[str]]:
    """Attach a fitted strength to each team; report which fell back to the prior.

    A zero-centred logit strength of 0.0 IS the average-team prior, so an
    unrated roster is not an error — but it must be named, per spec III's
    requirement to report which teams are prior-driven.
    """
    out, prior_driven = {}, []
    for name, rvid in resolved.items():
        if rvid in strengths:
            out[name] = float(strengths[rvid])
        else:
            out[name] = 0.0
            prior_driven.append(name)
    return out, sorted(prior_driven)


DAY_SECONDS = 86400

# A migration candidate needs at least this many of the 5 accounts shared
# with the configured roster. 5/5 is an exact match; 4/5 catches a roster
# change happening AT THE SAME TIME as an org move (one sub plus a new
# team_id), which an exact-match-only search would miss entirely.
MIN_MIGRATION_OVERLAP = 4


@dataclass(frozen=True)
class RosterStaleness:
    """Per-team staleness/migration diagnostic (see `check_roster_staleness`).

    `last_map_at` is THIS roster's most recent map under the CONFIGURED
    (canonical) team_id specifically -- not the roster's global last map,
    which is exactly the distinction a migration search depends on.
    `migrated_to`/`migrated_at`/`migrated_overlap` are all `None` together
    when no later occurrence under a different id was found.
    """

    name: str
    team_id: int
    roster_version_id: str
    last_map_at: int
    stale_days: float
    migrated_to: int | None
    migrated_at: int | None
    migrated_overlap: int | None


def check_roster_staleness(
    rows: Sequence[MapRow], teams: Sequence[TeamEntry], aliases: Mapping[int, int]
) -> list[RosterStaleness]:
    """Detect a configured team whose org has moved to a new, unaliased
    team_id -- the exact failure mode that put a stale Tundra Esports/1win
    roster in `ti2026_teams.yaml` until a human fact-check caught it by
    hand. TI 2026's Swiss stage locks 2026-08-13; this is meant to run on
    every `cli_d2` invocation between now and then, not just once.

    Two signals, both cheap because the accounts are already in memory:

    1. Forward migration search: does the SAME roster (exact
       roster_version_id match, or >=4 of 5 accounts shared -- catching a
       simultaneous roster-and-org change) appear under a DIFFERENT
       canonical team_id, AFTER this team's configured id last fielded it?
       An exact match is preferred when both exist; only the EARLIEST hit
       of the preferred kind is reported, since that is the moment the
       migration first became visible.
    2. Plain staleness: `stale_days` since this roster's last map, relative
       to the store's own most recent map overall. A roster that simply
       stopped playing is a different, non-migration problem from one that
       moved somewhere this config doesn't point at.

    This does NOT try to tell a genuine org migration (Tundra -> 1win)
    apart from a harmless duplicate OpenDota team_id registration for the
    SAME org (confirmed for Xtreme Gaming, HULIGANI, Team Resilience in
    `ti2026_teams.yaml`'s ledger) -- that distinction rests on the
    organization's real-world identity, which this store does not carry
    (team names require a separate, network `teams` table query; this
    function is offline, like everything except `data/opendota.py`). Both
    produce the IDENTICAL signature: same roster, later map, different
    unaliased id. Both are reported here; a human cross-checks each hit
    against what is already documented before treating it as new news --
    which is exactly how the Tundra entry was found and fixed.
    """
    aliases = dict(aliases)
    ordered = sorted(rows, key=lambda r: (r.start_time, r.match_id))
    store_last_map = ordered[-1].start_time if ordered else 0

    fielded: list[tuple[int | None, tuple[int, ...], int]] = []
    for r in ordered:
        fielded.append((canonical_team_id(r.radiant_team_id, aliases), r.radiant_accounts, r.start_time))
        fielded.append((canonical_team_id(r.dire_team_id, aliases), r.dire_accounts, r.start_time))

    latest = _latest_roster_accounts(rows, aliases)

    checks = []
    for team in teams:
        canonical = canonical_team_id(team.team_id, aliases)
        if canonical is None or canonical not in latest:
            continue  # resolve_rosters already raises for this; nothing more to add
        last_ts, accounts = latest[canonical]
        rvid = roster_version_id(accounts)
        core = {a for a in accounts if a >= 0}

        best_exact: tuple[int, int] | None = None  # (start_time, other_canonical)
        best_partial: tuple[int, int, int] | None = None  # (start_time, other_canonical, overlap)
        for other_canonical, other_accounts, ts in fielded:
            if other_canonical is None or other_canonical == canonical or ts <= last_ts:
                continue
            if roster_version_id(other_accounts) == rvid:
                if best_exact is None or ts < best_exact[0]:
                    best_exact = (ts, other_canonical)
            else:
                overlap = len(core & {a for a in other_accounts if a >= 0})
                if overlap >= MIN_MIGRATION_OVERLAP and (best_partial is None or ts < best_partial[0]):
                    best_partial = (ts, other_canonical, overlap)

        if best_exact is not None:
            migrated_at, migrated_to, migrated_overlap = best_exact[0], best_exact[1], 5
        elif best_partial is not None:
            migrated_at, migrated_to, migrated_overlap = best_partial
        else:
            migrated_at = migrated_to = migrated_overlap = None

        checks.append(
            RosterStaleness(
                name=team.name,
                team_id=team.team_id,
                roster_version_id=rvid,
                last_map_at=last_ts,
                stale_days=(store_last_map - last_ts) / DAY_SECONDS,
                migrated_to=migrated_to,
                migrated_at=migrated_at,
                migrated_overlap=migrated_overlap,
            )
        )
    return checks
