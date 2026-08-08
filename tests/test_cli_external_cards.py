"""Scoring published expert cards, and the exact null they are read against.

The null is the load-bearing part. The scores are trivial arithmetic; it is the
p-values that carry the claim, and a wrong distribution would make an expert
card look either damning or reassuring with equal confidence.
"""

import random
from collections import Counter
from fractions import Fraction
from math import factorial
from pathlib import Path

import pytest
import yaml

from ti26.cli_external_cards import (
    ExternalCardError,
    check_capacities,
    exact_null_distribution,
    load_truth,
    resolve,
    run,
)

CAPACITIES = [5, 5, 2, 2, 1, 1]
TRUTH_PATH = Path("config/ti2025_backtest.yaml")
CARDS_PATH = Path("config/ti2025_external_cards.yaml")


def test_the_null_reproduces_the_projects_random_baseline_exactly():
    """Kills mutation: any sign or term error in the inclusion-exclusion.

    The mean number of hits for a random card is forced to sum(c^2)/n by the
    capacities alone -- 15/4 here, the 3.75 quoted in every other report in this
    project. An inclusion-exclusion with a flipped sign or a dropped binomial
    still produces a plausible-looking distribution; it does not produce this
    number. Asserted as an exact Fraction, so a float that merely rounds to 3.75
    does not pass.
    """
    pmf = exact_null_distribution(CAPACITIES)
    n = sum(CAPACITIES)

    assert sum(pmf) == 1
    assert all(p >= 0 for p in pmf)

    mean = sum(k * p for k, p in enumerate(pmf))
    assert mean == Fraction(sum(c * c for c in CAPACITIES), n)
    assert mean == Fraction(15, 4)


def test_exactly_one_mismatch_is_impossible():
    """Kills mutation: return an approximate or smoothed distribution.

    If fifteen of sixteen slots match, the sixteenth is forced -- the one
    remaining label goes in the one remaining slot and necessarily agrees. So
    P(15) is exactly zero, not merely small. Any implementation that samples,
    interpolates or otherwise blurs the distribution puts mass here.
    """
    pmf = exact_null_distribution(CAPACITIES)
    assert pmf[15] == 0


def test_a_perfect_card_is_one_arrangement_out_of_the_multiset():
    """Kills mutation: normalise by n! instead of the multiset count.

    Identical categories are interchangeable, so the number of distinct cards is
    the multinomial 16!/(5!5!2!2!1!1!), not 16!. Normalising by the wrong total
    leaves the shape of the distribution intact and scales every p-value in the
    report by a factor of 57600.
    """
    pmf = exact_null_distribution(CAPACITIES)
    arrangements = factorial(sum(CAPACITIES))
    for capacity in CAPACITIES:
        arrangements //= factorial(capacity)
    assert pmf[16] == Fraction(1, arrangements)


def test_the_exact_null_agrees_with_a_simulation():
    """Kills mutation: a closed form that is self-consistent but wrong.

    The three tests above pin properties the distribution must have. This one
    pins the distribution itself against the obvious brute-force alternative,
    which is what the first draft of this analysis used.
    """
    labels = [c for c, n in zip("ABCDEF", CAPACITIES, strict=True) for _ in range(n)]
    target = labels[:]
    rng = random.Random(20260808)
    trials, counts = 60_000, Counter()
    for _ in range(trials):
        shuffled = labels[:]
        rng.shuffle(shuffled)
        counts[sum(a == b for a, b in zip(shuffled, target, strict=True))] += 1

    pmf = exact_null_distribution(CAPACITIES)
    for k in range(9):
        assert abs(counts[k] / trials - float(pmf[k])) < 0.01, f"score {k}"


def test_a_card_that_breaks_the_capacities_is_refused():
    """Kills mutation: score any assignment the file happens to contain.

    A card with three teams in `4-0` is not a worse forecast, it is a different
    and easier game -- more slots in a category means more chances to hit it --
    and scoring it against a null built from the real capacities would compare
    two things that are not comparable.
    """
    truth = {"A": "4-0", "B": "4-1", "C": "4-1", "D": "0-4"}
    card = {"A": "4-0", "B": "4-0", "C": "4-1", "D": "0-4"}
    with pytest.raises(ExternalCardError, match="do not match the format's capacities"):
        check_capacities(card, truth, "bad")


def test_a_card_covering_a_different_field_is_refused():
    truth = {"A": "4-0", "B": "0-4"}
    with pytest.raises(ExternalCardError, match="different field"):
        check_capacities({"A": "4-0", "Z": "0-4"}, truth, "bad")


def test_a_stale_alias_is_refused():
    """Kills mutation: ignore aliases that no longer match a team on the card.

    An alias for a team the card does not list means the card was edited and its
    name map was not. Left unchecked, the next edit silently scores a team under
    the wrong org -- and these cards are transcribed from screenshots by hand,
    which is exactly where that happens.
    """
    truth = {"TEAM VISION": "elim_win"}
    card = {
        "id": "stale",
        "aliases": {"PVISION": "TEAM VISION", "Gaimin Gladiators": "TEAM VISION"},
        "assignments": {"PVISION": "elim_win"},
    }
    with pytest.raises(ExternalCardError, match="aliases for teams not on the card"):
        resolve(card, truth)


def test_an_unresolvable_name_is_refused():
    truth = {"TEAM VISION": "elim_win"}
    card = {"id": "unknown", "aliases": {}, "assignments": {"Some Org": "elim_win"}}
    with pytest.raises(ExternalCardError, match="not in the truth file"):
        resolve(card, truth)


def test_the_published_cards_score_what_the_documentation_quotes():
    """Kills mutation: edit a shipped card's assignments after its score is cited.

    `docs/ti26/2026-08-08-known-weaknesses.md` quotes these two scores, and the
    argument built on them -- that one sixteen-slot card cannot separate skill
    from luck -- depends on the final card landing inside the null. Pinning the
    numbers here means the transcription cannot drift away from the prose.
    """
    payload = run("config/ti2025_backtest.yaml", "config/ti2025_external_cards.yaml")
    scores = {card["id"]: card["score"] for card in payload["cards"]}
    assert scores == {"noxville-final": 5, "noxville-first": 4}

    final = next(c for c in payload["cards"] if c["id"] == "noxville-final")
    assert final["hits"] == [
        "BOOM Esports", "TEAM VISION", "Team Nemesis", "Tundra Esports", "Yakult Brothers",
    ]
    # The whole point of the diagnostic: an expert card sits inside the null.
    assert final["p_random_at_least"] > 0.30


def test_every_shipped_card_carries_a_source_and_a_date():
    """Kills mutation: admit a card with no provenance.

    The admission rule in the config exists so this cannot become a curated list
    of cards that flatter the pipeline. A card with no URL and no date cannot be
    checked as having been published in advance.
    """
    cards = yaml.safe_load(CARDS_PATH.read_text())["cards"]
    for card in cards:
        assert card.get("source", "").startswith("http"), card["id"]
        assert card.get("published"), card["id"]
        assert card.get("author"), card["id"]


def test_the_truth_file_and_the_cards_describe_the_same_sixteen():
    truth = load_truth("config/ti2025_backtest.yaml")
    assert len(truth) == 16
    for card in yaml.safe_load(CARDS_PATH.read_text())["cards"]:
        resolved = resolve(card, truth)
        check_capacities(resolved, truth, card["id"])
