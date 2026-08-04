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


def _identical_row_field() -> tuple[dict[str, dict[Category, float]], dict[str, str]]:
    """16 marginal rows, two of them byte-identical, with stable ids.

    team03 and team04 share a row, and their ids are swapped relative to name
    order, so ordering by name and ordering by id put a different team first.
    """
    cats = list(Category)
    marginals = {
        f"team{i:02d}": {c: 0.5 - 0.011 * i - 0.017 * j for j, c in enumerate(cats)}
        for i in range(16)
    }
    marginals["team04"] = dict(marginals["team03"])
    ids = {name: f"id{i:02d}" for i, name in enumerate(sorted(marginals))}
    ids["team03"], ids["team04"] = ids["team04"], ids["team03"]
    return marginals, ids


def test_identical_marginal_rows_are_ordered_by_stable_id_not_display_name():
    """Kills mutation: fall back to the display name as solve_card's row-order key.

    Row order decides among equal-cost optima inside linear_sum_assignment. For
    two byte-identical rows the existing order key is exhausted and the name
    breaks the tie, so renaming one of them moves its slot -- the audit executed
    exactly this and watched an assignment change. Keyed on the configured team
    id, the assignment is a function of the probabilities alone.
    """
    marginals, ids = _identical_row_field()
    before, _ = solve_card(marginals, CAPS, team_ids=ids)

    rename = lambda k: "0aaa" if k == "team04" else k
    renamed = {rename(k): v for k, v in marginals.items()}
    renamed_ids = {rename(k): v for k, v in ids.items()}
    after, _ = solve_card(renamed, CAPS, team_ids=renamed_ids)

    by_id_before = {ids[t]: c for t, c in before.items()}
    by_id_after = {renamed_ids[t]: c for t, c in after.items()}
    assert by_id_after == by_id_before


def test_identical_marginal_rows_are_unmoved_by_input_row_order():
    """Kills mutation: let dict insertion order reach the solver as identity.

    Reordering the input rows must not change any assignment either; if it did,
    a caller could change the card by changing how it built its mapping.
    """
    marginals, ids = _identical_row_field()
    before, _ = solve_card(marginals, CAPS, team_ids=ids)
    reversed_rows = dict(reversed(list(marginals.items())))
    after, _ = solve_card(reversed_rows, CAPS, team_ids=ids)
    assert after == before


def test_solve_card_rejects_team_ids_that_do_not_match_its_rows():
    """Kills mutation: silently ignore a mismatched team_ids mapping."""
    marginals, ids = _identical_row_field()
    del ids["team00"]
    with pytest.raises(ValueError, match="team_ids"):
        solve_card(marginals, CAPS, team_ids=ids)


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


def _bottom_slot_instance():
    """Three teams for one 0-4 slot and two 1-4 slots, from the real 2026-08-04 run.

    The numbers are the shape that exposed the defect: the team with the HIGHEST
    P(0-4) is not the one the raw optimum puts there, because the totals differ
    by 0.001 the other way.
    """
    caps = dict.fromkeys(Category, 0)
    caps[Category.L1_4] = 2
    caps[Category.L0_4] = 1

    def row(p04, p14):
        r = {c: 0.0 for c in Category}
        r[Category.L0_4] = p04
        r[Category.L1_4] = p14
        return r

    # a: highest P(0-4). b: raw optimum's pick. c: in between.
    return caps, {"a": row(0.148, 0.236), "b": row(0.122, 0.209), "c": row(0.126, 0.214)}


def _zero_four(card):
    return next(t for t, c in card.items() if c == Category.L0_4)


def test_raw_optimum_gives_the_scarce_slot_to_a_lower_probability_team():
    """Baseline for the two tests below -- without a tolerance nothing changes.

    Documents the behaviour the tie-break exists to override: maximising the
    total alone hands 0-4 to `b` even though `a` is likelier to finish there.
    """
    caps, marginals = _bottom_slot_instance()
    card, score = solve_card(marginals, caps)
    assert _zero_four(card) == "b"
    assert score == pytest.approx(0.572)


def test_tie_break_gives_a_scarce_slot_to_the_likeliest_team():
    caps, marginals = _bottom_slot_instance()
    card, score = solve_card(marginals, caps, tie_tolerance=0.002)
    assert _zero_four(card) == "a", "0-4 should go to the highest P(0-4) team"
    # Costs exactly the 0.001 the raw optimum was ahead by, which is inside the
    # stated tolerance -- so the tie-break spent what it was allowed and no more.
    assert score == pytest.approx(0.571)
    assert score >= 0.572 - 0.002


def test_tie_break_refuses_to_move_when_the_gap_exceeds_the_tolerance():
    """The tolerance is a real bound, not a licence to always apply the rule.

    Without this, a tie-break that fired unconditionally would pass the test
    above while silently overriding differences the model CAN resolve.
    """
    caps, marginals = _bottom_slot_instance()
    card, _ = solve_card(marginals, caps, tie_tolerance=0.0005)
    assert _zero_four(card) == "b"


def test_tie_break_never_drops_more_than_the_tolerance_on_the_real_capacities():
    """Chained free swaps must not drift below the optimum cumulatively."""
    rng = random.Random(20260804)
    for _ in range(25):
        marginals = {
            t: {c: rng.random() for c in Category} for t in TEAMS
        }
        _, optimum = solve_card(marginals, CAPS)
        _, tied = solve_card(marginals, CAPS, tie_tolerance=0.01)
        assert tied <= optimum + 1e-12
        assert tied >= optimum - 0.01 - 1e-12
