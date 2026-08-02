import pytest

from ti26.elimination import ChoicePolicy
from ti26.montecarlo import category_marginals, monte_carlo_stderr
from ti26.rules import load_rules
from ti26.types import Category

RULES = load_rules("config/ti2026_rules.yaml")
CAPS = RULES.category_capacities
TEAMS = [f"t{i:02d}" for i in range(16)]


def test_each_team_row_sums_to_one():
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=200, seed=0)
    for row in marginals.values():
        assert sum(row.values()) == pytest.approx(1.0)


def test_each_category_column_sums_to_its_capacity():
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=200, seed=0)
    for category, capacity in CAPS.items():
        assert sum(r[category] for r in marginals.values()) == pytest.approx(capacity)


def test_stderr_formula():
    assert monte_carlo_stderr(0.5, 10_000) == pytest.approx(0.005)
    assert monte_carlo_stderr(0.0, 100) == 0.0


def test_stronger_team_is_likelier_to_go_four_zero():
    strengths = dict.fromkeys(TEAMS, 0.0)
    strengths["t00"] = 1.5
    marginals = category_marginals(strengths, RULES, n_sims=2000, seed=2)
    assert marginals["t00"][Category.W4_0] > marginals["t01"][Category.W4_0]
    assert marginals["t00"][Category.L0_4] < marginals["t01"][Category.L0_4]


def test_same_seed_reproduces_identical_marginals():
    a = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=100, seed=9)
    b = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=100, seed=9)
    assert a == b


def test_different_seeds_produce_different_marginals():
    a = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=100, seed=9)
    b = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=100, seed=10)
    assert a != b


def test_policy_choice_is_plumbed_through():
    """A rational chooser always picks its weakest available opponent; a
    random chooser does not. With the same seed and differentiated
    strengths, that mechanical difference must show up as a difference in
    the resulting marginals -- a row-sums-to-one check alone cannot tell
    the two policies apart."""
    strengths = {t: (i - 7.5) * 0.3 for i, t in enumerate(TEAMS)}
    rational = category_marginals(strengths, RULES, n_sims=300, seed=3, policy=ChoicePolicy.RATIONAL)
    randomised = category_marginals(strengths, RULES, n_sims=300, seed=3, policy=ChoicePolicy.RANDOM)
    assert rational != randomised


@pytest.mark.slow
def test_equal_strength_teams_approach_capacity_over_sixteen():
    n = 4000
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=n, seed=1)
    for team, row in marginals.items():
        for category, capacity in CAPS.items():
            expected = capacity / 16
            tolerance = 4 * monte_carlo_stderr(expected, n)
            assert row[category] == pytest.approx(expected, abs=tolerance), (
                f"{team}/{category}"
            )
