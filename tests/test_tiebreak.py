import random

import pytest

from ti26.tiebreak import (
    DurationResolver,
    DurationUnavailableError,
    game_win_pct,
    rank_teams,
)
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


def test_opponent_series_wins_break_identical_records():
    strong = make("strong", 3, 0, 6, 0)
    weak = make("weak", 0, 3, 0, 6)
    a = make("a", 1, 1, 2, 2, opponents=["strong"])
    b = make("b", 1, 1, 2, 2, opponents=["weak"])
    ranked = rank_teams([a, b, strong, weak], random.Random(0))
    assert ranked.index("a") < ranked.index("b")


def test_game_win_pct_breaks_equal_opponent_wins():
    shared = make("shared", 1, 1, 2, 2)
    a = make("a", 1, 1, 2, 1, opponents=["shared"])
    b = make("b", 1, 1, 2, 3, opponents=["shared"])
    ranked = rank_teams([a, b, shared], random.Random(0))
    assert ranked.index("a") < ranked.index("b")


def test_opponent_game_win_pct_is_the_fifth_criterion():
    # a and b identical through four criteria; their opponents differ on gwp.
    opp_good = make("opp_good", 1, 1, 3, 1)   # gwp 0.75
    opp_bad = make("opp_bad", 1, 1, 1, 3)     # gwp 0.25
    a = make("a", 1, 1, 2, 2, opponents=["opp_good"])
    b = make("b", 1, 1, 2, 2, opponents=["opp_bad"])
    ranked = rank_teams([a, b, opp_good, opp_bad], random.Random(0))
    assert ranked.index("a") < ranked.index("b")


def test_duration_is_not_consulted_when_five_criteria_separate():
    resolver = DurationResolver(random.Random(0), log_mean=7.65, log_sigma=0.25)
    states = [make("a", 1, 1, 3, 1), make("b", 1, 1, 1, 3)]
    rank_teams(states, random.Random(0), duration_fn=resolver.bind({s.team_id: s for s in states}))
    assert resolver.consultations == 0


def test_shorter_average_duration_wins_a_surviving_tie():
    tie_a, tie_b = make("a", 1, 1, 2, 2), make("b", 1, 1, 2, 2)
    consulted = []

    def duration_fn(team_id):
        consulted.append(team_id)
        return {"a": 1800.0, "b": 2400.0}[team_id]

    ranked = rank_teams([tie_a, tie_b], random.Random(0), duration_fn=duration_fn)
    assert sorted(consulted) == ["a", "b"]
    assert ranked == ["a", "b"]


def test_missing_duration_resolver_raises_rather_than_skipping_to_coin_toss():
    tie_a, tie_b = make("a", 1, 1, 2, 2), make("b", 1, 1, 2, 2)
    with pytest.raises(DurationUnavailableError, match="tied"):
        rank_teams([tie_a, tie_b], random.Random(0))


def test_exact_duration_ties_fall_to_a_seeded_coin_toss():
    tie_a, tie_b = make("a", 1, 1, 2, 2), make("b", 1, 1, 2, 2)
    fn = lambda _team_id: 2000.0  # identical durations by design
    first = rank_teams([tie_a, tie_b], random.Random(7), duration_fn=fn)
    second = rank_teams([tie_a, tie_b], random.Random(7), duration_fn=fn)
    assert first == second
    assert sorted(first) == ["a", "b"]


def test_resolver_memoises_and_extends_as_maps_accumulate():
    resolver = DurationResolver(random.Random(3), log_mean=7.65, log_sigma=0.25)
    first = resolver.average_for("a", maps_played=2)
    again = resolver.average_for("a", maps_played=2)
    assert first == again, "same map count must return the memoised average"
    extended = resolver.average_for("a", maps_played=5)
    assert extended != first, "more maps must extend the sample, not reuse it"


def test_resolver_raises_when_no_maps_have_been_played():
    resolver = DurationResolver(random.Random(0), log_mean=7.65, log_sigma=0.25)
    with pytest.raises(DurationUnavailableError, match="no maps"):
        resolver.average_for("a", maps_played=0)


def test_unknown_opponent_raises_instead_of_silently_dropping():
    a = make("a", 1, 1, 2, 2, opponents=["ghost"])
    with pytest.raises(ValueError, match="ghost"):
        rank_teams([a], random.Random(0))


def test_average_for_rejects_a_smaller_maps_played_than_cached():
    resolver = DurationResolver(random.Random(0), log_mean=7.65, log_sigma=0.25)
    resolver.average_for("a", maps_played=5)
    with pytest.raises(DurationUnavailableError, match="5"):
        resolver.average_for("a", maps_played=2)


def test_ranking_is_a_permutation_of_input():
    states = [make(f"t{i}", i % 3, 2 - i % 3, i, 5 - i % 5) for i in range(8)]
    resolver = DurationResolver(random.Random(1), log_mean=7.65, log_sigma=0.25)
    ranked = rank_teams(
        states, random.Random(3), duration_fn=resolver.bind({s.team_id: s for s in states})
    )
    assert sorted(ranked) == sorted(s.team_id for s in states)
