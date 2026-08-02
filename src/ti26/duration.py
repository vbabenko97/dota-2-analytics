"""Fit the average-duration tiebreak model from real match durations.

Spec XII: the resolver is consulted on ~30% of ranking instances in every
simulated tournament, and until this task runs it is driven by an invented
log-normal tagged `arbitrary`. That parameter is steering a meaningful share
of simulated standings, so it gets estimated, not guessed.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from ti26.data.schema import MapRow

# Below 10 minutes a pro map is a forfeit or an abandon; above 2.5 hours it is
# a data error. Both are excluded from the fit and counted.
MIN_DURATION_SECONDS = 600
MAX_DURATION_SECONDS = 9000

# A gap effect counts as material when it shifts the conditional mean by at
# least 10% of the residual spread across the observed inter-quartile gap
# range. Below that it cannot move a duration tiebreak often enough to matter.
MATERIALITY_FRACTION = 0.10


@dataclass(frozen=True)
class DurationFit:
    log_mean: float
    log_sigma: float
    gap_coefficient: float
    gap_se: float
    n: int
    material: bool


def fit_duration_model(
    rows: Sequence[MapRow], gaps: Mapping[int, float] | None = None
) -> DurationFit:
    usable = [
        r for r in rows if MIN_DURATION_SECONDS < r.duration < MAX_DURATION_SECONDS
    ]
    if not usable:
        raise ValueError(
            "no usable durations in range; refusing to fall back to a placeholder"
        )

    logs = np.log(np.asarray([r.duration for r in usable], dtype=float))

    if gaps is None:
        return DurationFit(
            log_mean=float(logs.mean()),
            log_sigma=float(logs.std(ddof=1)),
            gap_coefficient=0.0,
            gap_se=float("nan"),
            n=len(usable),
            material=False,
        )

    paired = [(gaps[r.match_id], math.log(r.duration)) for r in usable if r.match_id in gaps]
    if len(paired) < 100:
        return DurationFit(
            log_mean=float(logs.mean()),
            log_sigma=float(logs.std(ddof=1)),
            gap_coefficient=0.0,
            gap_se=float("nan"),
            n=len(usable),
            material=False,
        )

    x = np.asarray([p[0] for p in paired])
    y = np.asarray([p[1] for p in paired])
    design = np.column_stack([np.ones_like(x), x])
    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
    intercept, slope = float(coefficients[0]), float(coefficients[1])

    residuals = y - design @ coefficients
    dof = len(y) - 2
    sigma = float(np.sqrt((residuals**2).sum() / dof))
    covariance = sigma**2 * np.linalg.inv(design.T @ design)
    slope_se = float(np.sqrt(covariance[1, 1]))

    q1, q3 = np.quantile(x, [0.25, 0.75])
    shift = abs(slope) * (q3 - q1)
    material = shift >= MATERIALITY_FRACTION * sigma and abs(slope) > 2 * slope_se

    return DurationFit(
        log_mean=intercept + slope * float(x.mean()),
        log_sigma=sigma,
        gap_coefficient=slope,
        gap_se=slope_se,
        n=len(usable),
        material=bool(material),
    )


def rating_gaps(rows: Sequence[MapRow], model) -> dict[int, float]:
    """Absolute pre-match logit gap per map, from a model walked in time order.

    Predict-then-update, so the gap for a map never sees that map's result.
    Spec XII requires the duration fit be conditioned at minimum on rating
    gap; this is what supplies it.
    """
    gaps: dict[int, float] = {}
    for row in sorted(rows, key=lambda r: (r.start_time, r.match_id)):
        p = min(max(model.predict(row), 1e-6), 1.0 - 1e-6)
        gaps[row.match_id] = abs(math.log(p / (1.0 - p)))
        model.update(row)
    return gaps


def sensitivity_sweep(
    strengths: Mapping[str, float],
    rules,
    sigmas: Sequence[float],
    n_sims: int = 20000,
    seed: int = 0,
) -> list[dict]:
    """How far does the card move across plausible `log_sigma` values?

    Spec XII: the duration parameter steers ~30% of every ranking, so the
    honest report is not just a point estimate but how much the answer depends
    on it. Compares each sigma's category marginals against the first sigma in
    the list, which the caller passes as the fitted value.
    """
    from dataclasses import replace

    from ti26.montecarlo import category_marginals
    from ti26.types import Category

    baseline: dict[str, dict] | None = None
    out: list[dict] = []
    for sigma in sigmas:
        marginals = category_marginals(
            dict(strengths), replace(rules, duration_log_sigma=sigma), n_sims=n_sims, seed=seed
        )
        if baseline is None:
            baseline = marginals
            out.append({"log_sigma": sigma, "max_abs_delta": 0.0, "is_baseline": True})
            continue
        delta = max(
            abs(marginals[team][category] - baseline[team][category])
            for team in baseline
            for category in Category
        )
        out.append({"log_sigma": sigma, "max_abs_delta": float(delta), "is_baseline": False})
    return out
