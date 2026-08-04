"""Rolling event-cutoff backtesting and the pre-registered D2 gate.

Random train/test splitting is invalid here (spec IV): it lets future matches
inform past predictions, producing excellent metrics and useless forecasts.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from ti26.data.schema import MapRow
from ti26.data.store import assert_no_leakage
from ti26.ratings import GateConfig, Prediction, skip_reason

DAY_SECONDS = 86400
EPS = 1e-15


@dataclass(frozen=True)
class Fold:
    fold_id: int
    league_id: int
    as_of: int
    first_match: int
    n_train: int
    n_test: int


class FoldIntegrityError(AssertionError):
    """A fold violated a property the backtest's validity depends on."""


def assert_fold_integrity(folds: Sequence[Fold], rows: Sequence[MapRow]) -> None:
    """Check the properties that make a rolling backtest mean anything.

    Every one of these has silently produced good-looking, worthless metrics
    in real projects, so they are assertions rather than comments.
    """
    by_id = {}
    for fold in folds:
        if fold.fold_id in by_id:
            raise FoldIntegrityError(f"duplicate fold_id {fold.fold_id}")
        by_id[fold.fold_id] = fold

    seen_leagues = set()
    for fold in folds:
        if fold.league_id in seen_leagues:
            raise FoldIntegrityError(
                f"league {fold.league_id} appears in more than one fold; its maps "
                "would be scored twice and weighted double in the gate"
            )
        seen_leagues.add(fold.league_id)

        if fold.as_of >= fold.first_match:
            raise FoldIntegrityError(
                f"fold {fold.fold_id}: as_of={fold.as_of} is not before its first "
                f"match at {fold.first_match}"
            )
        test_rows = [r for r in rows if r.league_id == fold.league_id]
        if not test_rows:
            raise FoldIntegrityError(f"fold {fold.fold_id} has no test rows")
        earliest = min(r.start_time for r in test_rows)
        if earliest <= fold.as_of:
            raise FoldIntegrityError(
                f"fold {fold.fold_id}: a test map at {earliest} is at or before "
                f"as_of={fold.as_of}; it was in the training set"
            )
        if fold.n_test != len(test_rows):
            raise FoldIntegrityError(
                f"fold {fold.fold_id}: n_test={fold.n_test} but {len(test_rows)} rows match"
            )
        train_rows = [r for r in rows if r.start_time <= fold.as_of]
        if fold.n_train != len(train_rows):
            raise FoldIntegrityError(
                f"fold {fold.fold_id}: n_train={fold.n_train} but {len(train_rows)} "
                "rows precede as_of"
            )


@dataclass(frozen=True)
class GateResult:
    margin: float
    ci_low: float
    ci_high: float
    passed: bool
    method: str
    n_maps: int
    reasons: list[str] = field(default_factory=list)
    excluded: dict[str, int] = field(default_factory=dict)
    # Per-condition outcomes, exposed so a machine-readable result can record
    # which condition failed without re-deriving the gate's own predicates
    # elsewhere (or, worse, parsing them back out of `reasons`). They default
    # to True so an explicitly constructed passing result stays consistent;
    # `evaluate_gate` always sets both. `passed` remains their conjunction and
    # is unchanged by their presence.
    margin_passed: bool = True
    ci_passed: bool = True


def rolling_folds(rows: Sequence[MapRow], min_train: int = 500) -> list[Fold]:
    """One fold per tournament, cut 24h before its first match."""
    ordered = sorted(rows, key=lambda r: (r.start_time, r.match_id))
    first_seen: dict[int, int] = {}
    for row in ordered:
        if row.league_id is not None and row.league_id not in first_seen:
            first_seen[row.league_id] = row.start_time

    folds = []
    for league_id, first in sorted(first_seen.items(), key=lambda kv: kv[1]):
        as_of = first - DAY_SECONDS
        n_train = sum(1 for r in ordered if r.start_time <= as_of)
        n_test = sum(1 for r in ordered if r.league_id == league_id)
        if n_train < min_train:
            continue
        folds.append(
            Fold(
                fold_id=len(folds),
                league_id=league_id,
                as_of=as_of,
                first_match=first,
                n_train=n_train,
                n_test=n_test,
            )
        )
    return folds


