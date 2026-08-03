import math

import pytest

from ti26.data.schema import MapRow
from ti26.ratings.simple import ConstantModel, EwmaModel


def row(match_id, radiant, dire, radiant_win=True):
    return MapRow(
        match_id=match_id, start_time=100 + match_id, duration=2000,
        radiant_win=radiant_win, league_id=1, tier="professional",
        radiant_team_id=10, dire_team_id=20, series_id=1, series_type=1, patch="7.41",
        radiant_accounts=tuple(radiant), dire_accounts=tuple(dire),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


A, B = [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]


def test_constant_model_log_loss_is_ln_two():
    model = ConstantModel()
    assert -math.log(model.predict(row(1, A, B))) == pytest.approx(math.log(2))


def test_ewma_starts_even_and_moves_toward_the_winner():
    model = EwmaModel(half_life_maps=30.0)
    assert model.predict(row(1, A, B)) == pytest.approx(0.5)
    for i in range(10):
        model.update(row(i, A, B, radiant_win=True))
    assert model.predict(row(99, A, B)) > 0.7


def test_ewma_forgets_old_results_faster_with_a_shorter_half_life():
    """A half-life that does nothing would make the parameter decorative.

    Both models see the same 10 losses then 10 wins; the shorter half-life
    must end up more convinced by the recent wins.
    """
    fast, slow = EwmaModel(half_life_maps=3.0), EwmaModel(half_life_maps=100.0)
    for model in (fast, slow):
        for i in range(10):
            model.update(row(i, A, B, radiant_win=False))
        for i in range(10, 20):
            model.update(row(i, A, B, radiant_win=True))
    assert fast.predict(row(99, A, B)) > slow.predict(row(99, A, B))


def test_ewma_is_more_confident_about_a_longer_winning_streak():
    """A roster that has won its only game and one that has won 200 straight
    both have a raw win rate of 1.0, which would clip to the same predicted
    probability and make the model unable to tell a single data point from
    a long streak. Laplace smoothing makes the rate sample-size aware, so
    against the same unrated opponent the 200-win roster must be predicted
    more confidently than the 1-win roster."""
    C = [21, 22, 23, 24, 25]

    one_win = EwmaModel(half_life_maps=30.0)
    one_win.update(row(1, A, B, radiant_win=True))

    two_hundred_wins = EwmaModel(half_life_maps=30.0)
    for i in range(200):
        two_hundred_wins.update(row(i, A, B, radiant_win=True))

    p_one_win = one_win.predict(row(998, A, C))
    p_two_hundred_wins = two_hundred_wins.predict(row(999, A, C))
    assert p_two_hundred_wins > p_one_win


def test_ewma_predictions_stay_in_the_open_unit_interval():
    """An unbeaten roster must not produce p = 1.0; log loss would be inf and
    a single upset would dominate every metric."""
    model = EwmaModel(half_life_maps=30.0)
    for i in range(200):
        model.update(row(i, A, B, radiant_win=True))
    p = model.predict(row(999, A, B))
    assert 0.0 < p < 1.0
