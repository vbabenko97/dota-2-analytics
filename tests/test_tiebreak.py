import random

import pytest

from ti26.tiebreak import TIEBREAK_ORDER, game_win_pct, rank_teams
from ti26.types import TeamState


def make(team_id, sw, sl, mw, ml, opponents=(), group="A"):
    return TeamState(
        team_id=team_id,
        initial_group=group,
        series_wins=sw,
        series_losses=sl,
        map_wins=mw,
        map_losses=ml,
        opponents=list(opponents),
    )


def test_game_win_pct_handles_zero_maps():
    assert game_win_pct(make("a", 0, 0, 0, 0)) == 0.0
    assert game_win_pct(make("b", 1, 0, 2, 1)) == 2 / 3


def test_series_wins_dominate():
    states = [make("low", 1, 2, 3, 5), make("high", 3, 0, 6, 1)]
    assert rank_teams(states, random.Random(0)) == ["high", "low"]


def test_series_losses_break_equal_wins():
    states = [make("more", 2, 2, 4, 4), make("fewer", 2, 1, 4, 3)]
    assert rank_teams(states, random.Random(0)) == ["fewer", "more"]


def test_game_win_pct_is_the_third_criterion():
    shared = make("shared", 1, 1, 2, 2)
    a = make("a", 1, 1, 2, 1, opponents=["shared"])
    b = make("b", 1, 1, 2, 3, opponents=["shared"])
    ranked = rank_teams([a, b, shared], random.Random(0))
    assert ranked.index("a") < ranked.index("b")


def test_opponent_series_wins_is_the_fourth_criterion():
    strong = make("strong", 3, 0, 6, 0)
    weak = make("weak", 0, 3, 0, 6)
    a = make("a", 1, 1, 2, 2, opponents=["strong"])
    b = make("b", 1, 1, 2, 2, opponents=["weak"])
    ranked = rank_teams([a, b, strong, weak], random.Random(0))
    assert ranked.index("a") < ranked.index("b")


def test_game_win_pct_outranks_opponent_series_wins():
    """Kills mutation: swap criteria 3 and 4 back, as they were until 2026-08-08.

    Every other ordering test passes under BOTH orders, because it varies only
    one criterion and leaves the other tied. This one puts them in direct
    conflict: `a` has the better game-win percentage (0.75 vs 0.25) and the
    weaker opponent (0 match wins vs 3). The published rules put percentage of
    games won third and opponents' matches won fourth, so `a` ranks first.
    Under the transposed order `b` does, and this is the only test that sees it.
    """
    strong = make("strong", 3, 0, 6, 0)
    weak = make("weak", 0, 3, 0, 6)
    a = make("a", 1, 1, 3, 1, opponents=["weak"])
    b = make("b", 1, 1, 1, 3, opponents=["strong"])
    ranked = rank_teams([a, b, strong, weak], random.Random(0))
    assert ranked.index("a") < ranked.index("b")


def test_opponent_game_win_pct_is_the_fifth_criterion():
    # a and b identical through four criteria; their opponents differ on gwp.
    opp_good = make("opp_good", 1, 1, 3, 1)   # gwp 0.75
    opp_bad = make("opp_bad", 1, 1, 1, 3)     # gwp 0.25
    a = make("a", 1, 1, 2, 2, opponents=["opp_good"])
    b = make("b", 1, 1, 2, 2, opponents=["opp_bad"])
    ranked = rank_teams([a, b, opp_good, opp_bad], random.Random(0))
    assert ranked.index("a") < ranked.index("b")


def test_a_surviving_tie_goes_straight_to_the_coin_toss():
    """Kills mutation: reinstate an average-duration criterion before the toss.

    Two teams identical through all five published criteria. This used to
    RAISE `DurationUnavailableError` unless the caller supplied a duration
    source, because the implementation had a sixth criterion the published
    rules do not list. It must now resolve, from the rng alone.
    """
    tie_a, tie_b = make("a", 1, 1, 2, 2), make("b", 1, 1, 2, 2)
    first = rank_teams([tie_a, tie_b], random.Random(7))
    second = rank_teams([tie_a, tie_b], random.Random(7))
    assert first == second
    assert sorted(first) == ["a", "b"]


def test_the_coin_toss_can_land_either_way():
    """Kills mutation: resolve surviving ties by team id instead of the rng.

    A stable sort on equal keys returns input order, so a tie-break that does
    nothing looks identical to a coin toss under any single seed. Only a seed
    sweep separates them.
    """
    orders = set()
    for seed in range(20):
        tie_a, tie_b = make("a", 1, 1, 2, 2), make("b", 1, 1, 2, 2)
        orders.add(tuple(rank_teams([tie_a, tie_b], random.Random(seed))))
    assert orders == {("a", "b"), ("b", "a")}


def test_the_published_order_has_six_criteria_and_no_duration():
    """Kills mutation: re-add avg_duration to TIEBREAK_ORDER.

    `rules.load_rules` compares the config against this list, so the two can
    only drift together. This pins the list itself against the transcript in
    docs/ti26/2026-08-08-published-format-rules.md.
    """
    assert TIEBREAK_ORDER == [
        "series_wins",
        "series_losses",
        "game_win_pct",
        "opponent_series_wins",
        "opponent_game_win_pct",
        "coin_toss",
    ]


def test_unknown_opponent_raises_instead_of_silently_dropping():
    a = make("a", 1, 1, 2, 2, opponents=["ghost"])
    with pytest.raises(ValueError, match="ghost"):
        rank_teams([a], random.Random(0))


def test_ranking_is_a_permutation_of_input():
    states = [make(f"t{i}", i % 3, 2 - i % 3, i, 5 - i % 5) for i in range(8)]
    ranked = rank_teams(states, random.Random(3))
    assert sorted(ranked) == sorted(s.team_id for s in states)