def run_model(
    rows: Sequence[MapRow],
    model_factory: Callable[[], object],
    folds: Sequence[Fold],
) -> list[Prediction]:
    """Refit from scratch at each cutoff, then predict that tournament.

    The factory must return a fully wired model — the same object `cli_d2`
    constructs. Nothing here injects collaborators the runner would not.
    """
    ordered = sorted(rows, key=lambda r: (r.start_time, r.match_id))
    assert_fold_integrity(folds, ordered)
    predictions: list[Prediction] = []
    for fold in folds:
        train = [r for r in ordered if r.start_time <= fold.as_of]
        assert_no_leakage(train, fold.as_of)  # spec IV: blocking
        model = model_factory()
        for row in train:
            model.update(row)
        if hasattr(model, "flush"):
            model.flush()
        for row in ordered:
            if row.league_id != fold.league_id:
                continue
            reason = skip_reason(row)
            predictions.append(
                Prediction(
                    fold_id=fold.fold_id,
                    match_id=row.match_id,
                    start_time=row.start_time,
                    league_id=row.league_id,
                    series_id=row.series_id,
                    p_radiant=model.predict(row),
                    rated=reason is None,
                    reason=reason,
                )
            )
    return predictions


def _aligned(predictions: Sequence[Prediction], rows: Sequence[MapRow]) -> tuple:
    outcomes = {r.match_id: r.radiant_win for r in rows}
    ps, ys = [], []
    for prediction in predictions:
        if prediction.match_id in outcomes and prediction.rated:
            ps.append(min(max(prediction.p_radiant, EPS), 1.0 - EPS))
            ys.append(1.0 if outcomes[prediction.match_id] else 0.0)
    return np.asarray(ps), np.asarray(ys)


def excluded_by_reason(predictions: Sequence[Prediction]) -> dict[str, int]:
    """Tally of `rated=False` predictions by `reason`.

    Exposed so a report can show what was excluded from scoring rather than
    silently dropping it: the gate scores only what the model was willing to
    train on (`rated=True`), and that exclusion should be visible, not mute.
    """
    counts: dict[str, int] = {}
    for prediction in predictions:
        if not prediction.rated:
            key = prediction.reason if prediction.reason is not None else "unknown"
            counts[key] = counts.get(key, 0) + 1
    return counts


def per_map_log_loss(predictions: Sequence[Prediction], rows: Sequence[MapRow]) -> np.ndarray:
    ps, ys = _aligned(predictions, rows)
    return -(ys * np.log(ps) + (1 - ys) * np.log(1 - ps))


def log_loss(predictions: Sequence[Prediction], rows: Sequence[MapRow]) -> float:
    return float(per_map_log_loss(predictions, rows).mean())


def brier(predictions: Sequence[Prediction], rows: Sequence[MapRow]) -> float:
    ps, ys = _aligned(predictions, rows)
    return float(((ps - ys) ** 2).mean())


def accuracy(predictions: Sequence[Prediction], rows: Sequence[MapRow]) -> float:
    """Reported only. Spec II forbids using this for selection."""
    ps, ys = _aligned(predictions, rows)
    return float(((ps >= 0.5) == (ys >= 0.5)).mean())


def calibration(
    predictions: Sequence[Prediction], rows: Sequence[MapRow]
) -> tuple[float, float]:
    """Logistic recalibration: fit y ~ intercept + slope * logit(p).

    Slope 1 / intercept 0 is perfect. Slope < 1 means over-dispersion — the
    failure mode spec VI names as the one to hunt. Returns (nan, nan) if the
    Newton-Raphson hits a singular Hessian or fails to converge within the
    iteration cap: a bailed-out or partial fit is not a fit, and (1.0, 0.0)
    would silently read as a perfectly calibrated forecaster.
    """
    ps, ys = _aligned(predictions, rows)
    x = np.log(ps / (1 - ps))
    slope, intercept = 1.0, 0.0
    for _ in range(50):  # Newton-Raphson on the logistic likelihood
        z = intercept + slope * x
        mu = 1.0 / (1.0 + np.exp(-z))
        w = np.clip(mu * (1 - mu), 1e-12, None)
        residual = ys - mu
        design = np.column_stack([np.ones_like(x), x])
        hessian = design.T @ (design * w[:, None])
        gradient = design.T @ residual
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            return float("nan"), float("nan")
        intercept += step[0]
        slope += step[1]
        if np.max(np.abs(step)) < 1e-10:
            return float(slope), float(intercept)
    return float("nan"), float("nan")


class MisalignedPredictionsError(ValueError):
    """Two models produced predictions over different match sets."""


