import dataclasses
import math

import numpy as np
import pytest

from ti26.backtest import Fold, calibration
from ti26.calibrate import (
    CalibratedModel,
    D3GateResult,
    evaluate_d3_gate,
    fit_in_fold_calibration,
    run_calibrated_model,
)
from ti26.data.schema import MapRow
from ti26.ratings import GateConfig, Prediction


def row(match_id, start_time, league_id, radiant_win=True):
    return MapRow(
        match_id=match_id, start_time=start_time, duration=2000, radiant_win=radiant_win,
        league_id=league_id, tier="professional", radiant_team_id=10, dire_team_id=20,
        series_id=match_id, series_type=1, patch="7.41",
        radiant_accounts=(1, 2, 3, 4, 5), dire_accounts=(6, 7, 8, 9, 10),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


def pred(match_id, p, league_id=1, series_id=None, fold_id=0, rated=True, reason=None):
    return Prediction(
        fold_id=fold_id, match_id=match_id, start_time=match_id, league_id=league_id,
        series_id=series_id if series_id is not None else match_id, p_radiant=p,
        rated=rated, reason=reason,
    )


# ---------------------------------------------------------------------------
# CalibratedModel
# ---------------------------------------------------------------------------


class _ConstantBase:
    """A base model with a KNOWN, fixed raw prediction. Ignoring update()
    isolates CalibratedModel's own arithmetic from any real fitting dynamics.
    """

    def __init__(self, p):
        self._p = p
        self.update_calls = 0

    def update(self, r):
        self.update_calls += 1

    def predict(self, r):
        return self._p


class _ConstantBaseWithFlush(_ConstantBase):
    def __init__(self, p):
        super().__init__(p)
        self.flushed = False

    def flush(self):
        self.flushed = True


def test_calibrated_model_applies_the_sigmoid_intercept_slope_logit_formula():
    """Catches a swapped slope/intercept, a sign flip on the slope term, or a
    missing sigmoid: p=0.8 is asymmetric enough (logit(0.8) != 0) that any of
    those mutations produces a materially different number from the formula
    computed independently here.
    """
    base = _ConstantBase(0.8)
    model = CalibratedModel(base, slope=2.0, intercept=-0.5)
    logit = math.log(0.8 / 0.2)
    expected = 1.0 / (1.0 + math.exp(-(-0.5 + 2.0 * logit)))
    assert model.predict(row(1, 1, 1)) == pytest.approx(expected, abs=1e-12)


def test_calibrated_model_identity_parameters_are_a_true_no_op():
    """slope=1, intercept=0 must reproduce the base model's raw probability
    exactly. Catches an implementation that distorts the output regardless
    of the parameters actually passed in (e.g. a hardcoded transform)."""
    base = _ConstantBase(0.37)
    model = CalibratedModel(base, slope=1.0, intercept=0.0)
    assert model.predict(row(1, 1, 1)) == pytest.approx(0.37, abs=1e-9)


def test_calibrated_model_clips_extreme_base_probabilities_before_the_logit():
    """An unclipped p=1.0 gives logit=inf and poisons every downstream
    number with nan. Consistent with backtest.EPS (spec: "clamp ... consistent
    with backtest.EPS")."""
    base = _ConstantBase(1.0)
    model = CalibratedModel(base, slope=1.0, intercept=0.0)
    result = model.predict(row(1, 1, 1))
    assert math.isfinite(result)
    assert result > 0.999


def test_calibrated_model_update_delegates_to_the_base_model():
    base = _ConstantBase(0.5)
    model = CalibratedModel(base, slope=1.0, intercept=0.0)
    model.update(row(1, 1, 1))
    model.update(row(2, 2, 1))
    assert base.update_calls == 2


def test_calibrated_model_flush_delegates_when_the_base_model_has_one():
    base = _ConstantBaseWithFlush(0.5)
    model = CalibratedModel(base, slope=1.0, intercept=0.0)
    model.flush()
    assert base.flushed is True


def test_calibrated_model_flush_is_a_no_op_when_the_base_model_lacks_one():
    base = _ConstantBase(0.5)  # no flush attribute at all
    model = CalibratedModel(base, slope=1.0, intercept=0.0)
    model.flush()  # must not raise


# ---------------------------------------------------------------------------
# fit_in_fold_calibration / run_calibrated_model -- the leakage guard
# ---------------------------------------------------------------------------


class _LookupModel:
    """Ignores update(); predict() returns a caller-supplied fixed value per
    match_id. Isolates exactly WHICH rows the calibration fit sees,
    independent of any real fitting dynamics -- essential for the leakage
    guard test below, where the whole point is to catch code reading the
    wrong slice of rows, not to catch a bad model fit.
    """

    def __init__(self, table):
        self._table = table

    def update(self, r):
        pass

    def predict(self, r):
        return self._table[r.match_id]


def _build_fold(seed, league_id, id_base, n_filler=800, n_holdout=200, n_test=200,
                 well_calibrated_holdout=True, well_calibrated_test=False):
    """One fold's synthetic (filler + holdout + test) rows, a lookup table for
    `_LookupModel`, the `Fold` describing it, and the REFERENCE slope/intercept
    obtained by fitting `calibration()` directly on the intended holdout.

    `well_calibrated_*` picks whether that population's outcomes are drawn
    from Bernoulli(p) (well-calibrated, slope near 1) or Bernoulli(1-p)
    (inverted, slope strongly negative) relative to the raw p's the lookup
    model reports for it -- giving two widely-separated, unambiguous fits to
    tell apart. match_id is deliberately DECREASING as start_time increases
    (id_base - i), so sorting by match_id instead of start_time would select
    a completely different, easily-distinguished slice -- the fixture cannot
    pass by an implementation that sorts on the wrong key or trusts input
    order.
    """
    rng = np.random.default_rng(seed)
    ps_holdout = rng.uniform(0.1, 0.9, size=n_holdout)
    outcomes_holdout = rng.uniform(size=n_holdout) < (
        ps_holdout if well_calibrated_holdout else 1 - ps_holdout
    )
    ps_test = rng.uniform(0.1, 0.9, size=n_test)
    outcomes_test = rng.uniform(size=n_test) < (ps_test if well_calibrated_test else 1 - ps_test)

    # Training rows carry a DIFFERENT league_id from the fold's own tournament
    # -- they represent earlier, unrelated tournaments. If they shared
    # `league_id`, `assert_fold_integrity`'s own test-row count (which
    # filters `rows` by `r.league_id == fold.league_id`) would wrongly
    # include them, since it does not otherwise know "training" from "test".
    train_league_id = league_id + 1_000_000
    filler = [
        row(id_base - i, i, train_league_id, radiant_win=(i % 2 == 0)) for i in range(n_filler)
    ]
    holdout = [
        row(id_base - (n_filler + i), n_filler + i, train_league_id,
            radiant_win=bool(outcomes_holdout[i]))
        for i in range(n_holdout)
    ]
    first_test_time = n_filler + n_holdout + 1_000
    test = [
        row(id_base - (n_filler + n_holdout + 10_000 + j), first_test_time + j, league_id,
            radiant_win=bool(outcomes_test[j]))
        for j in range(n_test)
    ]

    lookup = {r.match_id: 0.5 for r in filler}
    lookup.update({r.match_id: float(p) for r, p in zip(holdout, ps_holdout, strict=True)})
    lookup.update({r.match_id: float(p) for r, p in zip(test, ps_test, strict=True)})

    holdout_preds = [
        Prediction(fold_id=-1, match_id=r.match_id, start_time=r.start_time,
                   league_id=r.league_id, series_id=r.series_id,
                   p_radiant=lookup[r.match_id], rated=True, reason=None)
        for r in holdout
    ]
    reference_slope, reference_intercept = calibration(holdout_preds, holdout)

    train = filler + holdout
    fold = Fold(
        fold_id=league_id, league_id=league_id, as_of=n_filler + n_holdout - 1,
        first_match=first_test_time, n_train=len(train), n_test=len(test),
    )
    return train, test, lookup, fold, (reference_slope, reference_intercept)


def test_calibration_is_fitted_on_the_training_holdout_not_the_test_tournament():
    """THE most important test in this module.

    The holdout population is well-calibrated (outcomes ~ Bernoulli(p)); the
    test tournament is badly miscalibrated in the OPPOSITE direction
    (outcomes ~ Bernoulli(1-p)) for the SAME raw probabilities. If
    `run_calibrated_model` ever let the fit see the test tournament's
    outcomes instead of the training hold-out's, the returned slope/intercept
    would swing sharply toward the inverted relationship instead of the
    well-calibrated one -- a difference no ordinary fitting noise could
    produce by accident.
    """
    train, test, lookup, fold, (correct_slope, correct_intercept) = _build_fold(
        seed=123, league_id=2, id_base=1_000_000,
        well_calibrated_holdout=True, well_calibrated_test=False,
    )
    all_rows = train + test

    _, fitted = run_calibrated_model(all_rows, lambda: _LookupModel(lookup), [fold])
    assert len(fitted) == 1
    fold_id, slope, intercept = fitted[0]
    assert fold_id == fold.fold_id

    # The LEAKY reference: what calibration() would return if fitted on the
    # test tournament instead of the training hold-out.
    test_preds = [
        Prediction(fold_id=-1, match_id=r.match_id, start_time=r.start_time,
                   league_id=r.league_id, series_id=r.series_id,
                   p_radiant=lookup[r.match_id], rated=True, reason=None)
        for r in test
    ]
    leaky_slope, leaky_intercept = calibration(test_preds, test)

    # Sanity: the two references must actually be far apart, or this test
    # could pass by coincidence even reading the wrong slice.
    assert abs(correct_slope - leaky_slope) > 0.5 or abs(correct_intercept - leaky_intercept) > 0.5

    assert slope == pytest.approx(correct_slope, abs=1e-6)
    assert intercept == pytest.approx(correct_intercept, abs=1e-6)
    assert slope != pytest.approx(leaky_slope, abs=0.3)


class _CountingModel:
    """update()-counting, flush()-observing stand-in -- proves
    `run_calibrated_model` creates a FRESH instance for the 80% calibration
    fit AND a separate fresh instance for the 100% final fit, every fold,
    with no state leaking from one fold's instances into the next fold's.
    Predicts a constant so calibration arithmetic never enters into this
    structural check.
    """

    def __init__(self):
        self.updates = 0
        self.flushed = False

    def update(self, r):
        self.updates += 1

    def predict(self, r):
        return 0.5

    def flush(self):
        self.flushed = True


def test_run_calibrated_model_uses_a_fresh_model_instance_per_stage_per_fold():
    """Each fold needs TWO independent model instances -- the 80%-only model
    used to fit the correction, and the 100% final model used to score the
    tournament -- and neither may carry a count from a previous fold or the
    other stage. Catches a bug where an instance is reused across the two
    stages, or across folds (e.g. a factory that memoizes, or a variable
    captured by mistake instead of a fresh `model_factory()` call).

    Fold 2's training window legitimately includes fold 1's train+test rows
    (rolling-fold design: later folds see earlier tournaments as history) --
    the expected counts below are computed accounting for that, not assuming
    the folds are independent.
    """
    rows_1 = [row(i, i * 100, league_id=1) for i in range(600)]
    tourney_1 = [row(1000 + i, 10_000_000 + i * 100, league_id=2) for i in range(50)]
    rows_2 = [row(2000 + i, 20_000_000 + i * 100, league_id=1) for i in range(200)]
    tourney_2 = [row(3000 + i, 30_000_000 + i * 100, league_id=3) for i in range(50)]
    all_rows = rows_1 + tourney_1 + rows_2 + tourney_2

    fold_1 = Fold(fold_id=0, league_id=2, as_of=10_000_000 - 1, first_match=10_000_000,
                  n_train=len(rows_1), n_test=len(tourney_1))
    combined_fold_2_train = len(rows_1) + len(tourney_1) + len(rows_2)
    fold_2 = Fold(fold_id=1, league_id=3, as_of=30_000_000 - 1, first_match=30_000_000,
                  n_train=combined_fold_2_train, n_test=len(tourney_2))

    instances = []

    def factory():
        model = _CountingModel()
        instances.append(model)
        return model

    run_calibrated_model(all_rows, factory, [fold_1, fold_2])

    # 2 folds x 2 stages (80% calibration fit, 100% final fit) = 4 instances.
    assert len(instances) == 4
    assert all(inst.flushed for inst in instances)

    assert instances[0].updates == int(600 * 0.8), "fold 1's 80% calibration-fit stage"
    assert instances[1].updates == 600, "fold 1's 100% final-fit stage"

    assert instances[2].updates == int(combined_fold_2_train * 0.8), (
        "fold 2's 80% stage must see fold 1's rows too (rolling design), starting its "
        "own count from zero -- not fold 1's leftover count and not fold 2's own rows alone"
    )
    assert instances[3].updates == combined_fold_2_train, "fold 2's 100% final-fit stage"


def test_fit_in_fold_calibration_never_receives_rows_past_as_of():
    """`fit_in_fold_calibration` receives exactly the fold's training window
    (never the tournament) -- proven directly rather than only through the
    full pipeline above."""
    train, _test, lookup, _fold, (correct_slope, correct_intercept) = _build_fold(
        seed=7, league_id=1, id_base=500_000,
    )
    slope, intercept = fit_in_fold_calibration(train, lambda: _LookupModel(lookup))
    assert slope == pytest.approx(correct_slope, abs=1e-6)
    assert intercept == pytest.approx(correct_intercept, abs=1e-6)


def test_fit_in_fold_calibration_returns_identity_when_data_is_too_thin_to_split():
    """A single training row cannot be split into two non-empty pieces; the
    identity correction must not raise or return nan."""
    slope, intercept = fit_in_fold_calibration(
        [row(1, 1, 1)], lambda: _LookupModel({1: 0.5})
    )
    assert (slope, intercept) == (1.0, 0.0)


def test_fit_in_fold_calibration_returns_identity_on_a_singular_fit_not_nan():
    """A constant raw prediction across the whole hold-out makes the design
    matrix's slope column constant, which `backtest.calibration` reports as
    (nan, nan). Propagating nan would poison every downstream prediction in
    the fold; identity must be substituted instead."""
    rows = [row(100 - i, i, 1, radiant_win=(i % 2 == 0)) for i in range(20)]
    slope, intercept = fit_in_fold_calibration(
        rows, lambda: _LookupModel(dict.fromkeys((r.match_id for r in rows), 0.5))
    )
    assert (slope, intercept) == (1.0, 0.0)


# ---------------------------------------------------------------------------
# evaluate_d3_gate -- controlled arithmetic
# ---------------------------------------------------------------------------


def d3_config(**kw):
    base = {
        "min_margin_nats": 0.003, "bootstrap_draws": 2000, "bootstrap_ci": 0.95, "seed": 1,
        "elo_k": 20.0, "glicko_tau": 0.5, "ewma_half_life_maps": 30.0,
    }
    base.update(kw)
    return GateConfig(**base)


def _diff_fixture(value, n_tournaments, series_per, maps_per, jitter, seed):
    """Real Prediction/MapRow pairs whose per-map log-loss difference
    (constant - calibrated) is exactly `value` on every map when jitter=0,
    or `value` plus a per-tournament shared shift when jitter>0 (for
    between-tournament CI-width control). Built by fixing the constant
    model's probability at 0.5 with radiant_win always True (so its loss is
    exactly ln 2) and solving for the calibrated model's probability that
    gives the target per-map difference -- avoids re-deriving the bootstrap
    machinery already covered in test_backtest.py.
    """
    rng = np.random.default_rng(seed)
    rows, a, b = [], [], []
    match_id = 0
    sid = 0
    for t in range(n_tournaments):
        tournament_shift = rng.normal(0.0, jitter) if jitter else 0.0
        for _ in range(series_per):
            for _ in range(maps_per):
                d = value + tournament_shift
                p_b = min(max(math.exp(d) / 2.0, 1e-6), 1.0 - 1e-6)
                rows.append(row(match_id, match_id, league_id=t, radiant_win=True))
                a.append(pred(match_id, 0.5, league_id=t, series_id=sid, fold_id=t))
                b.append(pred(match_id, p_b, league_id=t, series_id=sid, fold_id=t))
                match_id += 1
            sid += 1
    return a, b, rows


def test_d3_gate_passes_when_all_three_conditions_hold():
    a, b, rows = _diff_fixture(0.05, n_tournaments=40, series_per=3, maps_per=2, jitter=0.005, seed=3)
    result = evaluate_d3_gate(a, b, rows, d3_config(), calibration_slope=1.0, calibration_intercept=0.0)
    assert result.margin_passed is True
    assert result.ci_passed is True
    assert result.slope_passed is True
    assert result.passed is True
    assert result.reasons == []


def test_d3_gate_fails_on_margin_condition_alone():
    """A small, but statistically clear, edge: CI excludes zero while the
    mean margin sits below the pre-registered threshold. Exactly one
    reason -- margin -- must fire."""
    a, b, rows = _diff_fixture(0.001, n_tournaments=40, series_per=3, maps_per=2, jitter=0.0002, seed=5)
    result = evaluate_d3_gate(a, b, rows, d3_config(), calibration_slope=1.0, calibration_intercept=0.0)
    assert result.margin_passed is False
    assert result.ci_passed is True
    assert result.slope_passed is True
    assert result.passed is False
    assert len(result.reasons) == 1
    assert "margin" in result.reasons[0]


def test_d3_gate_fails_on_ci_condition_alone():
    """A margin comfortably above threshold, but with enough between-
    tournament noise that the CI straddles zero. Exactly one reason -- CI --
    must fire."""
    a, b, rows = _diff_fixture(0.01, n_tournaments=15, series_per=6, maps_per=3, jitter=0.08, seed=11)
    result = evaluate_d3_gate(a, b, rows, d3_config(), calibration_slope=1.0, calibration_intercept=0.0)
    assert result.margin_passed is True
    assert result.ci_passed is False
    assert result.slope_passed is True
    assert result.passed is False
    assert len(result.reasons) == 1
    assert "CI" in result.reasons[0]


def test_d3_gate_fails_on_slope_condition_alone():
    a, b, rows = _diff_fixture(0.05, n_tournaments=40, series_per=3, maps_per=2, jitter=0.005, seed=9)
    result = evaluate_d3_gate(a, b, rows, d3_config(), calibration_slope=0.5, calibration_intercept=0.0)
    assert result.margin_passed is True
    assert result.ci_passed is True
    assert result.slope_passed is False
    assert result.passed is False
    assert len(result.reasons) == 1
    assert "slope" in result.reasons[0]


def test_d3_gate_nan_slope_fails_the_slope_condition():
    """A bailed-out calibration fit (nan) must read as FAIL, never as a
    silent pass -- nan compared with <= is always False, so a careless
    `not (nan < lo or nan > hi)`-style check could wrongly pass this."""
    a, b, rows = _diff_fixture(0.05, n_tournaments=40, series_per=3, maps_per=2, jitter=0.005, seed=13)
    result = evaluate_d3_gate(
        a, b, rows, d3_config(), calibration_slope=float("nan"), calibration_intercept=0.0
    )
    assert result.slope_passed is False
    assert result.passed is False


def test_d3_gate_margin_boundary_is_inclusive():
    """Spec: '>= 0.003'. Exactly at the threshold must PASS; the smallest
    possible increment above the threshold must FAIL.

    Reads back the fixture's OWN actual margin and uses it as the
    threshold, rather than trying to engineer the fixture to land on an
    exact literal like 0.003 -- `_diff_fixture` reaches its target `diff`
    value through exp()/log(), and floating-point round-trip through those
    is not guaranteed to hit a literal bit-exactly (confirmed: it does not
    always). Comparing the SAME computed float to itself, and to the next
    representable float above it via `math.nextafter`, tests the exact `>=`
    boundary without depending on that round-trip's precision. Mutating
    `>=` to `>` flips only the exact-threshold case.
    """
    a, b, rows = _diff_fixture(0.05, n_tournaments=40, series_per=3, maps_per=2, jitter=0.0, seed=1)
    probe = evaluate_d3_gate(
        a, b, rows, d3_config(min_margin_nats=-1e9), calibration_slope=1.0, calibration_intercept=0.0
    )
    actual_margin = probe.margin

    at_threshold = evaluate_d3_gate(
        a, b, rows, d3_config(min_margin_nats=actual_margin),
        calibration_slope=1.0, calibration_intercept=0.0,
    )
    assert at_threshold.margin_passed is True, "margin exactly equal to the threshold must PASS"

    just_above = math.nextafter(actual_margin, math.inf)
    result_just_above = evaluate_d3_gate(
        a, b, rows, d3_config(min_margin_nats=just_above),
        calibration_slope=1.0, calibration_intercept=0.0,
    )
    assert result_just_above.margin_passed is False, (
        "a threshold the smallest possible float increment above the margin must FAIL"
    )


def test_d3_gate_slope_band_boundary_is_inclusive():
    """Spec: 'in [0.9, 1.1]'. Exactly at either boundary must PASS; a hair
    outside must FAIL. Mutating either `<=` to `<` flips only the
    exact-boundary case."""
    a, b, rows = _diff_fixture(0.05, n_tournaments=40, series_per=3, maps_per=2, jitter=0.005, seed=17)
    for slope in (0.9, 1.1):
        result = evaluate_d3_gate(a, b, rows, d3_config(), calibration_slope=slope, calibration_intercept=0.0)
        assert result.slope_passed is True, f"slope={slope} is the inclusive boundary"
    for slope in (0.8999999, 1.1000001):
        result = evaluate_d3_gate(a, b, rows, d3_config(), calibration_slope=slope, calibration_intercept=0.0)
        assert result.slope_passed is False, f"slope={slope} is just outside the band"


def test_d3_gate_reports_a_ci_entirely_below_zero_distinctly_from_including_zero():
    """A confidently negative diff (calibrated model far worse than constant)
    must not be reported as 'CI includes 0' -- that phrase is false when the
    whole interval sits below zero."""
    a, b, rows = _diff_fixture(-0.05, n_tournaments=40, series_per=3, maps_per=2, jitter=0.001, seed=19)
    result = evaluate_d3_gate(a, b, rows, d3_config(), calibration_slope=1.0, calibration_intercept=0.0)
    assert result.ci_high < 0.0
    assert result.ci_passed is False
    assert any("entirely negative" in r for r in result.reasons)
    assert not any("includes 0" in r for r in result.reasons)


def test_d3_gate_excludes_the_same_reasons_the_constant_predictions_report():
    a, b, rows = _diff_fixture(0.05, n_tournaments=40, series_per=3, maps_per=2, jitter=0.005, seed=21)
    next_id = max(p.match_id for p in a) + 1
    rows.append(row(next_id, next_id, league_id=0, radiant_win=True))
    a.append(pred(next_id, 0.5, league_id=0, series_id=0, fold_id=0, rated=False, reason="null_team"))
    b.append(pred(next_id, 0.5, league_id=0, series_id=0, fold_id=0, rated=False, reason="null_team"))

    result = evaluate_d3_gate(a, b, rows, d3_config(), calibration_slope=1.0, calibration_intercept=0.0)
    assert result.excluded == {"null_team": 1}
    assert result.n_maps == len(rows) - 1


def test_d3_gate_result_is_a_frozen_dataclass_with_all_fields():
    """Cheap structural check that nothing was left off the result type the
    CLI report depends on."""
    a, b, rows = _diff_fixture(0.05, n_tournaments=40, series_per=3, maps_per=2, jitter=0.005, seed=23)
    result = evaluate_d3_gate(a, b, rows, d3_config(), calibration_slope=1.0, calibration_intercept=0.0)
    assert isinstance(result, D3GateResult)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.passed = False
