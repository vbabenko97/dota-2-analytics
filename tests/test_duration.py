import math

import numpy as np
import pytest

from ti26.data.schema import MapRow
from ti26.duration import (
    MAX_DURATION_SECONDS,
    MIN_DURATION_SECONDS,
    fit_duration_model,
)


def row(match_id, duration, radiant_team_id=10, dire_team_id=20):
    return MapRow(
        match_id=match_id, start_time=100 + match_id, duration=duration, radiant_win=True,
        league_id=1, tier="professional", radiant_team_id=radiant_team_id,
        dire_team_id=dire_team_id, series_id=1, series_type=1, patch="7.41",
        radiant_accounts=(1, 2, 3, 4, 5), dire_accounts=(6, 7, 8, 9, 10),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


def test_recovers_the_parameters_of_a_known_lognormal():
    """The only test that can catch an estimator that is confidently wrong."""
    rng = np.random.default_rng(17)
    durations = rng.lognormal(mean=7.5, sigma=0.30, size=20000)
    rows = [row(i, int(d)) for i, d in enumerate(durations) if 600 < d < 9000]
    fit = fit_duration_model(rows)
    assert fit.log_mean == pytest.approx(7.5, abs=0.02)
    assert fit.log_sigma == pytest.approx(0.30, abs=0.02)
    assert fit.n == len(rows)


def test_implausible_durations_are_excluded():
    """Sub-10-minute results are forfeits and abandons, not games. Spec VI
    says flag and downweight rather than silently keep."""
    rng = np.random.default_rng(19)
    good = [row(i, int(d)) for i, d in enumerate(rng.lognormal(7.5, 0.25, size=5000))
            if MIN_DURATION_SECONDS < d < MAX_DURATION_SECONDS]
    junk = [row(90000 + i, 45) for i in range(500)]
    fit = fit_duration_model(good + junk)
    assert fit.n == len(good), "the 500 junk rows must not enter the fit"
    assert fit.log_mean == pytest.approx(7.5, abs=0.05)


def test_empty_input_raises_rather_than_returning_the_placeholder():
    """Silently falling back to the invented 7.65/0.25 would let a broken
    ingest ship a card steered by a fabricated parameter, which is exactly
    the failure spec XII documents."""
    with pytest.raises(ValueError, match="no usable durations"):
        fit_duration_model([])


def test_gap_coefficient_is_recovered_when_a_real_effect_exists():
    """Spec XII requires the fit be conditioned at minimum on rating gap."""
    rng = np.random.default_rng(23)
    gaps, rows = {}, []
    for i in range(20000):
        gap = float(rng.uniform(0, 2.0))
        # Bigger mismatches end faster: -0.15 log-seconds per unit of gap.
        duration = math.exp(7.6 - 0.15 * gap + rng.normal(0, 0.25))
        if MIN_DURATION_SECONDS < duration < MAX_DURATION_SECONDS:
            gaps[i] = gap
            rows.append(row(i, int(duration)))
    fit = fit_duration_model(rows, gaps=gaps)
    assert fit.gap_coefficient == pytest.approx(-0.15, abs=0.02)
    assert fit.material is True


def test_gap_effect_is_reported_immaterial_when_it_is_noise():
    """A decision rule that always says 'material' is not a decision rule."""
    rng = np.random.default_rng(29)
    gaps, rows = {}, []
    for i in range(20000):
        gaps[i] = float(rng.uniform(0, 2.0))
        duration = math.exp(7.6 + rng.normal(0, 0.25))  # no gap dependence
        if MIN_DURATION_SECONDS < duration < MAX_DURATION_SECONDS:
            rows.append(row(i, int(duration)))
    fit = fit_duration_model(rows, gaps=gaps)
    assert abs(fit.gap_coefficient) < 0.02
    assert fit.material is False


def test_rating_gaps_are_computed_before_the_result_is_known():
    """Predict-then-update. If the model were updated first, the gap for a map
    would encode that map's own outcome and the duration fit would be
    conditioned on the future."""
    from ti26.duration import rating_gaps
    from ti26.ratings.elo import EloModel

    A, B = [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]
    rows = [
        MapRow(
            match_id=i, start_time=100 + i, duration=2000, radiant_win=True,
            league_id=1, tier="professional", radiant_team_id=10, dire_team_id=20,
            series_id=1, series_type=1, patch="7.41",
            radiant_accounts=tuple(A), dire_accounts=tuple(B),
            radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
            has_null_team=False, has_bad_roster=False,
        )
        for i in range(10)
    ]
    gaps = rating_gaps(rows, EloModel())
    assert gaps[0] == pytest.approx(0.0), "the first map has no prior evidence at all"
    assert gaps[9] > gaps[1], "the gap widens as A keeps winning"
    assert set(gaps) == {r.match_id for r in rows}


def test_sensitivity_sweep_reports_zero_delta_for_its_own_baseline():
    from ti26.duration import sensitivity_sweep
    from ti26.rules import load_rules

    rules = load_rules("config/ti2026_rules.yaml")
    strengths = {f"t{i:02d}": (i - 7.5) * 0.15 for i in range(16)}
    result = sensitivity_sweep(strengths, rules, [0.25, 0.45], n_sims=2000, seed=3)
    assert result[0]["is_baseline"] is True
    assert result[0]["max_abs_delta"] == 0.0
    assert result[1]["max_abs_delta"] >= 0.0


@pytest.mark.slow
def test_sensitivity_sweep_detects_that_log_sigma_moves_the_card():
    """Spec XII: this parameter steers ~30% of every ranking, so a sweep that
    reports no movement at any sigma would mean the resolver is not wired in.

    Marked slow: it needs enough simulations that the delta is signal rather
    than Monte Carlo noise.
    """
    from ti26.duration import sensitivity_sweep
    from ti26.rules import load_rules

    rules = load_rules("config/ti2026_rules.yaml")
    strengths = {f"t{i:02d}": 0.0 for i in range(16)}  # fully tied: duration decides
    result = sensitivity_sweep(strengths, rules, [0.05, 1.20], n_sims=60000, seed=5)
    assert result[1]["max_abs_delta"] > 0.005


def test_fitted_sigma_differs_from_the_invented_placeholder():
    """If the fit reproduces 0.25 exactly, someone wired the placeholder
    through instead of estimating. Real pro durations are more dispersed."""
    rng = np.random.default_rng(31)
    durations = rng.lognormal(mean=7.55, sigma=0.34, size=15000)
    rows = [row(i, int(d)) for i, d in enumerate(durations)
            if MIN_DURATION_SECONDS < d < MAX_DURATION_SECONDS]
    fit = fit_duration_model(rows)
    assert abs(fit.log_sigma - 0.25) > 0.03
