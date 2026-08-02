import pytest

from ti26.data.schema import MapRow
from ti26.roster import (
    RosterIndex,
    canonical_team_id,
    continuity,
    load_aliases,
    roster_version_id,
)


def row(match_id, start_time, radiant, dire, r_team=10, d_team=20):
    return MapRow(
        match_id=match_id, start_time=start_time, duration=2000, radiant_win=True,
        league_id=1, tier="professional", radiant_team_id=r_team, dire_team_id=d_team,
        series_id=1, series_type=1, patch="7.41",
        radiant_accounts=tuple(radiant), dire_accounts=tuple(dire),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


def test_roster_id_is_order_independent():
    assert roster_version_id([5, 3, 1, 4, 2]) == roster_version_id([1, 2, 3, 4, 5])


def test_roster_id_changes_when_a_single_player_changes():
    """The whole design rests on this: a substitution must produce a new
    statistical identity, otherwise roster-awareness is decorative."""
    assert roster_version_id([1, 2, 3, 4, 5]) != roster_version_id([1, 2, 3, 4, 6])


def test_roster_id_is_a_16_char_hex_digest():
    rvid = roster_version_id([1, 2, 3, 4, 5])
    assert len(rvid) == 16
    assert all(c in "0123456789abcdef" for c in rvid)


def test_roster_id_is_stable_across_processes():
    """sqlite rows written in one run are read in another, so the id must not
    depend on PYTHONHASHSEED. Python's built-in hash() would fail this."""
    import subprocess
    import sys

    script = (
        "from ti26.roster import roster_version_id; "
        "print(roster_version_id([5, 3, 1, 4, 2]))"
    )
    out = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, check=True,
        env={"PYTHONPATH": "src", "PYTHONHASHSEED": "1"},
    )
    assert out.stdout.strip() == roster_version_id([1, 2, 3, 4, 5])


def test_continuity_counts_shared_players_out_of_five():
    assert continuity([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == 1.0
    assert continuity([1, 2, 3, 4, 5], [1, 2, 3, 4, 9]) == 0.8
    assert continuity([1, 2, 3, 4, 5], [6, 7, 8, 9, 10]) == 0.0


def test_alias_maps_rebranded_org_to_canonical_id(tmp_path):
    path = tmp_path / "aliases.yaml"
    path.write_text("aliases:\n  - {from: 8255888, to: 9247354, note: Iron Wing}\n")
    aliases = load_aliases(path)
    assert canonical_team_id(8255888, aliases) == 9247354
    assert canonical_team_id(9247354, aliases) == 9247354, "canonical ids are fixed points"
    assert canonical_team_id(None, aliases) is None


def test_index_returns_distinct_ids_for_the_two_sides():
    index = RosterIndex()
    r, d = index.observe(row(1, 100, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]))
    assert r != d
    assert r == roster_version_id([1, 2, 3, 4, 5])


def test_predecessor_is_the_most_recent_roster_of_the_same_team():
    """A team that swaps one player should inherit from its own prior roster,
    not from the global prior. This is the re-brand / stand-in case in spec VI."""
    index = RosterIndex()
    index.observe(row(1, 100, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]))
    index.observe(row(2, 200, [1, 2, 3, 4, 9], [6, 7, 8, 9, 10]))
    new_rvid = roster_version_id([1, 2, 3, 4, 9])
    assert index.predecessor(new_rvid) == roster_version_id([1, 2, 3, 4, 5])


def test_first_roster_of_a_team_has_no_predecessor():
    index = RosterIndex()
    r, _ = index.observe(row(1, 100, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]))
    assert index.predecessor(r) is None


def test_predecessor_ignores_a_different_team_with_a_similar_roster():
    """Predecessor lookup is keyed by canonical team, not by player overlap.

    Without this, two unrelated orgs sharing a stand-in would chain histories.
    """
    index = RosterIndex()
    index.observe(row(1, 100, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10], r_team=10))
    r2, _ = index.observe(row(2, 200, [1, 2, 3, 4, 99], [6, 7, 8, 9, 10], r_team=77))
    assert index.predecessor(r2) is None, "team 77 has no history despite 4 shared players"


def test_continuity_with_predecessor_measures_actual_overlap():
    """The inheritance weight is measured, not assumed.

    A one-player swap and a three-player rebuild must NOT receive the same
    weight; a fixed constant cannot tell them apart, which is precisely why
    the index stores account sets.
    """
    index = RosterIndex()
    index.observe(row(1, 100, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]))
    one_swap, _ = index.observe(row(2, 200, [1, 2, 3, 4, 91], [6, 7, 8, 9, 10]))
    assert index.continuity_with_predecessor(one_swap) == pytest.approx(0.8)

    other = RosterIndex()
    other.observe(row(1, 100, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]))
    rebuild, _ = other.observe(row(2, 200, [1, 2, 91, 92, 93], [6, 7, 8, 9, 10]))
    assert other.continuity_with_predecessor(rebuild) == pytest.approx(0.4)


def test_continuity_is_zero_for_a_roster_with_no_history():
    index = RosterIndex()
    first, _ = index.observe(row(1, 100, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]))
    assert index.continuity_with_predecessor(first) == 0.0


def test_aliases_chain_history_across_a_rebrand():
    """The alias table is inert unless observe() consults it. This test fails
    if `canonical_team_id` is dropped from the observe path."""
    index = RosterIndex(aliases={77: 10})
    index.observe(row(1, 100, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10], r_team=10))
    rebranded, _ = index.observe(row(2, 200, [1, 2, 3, 4, 91], [6, 7, 8, 9, 10], r_team=77))
    assert index.predecessor(rebranded) == roster_version_id([1, 2, 3, 4, 5])
    assert index.continuity_with_predecessor(rebranded) == pytest.approx(0.8)
