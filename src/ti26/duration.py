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
    """`log_sigma` is the marginal (unconditional) SD of log-duration over the
    rows the fit actually used -- the quantity `DurationResolver`
    (`tiebreak.py`) samples from, since it draws
    `lognormvariate(log_mean, log_sigma)` with no gap term of its own.
    `residual_log_sigma` is the SD left over after conditioning on rating gap;
    it is a diagnostic for the materiality test only, is `nan` unless the gap
    regression ran, and must never be fed to the resolver in its place.
    """

    log_mean: float
    log_sigma: float
    residual_log_sigma: float
    gap_coefficient: float
    gap_se: float
    n: int
    material: bool


def fit_duration_model(
    rows: Sequence[MapRow], gaps: Mapping[int, float] | None = None
) -> DurationFit:
    """Fit log-duration to a log-normal, optionally conditioned on rating gap.

    `log_sigma` is always the marginal dispersion of the rows the fit used --
    see `DurationFit`. `n` is the sample size behind the estimate actually
    returned: every usable row on the two marginal-only paths below, but only
    the rows the regression ran on (`paired`) once a gap regression runs.
    """
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
            residual_log_sigma=float("nan"),
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
            residual_log_sigma=float("nan"),
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
    # Residual (conditional-on-gap) dispersion: the correct denominator for
    # "does the gap shift the mean relative to unexplained spread", used only
    # by the materiality test below -- never returned as `log_sigma`.
    residual_sigma = float(np.sqrt((residuals**2).sum() / dof))
    covariance = residual_sigma**2 * np.linalg.inv(design.T @ design)
    slope_se = float(np.sqrt(covariance[1, 1]))

    q1, q3 = np.quantile(x, [0.25, 0.75])
    shift = abs(slope) * (q3 - q1)
    material = shift >= MATERIALITY_FRACTION * residual_sigma and abs(slope) > 2 * slope_se

    return DurationFit(
        log_mean=intercept + slope * float(x.mean()),
        log_sigma=float(y.std(ddof=1)),
        residual_log_sigma=residual_sigma,
        gap_coefficient=slope,
        gap_se=slope_se,
        n=len(paired),
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

    Spec XII: the resolver is consulted on ~30% of every ranking, but that
    high consultation rate does not by itself mean this parameter moves the
    card -- it only means the resolver is asked often. Whether the answer
    actually depends on `log_sigma` has to be checked against this
    statistic's own resampling noise, not assumed.

    `noise_floor` is an ESTIMATE of that resampling noise from a small number
    of draws, not a fixed property of the sweep: it is the largest of the
    three pairwise max-abs-deltas among three runs of the *same* baseline
    sigma (the first entry in `sigmas`) under seeds `seed`, `seed + 1`, and
    `seed + 2`. Taking the max of three pairs is deliberately conservative
    (biased toward a higher floor, i.e. toward calling fewer sigmas
    resolvable), because a single pair was observed to vary roughly 2x across
    unrelated seed choices at typical sample sizes -- a floor that happened to
    land at the low end of that range would wrongly report `resolvable=True`
    for a delta that was still just noise. Even so, `noise_floor` remains
    variable from run to run, and the same value is reported on every
    returned entry since it is a property of the sweep's sampling noise, not
    of any particular sigma.

    A `max_abs_delta` at or below `noise_floor` is NOT evidence that sigma
    moved anything; it is what pure resampling noise looks like. Only
    `resolvable=True` (`max_abs_delta > noise_floor`) entries indicate a
    change distinguishable from noise, and a `resolvable` result near the
    boundary should not be read as a firm finding -- rerun with a fresh seed
    before trusting it. Measured for this model (tied and spread strengths,
    sigma 0.05 vs 1.20, n_sims=20000): every sigma-varying delta observed so
    far fell inside or below the noise-floor range, so the honest reading is
    that `log_sigma` does not move the card resolvably at the sample sizes
    checked so far, even though the resolver itself is consulted constantly.
    See spec XII for the fuller writeup.
    """
    from dataclasses import replace

    from ti26.montecarlo import category_marginals
    from ti26.types import Category

    def _max_abs_delta(a: dict[str, dict], b: dict[str, dict]) -> float:
        return max(
            abs(a[team][category] - b[team][category]) for team in a for category in Category
        )

    baseline: dict[str, dict] | None = None
    noise_floor = 0.0
    out: list[dict] = []
    for sigma in sigmas:
        marginals = category_marginals(
            dict(strengths), replace(rules, duration_log_sigma=sigma), n_sims=n_sims, seed=seed
        )
        if baseline is None:
            baseline = marginals
            baseline_runs = [
                marginals,
                category_marginals(
                    dict(strengths),
                    replace(rules, duration_log_sigma=sigma),
                    n_sims=n_sims,
                    seed=seed + 1,
                ),
                category_marginals(
                    dict(strengths),
                    replace(rules, duration_log_sigma=sigma),
                    n_sims=n_sims,
                    seed=seed + 2,
                ),
            ]
            noise_floor = max(
                _max_abs_delta(baseline_runs[a], baseline_runs[b])
                for a, b in [(0, 1), (0, 2), (1, 2)]
            )
            out.append(
                {
                    "log_sigma": sigma,
                    "max_abs_delta": 0.0,
                    "is_baseline": True,
                    "noise_floor": noise_floor,
                    "resolvable": False,
                }
            )
            continue
        delta = _max_abs_delta(marginals, baseline)
        out.append(
            {
                "log_sigma": sigma,
                "max_abs_delta": float(delta),
                "is_baseline": False,
                "noise_floor": noise_floor,
                "resolvable": bool(delta > noise_floor),
            }
        )
    return out
