import itertools
import random

import pytest

from ti26.optimize import solve_card
from ti26.rules import load_rules
from ti26.types import Category

RULES = load_rules("config/ti2026_rules.yaml")
CAPS = RULES.category_capacities
TEAMS = [f"t{i:02d}" for i in range(16)]


def uniform_marginals():
    return {t: {c: CAPS[c] / 16 for c in Category} for t in TEAMS}


def _brute_force_best(teams, marginals, slots, weights=None):
    """Exhaustively score every distinct team->category assignment.

    `slots` may repeat a category (one entry per unit of capacity);
    permutations that yield the same team->category mapping are deduplicated
    so this is a search over legal assignments, not over slot orderings.
    """
    weight = weights or dict.fromkeys(Category, 1.0)
    best_score = None
    best_cards = []
    seen = set()
    for perm in itertools.permutations(slots):
        if perm in seen:
            continue
        seen.add(perm)
        score = sum(marginals[t][c] * weight[c] for t, c in zip(teams, perm, strict=True))
        if best_score is None or score > best_score + 1e-9:
            best_score = score
            best_cards = [dict(zip(teams, perm, strict=True))]
        elif abs(score - best_score) <= 1e-9:
            best_cards.append(dict(zip(teams, perm, strict=True)))
    return best_score, best_cards


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


def test_solver_matches_brute_force_optimum_on_random_small_instances():
    """A legal-but-suboptimal capacity-respecting greedy also passes every
    test above (verified by mutation, see the task-7 report). This proves
    the solver finds the true maximum, not merely a legal assignment, on a
    small instance where brute force is tractable."""
    small_caps = {c: 0 for c in Category}
    small_caps[Category.W4_0] = 2
    small_caps[Category.L0_4] = 2
    slots = [c for c in Category for _ in range(small_caps[c])]
    small_teams = ["t0", "t1", "t2", "t3"]
    rng = random.Random(20260801)
    for _ in range(200):
        marginals = {
            t: {c: round(rng.uniform(0.0, 1.0), 2) for c in Category} for t in small_teams
        }
        card, score = solve_card(marginals, small_caps)
        best_score, best_cards = _brute_force_best(small_teams, marginals, slots)
        assert score == pytest.approx(best_score)
        assert card in best_cards


def test_solver_beats_a_provably_worse_greedy_on_an_adversarial_instance():
    """t0's own argmax (W4_0 over L0_4, by a hair: 0.51 vs 0.50) is what a
    team-order greedy would take first, consuming a W4_0 slot. That starves
    t2 -- whose W4_0 value (0.99) is far higher than t0's -- of the category
    it needs, forcing t2 into L0_4 for 0.0. The optimal assignment instead
    gives both W4_0 slots to t1 and t2, and both L0_4 slots to t0 and t3."""
    small_caps = {c: 0 for c in Category}
    small_caps[Category.W4_0] = 2
    small_caps[Category.L0_4] = 2
    marginals = {t: {c: 0.0 for c in Category} for t in ["t0", "t1", "t2", "t3"]}
    marginals["t0"][Category.W4_0] = 0.51
    marginals["t0"][Category.L0_4] = 0.50
    marginals["t1"][Category.W4_0] = 0.99
    marginals["t2"][Category.W4_0] = 0.99
    marginals["t3"][Category.W4_0] = 0.01
    marginals["t3"][Category.L0_4] = 0.98

    card, score = solve_card(marginals, small_caps)

    assert card == {
        "t0": Category.L0_4,
        "t1": Category.W4_0,
        "t2": Category.W4_0,
        "t3": Category.L0_4,
    }
    assert score == pytest.approx(3.46)