def paired_differences(
    predictions_a: Sequence[Prediction],
    predictions_b: Sequence[Prediction],
    rows: Sequence[MapRow],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Align two models' per-map losses BY match_id, not by position.

    Positional alignment is a silent corruption waiting to happen: the moment
    one model skips a row the other rates, every subsequent pair is mismatched
    and the gate compares unrelated maps while looking perfectly healthy.

    Only `rated=True` predictions are scored: the pre-registered gate should
    decide on the same population the model was willing to train on, so a
    row the model itself refused (`null_team`, `bad_roster`) is excluded from
    both sides rather than scored on a sentinel roster.
    """
    outcomes = {r.match_id: r.radiant_win for r in rows}

    def losses(predictions: Sequence[Prediction]) -> dict[int, float]:
        # Computed here rather than by zipping against `per_map_log_loss`,
        # which filters unmatched predictions out and would shift every
        # subsequent pairing by one -- silently, and only sometimes.
        out = {}
        for prediction in predictions:
            if prediction.match_id not in outcomes or not prediction.rated:
                continue
            p = min(max(prediction.p_radiant, EPS), 1.0 - EPS)
            y = 1.0 if outcomes[prediction.match_id] else 0.0
            out[prediction.match_id] = -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
        return out

    loss_a, loss_b = losses(predictions_a), losses(predictions_b)
    if set(loss_a) != set(loss_b):
        only_a = sorted(set(loss_a) - set(loss_b))[:5]
        only_b = sorted(set(loss_b) - set(loss_a))[:5]
        raise MisalignedPredictionsError(
            f"prediction sets differ: {len(loss_a)} vs {len(loss_b)} matches; "
            f"only in A {only_a}, only in B {only_b}"
        )

    cluster = {p.match_id: (p.league_id, p.series_id) for p in predictions_a}
    match_ids = sorted(loss_a)
    diff = np.asarray([loss_a[m] - loss_b[m] for m in match_ids], dtype=float)
    # A null league_id or series_id would silently merge unrelated maps into
    # one shared cluster, so both fall back to the match's own id: a
    # singleton cluster, never a merge.
    tournament = np.asarray(
        [cluster[m][0] if cluster[m][0] is not None else -m for m in match_ids]
    )
    series = np.asarray(
        [cluster[m][1] if cluster[m][1] is not None else -m for m in match_ids]
    )
    return diff, tournament, series


# Below this many tournaments, resampling whole tournaments yields too few
# distinct draws to form a usable distribution, so the second stage is added.
MIN_TOURNAMENTS_FOR_SINGLE_STAGE = 30

# Peak elements held by any one bootstrap batch. Batches are sized from this,
# so memory stays flat regardless of `draws`.
BOOTSTRAP_MEMORY_BUDGET = 2_000_000


def paired_cluster_bootstrap(
    diff: np.ndarray,
    tournament: np.ndarray,
    series: np.ndarray,
    draws: int,
    ci: float,
    seed: int,
    memory_budget: int = BOOTSTRAP_MEMORY_BUDGET,
) -> tuple[float, float, float, str]:
    """Cluster bootstrap over tournaments, falling back to two stages.

    Maps within a series share teams, day, patch and momentum, so iid
    resampling over maps treats ~3 correlated observations as 3 independent
    ones, understates the interval, and lets the gate pass on noise.

    Resampling WHOLE tournaments is the conservative choice: every correlated
    unit inside moves together. When tournaments are few, a second stage
    resamples series within each drawn tournament so the distribution is not
    degenerate. Returns the method actually used, which the report prints.
    """
    if len(diff) == 0:
        raise ValueError("no paired differences to bootstrap")

    # Collapse to series-level sums/counts first: the unit of resampling is
    # never the individual map.
    series_keys, series_inverse = np.unique(series, return_inverse=True)
    series_sum = np.bincount(series_inverse, weights=diff)
    series_cnt = np.bincount(series_inverse).astype(float)
    series_tournament = np.zeros(len(series_keys), dtype=tournament.dtype)
    series_tournament[series_inverse] = tournament

    tournament_keys, tournament_inverse = np.unique(series_tournament, return_inverse=True)
    n_tournaments = len(tournament_keys)
    alpha = (1.0 - ci) / 2.0
    means: list[np.ndarray] = []

    if n_tournaments >= MIN_TOURNAMENTS_FOR_SINGLE_STAGE:
        method = f"cluster bootstrap over {n_tournaments} tournaments"
        rng = np.random.default_rng(seed)
        t_sum = np.bincount(tournament_inverse, weights=series_sum)
        t_cnt = np.bincount(tournament_inverse, weights=series_cnt)
        batch = max(1, memory_budget // max(n_tournaments, 1))
        remaining = draws
        while remaining > 0:
            b = min(batch, remaining)
            idx = rng.integers(0, n_tournaments, size=(b, n_tournaments))
            means.append(t_sum[idx].sum(axis=1) / t_cnt[idx].sum(axis=1))
            remaining -= b
    else:
        method = (
            f"two-stage cluster bootstrap (tournament then series) over "
            f"{n_tournaments} tournaments"
        )
        by_tournament = [np.flatnonzero(tournament_inverse == t) for t in range(n_tournaments)]
        n_series = np.asarray([len(s) for s in by_tournament])
        width = int(n_series.max())
        padded_sum = np.zeros((n_tournaments, width))
        padded_cnt = np.zeros((n_tournaments, width))
        for t, members in enumerate(by_tournament):
            padded_sum[t, : len(members)] = series_sum[members]
            padded_cnt[t, : len(members)] = series_cnt[members]

        # Two INDEPENDENT generators, one per kind of draw. A single shared
        # generator interleaves rng.integers (t_idx) and rng.random (s_idx)
        # once per batch, so splitting `draws` across batches shifts where
        # each call lands in the stream and the result becomes batch-size
        # dependent -- verified empirically: the same seed and data gave a
        # different CI at memory_budget=50 than at memory_budget=2_000_000.
        # Two streams, each consuming only its own kind of call in a fixed
        # order regardless of batching, make this provably batch-invariant --
        # the same property the single-stage branch gets for free from using
        # only one kind of call.
        rng_t = np.random.default_rng(seed)
        rng_s = np.random.default_rng(seed + 1)
        batch = max(1, memory_budget // max(n_tournaments * width, 1))
        positions = np.arange(width)[None, None, :]
        remaining = draws
        while remaining > 0:
            b = min(batch, remaining)
            t_idx = rng_t.integers(0, n_tournaments, size=(b, n_tournaments))
            counts = n_series[t_idx][..., None]
            s_idx = (rng_s.random((b, n_tournaments, width)) * counts).astype(np.int64)
            mask = positions < counts
            sums = np.take_along_axis(padded_sum[t_idx], s_idx, axis=2) * mask
            cnts = np.take_along_axis(padded_cnt[t_idx], s_idx, axis=2) * mask
            means.append(sums.sum(axis=(1, 2)) / cnts.sum(axis=(1, 2)))
            remaining -= b

    distribution = np.concatenate(means)
    lo, hi = np.quantile(distribution, [alpha, 1.0 - alpha])
    return float(diff.mean()), float(lo), float(hi), method


def evaluate_gate(
    predictions_elo: Sequence[Prediction],
    predictions_glicko: Sequence[Prediction],
    rows: Sequence[MapRow],
    config: GateConfig,
) -> GateResult:
    """The pre-registered gate. BOTH conditions, per spec II."""
    diff, tournament, series = paired_differences(predictions_elo, predictions_glicko, rows)
    margin, lo, hi, method = paired_cluster_bootstrap(
        diff, tournament, series, config.bootstrap_draws, config.bootstrap_ci, config.seed
    )
    reasons = []
    margin_passed = not margin < config.min_margin_nats
    if not margin_passed:
        reasons.append(
            f"margin {margin:.5f} < pre-registered {config.min_margin_nats} nats/map"
        )
    ci_includes_zero = lo <= 0.0 <= hi
    ci_entirely_negative = hi < 0.0
    if ci_includes_zero:
        reasons.append(f"bootstrap {config.bootstrap_ci:.0%} CI [{lo:.5f}, {hi:.5f}] includes 0")
    elif ci_entirely_negative:
        reasons.append(
            f"bootstrap {config.bootstrap_ci:.0%} CI [{lo:.5f}, {hi:.5f}] is entirely "
            "negative (the comparator is significantly better)"
        )
    return GateResult(
        margin=margin,
        ci_low=lo,
        ci_high=hi,
        passed=not reasons,
        reasons=reasons,
        method=method,
        n_maps=len(diff),
        margin_passed=margin_passed,
        ci_passed=not ci_includes_zero and not ci_entirely_negative,
        # `rated` is a property of the row (`skip_reason`), not the model, so
        # elo and glicko agree on it whenever paired_differences didn't
        # already raise for a disagreement -- either side's tally is complete.
        excluded=excluded_by_reason(predictions_elo),
    )
