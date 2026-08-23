"""Tests for the playoff card postmortem.

None of these read the match store: it is not a tracked artifact, so a test
depending on it would pass here and fail on a fresh clone. Every probability
below is either synthetic or the fair coin, which makes the oracles independent
of the ratings entirely.
"""

import math
from pathlib import Path

import pytest
import yaml

from ti26.bracket import SLOTS, all_brackets, slot_distributions
from ti26.cli_playoff_cards import PlayoffCardError
from ti26.cli_playoff_postmortem import (
    IN_SAMPLE_OPTIMUM,
    assert_reproduces_frozen,
    coin_reference,
    hit_count_distributions,
    moments,
    slot_scores,
    three_terms,
)
from ti26.cli_playoff_score import exact_null_tail, load_outcome

FROZEN = yaml.safe_load(Path("data/ti2026_playoff_cards.yaml").read_text())
SEEDS = list(FROZEN["seeds"])
OUTCOME = load_outcome(Path("data/ti2026_playoff_outcome.yaml"))
FAIR = 0.5


def fair_coin(a, b, best_of):
    return FAIR


def test_the_fair_coin_distribution_matches_the_independent_scorer_enumeration():
    """Kills a wrong weight or a wrong hit comparison in the enumeration.

    Under a fair coin every leaf weighs 2**-14, so the probability that a fixed
    card scores k must equal the fraction of coherent brackets scoring k against
    that card -- which `cli_playoff_score.exact_null_tail` computes by an
    entirely separate counting path. Drop the weight multiply, compare the wrong
    slot, or accumulate into the wrong card's table and these two disagree.
    """
    cards = [entry for entry in FROZEN["cards"] if entry["id"] in ("A-model", "H-owner-final")]
    tables = hit_count_distributions(SEEDS, fair_coin, True, cards)
    for entry in cards:
        counted = exact_null_tail(SEEDS, True, entry["picks"])
        for score in range(len(SLOTS) + 1):
            assert tables[entry["id"]][score] == pytest.approx(counted[score], abs=1e-12), (
                entry["id"],
                score,
            )


def test_every_card_distribution_is_a_distribution():
    """Kills a table that silently loses or double-counts leaves.

    A missing score or a leaf counted twice still prints as a plausible row of
    four-decimal numbers, and every tail read off it would be wrong by exactly
    the amount that went missing.
    """
    tables = hit_count_distributions(SEEDS, fair_coin, True, FROZEN["cards"])
    assert set(tables) == {entry["id"] for entry in FROZEN["cards"]}
    for card_id, table in tables.items():
        assert set(table) == set(range(len(SLOTS) + 1)), card_id
        assert math.fsum(table.values()) == pytest.approx(1.0, abs=1e-12), card_id
        assert all(p >= 0.0 for p in table.values()), card_id


def test_the_enumerated_mean_equals_the_slot_marginal_sum():
    """Kills a mean computed over the wrong axis.

    `E[S]` has two exact derivations: the mean of the enumerated hit-count
    distribution, and the sum of the per-slot probabilities the card bet on.
    The producer's precondition compares both against the frozen literal, so if
    the two paths could disagree the check would be comparing one number to
    itself.
    """
    dist = slot_distributions(SEEDS, fair_coin, True)
    tables = hit_count_distributions(SEEDS, fair_coin, True, FROZEN["cards"])
    for entry in FROZEN["cards"]:
        mean, _sd = moments(tables[entry["id"]])
        marginal = math.fsum(dist[slot][entry["picks"][slot]] for slot in SLOTS)
        assert mean == pytest.approx(marginal, abs=1e-12), entry["id"]
        # Under a fair coin every card's expectation is the registered null.
        assert mean == pytest.approx(FROZEN["null_expected_hits"], abs=5e-5), entry["id"]


def test_moments_returns_a_standard_deviation_not_a_variance():
    """Kills omitting the square root, or a mean of squares.

    A variance reported as an SD is roughly 2.5x too large on this scale and
    would make every card look far more dispersed than it is. The oracle is a
    two-point distribution whose variance and SD DIFFER -- a spread of 1 makes
    them equal and the test could not tell the two apart.
    """
    table = {k: 0.0 for k in range(15)}
    table.update({0: 0.5, 4: 0.5})
    mean, sd = moments(table)
    assert mean == pytest.approx(2.0)
    assert sd == pytest.approx(2.0), "SD of this distribution is 2; its variance is 4"
    point = {k: 0.0 for k in range(15)}
    point[4] = 1.0
    assert moments(point) == pytest.approx((4.0, 0.0))


