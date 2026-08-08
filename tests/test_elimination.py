import random
from collections import Counter

import pytest

from ti26.elimination import ChoicePolicy, pair_elimination, run_elimination
from ti26.rules import load_rules
from ti26.swiss import run_swiss
from ti26.tiebreak import DurationResolver
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
    resolver = DurationResolver(random.Random(0), RULES.duration_log_mean, RULES.duration_log_sigma)
    run = SwissRun(states=states, groups={}, rounds=[], resolver=resolver)
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


def test_resolver_is_shared_across_the_swiss_to_elimination_boundary():
    """The elimination ranking must consult the SAME DurationResolver that
    accumulated samples during the Swiss stage, not a fresh independent one.

    Builds a minimal SwissRun where two duration ties are forced by
    construction (a1/a2 tie at (3,2), b1/b2 tie at (2,3)), so the elimination
    ranking is guaranteed to consult durations. A resolver that is genuinely
    shared: (1) has its `.consultations` counter advanced by the elimination
    ranking, and (2) still returns the SAME cached average for a team probed
    before and after, because maps_played has not changed by ranking time. A
    fresh, independent resolver (the pre-fix bug) would leave the original
    instance's `.consultations` untouched and would never share its samples.
    """
    states = {
        "a1": TeamState(
            team_id="a1", initial_group="A", series_wins=3, series_losses=2,
            map_wins=8, map_losses=6,
        ),
        "a2": TeamState(
            team_id="a2", initial_group="A", series_wins=3, series_losses=2,
            map_wins=8, map_losses=6,
        ),
        "b1": TeamState(
            team_id="b1", initial_group="A", series_wins=2, series_losses=3,
            map_wins=6, map_losses=8,
        ),
        "b2": TeamState(
            team_id="b2", initial_group="A", series_wins=2, series_losses=3,
            map_wins=6, map_losses=8,
        ),
    }
    resolver = DurationResolver(random.Random(0), RULES.duration_log_mean, RULES.duration_log_sigma)
    run = SwissRun(
        states=states, groups=dict.fromkeys(states, "A"), rounds=[], resolver=resolver
    )

    # Consult the resolver ourselves the way group-stage ranking would.
    baseline = resolver.average_for("a1", states["a1"].maps_played)
    consultations_before = resolver.consultations

    strengths = dict.fromkeys(states, 0.0)
    run_elimination(run, strengths, RULES, random.Random(1))

    assert resolver.consultations > consultations_before, (
        "elimination ranking must consult the SAME resolver instance carried "
        "on SwissRun, not a fresh independent one"
    )
    assert resolver.average_for("a1", states["a1"].maps_played) == baseline, (
        "a1's average must reuse the memoised group-stage samples, not a "
        "fresh draw from an independent resolver"
    )


# --- TI 2025's elimination rule -------------------------------------------
#
# `pair_elimination` implements maximum-ranking-distance pairing, which is what
# TI 2025 ran and what TI 2026 replaced with a sequential choice. Nothing in the
# 2026 simulation calls it. It stays because `cli_pairing_check` validates this
# engine against TI 2025's real bracket, and validating against that event
# requires that event's rule.


def test_the_fast_path_returns_what_an_exhaustive_filter_would():
    """Kills mutation: let the fast path change tie-breaking, not just speed.

    `pair_elimination` short-circuits at the first distance group holding a
    rematch-free permutation instead of scoring all n!. That is only sound if
    the candidate list handed to `rng.choice` is the one an exhaustive
    lexicographic filter would have built -- same members, SAME ORDER. A
    different order picks a different element from the same rng state, which
    silently moves the diagnostic's verdict.

    This reimplements the exhaustive version and demands identical output over
    many random repeat patterns and seeds, including patterns dense enough to
    force the slow path.
    """
    from itertools import permutations as _perms

    def exhaustive(higher, lower, prior, rng, maximize):
        def repeats(perm):
            return sum(1 for i, j in enumerate(perm) if lower[j] in prior.get(higher[i], ()))

        def distance(perm):
            return sum(abs(i - j) for i, j in enumerate(perm))

        cands = list(_perms(range(len(higher))))
        fewest = min(repeats(p) for p in cands)
        cands = [p for p in cands if repeats(p) == fewest]
        best = (max if maximize else min)(distance(p) for p in cands)
        cands = [p for p in cands if distance(p) == best]
        chosen = rng.choice(cands)
        return [(higher[i], lower[j]) for i, j in enumerate(chosen)]

    n = 5
    high = [f"h{i}" for i in range(n)]
    low = [f"l{i}" for i in range(n)]
    forced_slow_path = 0
    gen = random.Random(99)
    for trial in range(120):
        # Density climbs across trials so late ones make every permutation a
        # rematch, which is the only way the slow path is reached at all.
        density = trial / 120
        prior = {h: {ll for ll in low if gen.random() < density} for h in high}
        if all(any(low[j] in prior[high[i]] for j in range(n)) for i in range(n)):
            forced_slow_path += 1
        for maximize in (True, False):
            got = pair_elimination(high, low, prior, random.Random(trial), maximize)
            want = exhaustive(high, low, prior, random.Random(trial), maximize)
            assert got == want, f"trial {trial}, maximize={maximize}"
    assert forced_slow_path, (
        "precondition: some trial must make every permutation a rematch, or the "
        "slow path is never exercised and this proves only the fast path"
    )


def test_the_2026_simulation_does_not_use_the_2025_pairing_rule():
    """Kills mutation: quietly route `run_elimination` back through pairing.

    The two rules produce different brackets and both live in this module, so
    the failure mode is not a crash -- it is a plausible-looking card built on
    last year's format. Under the 2026 chooser, making one 2-3 team far weaker
    pulls it into the first match; under 2025's distance rule the pairing is a
    function of the ranking alone and cannot move.
    """
    strengths = flat()
    run = run_swiss(strengths, RULES, random.Random(2))
    two_three = [t for t, s in run.states.items() if s.record == (2, 3)]
    weakest = min(two_three)
    strengths[weakest] = -8.0

    result = run_elimination(
        run, strengths, RULES, random.Random(2), policy=ChoicePolicy.RATIONAL
    )
    assert result.matches[0].opponent == weakest
