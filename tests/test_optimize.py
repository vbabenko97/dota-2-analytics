import pytest

from ti26.optimize import solve_card
from ti26.rules import load_rules
from ti26.types import Category

RULES = load_rules("config/ti2026_rules.yaml")
CAPS = RULES.category_capacities
TEAMS = [f"t{i:02d}" for i in range(16)]


def uniform_marginals():
    return {t: {c: CAPS[c] / 16 for c in Category} for t in TEAMS}


def test_card_respects_capacities():
    card, _ = solve_card(uniform_marginals(), CAPS)
    counts = {c: sum(1 for v in card.values() if v == c) for c in Category}
    assert counts == CAPS


def test_every_team_assigned_exactly_once():
    card, _ = solve_card(uniform_marginals(), CAPS)
    assert sorted(card) == sorted(TEAMS)


def test_uniform_marginals_score_the_random_baseline():
    _, score = solve_card(uniform_marginals(), CAPS)
    assert score == pytest.approx(RULES.random_baseline)
    assert score == pytest.approx(3.75)


def test_confident_marginals_beat_the_baseline():
    marginals = uniform_marginals()
    marginals["t00"] = {c: 0.0 for c in Category}
    marginals["t00"][Category.W4_0] = 1.0
    _, score = solve_card(marginals, CAPS)
    assert score > RULES.random_baseline


def test_greedy_argmax_would_violate_capacity_but_solver_does_not():
    marginals = {}
    for t in TEAMS:
        row = {c: 0.01 for c in Category}
        row[Category.W4_0] = 0.95
        marginals[t] = row
    card, _ = solve_card(marginals, CAPS)
    assert sum(1 for v in card.values() if v == Category.W4_0) == 1


def test_category_weights_shift_the_assignment():
    marginals = uniform_marginals()
    marginals["t00"][Category.L0_4] = 0.30
    marginals["t00"][Category.ELIM_WIN] = 0.31
    heavy = {c: 1.0 for c in Category}
    heavy[Category.L0_4] = 10.0
    card, _ = solve_card(marginals, CAPS, weights=heavy)
    assert card["t00"] == Category.L0_4


def test_team_count_mismatch_raises():
    marginals = {t: {c: CAPS[c] / 16 for c in Category} for t in TEAMS[:15]}
    with pytest.raises(ValueError, match="slots"):
        solve_card(marginals, CAPS)
