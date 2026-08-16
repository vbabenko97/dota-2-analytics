import math

import pytest

from ti26.bracket import (
    BEST_OF,
    SLOTS,
    all_brackets,
    best_bracket,
    coherent_coin_null,
    disagreements,
    resolve,
    slot_distributions,
)

SEEDS = list("ABCDEFGH")


def favour(order):
    """Decide every series in favour of whichever team comes first in `order`."""
    rank = {t: i for i, t in enumerate(order)}
    return lambda a, b, _slot: a if rank[a] < rank[b] else b


def test_both_registered_nulls_are_reproduced():
    """Kills making `cross_feed` a no-op, or routing both variants the same way.

    The two topologies differ only in the lower-bracket quarterfinal feed, and
    that single edge is worth exactly a quarter of a slot. If the parameter
    stopped changing the routing, both values would collapse to one and the
    registered selection rule would silently become vacuous.
    """
    assert coherent_coin_null(SEEDS, cross_feed=True) == pytest.approx(3.75)
    assert coherent_coin_null(SEEDS, cross_feed=False) == pytest.approx(4.0)


def test_bracket_space_is_exactly_two_to_the_fourteen():
    """Kills adding or dropping a match, which would silently rescale every null."""
    assert len(SLOTS) == 14
    for cross in (True, False):
        brackets = all_brackets(SEEDS, cross)
        assert len(brackets) == 2**14
        assert len({tuple(b[s] for s in SLOTS) for b in brackets}) == 2**14


def test_cross_feed_sends_a_semifinal_loser_to_the_other_half():
    """Kills swapping the two feed variants, which is the whole open question.

    With the listed order winning everything, UB SF2's loser is C and LB R1M1's
    winner is B. Cross-feed must pair them; direct-feed must not.
    """
    seen = {}

    def decide(a, b, slot):
        seen.setdefault(slot, (a, b))
        return favour(SEEDS)(a, b, slot)

    resolve(SEEDS, decide, cross_feed=True)
    assert seen["LB QF1"] == ("B", "G")

    seen.clear()
    resolve(SEEDS, decide, cross_feed=False)
    assert seen["LB QF1"] == ("B", "C")


def test_a_decision_naming_a_team_that_is_not_playing_is_refused():
    """Kills trusting the callback, which would let a slate contain a phantom team."""
    with pytest.raises(ValueError, match="not playing"):
        resolve(SEEDS, lambda a, b, _slot: "Z", cross_feed=True)


def test_only_the_grand_final_is_best_of_five():
    """Kills a uniform best-of, which mis-weights the single highest-value slot."""
    assert BEST_OF["Grand Final"] == 5
    assert {BEST_OF[s] for s in SLOTS if s != "Grand Final"} == {3}

    lengths = []
    resolve(SEEDS, lambda a, b, slot: (lengths.append(BEST_OF[slot]), a)[1], cross_feed=True)
    assert sorted(lengths) == [3] * 13 + [5]


def test_every_slot_distribution_is_a_distribution():
    """Kills losing or double-counting branch weight while accumulating.

    A slot whose team probabilities do not sum to one means the enumeration
    dropped or duplicated leaves, and every expected score built on it would be
    quietly wrong rather than obviously broken.
    """
    strength = {t: i * 0.2 for i, t in enumerate(SEEDS)}

    def prob(a, b, best_of):
        p = 1 / (1 + math.exp(-(strength[a] - strength[b])))
        need = best_of // 2 + 1
        return sum(
            math.comb(best_of, k) * p**k * (1 - p) ** (best_of - k)
            for k in range(need, best_of + 1)
        )

    dist = slot_distributions(SEEDS, prob, cross_feed=True)
    for slot in SLOTS:
        assert sum(dist[slot].values()) == pytest.approx(1.0)
    # The strongest seed cannot be beaten to the Grand Final by the weakest.
    assert dist["Grand Final"]["H"] > dist["Grand Final"]["A"]


def test_the_returned_slate_is_coherent_and_beats_the_coin():
    """Kills returning a per-slot argmax, which need not be a reachable bracket.

    Picking the most likely winner of each slot independently can name a team
    the same bracket never advanced. The returned slate must be one of the
    enumerated coherent brackets.
    """
    strength = {t: i * 0.3 for i, t in enumerate(SEEDS)}

    def prob(a, b, best_of):
        p = 1 / (1 + math.exp(-(strength[a] - strength[b])))
        need = best_of // 2 + 1
        return sum(
            math.comb(best_of, k) * p**k * (1 - p) ** (best_of - k)
            for k in range(need, best_of + 1)
        )

    slate, expected = best_bracket(SEEDS, prob, cross_feed=True)
    assert tuple(slate[s] for s in SLOTS) in {
        tuple(b[s] for s in SLOTS) for b in all_brackets(SEEDS, cross_feed=True)
    }
    assert expected > coherent_coin_null(SEEDS, cross_feed=True)


def test_disagreements_reports_slots_in_registered_order():
    """Kills reporting differing slots in dict or set order, which is not stable."""
    left = dict.fromkeys(SLOTS, "A")
    right = dict(left, **{"Grand Final": "B", "UB QF1": "B"})
    assert disagreements(left, right) == ["UB QF1", "Grand Final"]
