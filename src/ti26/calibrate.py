"""D3: in-fold post-hoc calibration and the pre-registered calibration gate.

Spec: docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md, section
"D3 calibration gate". Registered 2026-08-02/03, before any calibration code
or model score existed:

    mean(LL_constant - LL_calibrated) >= 0.003 nats/map
    AND paired cluster bootstrap 95% CI on that difference excludes 0
    AND calibration slope of the calibrated model in [0.9, 1.1]

All three conditions, not any. Elo is the primary and only gated candidate
(registered 2026-08-03); calibrated Glicko is computed and reported as a
diagnostic only -- see `cli_d3.py` for where that split is enforced.

The correction must never see the outcomes it is later scored on. Within
each fold's OWN training window (never the fold's tournament): hold out the
most recent 20% as a calibration set, fit the base model on the first 80%,
predict the held-out 20%, fit slope/intercept there via `backtest.calibration`
(reused, not reimplemented), THEN refit the base model on the full 100% of
training rows and apply that fixed correction when predicting the fold's
tournament.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from ti26.backtest import (
    EPS,
    Fold,
    assert_fold_integrity,
    calibration,
    excluded_by_reason,
    paired_cluster_bootstrap,
    paired_differences,
)
from ti26.data.schema import MapRow
from ti26.data.store import assert_no_leakage
from ti26.ratings import GateConfig, Prediction, skip_reason

# Spec: "hold out the most recent 20% of training rows" -- fixed, not swept.
# Moving it after seeing a result would be exactly the post-hoc choice
# pre-registration exists to prevent.
HOLDOUT_FRACTION = 0.2

# Spec-registered D3 acceptance band for the calibrated model's out-of-sample
# calibration slope.
SLOPE_BAND = (0.9, 1.1)


def _clip(p: float) -> float:
    return min(max(p, EPS), 1.0 - EPS)


class CalibratedModel:
    """Wraps a base model with a FIXED logistic correction.

    `p' = sigmoid(intercept + slope * logit(p))`. `slope`/`intercept` are
    supplied already fitted -- this class never fits anything itself, so it
    cannot itself see the outcomes it is later scored against. `update()`
    delegates straight to the base model: calibration changes how the output
    is READ, not how the base model learns.
    """

    def __init__(self, base: object, slope: float, intercept: float) -> None:
        self._base = base
        self.slope = slope
        self.intercept = intercept

    def predict(self, row: MapRow) -> float:
        p = _clip(self._base.predict(row))
        logit = math.log(p / (1.0 - p))
        z = self.intercept + self.slope * logit
        return 1.0 / (1.0 + math.exp(-z))

    def update(self, row: MapRow) -> None:
        self._base.update(row)

    def flush(self) -> None:
        if hasattr(self._base, "flush"):
            self._base.flush()


def _predict_rows(model: object, rows: Sequence[MapRow]) -> list[Prediction]:
    predictions = []
    for row in rows:
        reason = skip_reason(row)
        predictions.append(
            Prediction(
                fold_id=-1, match_id=row.match_id, start_time=row.start_time,
                league_id=row.league_id, series_id=row.series_id,
                p_radiant=model.predict(row), rated=reason is None, reason=reason,
            )
        )
    return predictions


def fit_in_fold_calibration(
    train_rows: Sequence[MapRow],
    model_factory: Callable[[], object],
    holdout_fraction: float = HOLDOUT_FRACTION,
) -> tuple[float, float]:
    """The 80/20 in-fold split (spec: "In-fold calibration fitting").

    `train_rows` MUST already be one fold's own training window
    (`start_time <= fold.as_of`) -- this function never looks past what it
    is given, so it structurally cannot reach the fold's tournament. Sorts
    its own input chronologically rather than trusting caller order, so the
    held-out slice is always the most RECENT `holdout_fraction` of training
    data regardless of how `train_rows` was passed in.

    Returns the identity correction `(1.0, 0.0)` if there is too little data
    to split into two non-empty pieces, or if `backtest.calibration` bails
    out on a singular Hessian -- propagating NaN would poison every
    downstream prediction in the fold silently.
    """
    ordered = sorted(train_rows, key=lambda r: (r.start_time, r.match_id))
    split = int(len(ordered) * (1.0 - holdout_fraction))
    fit_rows, holdout_rows = ordered[:split], ordered[split:]
    if not fit_rows or not holdout_rows:
        return 1.0, 0.0

    model = model_factory()
    for row in fit_rows:
        model.update(row)
    if hasattr(model, "flush"):
        model.flush()

    predictions = _predict_rows(model, holdout_rows)
    slope, intercept = calibration(predictions, holdout_rows)
    if math.isnan(slope) or math.isnan(intercept):
        return 1.0, 0.0
    return slope, intercept


def run_calibrated_model(
    rows: Sequence[MapRow],
    model_factory: Callable[[], object],
    folds: Sequence[Fold],
    holdout_fraction: float = HOLDOUT_FRACTION,
) -> tuple[list[Prediction], list[tuple[int, float, float]]]:
    """Like `backtest.run_model`, but with an in-fold-fitted calibration
    correction applied to every out-of-sample prediction.

    Written as a SIBLING of `run_model`, not an extension of it: the two
    share the refit-from-scratch-per-fold structure, but the calibrated path
    needs a second, held-out-fitting model instance per fold that every
    existing caller of `run_model` (the already-shipped, already-reviewed D2
    gate) must never see. Adding an optional hook to `run_model` risked a new
    conditional branch inside code its existing tests already pin
    byte-for-byte; not touching `backtest.py` at all is the strongest
    available guarantee that D2's behaviour is unchanged.

    Per fold: fit the in-fold 80/20 calibration from the fold's training
    window only (`fit_in_fold_calibration`), then refit a FRESH base-model
    instance on the fold's FULL training window and wrap it in
    `CalibratedModel` before predicting the fold's tournament. The
    slope/intercept fitted here are local to this loop iteration -- nothing
    carries them into the next fold.

    Returns `(predictions, fitted_params)`, where `fitted_params` is
    `(fold_id, slope, intercept)` per fold, for reporting.
    """
    ordered = sorted(rows, key=lambda r: (r.start_time, r.match_id))
    assert_fold_integrity(folds, ordered)
    predictions: list[Prediction] = []
    fitted_params: list[tuple[int, float, float]] = []
    for fold in folds:
        train = [r for r in ordered if r.start_time <= fold.as_of]
        assert_no_leakage(train, fold.as_of)  # spec IV: blocking

        slope, intercept = fit_in_fold_calibration(train, model_factory, holdout_fraction)
        fitted_params.append((fold.fold_id, slope, intercept))

        final_base = model_factory()
        for row in train:
            final_base.update(row)
        calibrated = CalibratedModel(final_base, slope, intercept)
        calibrated.flush()

        for row in ordered:
            if row.league_id != fold.league_id:
                continue
            reason = skip_reason(row)
            predictions.append(
                Prediction(
                    fold_id=fold.fold_id, match_id=row.match_id, start_time=row.start_time,
                    league_id=row.league_id, series_id=row.series_id,
                    p_radiant=calibrated.predict(row), rated=reason is None, reason=reason,
                )
            )
    return predictions, fitted_params


@dataclass(frozen=True)
class D3GateResult:
    margin: float
    ci_low: float
    ci_high: float
    calibration_slope: float
    calibration_intercept: float
    slope_band: tuple[float, float]
    method: str
    n_maps: int
    margin_passed: bool
    ci_passed: bool
    slope_passed: bool
    passed: bool
    reasons: list[str] = field(default_factory=list)
    excluded: dict[str, int] = field(default_factory=dict)


def evaluate_d3_gate(
    predictions_constant: Sequence[Prediction],
    predictions_calibrated: Sequence[Prediction],
    rows: Sequence[MapRow],
    config: GateConfig,
    calibration_slope: float,
    calibration_intercept: float,
    slope_band: tuple[float, float] = SLOPE_BAND,
) -> D3GateResult:
    """The pre-registered D3 gate. ALL THREE conditions, per spec.

    `calibration_slope`/`calibration_intercept` must be measured OUT OF
    SAMPLE -- pass `backtest.calibration(predictions_calibrated, rows)`'s own
    output over the calibrated model's actual out-of-sample predictions, not
    a value read from any single fold's in-fold fit. The in-fold value
    corrects each fold's predictions internally; this one checks whether
    that correction actually worked, on the held-out tournaments the gate is
    scored on.

    Mirrors `backtest.evaluate_gate`'s margin/CI logic exactly (same
    pre-registered margin and clustered-bootstrap method as the D2 gate, so
    the two are directly comparable, per spec), and adds the slope-band
    condition the D2 gate did not have.
    """
    diff, tournament, series = paired_differences(
        predictions_constant, predictions_calibrated, rows
    )
    margin, lo, hi, method = paired_cluster_bootstrap(
        diff, tournament, series, config.bootstrap_draws, config.bootstrap_ci, config.seed
    )

    reasons: list[str] = []

    margin_passed = margin >= config.min_margin_nats
    if not margin_passed:
        reasons.append(
            f"margin {margin:.5f} < pre-registered {config.min_margin_nats} nats/map"
        )

    if lo <= 0.0 <= hi:
        ci_passed = False
        reasons.append(f"bootstrap {config.bootstrap_ci:.0%} CI [{lo:.5f}, {hi:.5f}] includes 0")
    elif hi < 0.0:
        ci_passed = False
        reasons.append(
            f"bootstrap {config.bootstrap_ci:.0%} CI [{lo:.5f}, {hi:.5f}] is entirely "
            "negative (the calibrated model is significantly worse than constant)"
        )
    else:
        ci_passed = True

    slope_passed = (
        not math.isnan(calibration_slope)
        and slope_band[0] <= calibration_slope <= slope_band[1]
    )
    if not slope_passed:
        reasons.append(
            f"calibration slope {calibration_slope:.4f} outside pre-registered "
            f"[{slope_band[0]}, {slope_band[1]}]"
        )

    return D3GateResult(
        margin=margin, ci_low=lo, ci_high=hi,
        calibration_slope=calibration_slope, calibration_intercept=calibration_intercept,
        slope_band=slope_band, method=method, n_maps=len(diff),
        margin_passed=margin_passed, ci_passed=ci_passed, slope_passed=slope_passed,
        passed=margin_passed and ci_passed and slope_passed,
        reasons=reasons,
        excluded=excluded_by_reason(predictions_constant),
    )
