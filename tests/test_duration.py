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


def test_log_sigma_is_marginal_not_residual_and_n_is_the_regression_sample():
    """DurationResolver (tiebreak.py) draws lognormvariate(log_mean,
    log_sigma) with no gap term, so log_sigma must be the unconditional
    dispersion of the rows the fit used -- not the residual dispersion left
    over after conditioning on gap, which is a materiality diagnostic, never
    a simulation parameter. `n` must count only the rows the regression ran
    on (`paired`), not every row that merely cleared the duration bounds.

    Fixture: the same material=True gap-conditioned rows as above, plus 500
    identical-duration rows that clear the bounds but carry no gap entry.
    Those 500 are `usable` but never enter the regression, so a correct
    implementation must exclude them from both `log_sigma` and `n`; if it put
    the residual sigma back in `log_sigma`, or computed `log_sigma`/`n` over
    every usable row instead of the fitted `paired` subset, this fails.
    """
    rng = np.random.default_rng(23)
    gaps, rows = {}, []
    for i in range(20000):
        gap = float(rng.uniform(0, 2.0))
        duration = math.exp(7.6 - 0.15 * gap + rng.normal(0, 0.25))
        if MIN_DURATION_SECONDS < duration < MAX_DURATION_SECONDS:
            gaps[i] = gap
            rows.append(row(i, int(duration)))
    ungapped = [row(90000 + i, 2000) for i in range(500)]

    fit = fit_duration_model(rows + ungapped, gaps=gaps)

    assert fit.material is True
    assert fit.n == len(rows), "n must be the regression sample, not every usable row"

    expected_marginal_sigma = float(np.std(np.log([r.duration for r in rows]), ddof=1))
    assert fit.log_sigma == pytest.approx(expected_marginal_sigma, abs=1e-9)
    assert fit.log_sigma > fit.residual_log_sigma


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


def test_rating_gaps_use_chronological_order_when_match_id_disagrees():
    """The fixture above uses start_time = 100 + match_id, so a sort on
    match_id alone gives the identical order as a sort on start_time and
    cannot be told apart from the correct implementation. This fixture makes
    the two orders disagree: match_id 5 is played first chronologically
    (smallest start_time) but has the largest match_id of the three. Sorting
    by match_id alone would walk it last and give it a contaminated, nonzero
    gap instead of the empty-history gap of 0 a correct chronological walk
    gives it.

    Verified by mutation: changing the sort key in `rating_gaps` from
    `(r.start_time, r.match_id)` to `r.match_id` makes both assertions below
    fail (documented in the task report).
    """
    from ti26.duration import rating_gaps
    from ti26.ratings.elo import EloModel

    A, B = [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]

    def make(match_id, start_time):
        return MapRow(
            match_id=match_id, start_time=start_time, duration=2000, radiant_win=True,
            league_id=1, tier="professional", radiant_team_id=10, dire_team_id=20,
            series_id=1, series_type=1, patch="7.41",
            radiant_accounts=tuple(A), dire_accounts=tuple(B),
            radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
            has_null_team=False, has_bad_roster=False,
        )

    rows = [make(5, 100), make(1, 200), make(3, 300)]
    gaps = rating_gaps(rows, EloModel())

    assert gaps[5] == pytest.approx(0.0), (
        "match 5 has the earliest start_time; a chronological walk gives it no prior evidence"
    )
    assert gaps[5] < gaps[1] < gaps[3], "gap must widen in start_time order, not match_id order"


def test_sensitivity_sweep_reports_zero_delta_for_its_own_baseline():
    from ti26.duration import sensitivity_sweep
    from ti26.rules import load_rules

    rules = load_rules("config/ti2026_rules.yaml")
    strengths = {f"t{i:02d}": (i - 7.5) * 0.15 for i in range(16)}
    result = sensitivity_sweep(strengths, rules, [0.25, 0.45], n_sims=2000, seed=3)
    assert result[0]["is_baseline"] is True
    assert result[0]["max_abs_delta"] == 0.0
    assert result[1]["log_sigma"] == 0.45, "each entry must carry its own sigma, not the baseline's"
    assert result[1]["is_baseline"] is False


def test_sensitivity_sweep_reports_a_noise_floor_and_resolvability():
    """A magnitude assertion here would be measuring Monte Carlo noise, not an
    effect: control runs (same sigma, seeds 5 vs 6 vs 7) produced deltas as
    large as any sigma-varying comparison, so no fixed threshold on
    max_abs_delta can distinguish "sigma moved the card" from "resampling
    noise" at these sample sizes. Check the structural contract instead.

    A `noise_floor` hardcoded to 0.0 would make `resolvable` meaningless (any
    nonzero delta would look resolvable); computing `noise_floor` fresh per
    sigma instead of once from the baseline would break the "same value on
    every entry" contract the docstring promises. Both are caught below.
    """
    from ti26.duration import sensitivity_sweep
    from ti26.rules import load_rules

    rules = load_rules("config/ti2026_rules.yaml")
    strengths = {f"t{i:02d}": (i - 7.5) * 0.15 for i in range(16)}
    result = sensitivity_sweep(strengths, rules, [0.25, 0.45, 0.80], n_sims=3000, seed=3)

    assert result[0]["max_abs_delta"] == 0.0
    assert result[0]["is_baseline"] is True
    assert result[0]["resolvable"] is False

    floors = {entry["noise_floor"] for entry in result}
    assert len(floors) == 1, "noise_floor must be one value shared by every entry"
    assert next(iter(floors)) > 0.0, "a hardcoded-zero floor would make every delta look resolvable"

    expected_keys = {"log_sigma", "max_abs_delta", "is_baseline", "noise_floor", "resolvable"}
    for entry in result:
        assert set(entry) == expected_keys


def test_fitted_sigma_differs_from_the_invented_placeholder():
    """If the fit reproduces 0.25 exactly, someone wired the placeholder
    through instead of estimating. Real pro durations are more dispersed."""
    rng = np.random.default_rng(31)
    durations = rng.lognormal(mean=7.55, sigma=0.34, size=15000)
    rows = [row(i, int(d)) for i, d in enumerate(durations)
            if MIN_DURATION_SECONDS < d < MAX_DURATION_SECONDS]
    fit = fit_duration_model(rows)
    assert abs(fit.log_sigma - 0.25) > 0.03
