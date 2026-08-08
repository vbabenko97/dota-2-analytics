import random

import pytest

from ti26.series import map_win_prob, series_win_prob, simulate_series


def test_equal_strength_is_a_coin_flip():
    assert map_win_prob(0.0, 0.0) == pytest.approx(0.5)


def test_map_prob_is_monotone_in_strength_gap():
    assert map_win_prob(1.0, 0.0) > map_win_prob(0.5, 0.0) > map_win_prob(0.0, 0.0)


def test_quarter_logit_matches_closed_form():
    # Referenced in the spec's manual-adjustment table.
    assert map_win_prob(0.25, 0.0) == pytest.approx(0.5621765, abs=1e-6)


def test_series_win_prob_closed_form():
    assert series_win_prob(0.5) == pytest.approx(0.5)
    assert series_win_prob(0.5621765) == pytest.approx(0.5928, abs=1e-4)
    assert series_win_prob(0.525) == pytest.approx(0.5375, abs=1e-4)


def test_simulate_series_always_reaches_two_wins():
    rng = random.Random(0)
    for _ in range(500):
        wa, wb = simulate_series(0.3, -0.2, rng)
        assert max(wa, wb) == 2
        assert min(wa, wb) in (0, 1)
        assert wa + wb in (2, 3)


def test_simulated_frequency_matches_closed_form():
    rng = random.Random(42)
    trials = 20_000
    wins = sum(1 for _ in range(trials) if simulate_series(0.4, 0.0, rng)[0] == 2)
    expected = series_win_prob(map_win_prob(0.4, 0.0))
    assert wins / trials == pytest.approx(expected, abs=0.015)


def test_shared_rng_stream_is_reproducible_and_actually_varies():
    """A fresh Random per call would make this pass vacuously — use one stream."""
    rng_a = random.Random(5)
    first = [simulate_series(0.1, 0.0, rng_a) for _ in range(20)]
    rng_b = random.Random(5)
    second = [simulate_series(0.1, 0.0, rng_b) for _ in range(20)]
    assert first == second
    assert len(set(first)) > 1, "sequence must vary; identical results prove nothing"


def test_different_seeds_produce_different_sequences():
    rng_a, rng_b = random.Random(5), random.Random(99)
    seq_a = [simulate_series(0.0, 0.0, rng_a) for _ in range(30)]
    seq_b = [simulate_series(0.0, 0.0, rng_b) for _ in range(30)]
    assert seq_a != seq_b


def test_series_win_prob_rejects_even_and_non_positive_best_of():
    """Was `test_unsupported_best_of_raises`, asserting Bo5 was rejected.

    `series_win_prob` was Bo3-only until 2026-08-08, when the TI 2025 series
    scoring needed the Bo5 grand final. Bo5 is now computed, so what remains
    rejectable is what has no "first to N" reading at all.
    """
    for bad in (0, -1, 2, 4):
        with pytest.raises(ValueError, match="odd"):
            series_win_prob(0.5, best_of=bad)


def test_longer_series_amplify_a_map_edge():
    """Kills mutation: keep the Bo3 closed form for every best_of.

    The generalisation is only worth having if it actually varies with length:
    a 60% map edge is worth more over five maps than three, and nothing over
    one. Bo3 must still equal the exact expression it used to hardcode.
    """
    assert series_win_prob(0.6, 1) == pytest.approx(0.6)
    assert series_win_prob(0.6, 3) == pytest.approx(0.6**2 * (3 - 2 * 0.6))
    assert series_win_prob(0.6, 5) > series_win_prob(0.6, 3) > series_win_prob(0.6, 1)
    for best_of in (1, 3, 5, 7):
        assert series_win_prob(0.5, best_of) == pytest.approx(0.5)


def test_simulate_series_rejects_even_best_of():
    rng = random.Random(0)
    with pytest.raises(ValueError, match="4"):
        simulate_series(0.0, 0.0, rng, best_of=4)


def test_simulate_series_rejects_non_positive_best_of():
    rng = random.Random(0)
    with pytest.raises(ValueError, match="0"):
        simulate_series(0.0, 0.0, rng, best_of=0)


def test_simulate_series_supports_best_of_five():
    rng = random.Random(0)
    for _ in range(500):
        wa, wb = simulate_series(0.3, -0.2, rng, best_of=5)
        assert max(wa, wb) == 3
        assert wa + wb in (3, 4, 5)
