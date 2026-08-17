import math

import pytest

from ti26.proper_scores import (
    ScoreInputError,
    brier_skill_score,
    capacity_marginal_reference,
    expected_hits,
    multiclass_brier,
    multiclass_log_loss,
)

CATEGORIES = ("4-0", "4-1", "elim_win", "elim_loss", "1-4", "0-4")
TI2026_CAPACITIES = {"4-0": 1, "4-1": 2, "elim_win": 5, "elim_loss": 5, "1-4": 2, "0-4": 1}
TEAMS = [f"t{i:02d}" for i in range(16)]
# One realised outcome that fills exactly those capacities.
ACTUAL = dict(
    zip(
        TEAMS,
        ["4-0"] + ["4-1"] * 2 + ["elim_win"] * 5 + ["elim_loss"] * 5 + ["1-4"] * 2 + ["0-4"],
        strict=True,
    )
)


def test_capacity_reference_brier_is_the_registered_constant():
    """Kills a scaled Brier convention.

    The spec froze `BS = mean_i sum_k (p_ik - y_ik)^2` UNSCALED and published
    `Brier_ref = 0.765625` as the oracle. Dividing by 2 -- the binary
    convention `backtest.brier` uses, and the one a reader is most likely to
    reach for -- yields 0.3828125 and fails here.
    """
    reference = capacity_marginal_reference(TI2026_CAPACITIES, TEAMS)
    assert multiclass_brier(reference, ACTUAL, CATEGORIES) == pytest.approx(0.765625, abs=1e-12)


def test_capacity_reference_log_loss_is_the_registered_constant():
    """Kills a base-2 log loss.

    The spec froze natural log, matching `backtest.log_loss`, and published
    1.593403231828482. Base 2 gives 2.2988..., which would silently make every
    `dLL` comparison wrong by a factor of ln(2).
    """
    reference = capacity_marginal_reference(TI2026_CAPACITIES, TEAMS)
    assert multiclass_log_loss(reference, ACTUAL, CATEGORIES) == pytest.approx(
        1.593403231828482, abs=1e-12
    )


def test_capacity_reference_reproduces_the_registered_null_hit_count():
    """Kills a reference built from anything but the capacities.

    The whole justification for `q = capacity / 16` is that it reproduces the
    preregistered null's 3.75 expected hits. A uniform 1/6 reference -- the
    obvious alternative -- gives 16/6 = 2.667 and fails, which is the point:
    it would not be the registered null's marginal at all.
    """
    reference = capacity_marginal_reference(TI2026_CAPACITIES, TEAMS)
    any_coherent_card = dict(ACTUAL)
    assert expected_hits(reference, any_coherent_card) == pytest.approx(3.75, abs=1e-12)


def test_brier_rewards_a_forecast_that_concentrated_on_the_truth():
    """Kills a sign flip in the squared error.

    Both scores are negatively oriented -- lower is better -- and a flipped
    comparison would make the confident-and-right forecast look worse than the
    diffuse one while every individual number stayed plausible.
    """
    reference = capacity_marginal_reference(TI2026_CAPACITIES, TEAMS)
    sharp = {
        team: {c: (0.9 if c == ACTUAL[team] else 0.02) for c in CATEGORIES} for team in TEAMS
    }
    assert multiclass_brier(sharp, ACTUAL, CATEGORIES) < multiclass_brier(
        reference, ACTUAL, CATEGORIES
    )
    assert multiclass_log_loss(sharp, ACTUAL, CATEGORIES) < multiclass_log_loss(
        reference, ACTUAL, CATEGORIES
    )
    assert brier_skill_score(
        multiclass_brier(sharp, ACTUAL, CATEGORIES),
        multiclass_brier(reference, ACTUAL, CATEGORIES),
    ) > 0


def test_log_loss_returns_inf_when_the_realised_category_was_called_impossible():
    """Kills clipping the probability to an epsilon.

    Clipping converts the single most informative failure a probabilistic
    forecast can have -- it called the observed outcome impossible -- into a
    large but finite number that averages away against the other fifteen
    subjects. `math.inf` refuses to be averaged away.
    """
    forecasts = {
        team: {c: (0.0 if c == ACTUAL[team] else 0.2) for c in CATEGORIES} for team in TEAMS
    }
    assert multiclass_log_loss(forecasts, ACTUAL, CATEGORIES) == math.inf


def test_a_forecast_that_is_not_a_distribution_is_rejected():
    """Kills accepting unnormalised rows.

    A row summing to 0.8 scores BETTER on Brier than a correct one for the
    categories it under-weights, so an unnormalised forecast reads as a good
    forecast rather than as the bug it is.
    """
    forecasts = capacity_marginal_reference(TI2026_CAPACITIES, TEAMS)
    forecasts[TEAMS[0]]["elim_win"] = 0.01
    with pytest.raises(ScoreInputError, match="sums to"):
        multiclass_brier(forecasts, ACTUAL, CATEGORIES)


def test_a_subject_missing_a_forecast_is_rejected_not_skipped():
    """Kills silently scoring only the subjects that happen to have forecasts.

    Skipping would divide by a smaller n and quietly report a score for 15
    teams as though it covered 16.
    """
    forecasts = capacity_marginal_reference(TI2026_CAPACITIES, TEAMS)
    del forecasts[TEAMS[3]]
    with pytest.raises(ScoreInputError, match="no forecast for"):
        multiclass_brier(forecasts, ACTUAL, CATEGORIES)


def test_reference_requires_capacities_to_cover_the_subjects():
    """Kills building a reference whose capacities do not sum to the field.

    If they did not, `q` would not be a distribution and the 3.75 identity --
    the entire reason this reference is the registered one -- would not hold.
    """
    with pytest.raises(ScoreInputError, match="capacities sum to"):
        capacity_marginal_reference(TI2026_CAPACITIES, TEAMS[:15])
