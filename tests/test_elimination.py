import random
from collections import Counter
from dataclasses import replace

import pytest

from ti26.elimination import run_elimination
from ti26.rules import load_rules
from ti26.swiss import run_swiss
from ti26.types import Category, SwissRun, TeamState

RULES = load_rules("config/ti2026_rules.yaml")
TEAMS = [f"t{i:02d}" for i in range(16)]


def flat(value=0.0):
    return dict.fromkeys(TEAMS, value)


def _two_by_two() -> dict[str, TeamState]:
    """Four teams whose ranking is forced by game-win percentage alone.

    a1 > a2 on the 3-2 side, b1 > b2 on the 2-3 side, with no opponents
    recorded so criteria 4 and 5 are identically zero and cannot interfere.
    """
    return {
        "a1": TeamState(
            team_id="a1", initial_group="A", series_wins=3, series_losses=2,
            map_wins=9, map_losses=6,
        ),
        "a2": TeamState(
            team_id="a2", initial_group="A", series_wins=3, series_losses=2,
            map_wins=8, map_losses=7,
        ),
        "b1": TeamState(
            team_id="b1", initial_group="A", series_wins=2, series_losses=3,
            map_wins=7, map_losses=7,
        ),
        "b2": TeamState(
            team_id="b2", initial_group="A", series_wins=2, series_losses=3,
            map_wins=6, map_losses=9,
        ),
    }


def test_every_team_gets_exactly_one_category():
    run = run_swiss(flat(), RULES, random.Random(0))
    result = run_elimination(run, flat(), RULES, random.Random(0))
    assert set(result.categories) == set(TEAMS)


def test_category_counts_match_derived_capacities():
    for seed in range(10):
        run = run_swiss(flat(), RULES, random.Random(seed))
        result = run_elimination(run, flat(), RULES, random.Random(seed))
        assert Counter(result.categories.values()) == RULES.category_capacities


def test_swiss_records_map_to_the_right_categories():
    run = run_swiss(flat(), RULES, random.Random(1))
    result = run_elimination(run, flat(), RULES, random.Random(1))
    for tid, state in run.states.items():
        if state.record == (4, 0):
            assert result.categories[tid] == Category.W4_0
        elif state.record == (4, 1):
            assert result.categories[tid] == Category.W4_1
        elif state.record == (1, 4):
            assert result.categories[tid] == Category.L1_4
        elif state.record == (0, 4):
            assert result.categories[tid] == Category.L0_4
        else:
            assert result.categories[tid] in (Category.ELIM_WIN, Category.ELIM_LOSS)


def test_five_matches_pair_three_two_against_two_three():
    run = run_swiss(flat(), RULES, random.Random(7))
    result = run_elimination(run, flat(), RULES, random.Random(7))
    assert len(result.matches) == 5
    for match in result.matches:
        assert run.states[match.higher].record == (3, 2)
        assert run.states[match.lower].record == (2, 3)


def test_maximum_ranking_distance_pairs_best_against_worst():
    """Kills mutation: pair the elimination round in ranking order instead.

    The published rule maximises distance in ranking, so the best 3-2 team
    faces the WORST 2-3 team. Pairing a1-b1 and a2-b2 -- the general Swiss
    minimum-distance rule, and what this function effectively did before
    2026-08-08 under a different mechanism -- reverses both pairs here.
    """
    run = SwissRun(states=_two_by_two(), groups={}, rounds=[])
    strengths = dict.fromkeys(run.states, 0.0)
    result = run_elimination(run, strengths, RULES, random.Random(0))
    assert [(m.higher, m.lower) for m in result.matches] == [("a1", "b2"), ("a2", "b1")]


def test_minimum_distance_fallback_pairs_best_against_best():
    """Kills mutation: ignore the config flag and always maximise distance.

    The flag exists so the sensitivity diagnostic can price the rule. If
    `elimination_maximizes_ranking_distance` is not actually read, this test
    sees the maximised pairing and fails.
    """
    run = SwissRun(states=_two_by_two(), groups={}, rounds=[])
    strengths = dict.fromkeys(run.states, 0.0)
    rules = replace(RULES, elimination_maximizes_ranking_distance=False)
    result = run_elimination(run, strengths, rules, random.Random(0))
    assert [(m.higher, m.lower) for m in result.matches] == [("a1", "b1"), ("a2", "b2")]


def test_pairing_is_seed_reproducible():
    run = run_swiss(flat(), RULES, random.Random(6))
    a = run_elimination(run, flat(), RULES, random.Random(6))
    b = run_elimination(run, flat(), RULES, random.Random(6))
    assert a.categories == b.categories
    assert [m.lower for m in a.matches] == [m.lower for m in b.matches]


def test_pairing_does_not_depend_on_strengths():
    """Kills mutation: restore opponent selection by win probability.

    The published rule is a function of the ranking alone. Under the old
    chooser model, making one 2-3 team overwhelmingly weak pulled it into the
    first match; under the published rule the pairing cannot move at all.
    """
    run = SwissRun(states=_two_by_two(), groups={}, rounds=[])
    even = dict.fromkeys(run.states, 0.0)
    skewed = {**even, "b1": -8.0}
    first = run_elimination(run, even, RULES, random.Random(0))
    second = run_elimination(run, skewed, RULES, random.Random(0))
    assert [(m.higher, m.lower) for m in first.matches] == [
        (m.higher, m.lower) for m in second.matches
    ]


def test_three_undecided_record_groups_raise():
    """A future rules config that leaves a third record group undecided must
    not be silently swept into the elimination pool."""
    states = {
        "a1": TeamState(team_id="a1", initial_group="A", series_wins=3, series_losses=2),
        "a2": TeamState(team_id="a2", initial_group="A", series_wins=3, series_losses=2),
        "b1": TeamState(team_id="b1", initial_group="A", series_wins=2, series_losses=3),
        "b2": TeamState(team_id="b2", initial_group="A", series_wins=2, series_losses=3),
        "c1": TeamState(team_id="c1", initial_group="A", series_wins=2, series_losses=2),
        "c2": TeamState(team_id="c2", initial_group="A", series_wins=2, series_losses=2),
    }
    run = SwissRun(states=states, groups={}, rounds=[])
    strengths = dict.fromkeys(states, 0.0)
    with pytest.raises(ValueError):
        run_elimination(run, strengths, RULES, random.Random(0))
