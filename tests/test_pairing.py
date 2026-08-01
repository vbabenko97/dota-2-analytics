import random

import pytest

from ti26.pairing import NoLegalPairingError, choose_pairing, perfect_matchings


def pairs_of(choice):
    return {frozenset(p) for p in choice.matching}


def _distinct_matching_count(matchings):
    return len({frozenset(map(frozenset, m)) for m in matchings})


def test_perfect_matchings_count_for_four_items():
    matchings = list(perfect_matchings(["a", "b", "c", "d"]))
    assert len(matchings) == 3
    assert _distinct_matching_count(matchings) == 3


def test_perfect_matchings_count_for_eight_items():
    matchings = list(perfect_matchings(list("abcdefgh")))
    assert len(matchings) == 105
    assert _distinct_matching_count(matchings) == 105


def test_perfect_matchings_raises_on_odd_length_input():
    with pytest.raises(NoLegalPairingError, match="odd"):
        list(perfect_matchings(["a", "b", "c"]))


def test_every_matching_covers_every_item_exactly_once():
    items = list("abcdef")
    for matching in perfect_matchings(items):
        flat = [x for pair in matching for x in pair]
        assert sorted(flat) == sorted(items)


def test_no_team_is_paired_with_itself():
    for matching in perfect_matchings(list("abcd")):
        assert all(a != b for a, b in matching)


def test_repeat_opponents_avoided_when_a_clean_matching_exists():
    teams = ["a", "b", "c", "d"]
    rank_index = {t: i for i, t in enumerate(teams)}
    prior = {"a": {"b"}, "b": {"a"}, "c": set(), "d": set()}
    choice = choose_pairing(teams, rank_index, prior, random.Random(0))
    assert choice.repeat_count == 0
    assert choice.min_possible_repeats == 0
    assert frozenset({"a", "b"}) not in pairs_of(choice)


def test_round_five_forced_repeat_takes_the_minimum_not_zero():
    """A realistic Round 5 record group where no repeat-free matching exists.

    Four teams share a 1-3 record. Team 'a' has already faced all three
    others, so every one of the three perfect matchings pairs 'a' with a
    previous opponent. The minimum achievable repeat count is 1, and the
    engine must take it rather than fail or silently allow more.
    """
    teams = ["a", "b", "c", "d"]
    rank_index = {t: i for i, t in enumerate(teams)}
    prior = {
        "a": {"b", "c", "d"},
        "b": {"a"},
        "c": {"a"},
        "d": {"a"},
    }
    choice = choose_pairing(teams, rank_index, prior, random.Random(0))
    assert choice.min_possible_repeats == 1
    assert choice.repeat_count == 1
    assert len(choice.matching) == 2
    flat = sorted(x for pair in choice.matching for x in pair)
    assert flat == teams


def test_complete_prior_history_yields_two_forced_repeats():
    teams = ["a", "b", "c", "d"]
    rank_index = {t: i for i, t in enumerate(teams)}
    prior = {t: set(teams) - {t} for t in teams}
    choice = choose_pairing(teams, rank_index, prior, random.Random(0))
    assert choice.min_possible_repeats == 2
    assert choice.repeat_count == 2


def test_forced_repeat_picks_the_cheaper_of_unequal_options():
    """Among matchings with genuinely different repeat counts, take the minimum.

    {ab, cd} and {ac, bd} each contain exactly one repeat pairing; {ad, bc}
    contains two (both 'ad' and 'bc' are prior opponents). Rank indices are
    chosen so {ad, bc} has the smallest ranking distance of the three -- if
    repeat-count filtering were skipped, distance alone would select it,
    which is exactly what this test must catch.
    """
    teams = ["a", "b", "c", "d"]
    rank_index = {"a": 0, "d": 1, "b": 2, "c": 3}
    prior = {
        "a": {"b", "c", "d"},
        "b": {"a", "c"},
        "c": {"a", "b"},
        "d": {"a"},
    }
    choice = choose_pairing(teams, rank_index, prior, random.Random(0))
    assert choice.min_possible_repeats == 1
    assert choice.repeat_count == 1
    assert pairs_of(choice) != {frozenset({"a", "d"}), frozenset({"b", "c"})}


