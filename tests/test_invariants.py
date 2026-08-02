"""The spec section IX invariant suite. These must hold in 100% of runs."""

import random
from collections import Counter

import pytest
from swiss_replay import assert_rounds_hit_independent_repeat_minimum

from ti26.elimination import ChoicePolicy, run_elimination
from ti26.montecarlo import category_marginals, monte_carlo_stderr
from ti26.rules import load_rules
from ti26.swiss import random_initial_groups, random_round_one_schedule, run_swiss
from ti26.types import Category

RULES = load_rules("config/ti2026_rules.yaml")
CAPS = RULES.category_capacities
TEAMS = [f"t{i:02d}" for i in range(16)]
SEEDS = range(60)


def varied_strengths(seed):
    rng = random.Random(seed)
    return {t: rng.gauss(0, 0.8) for t in TEAMS}


@pytest.mark.parametrize("seed", SEEDS)
def test_category_counts_are_always_exact(seed):
    strengths = varied_strengths(seed)
    run = run_swiss(strengths, RULES, random.Random(seed))
    outcome = run_elimination(run, strengths, RULES, random.Random(seed))
    assert Counter(outcome.categories.values()) == CAPS


@pytest.mark.parametrize("seed", SEEDS)
def test_exactly_eight_teams_advance(seed):
    strengths = varied_strengths(seed)
    run = run_swiss(strengths, RULES, random.Random(seed))
    outcome = run_elimination(run, strengths, RULES, random.Random(seed))
    advancing = sum(
        1
        for c in outcome.categories.values()
        if c in (Category.W4_0, Category.W4_1, Category.ELIM_WIN)
    )
    assert advancing == 8


@pytest.mark.parametrize("seed", SEEDS)
def test_no_self_pairing(seed):
    run = run_swiss(varied_strengths(seed), RULES, random.Random(seed))
    for state in run.states.values():
        assert state.team_id not in state.opponents


@pytest.mark.parametrize("seed", SEEDS)
def test_repeats_are_minimised_against_an_independent_recomputation(seed):
    """The engine must achieve the minimum repeat count every round.

    Do NOT assert `round_log.repeat_count == round_log.min_possible_repeats`.
    That is a tautology: `choose_pairing` filters candidates to those scoring
    `fewest` repeats and then reports both numbers from that same filtered
    set, so the equality holds for any input regardless of whether bucketing,
    the group constraint, or the distance ordering are correct.

    Instead reuse the independent recomputation helper from
    `tests/test_swiss.py`: replay the log to rebuild each round's entering
    records and prior-opponent sets, rebuild the buckets from the rules
    config, brute-force `perfect_matchings` over each bucket, and compare the
    minimum found that way against the repeat count of the pairings the
    engine actually logged. Nothing in that path reads `PairingChoice`.
    """
    run = run_swiss(varied_strengths(seed), RULES, random.Random(seed))
    assert_rounds_hit_independent_repeat_minimum(run, RULES)


@pytest.mark.parametrize("seed", SEEDS)
def test_group_constraints_hold(seed):
    rng = random.Random(seed)
    groups = random_initial_groups(TEAMS, rng)
    schedule = random_round_one_schedule(groups, rng)
    run = run_swiss(varied_strengths(seed), RULES, rng, groups=groups, round_one=schedule)
    for state in run.states.values():
        for opponent in state.opponents[:3]:
            assert groups[opponent] == groups[state.team_id], "rounds 1-3 stay in group"
        if len(state.opponents) >= 4:
            assert groups[state.opponents[3]] != groups[state.team_id], "R4 cross-group"


@pytest.mark.parametrize("policy", list(ChoicePolicy))
def test_invariants_hold_under_every_choice_policy(policy):
    strengths = {t: (i - 7.5) * 0.3 for i, t in enumerate(TEAMS)}
    for seed in range(10):
        run = run_swiss(strengths, RULES, random.Random(seed))
        outcome = run_elimination(
            run, strengths, RULES, random.Random(seed), policy=policy
        )
        assert Counter(outcome.categories.values()) == CAPS


def test_probability_rows_sum_to_one():
    """Row sums can genuinely break (wrong denominator, dropped category).

    A column-sum check was deliberately omitted here: `Counter(outcome.categories
    .values()) == CAPS` holds exactly in every single simulated tournament (see
    `test_category_counts_are_always_exact`), so summing per-team tallies across
    teams for a fixed category is an exact identity with zero Monte Carlo noise
    to absorb -- it cannot discriminate any bug that survives that stronger,
    already-exact test.
    """
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=500, seed=8)
    for row in marginals.values():
        assert sum(row.values()) == pytest.approx(1.0)


def test_renaming_teams_maps_every_row_through_the_bijection():
    """Row-wise equivariance under an explicit order-preserving bijection.

    Team identity must not influence outcomes beyond ordering, so relabelling
    must reproduce each team's full probability row exactly -- not merely
    preserve column sums, which hold by construction and prove nothing.
    """
    n = 800
    bijection = {f"t{i:02d}": f"z{i:02d}" for i in range(16)}
    base = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=n, seed=5)
    renamed = category_marginals(
        {bijection[t]: 0.0 for t in TEAMS}, RULES, n_sims=n, seed=5
    )
    for team, row in base.items():
        target = renamed[bijection[team]]
        for category in Category:
            assert target[category] == row[category], f"{team}->{bijection[team]}"


@pytest.mark.slow
def test_permuting_strengths_permutes_the_marginals():
    """Outcomes must track strength, not team name."""
    n = 6000
    ladder = [(i - 7.5) * 0.5 for i in range(16)]
    straight = category_marginals(
        {t: ladder[i] for i, t in enumerate(TEAMS)}, RULES, n_sims=n, seed=21
    )
    reversed_map = {t: ladder[15 - i] for i, t in enumerate(TEAMS)}
    flipped = category_marginals(reversed_map, RULES, n_sims=n, seed=21)
    tolerance = 5 * monte_carlo_stderr(0.25, n)
    for i, team in enumerate(TEAMS):
        mirror = TEAMS[15 - i]
        for category in Category:
            assert flipped[mirror][category] == pytest.approx(
                straight[team][category], abs=tolerance
            ), f"{team} vs {mirror} / {category}"


@pytest.mark.slow
def test_equal_strength_symmetry_within_monte_carlo_tolerance():
    n = 6000
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=n, seed=101)
    for team, row in marginals.items():
        for category, capacity in CAPS.items():
            expected = capacity / 16
            tolerance = 4 * monte_carlo_stderr(expected, n)
            assert row[category] == pytest.approx(expected, abs=tolerance), (
                f"{team}/{category} outside {tolerance:.4f} of {expected:.4f}"
            )
