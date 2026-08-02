import pytest

from ti26.data.schema import MapRow
from ti26.roster import roster_version_id
from ti26.teams import (
    TeamEntry,
    UnresolvedTeamError,
    latest_rosters,
    load_teams,
    resolve_rosters,
    team_strengths,
)


def row(match_id, start_time, r_team, d_team, radiant, dire):
    return MapRow(
        match_id=match_id, start_time=start_time, duration=2000, radiant_win=True,
        league_id=1, tier="professional", radiant_team_id=r_team, dire_team_id=d_team,
        series_id=1, series_type=1, patch="7.41",
        radiant_accounts=tuple(radiant), dire_accounts=tuple(dire),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


A_OLD, A_NEW, B = [1, 2, 3, 4, 5], [1, 2, 3, 4, 9], [6, 7, 8, 9, 10]


def test_latest_roster_wins_over_an_earlier_one():
    """A team that substituted last week must be carried at its CURRENT
    roster, not the one that accumulated the rating."""
    rows = [row(1, 100, 10, 20, A_OLD, B), row(2, 200, 10, 20, A_NEW, B)]
    assert latest_rosters(rows, {})[10] == roster_version_id(A_NEW)


def test_aliases_are_applied_when_resolving():
    rows = [row(1, 100, 77, 20, A_NEW, B)]
    resolved = resolve_rosters(rows, [TeamEntry("Rebranded", 10)], {77: 10})
    assert resolved["Rebranded"] == roster_version_id(A_NEW)


def test_every_unresolved_team_is_reported_at_once():
    """Fifteen of sixteen resolving is not a partial success."""
    rows = [row(1, 100, 10, 20, A_NEW, B)]
    teams = [TeamEntry("Known", 10), TeamEntry("Ghost", 999), TeamEntry("Spectre", 998)]
    with pytest.raises(UnresolvedTeamError, match="2 of 3") as exc:
        resolve_rosters(rows, teams, {})
    assert "Ghost" in str(exc.value) and "Spectre" in str(exc.value)


def test_duplicate_names_or_ids_are_rejected(tmp_path):
    path = tmp_path / "teams.yaml"
    path.write_text("teams:\n  - {name: X, team_id: 1}\n  - {name: X, team_id: 2}\n")
    with pytest.raises(UnresolvedTeamError, match="duplicate team names"):
        load_teams(path)

    path.write_text("teams:\n  - {name: X, team_id: 1}\n  - {name: Y, team_id: 1}\n")
    with pytest.raises(UnresolvedTeamError, match="duplicate team_ids"):
        load_teams(path)


def test_unrated_rosters_get_the_average_prior_and_are_named():
    resolved = {"Rated": "aaa", "New": "bbb"}
    strengths, prior_driven = team_strengths(resolved, {"aaa": 0.7})
    assert strengths == {"Rated": 0.7, "New": 0.0}
    assert prior_driven == ["New"], "spec III: prior-driven teams must be reported"