def test_minimum_ranking_distance_is_preferred():
    teams = ["r0", "r1", "r2", "r3"]
    rank_index = {"r0": 0, "r1": 1, "r2": 2, "r3": 3}
    prior = {t: set() for t in teams}
    choice = choose_pairing(teams, rank_index, prior, random.Random(0))
    assert pairs_of(choice) == {frozenset({"r0", "r1"}), frozenset({"r2", "r3"})}


def test_maximize_distance_flips_the_preference():
    teams = ["r0", "r1", "r2", "r3"]
    rank_index = {"r0": 0, "r1": 1, "r2": 2, "r3": 3}
    prior = {t: set() for t in teams}
    choice = choose_pairing(
        teams, rank_index, prior, random.Random(0), maximize_distance=True
    )
    assert pairs_of(choice) == {frozenset({"r0", "r3"}), frozenset({"r1", "r2"})}


def test_repeat_minimisation_outranks_ranking_distance():
    teams = ["r0", "r1", "r2", "r3"]
    rank_index = {"r0": 0, "r1": 1, "r2": 2, "r3": 3}
    # The minimum-distance matching {r0r1, r2r3} is all repeats.
    prior = {"r0": {"r1"}, "r1": {"r0"}, "r2": {"r3"}, "r3": {"r2"}}
    choice = choose_pairing(teams, rank_index, prior, random.Random(0))
    assert choice.repeat_count == 0
    assert frozenset({"r0", "r1"}) not in pairs_of(choice)


def test_cross_group_constraint_pairs_only_across_groups():
    teams = ["a1", "a2", "b1", "b2"]
    group_of = {"a1": "A", "a2": "A", "b1": "B", "b2": "B"}
    rank_index = {t: i for i, t in enumerate(teams)}
    prior = {t: set() for t in teams}
    choice = choose_pairing(
        teams, rank_index, prior, random.Random(0), group_of=group_of, cross_group=True
    )
    assert all(group_of[a] != group_of[b] for a, b in choice.matching)


def test_impossible_cross_group_raises_rather_than_falling_back():
    """A hard round constraint must never degrade silently."""
    teams = ["a1", "a2", "a3", "a4"]
    group_of = dict.fromkeys(teams, "A")
    rank_index = {t: i for i, t in enumerate(teams)}
    prior = {t: set() for t in teams}
    with pytest.raises(NoLegalPairingError, match="cross-group"):
        choose_pairing(
            teams, rank_index, prior, random.Random(0), group_of=group_of, cross_group=True
        )


def test_odd_number_of_teams_raises():
    with pytest.raises(NoLegalPairingError, match="odd"):
        choose_pairing(["a", "b", "c"], {"a": 0, "b": 1, "c": 2}, {}, random.Random(0))


def test_selection_is_deterministic_under_a_fixed_seed():
    teams = list("abcdefgh")
    rank_index = {t: i for i, t in enumerate(teams)}
    prior = {t: set() for t in teams}
    first = choose_pairing(teams, rank_index, prior, random.Random(11))
    second = choose_pairing(teams, rank_index, prior, random.Random(11))
    assert first.matching == second.matching


def test_rng_argument_governs_a_genuine_multi_way_tie():
    """Equal ranks and no prior history leave all three matchings tied.

    All three matchings survive both the repeat-count and distance filters,
    so the final pick depends entirely on the passed-in `rng`. The same seed
    must reproduce the same pick every time, and at least two seeds among a
    handful must disagree -- otherwise the RNG argument could be ignored (or
    replaced by a module-level `random.choice`) without the test noticing.
    """
    teams = ["a", "b", "c", "d"]
    rank_index = dict.fromkeys(teams, 0)
    prior = {t: set() for t in teams}

    first = choose_pairing(teams, rank_index, prior, random.Random(0))
    second = choose_pairing(teams, rank_index, prior, random.Random(0))
    assert first.matching == second.matching

    outcomes = {
        tuple(choose_pairing(teams, rank_index, prior, random.Random(seed)).matching)
        for seed in range(8)
    }
    assert len(outcomes) >= 2
