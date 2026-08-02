import pytest

from ti26.data.schema import MapRow
from ti26.roster import roster_version_id
from ti26.teams import (
    DAY_SECONDS,
    TeamEntry,
    UnresolvedTeamError,
    check_roster_staleness,
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
    roster, not the one that accumulated the rating.

    List order is the REVERSE of chronological (start_time) order on
    purpose: `latest_rosters` must sort by start_time itself rather than
    trust input order. A fixture where the two orders coincide (as an
    earlier version of this test had, list order == chronological order)
    cannot tell a real sort from a no-op -- confirmed by mutation below.
    """
    rows = [row(2, 200, 10, 20, A_NEW, B), row(1, 100, 10, 20, A_OLD, B)]
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
    """Two unrated teams, inserted in REVERSE-alphabetical order, so the
    `sorted(prior_driven)` in `team_strengths` is actually exercised. A
    single-entry prior_driven list (as an earlier version of this test
    had) makes `sorted([x]) == [x]` trivially true regardless of whether
    the sort is even called -- this fixture cannot make that mistake.
    """
    resolved = {"Rated": "aaa", "Zebra": "ccc", "Apple": "ddd"}
    strengths, prior_driven = team_strengths(resolved, {"aaa": 0.7})
    assert strengths == {"Rated": 0.7, "Zebra": 0.0, "Apple": 0.0}
    assert prior_driven == ["Apple", "Zebra"], "spec III: prior-driven teams must be reported"


C = [11, 12, 13, 14, 15]  # unrelated third roster, used as filler opponents/rows


def test_no_migration_when_the_roster_never_reappears_elsewhere():
    """The common case: a configured team whose roster's last map really is
    its last map anywhere. Input order is reversed relative to start_time
    on purpose (the function must sort internally, not trust list order)."""
    rows = [row(2, 200, 55, 66, C, B), row(1, 100, 10, 20, A_NEW, B)]
    checks = check_roster_staleness(rows, [TeamEntry("Known", 10)], {})
    assert checks[0].migrated_to is None
    assert checks[0].migrated_at is None
    assert checks[0].migrated_overlap is None


def test_migration_detected_when_the_identical_roster_moves_to_a_new_id():
    """THE detector this fix round exists to build: the exact Tundra/1win
    signature -- same 5 accounts, later map, different, unaliased team_id.
    Catches an implementation that never searches forward, or that matches
    on team_id instead of on accounts.
    """
    rows = [row(2, 200, 999, 20, A_NEW, B), row(1, 100, 10, 20, A_NEW, B)]
    checks = check_roster_staleness(rows, [TeamEntry("Known", 10)], {})
    assert checks[0].migrated_to == 999
    assert checks[0].migrated_at == 200
    assert checks[0].migrated_overlap == 5


def test_the_earliest_migration_hit_is_reported_not_the_latest():
    """Two later occurrences of the identical roster exist under two
    DIFFERENT unaliased ids -- the earlier one is the moment the migration
    first became visible, and is what must be reported. None of the other
    tests in this file have two candidates to choose between, so a
    tie-break mutated from earliest-wins to latest-wins would pass all of
    them; only this one can catch it.
    """
    rows = [
        row(3, 300, 888, 20, A_NEW, B),  # later occurrence, but NOT the earliest
        row(2, 200, 999, 20, A_NEW, B),  # the earliest occurrence after last_ts=100
        row(1, 100, 10, 20, A_NEW, B),   # configured team's own last map
    ]
    checks = check_roster_staleness(rows, [TeamEntry("Known", 10)], {})
    assert checks[0].migrated_to == 999, "the EARLIEST later occurrence must win, not the latest"
    assert checks[0].migrated_at == 200


def test_an_exact_match_is_preferred_over_an_earlier_partial_match():
    """An exact (5/5) match must be reported even when a partial (4/5)
    match occurs EARLIER in time -- exact evidence is stronger than a
    partial-overlap coincidence regardless of which came first. Untested
    by every other case here, since none combine both kinds of hit."""
    a_sub = [1, 2, 3, 4, 99]  # 4/5 shared with A_NEW
    rows = [
        row(3, 300, 999, 20, A_NEW, B),  # exact match, later
        row(2, 200, 888, 20, a_sub, B),  # partial match, EARLIER
        row(1, 100, 10, 20, A_NEW, B),   # configured team's own last map
    ]
    checks = check_roster_staleness(rows, [TeamEntry("Known", 10)], {})
    assert checks[0].migrated_to == 999, "the exact match must win even though it is later"
    assert checks[0].migrated_overlap == 5


def test_partial_overlap_catches_a_simultaneous_roster_and_org_change():
    """4 of 5 accounts carry over to the new id -- the case an exact-hash-only
    search would miss entirely, per the coordinator's brief: a roster change
    AND an org change happening at once."""
    a_sub = [1, 2, 3, 4, 99]  # A_NEW with account 9 -> 99: 4/5 shared
    rows = [row(2, 200, 999, 20, a_sub, B), row(1, 100, 10, 20, A_NEW, B)]
    checks = check_roster_staleness(rows, [TeamEntry("Known", 10)], {})
    assert checks[0].migrated_to == 999
    assert checks[0].migrated_overlap == 4


def test_overlap_below_threshold_is_not_reported_as_a_migration():
    """Only 3 of 5 accounts carry over -- below MIN_MIGRATION_OVERLAP. This
    is the boundary a threshold-off-by-one bug (>=3 instead of >=4) would
    get wrong, and it is exactly the shared-stand-in false-positive shape
    `test_predecessor_ignores_a_different_team_with_a_similar_roster`
    guards against elsewhere in this codebase."""
    a_sub = [1, 2, 3, 88, 99]  # A_NEW with 2 of 5 swapped: 3/5 shared
    rows = [row(2, 200, 999, 20, a_sub, B), row(1, 100, 10, 20, A_NEW, B)]
    checks = check_roster_staleness(rows, [TeamEntry("Known", 10)], {})
    assert checks[0].migrated_to is None


def test_an_alias_suppresses_the_false_migration_it_would_otherwise_report():
    """Same two rows, same accounts, same later id -- differing only in
    whether that later id is aliased. Without the alias this is
    indistinguishable from a genuine migration (and IS reported as one);
    with it, the later id is already known to be the same organization, so
    it must not be. Testing both directions on identical data is what
    proves the alias argument actually does something here, rather than
    the assertion holding regardless of it.
    """
    rows = [row(2, 200, 77, 20, A_NEW, B), row(1, 100, 10, 20, A_NEW, B)]

    unaliased = check_roster_staleness(rows, [TeamEntry("Known", 10)], {})
    assert unaliased[0].migrated_to == 77, "without the alias this DOES look like a migration"

    aliased = check_roster_staleness(rows, [TeamEntry("Known", 10)], {77: 10})
    assert aliased[0].migrated_to is None, "aliased ids are the same org, not a migration"


def test_stale_days_reflects_the_gap_to_the_stores_own_most_recent_map():
    """Plain staleness is measured against the STORE's last map, not some
    fixed wall-clock time -- so this test stays correct regardless of when
    it runs. 10 days apart, chosen well above any timezone/rounding noise."""
    ten_days_later = 100 + 10 * DAY_SECONDS
    rows = [row(2, ten_days_later, 55, 66, C, [16, 17, 18, 19, 20]), row(1, 100, 10, 20, A_NEW, B)]
    checks = check_roster_staleness(rows, [TeamEntry("Known", 10)], {})
    assert checks[0].stale_days == pytest.approx(10.0)
