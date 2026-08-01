import random
from collections import Counter

import pytest

from ti26.elimination import ChoicePolicy, run_elimination
from ti26.rules import load_rules
from ti26.swiss import run_swiss
from ti26.types import Category, SwissRun, TeamState

RULES = load_rules("config/ti2026_rules.yaml")
TEAMS = [f"t{i:02d}" for i in range(16)]


def flat(value=0.0):
    return dict.fromkeys(TEAMS, value)


@pytest.mark.parametrize("policy", list(ChoicePolicy))
def test_every_team_gets_exactly_one_category(policy):
    run = run_swiss(flat(), RULES, random.Random(0))
    result = run_elimination(run, flat(), RULES, random.Random(0), policy=policy)
    assert set(result.categories) == set(TEAMS)


@pytest.mark.parametrize("policy", list(ChoicePolicy))
def test_category_counts_match_derived_capacities(policy):
    for seed in range(10):
        run = run_swiss(flat(), RULES, random.Random(seed))
        result = run_elimination(run, flat(), RULES, random.Random(seed), policy=policy)
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
        assert run.states[match.chooser].record == (3, 2)
        assert run.states[match.opponent].record == (2, 3)


def test_rational_policy_selects_the_weakest_available_opponent():
    """Assert the SELECTION, not a stochastic match outcome."""
    strengths = flat()
    run = run_swiss(strengths, RULES, random.Random(2))
    two_three = [t for t, s in run.states.items() if s.record == (2, 3)]
    weakest = min(two_three)
    strengths[weakest] = -6.0

    result = run_elimination(
        run, strengths, RULES, random.Random(2), policy=ChoicePolicy.RATIONAL
    )
    first = result.matches[0]
    assert weakest in first.available_when_choosing
    assert first.opponent == weakest


def test_rational_choices_are_never_worse_than_the_alternatives():
    from ti26.series import map_win_prob, series_win_prob

    strengths = {t: (i - 7.5) * 0.35 for i, t in enumerate(TEAMS)}
    run = run_swiss(strengths, RULES, random.Random(11))
    result = run_elimination(
        run, strengths, RULES, random.Random(11), policy=ChoicePolicy.RATIONAL
    )
    for match in result.matches:
        chosen = series_win_prob(
            map_win_prob(strengths[match.chooser], strengths[match.opponent])
        )
        for alternative in match.available_when_choosing:
            other = series_win_prob(
                map_win_prob(strengths[match.chooser], strengths[alternative])
            )
            assert chosen >= other - 1e-12


def test_choosers_act_in_ranking_order():
    run = run_swiss(flat(), RULES, random.Random(3))
    result = run_elimination(run, flat(), RULES, random.Random(3))
    sizes = [len(m.available_when_choosing) for m in result.matches]
    assert sizes == [5, 4, 3, 2, 1]


def test_random_policy_still_selects_from_available_only():
    run = run_swiss(flat(), RULES, random.Random(4))
    result = run_elimination(
        run, flat(), RULES, random.Random(4), policy=ChoicePolicy.RANDOM
    )
    taken: set[str] = set()
    for match in result.matches:
        assert match.opponent in match.available_when_choosing
        assert match.opponent not in taken
        taken.add(match.opponent)


def test_policies_are_seed_reproducible():
    run = run_swiss(flat(), RULES, random.Random(6))
    a = run_elimination(run, flat(), RULES, random.Random(6))
    b = run_elimination(run, flat(), RULES, random.Random(6))
    assert a.categories == b.categories
    assert [m.opponent for m in a.matches] == [m.opponent for m in b.matches]


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


def test_softmax_temp_zero_raises():
    run = run_swiss(flat(), RULES, random.Random(5))
    with pytest.raises(ValueError):
        run_elimination(
            run, flat(), RULES, random.Random(5), policy=ChoicePolicy.NOISY, softmax_temp=0.0
        )


def test_softmax_temp_negative_raises():
    run = run_swiss(flat(), RULES, random.Random(5))
    with pytest.raises(ValueError):
        run_elimination(
            run, flat(), RULES, random.Random(5), policy=ChoicePolicy.NOISY, softmax_temp=-1.0
        )