def test_the_three_terms_are_strict_and_partition_the_distribution():
    """Kills `<=` where `<` belongs, and a tail derived by complement.

    `P(S < s)` computed with `<=` swallows the point mass, so `P(S >= s)`
    derived from it is short by exactly `P(S = s)` -- here 0.0076 on the card
    whose result is being reported. The three terms must partition the mass with
    the observed score in the middle term alone.
    """
    table = {k: 0.0 for k in range(15)}
    table.update({3: 0.25, 5: 0.5, 8: 0.25})
    below, at, above = three_terms(table, 5)
    assert (below, at, above) == pytest.approx((0.25, 0.5, 0.25))
    assert below + at + above == pytest.approx(1.0)
    # A score the distribution never reaches has no mass on it and both tails
    # must still be exact rather than one being inferred from the other.
    below, at, above = three_terms(table, 4)
    assert (below, at, above) == pytest.approx((0.25, 0.0, 0.75))


def test_the_coin_reference_scores_equal_their_closed_form():
    """Kills a Brier convention swap and a log-base error in one assertion.

    For a slot with `n` reachable teams the fair coin is uniform, so its Brier
    is exactly `1 - 1/n` and its log loss `ln n`, independent of who won. The
    binary Brier convention would give half; log10 would give 0.434 of the log
    loss. Both mutations still print plausible six-decimal numbers.
    """
    coin = coin_reference(SEEDS, True)
    sizes = [len(coin[slot]) for slot in SLOTS]
    assert sorted(sizes) == [2, 2, 2, 2, 4, 4, 4, 4, 8, 8, 8, 8, 8, 8]
    expected_brier = math.fsum(1.0 - 1.0 / n for n in sizes) / len(SLOTS)
    expected_ll = math.fsum(math.log(n) for n in sizes) / len(SLOTS)
    brier, log_loss = slot_scores(coin, OUTCOME, SEEDS)
    assert brier == pytest.approx(expected_brier, abs=1e-12)
    assert log_loss == pytest.approx(expected_ll, abs=1e-12)


def test_the_reference_does_not_move_when_the_outcome_changes():
    """Kills a reference that is not structural, which the registration requires.

    A reference forecast that depends on who won is not a reference: the skill
    score would be measured against a moving target and could be improved by
    the outcome alone. Checked on three unrelated coherent brackets.
    """
    coin = coin_reference(SEEDS, True)
    brackets = all_brackets(SEEDS, True)
    scores = {slot_scores(coin, brackets[i], SEEDS) for i in (0, 7777, 16383)}
    assert len(scores) == 1, f"the coin reference moved with the outcome: {scores}"


def test_the_model_reference_does_move_when_the_outcome_changes():
    """Kills a scorer that ignores the outcome entirely.

    The previous test would also pass if `slot_scores` never read `actual` at
    all. A real forecast's score must depend on what happened, so an asymmetric
    forecast is required to score differently on different brackets.
    """
    lopsided = slot_distributions(SEEDS, lambda a, b, best_of: 0.9, True)
    brackets = all_brackets(SEEDS, True)
    scores = {slot_scores(lopsided, brackets[i], SEEDS) for i in (0, 16383)}
    assert len(scores) == 2


def test_the_precondition_refuses_a_distribution_that_is_not_the_frozen_one():
    """Kills reporting tails from a distribution the card was not frozen under.

    Either derivation drifting past TOLERANCE means the refitted strengths or
    the enumeration is not the pre-event one. Without the raise the producer
    would print a full table of tails describing a different model, and nothing
    in the output would say so.
    """
    assert_reproduces_frozen("ok", 4.3615, 4.36154, 4.36153)
    with pytest.raises(PlayoffCardError, match="nothing is reported"):
        assert_reproduces_frozen("drifted-mean", 4.3615, 4.3700, 4.3615)
    with pytest.raises(PlayoffCardError, match="nothing is reported"):
        assert_reproduces_frozen("drifted-marginal", 4.3615, 4.3615, 4.3700)


def test_the_in_sample_optimum_is_the_card_with_the_highest_frozen_expectation():
    """Kills labelling the wrong card as the in-sample optimum.

    The note that one card is the exact argmax is a caveat against its own
    numbers, not a compliment. Attached to the wrong card it would excuse a
    card that earned nothing and quietly drop the qualifier from the one that
    needs it.
    """
    literals = {e["id"]: e["model_implied_expected"] for e in FROZEN["cards"]}
    assert IN_SAMPLE_OPTIMUM == max(literals, key=literals.get)
    assert IN_SAMPLE_OPTIMUM in {e["id"] for e in FROZEN["cards"] if e["role"] == "headline"}
