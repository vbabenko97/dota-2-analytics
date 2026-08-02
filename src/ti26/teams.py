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


def latest_rosters(
    rows: Sequence[MapRow], aliases: Mapping[int, int]
) -> dict[int, str]:
    """Most recently fielded roster per canonical team id."""
    latest: dict[int, tuple[int, str]] = {}
    for row in sorted(rows, key=lambda r: (r.start_time, r.match_id)):
        for team_id, accounts in (
            (row.radiant_team_id, row.radiant_accounts),
            (row.dire_team_id, row.dire_accounts),
        ):
            canonical = canonical_team_id(team_id, dict(aliases))
            if canonical is None:
                continue
            latest[canonical] = (row.start_time, roster_version_id(accounts))
    return {team_id: rvid for team_id, (_, rvid) in latest.items()}


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
