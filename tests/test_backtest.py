import math

import numpy as np
import pytest

from ti26.backtest import (
    MIN_TOURNAMENTS_FOR_SINGLE_STAGE,
    FoldIntegrityError,
    MisalignedPredictionsError,
    accuracy,
    assert_fold_integrity,
    brier,
    calibration,
    evaluate_gate,
    excluded_by_reason,
    log_loss,
    paired_cluster_bootstrap,
    paired_differences,
    rolling_folds,
    run_model,
)
from ti26.data.schema import MapRow
from ti26.ratings import GateConfig, Prediction
from ti26.ratings.simple import ConstantModel


def row(match_id, start_time, league_id, radiant_win=True):
    return MapRow(
        match_id=match_id, start_time=start_time, duration=2000, radiant_win=radiant_win,
        league_id=league_id, tier="professional", radiant_team_id=10, dire_team_id=20,
        series_id=1, series_type=1, patch="7.41",
        radiant_accounts=(1, 2, 3, 4, 5), dire_accounts=(6, 7, 8, 9, 10),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


def pred(match_id, p, league_id=1, series_id=0, fold_id=0, rated=True, reason=None):
    return Prediction(
        fold_id=fold_id, match_id=match_id, start_time=match_id, league_id=league_id,
        series_id=series_id, p_radiant=p, rated=rated, reason=reason,
    )


DAY = 86400


def test_folds_cut_24h_before_each_tournaments_first_match():
    rows = (
        [row(i, i * 100, league_id=1) for i in range(600)]
        + [row(1000 + i, 10_000_000 + i * 100, league_id=2) for i in range(50)]
    )
    folds = rolling_folds(rows, min_train=500)
    assert len(folds) == 1
    fold = folds[0]
    assert fold.league_id == 2
    assert fold.as_of == 10_000_000 - DAY, "cutoff is 24h before the first match (spec IV)"
    assert fold.first_match == 10_000_000
    assert fold.n_test == 50
    assert fold.fold_id == 0


def test_fold_integrity_accepts_well_formed_folds():
    rows = (
        [row(i, i * 100, league_id=1) for i in range(600)]
        + [row(1000 + i, 10_000_000 + i * 100, league_id=2) for i in range(50)]
    )
    assert assert_fold_integrity(rolling_folds(rows, min_train=500), rows) is None


def test_fold_integrity_rejects_a_cutoff_that_does_not_precede_its_tournament():
    """A cutoff at or after the first match means the model trained on the
    tournament it is being scored on -- the exact leakage spec IV forbids,
    and it produces excellent metrics."""
    from ti26.backtest import Fold

    rows = [row(1, 5_000, league_id=7)]
    bad = [Fold(fold_id=0, league_id=7, as_of=5_000, first_match=5_000, n_train=1, n_test=1)]
    with pytest.raises(FoldIntegrityError, match="not before"):
        assert_fold_integrity(bad, rows)


def test_fold_integrity_rejects_a_league_appearing_twice():
    """Duplicated folds double-weight one tournament in the gate."""
    from ti26.backtest import Fold

    rows = [row(1, 5_000, league_id=7)]
    # n_train=0 here is the actually-correct count (the row is at 5_000,
    # which is after both folds' as_of): this fixture must pass every OTHER
    # integrity check so the duplicate-league check is what fires.
    dupes = [
        Fold(fold_id=0, league_id=7, as_of=1_000, first_match=5_000, n_train=0, n_test=1),
        Fold(fold_id=1, league_id=7, as_of=2_000, first_match=5_000, n_train=0, n_test=1),
    ]
    with pytest.raises(FoldIntegrityError, match="more than one fold"):
        assert_fold_integrity(dupes, rows)


def test_fold_integrity_rejects_a_miscounted_test_set():
    from ti26.backtest import Fold

    rows = [row(1, 5_000, league_id=7), row(2, 6_000, league_id=7)]
    wrong = [Fold(fold_id=0, league_id=7, as_of=1_000, first_match=5_000, n_train=9, n_test=5)]
    with pytest.raises(FoldIntegrityError, match="n_test=5"):
        assert_fold_integrity(wrong, rows)


def test_fold_integrity_rejects_a_miscounted_train_set():
    """Mirrors the n_test check: a wrong n_train is just as capable of
    hiding a broken rolling-window computation."""
    from ti26.backtest import Fold

    rows = [row(1, 5_000, league_id=7)]
    wrong = [Fold(fold_id=0, league_id=7, as_of=1_000, first_match=5_000, n_train=99, n_test=1)]
    with pytest.raises(FoldIntegrityError, match="n_train=99"):
        assert_fold_integrity(wrong, rows)


def test_tournaments_without_enough_history_are_skipped():
    """A fold fitted on 20 maps produces a number, not evidence."""
    rows = [row(i, i * 100, league_id=1) for i in range(20)] + [
        row(1000 + i, 10_000_000 + i * 100, league_id=2) for i in range(50)
    ]
    assert rolling_folds(rows, min_train=500) == []


def test_log_loss_of_a_perfect_forecaster_is_zero():
    rows = [row(1, 1, 1, radiant_win=True), row(2, 2, 1, radiant_win=False)]
    predictions = [pred(1, 1 - 1e-12), pred(2, 1e-12)]
    assert log_loss(predictions, rows) == pytest.approx(0.0, abs=1e-9)


def test_log_loss_of_the_constant_baseline_is_ln_two():
    rows = [row(i, i, 1, radiant_win=i % 2 == 0) for i in range(10)]
    predictions = [pred(i, 0.5) for i in range(10)]
    assert log_loss(predictions, rows) == pytest.approx(math.log(2))


def test_log_loss_is_finite_for_a_confidently_wrong_forecast():
    """An unclipped 0.0 would give inf and destroy every downstream metric."""
    rows = [row(1, 1, 1, radiant_win=True)]
    assert math.isfinite(log_loss([pred(1, 0.0)], rows))


def test_brier_matches_hand_computation():
    rows = [row(1, 1, 1, radiant_win=True), row(2, 2, 1, radiant_win=False)]
    predictions = [pred(1, 0.8), pred(2, 0.3)]
    assert brier(predictions, rows) == pytest.approx((0.04 + 0.09) / 2)


def test_accuracy_is_reported_but_distinguishable_from_log_loss():
    """Spec II: accuracy is reported, never used for selection. This test
    exists to prove the two metrics can disagree, which is exactly why."""
    rows = [row(1, 1, 1, radiant_win=True), row(2, 2, 1, radiant_win=True)]
    confident = [pred(1, 0.99), pred(2, 0.51)]
    timid = [pred(1, 0.51), pred(2, 0.51)]
    assert accuracy(confident, rows) == accuracy(timid, rows) == 1.0
    assert log_loss(confident, rows) < log_loss(timid, rows)


def test_unrated_predictions_are_excluded_from_scoring_and_pairing():
    """The gate scores only what the model was willing to train on: a
    `rated=False` row (null_team / bad_roster) must not move log_loss or
    paired_differences, no matter how extreme its prediction is."""
    rows = [row(i, i, 1, radiant_win=i % 2 == 0) for i in range(10)]
    a = [pred(i, 0.5) for i in range(10)]
    b = [pred(i, 0.5) for i in range(10)]
    # Mark row 0 unrated on both sides, as run_model would for a
    # null_team/bad_roster row, with a wildly different prediction so an
    # accidental inclusion would be obvious.
    a[0] = pred(0, 0.99, rated=False, reason="bad_roster")
    b[0] = pred(0, 0.01, rated=False, reason="bad_roster")

    assert log_loss(a, rows) == pytest.approx(log_loss(a[1:], rows[1:]))
    diff_all, _, _ = paired_differences(a, b, rows)
    diff_rated, _, _ = paired_differences(a[1:], b[1:], rows[1:])
    assert diff_all == pytest.approx(diff_rated)
    assert len(diff_all) == 9


def test_excluded_by_reason_tallies_unrated_predictions():
    preds = [
        pred(1, 0.5),
        pred(2, 0.5, rated=False, reason="null_team"),
        pred(3, 0.5, rated=False, reason="bad_roster"),
        pred(4, 0.5, rated=False, reason="null_team"),
    ]
    assert excluded_by_reason(preds) == {"null_team": 2, "bad_roster": 1}


def test_calibration_of_a_well_calibrated_forecaster_has_slope_near_one():
    rng = np.random.default_rng(7)
    ps = rng.uniform(0.05, 0.95, size=4000)
    outcomes = rng.uniform(size=4000) < ps
    rows = [row(i, i, 1, radiant_win=bool(o)) for i, o in enumerate(outcomes)]
    predictions = [pred(i, float(p)) for i, p in enumerate(ps)]
    slope, intercept = calibration(predictions, rows)
    assert slope == pytest.approx(1.0, abs=0.15)
    assert intercept == pytest.approx(0.0, abs=0.15)


def test_calibration_detects_an_overconfident_forecaster():
    """Spec VI names over-dispersion at large gaps as THE failure mode to
    hunt. A calibration function that cannot detect it is useless."""
    rng = np.random.default_rng(11)
    truth = rng.uniform(0.2, 0.8, size=4000)
    outcomes = rng.uniform(size=4000) < truth
    logits = np.log(truth / (1 - truth))
    inflated = 1 / (1 + np.exp(-2.0 * logits))  # twice as extreme as reality
    rows = [row(i, i, 1, radiant_win=bool(o)) for i, o in enumerate(outcomes)]
    predictions = [pred(i, float(p)) for i, p in enumerate(inflated)]
    slope, _ = calibration(predictions, rows)
    assert slope < 0.75, "overconfidence must show up as slope well below 1"


def test_calibration_returns_nan_on_a_singular_hessian_rather_than_a_fake_perfect_fit():
    """Constant predictions make logit(p) constant for every row, so the
    design matrix's slope column is literally all zeros and the Hessian is
    exactly singular. (1.0, 0.0) would be indistinguishable from a genuine
    perfect calibration; NaN is visibly not a fit."""
    rows = [row(i, i, 1, radiant_win=i % 2 == 0) for i in range(20)]
    predictions = [pred(i, 0.5) for i in range(20)]
    slope, intercept = calibration(predictions, rows)
    assert math.isnan(slope)
    assert math.isnan(intercept)


def clustered(n_tournaments, series_per_tournament, maps_per_series, effect, noise, seed):
    """Build (diff, tournament, series) with variance living BETWEEN series.

    Every map in a series shares one draw, which is the correlation structure
    an iid map-level bootstrap wrongly ignores.
    """
    rng = np.random.default_rng(seed)
    diff, tournaments, series = [], [], []
    sid = 0
    for t in range(n_tournaments):
        for _ in range(series_per_tournament):
            shared = rng.normal(effect, noise)
            for _ in range(maps_per_series):
                diff.append(shared + rng.normal(0, 0.001))
                tournaments.append(t)
                series.append(sid)
            sid += 1
    return np.asarray(diff), np.asarray(tournaments), np.asarray(series)


def test_cluster_bootstrap_ci_excludes_zero_for_a_real_difference():
    diff, tour, ser = clustered(40, 12, 3, effect=0.02, noise=0.01, seed=3)
    mean, lo, _hi, method = paired_cluster_bootstrap(diff, tour, ser, 2000, 0.95, seed=1)
    assert mean == pytest.approx(0.02, abs=0.004)
    assert lo > 0.0
    assert "tournaments" in method


def test_cluster_bootstrap_ci_includes_zero_for_pure_noise():
    diff, tour, ser = clustered(40, 12, 3, effect=0.0, noise=0.05, seed=4)
    _, lo, hi, _ = paired_cluster_bootstrap(diff, tour, ser, 2000, 0.95, seed=1)
    assert lo < 0.0 < hi


def test_clustered_interval_is_wider_than_the_iid_one():
    """When correlation lives between series, an iid map-level bootstrap
    sees 3x more independent evidence than exists and reports a CI that is
    too narrow. This proves clustering beats naive iid resampling; it does
    NOT by itself prove tournament-level grouping is doing anything --
    a series-only bootstrap that ignores tournaments passes this test too.
    See test_tournament_clustering_is_wider_than_series_only_clustering for
    the test that isolates tournament-level clustering specifically.
    """
    diff, tour, ser = clustered(40, 12, 3, effect=0.0, noise=0.05, seed=5)
    _, c_lo, c_hi, _ = paired_cluster_bootstrap(diff, tour, ser, 2000, 0.95, seed=1)

    rng = np.random.default_rng(1)
    idx = rng.integers(0, len(diff), size=(2000, len(diff)))
    iid = diff[idx].mean(axis=1)
    i_lo, i_hi = np.quantile(iid, [0.025, 0.975])

    assert (c_hi - c_lo) > 1.5 * (i_hi - i_lo)


def clustered_with_tournament_effect(
    n_tournaments, series_per_tournament, maps_per_series, effect, tournament_noise,
    series_noise, seed,
):
    """Like clustered(), but adds a per-tournament shared shift ON TOP of
    the per-series shift, giving genuine between-tournament correlation.
    That is what distinguishes tournament-level clustering from series-only
    clustering: without it, a series-only bootstrap sees the same
    between-unit variance as tournament resampling and would pass a test
    that should only pass for real tournament-level clustering.
    """
    rng = np.random.default_rng(seed)
    diff, tournaments, series = [], [], []
    sid = 0
    for t in range(n_tournaments):
        tournament_shift = rng.normal(0.0, tournament_noise)
        for _ in range(series_per_tournament):
            shared = rng.normal(effect + tournament_shift, series_noise)
            for _ in range(maps_per_series):
                diff.append(shared + rng.normal(0, 0.001))
                tournaments.append(t)
                series.append(sid)
            sid += 1
    return np.asarray(diff), np.asarray(tournaments), np.asarray(series)


def _series_only_bootstrap(diff, series, draws, ci, seed):
    """A cluster bootstrap that resamples SERIES directly, ignoring which
    tournament each belongs to. Comparison baseline only, written
    independently of `paired_cluster_bootstrap` -- used to prove
    tournament-level resampling captures between-tournament correlation
    that series-only resampling misses.
    """
    series_keys, series_inverse = np.unique(series, return_inverse=True)
    series_sum = np.bincount(series_inverse, weights=diff)
    series_cnt = np.bincount(series_inverse).astype(float)
    n_series = len(series_keys)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n_series, size=(draws, n_series))
    means = series_sum[idx].sum(axis=1) / series_cnt[idx].sum(axis=1)
    alpha = (1.0 - ci) / 2.0
    return np.quantile(means, [alpha, 1.0 - alpha])


def test_tournament_clustering_is_wider_than_series_only_clustering():
    """THE test for tournament-level clustering specifically. With a real
    per-tournament shared shift on top of the per-series one, resampling
    whole tournaments must produce a wider interval than resampling series
    alone -- otherwise the tournament grouping in `paired_cluster_bootstrap`
    is not doing anything beyond what series-level clustering already does.
    """
    diff, tour, ser = clustered_with_tournament_effect(
        40, 12, 3, effect=0.0, tournament_noise=0.05, series_noise=0.01, seed=5
    )
    _, t_lo, t_hi, method = paired_cluster_bootstrap(diff, tour, ser, 2000, 0.95, seed=1)
    s_lo, s_hi = _series_only_bootstrap(diff, ser, 2000, 0.95, seed=1)
    assert "tournaments" in method
    assert (t_hi - t_lo) > 1.5 * (s_hi - s_lo)


def test_two_stage_path_engages_when_tournaments_are_few():
    """With a handful of tournaments, single-stage resampling has too few
    distinct draws; the second stage keeps the distribution usable."""
    diff, tour, ser = clustered(4, 30, 3, effect=0.01, noise=0.02, seed=6)
    _mean, lo, hi, method = paired_cluster_bootstrap(diff, tour, ser, 1000, 0.95, seed=1)
    assert "two-stage" in method
    assert np.isfinite(lo) and np.isfinite(hi) and lo < hi


@pytest.mark.parametrize(
    "n_tournaments,series_per_tournament",
    [(40, 6), (4, 30)],
    ids=["single-stage", "two-stage"],
)
def test_bootstrap_memory_budget_does_not_change_the_answer(n_tournaments, series_per_tournament):
    """Batching is an implementation detail; a tiny budget must give the same
    interval as a large one, or the batching is wrong. Parametrised over
    both branches: the two-stage path interleaves two kinds of random draws
    per batch (tournament indices, then series indices) and needs its own
    independent generator per kind to stay batch-invariant -- the
    single-stage path gets this for free from using only one kind of call.
    """
    diff, tour, ser = clustered(
        n_tournaments, series_per_tournament, 3, effect=0.01, noise=0.02, seed=7
    )
    big = paired_cluster_bootstrap(diff, tour, ser, 1000, 0.95, seed=1, memory_budget=2_000_000)
    small = paired_cluster_bootstrap(diff, tour, ser, 1000, 0.95, seed=1, memory_budget=50)
    assert big[:3] == pytest.approx(small[:3])


def test_bootstrap_is_seed_reproducible():
    diff, tour, ser = clustered(40, 6, 3, effect=0.01, noise=0.02, seed=8)
    first = paired_cluster_bootstrap(diff, tour, ser, 500, 0.95, seed=42)
    second = paired_cluster_bootstrap(diff, tour, ser, 500, 0.95, seed=42)
    assert first == second


def ragged_clustered(series_counts, maps_per_series, effect, noise, seed):
    """Like clustered(), but each tournament gets a DIFFERENT number of
    series, exercising the two-stage bootstrap's padding/masking arithmetic.
    clustered()'s uniform series_per_tournament never does, since every
    tournament there gets exactly the same width.
    """
    rng = np.random.default_rng(seed)
    diff, tournaments, series = [], [], []
    sid = 0
    for t, n_series in enumerate(series_counts):
        for _ in range(n_series):
            shared = rng.normal(effect, noise)
            for _ in range(maps_per_series):
                diff.append(shared + rng.normal(0, 0.001))
                tournaments.append(t)
                series.append(sid)
            sid += 1
    return np.asarray(diff), np.asarray(tournaments), np.asarray(series)


def _two_stage_unmasked_reference(diff, tournament, series, draws, ci, seed):
    """Reference two-stage bootstrap that skips the padding mask, built
    independently of `paired_cluster_bootstrap`'s internals -- comparison
    only, so the result means something.
    """
    series_keys, series_inverse = np.unique(series, return_inverse=True)
    series_sum = np.bincount(series_inverse, weights=diff)
    series_cnt = np.bincount(series_inverse).astype(float)
    series_tournament = np.zeros(len(series_keys), dtype=tournament.dtype)
    series_tournament[series_inverse] = tournament
    tournament_keys, tournament_inverse = np.unique(series_tournament, return_inverse=True)
    n_tournaments = len(tournament_keys)

    by_tournament = [np.flatnonzero(tournament_inverse == t) for t in range(n_tournaments)]
    n_series = np.asarray([len(s) for s in by_tournament])
    width = int(n_series.max())
    padded_sum = np.zeros((n_tournaments, width))
    padded_cnt = np.zeros((n_tournaments, width))
    for t, members in enumerate(by_tournament):
        padded_sum[t, : len(members)] = series_sum[members]
        padded_cnt[t, : len(members)] = series_cnt[members]

    rng_t = np.random.default_rng(seed)
    rng_s = np.random.default_rng(seed + 1)
    t_idx = rng_t.integers(0, n_tournaments, size=(draws, n_tournaments))
    counts = n_series[t_idx][..., None]
    s_idx = (rng_s.random((draws, n_tournaments, width)) * counts).astype(np.int64)
    # No mask: every one of the `width` draws is summed, even beyond a
    # sparse tournament's own series count.
    sums = np.take_along_axis(padded_sum[t_idx], s_idx, axis=2)
    cnts = np.take_along_axis(padded_cnt[t_idx], s_idx, axis=2)
    means = sums.sum(axis=(1, 2)) / cnts.sum(axis=(1, 2))
    alpha = (1.0 - ci) / 2.0
    return np.quantile(means, [alpha, 1.0 - alpha])


def test_two_stage_padding_mask_gives_a_wider_ci_than_leaving_padding_unmasked():
    """A tournament with fewer real series than the widest one is padded to
    a common width; the mask must exclude that padding from both the
    numerator and denominator. Without it, a sparse tournament is silently
    treated as if it had `width` real series instead of its own (smaller)
    count, understating its resampling variance and narrowing the CI -- the
    same failure the tournament-level clustering exists to avoid, one level
    down. clustered()'s uniform series-per-tournament never exercises this;
    this fixture is deliberately ragged (series counts [2, 3, 4, 5, 20]).
    """
    diff, tour, ser = ragged_clustered([2, 3, 4, 5, 20], 3, effect=0.02, noise=0.01, seed=99)
    n_tournaments = len(set(tour.tolist()))
    assert n_tournaments < MIN_TOURNAMENTS_FOR_SINGLE_STAGE  # forces the two-stage path

    _, masked_lo, masked_hi, method = paired_cluster_bootstrap(diff, tour, ser, 4000, 0.95, seed=7)
    assert "two-stage" in method
    unmasked_lo, unmasked_hi = _two_stage_unmasked_reference(diff, tour, ser, 4000, 0.95, seed=7)

    assert (masked_hi - masked_lo) > (unmasked_hi - unmasked_lo)


def test_losses_align_by_match_id_not_by_position():
    """If one model's prediction list is reordered, the paired difference
    must be unchanged. Positional zipping would silently compare unrelated
    maps. `b` must vary per match: a constant b gives -log(0.5) for every
    row regardless of outcome, which is position-invariant BY CONSTRUCTION
    under either a correct match_id-keyed implementation or a broken
    positional zip, so a constant b cannot ever fail this test.
    """
    rows = [row(i, i, 1, radiant_win=i % 3 == 0) for i in range(50)]
    a = [pred(i, 0.4 + 0.004 * i) for i in range(50)]
    b = [pred(i, 0.3 + 0.01 * i) for i in range(50)]
    straight, _, _ = paired_differences(a, b, rows)
    shuffled, _, _ = paired_differences(a, list(reversed(b)), rows)
    assert straight == pytest.approx(shuffled)


def test_mismatched_prediction_sets_raise():
    rows = [row(i, i, 1) for i in range(10)]
    a = [pred(i, 0.5) for i in range(10)]
    b = [pred(i, 0.5) for i in range(9)]
    with pytest.raises(MisalignedPredictionsError, match="10 vs 9"):
        paired_differences(a, b, rows)


def test_a_prediction_with_no_matching_row_does_not_shift_the_pairing():
    """Dropping an unmatched prediction must not slide every later pair by one.

    Zipping predictions against a filtered loss array does exactly that, and
    it fails silently: the arrays still have equal length, so nothing raises
    and the gate quietly compares unrelated maps.
    """
    rows = [row(i, i, 1, radiant_win=i % 2 == 0) for i in range(10)]
    extra = 999  # present in both prediction sets, absent from `rows`
    a = [pred(i, 0.3 + 0.05 * i) for i in range(10)] + [pred(extra, 0.9)]
    b = [pred(i, 0.5) for i in range(10)] + [pred(extra, 0.1)]

    with_extra, _, _ = paired_differences(a, b, rows)
    without_extra, _, _ = paired_differences(a[:-1], b[:-1], rows)
    assert with_extra == pytest.approx(without_extra)
    assert len(with_extra) == 10


def test_null_series_ids_become_singleton_clusters_not_one_giant_cluster():
    """Collapsing every unlabelled map into a single shared cluster would
    make the CI absurdly wide and the gate unpassable for a data reason."""
    rows = [row(i, i, 1) for i in range(20)]
    a = [pred(i, 0.6, series_id=None) for i in range(20)]
    b = [pred(i, 0.5, series_id=None) for i in range(20)]
    _, _, series = paired_differences(a, b, rows)
    assert len(set(series.tolist())) == 20


def test_null_league_ids_become_singleton_tournaments_not_one_giant_tournament():
    """Mirrors the series_id handling: collapsing every unlabelled map into
    a single shared tournament would silently merge unrelated maps'
    clusters at the tournament level too."""
    rows = [row(i, i, 1) for i in range(20)]
    a = [pred(i, 0.6, league_id=None, series_id=i) for i in range(20)]
    b = [pred(i, 0.5, league_id=None, series_id=i) for i in range(20)]
    _, tournament, _ = paired_differences(a, b, rows)
    assert len(set(tournament.tolist())) == 20


def config(**kw):
    base = {
        "min_margin_nats": 0.003, "bootstrap_draws": 1000, "bootstrap_ci": 0.95, "seed": 1,
        "elo_k": 20.0, "glicko_tau": 0.5, "ewma_half_life_maps": 30.0,
    }
    base.update(kw)
    return GateConfig(**base)


def gate_fixture(edge, jitter, seed, n_tournaments=40, series_per=10, maps_per=3):
    """Two prediction sets over the same maps, where B is better by `edge`.

    Built as real Prediction objects over real rows so the gate exercises the
    same alignment and clustering path the runner uses.
    """
    rng = np.random.default_rng(seed)
    rows, a, b = [], [], []
    match_id = 0
    sid = 0
    for t in range(n_tournaments):
        for _ in range(series_per):
            base = rng.uniform(0.35, 0.65)
            shift = rng.normal(edge, jitter)
            for _ in range(maps_per):
                won = rng.random() < base
                rows.append(row(match_id, match_id, league_id=t, radiant_win=won))
                pa = base if won else 1 - base
                pb = min(max(pa + shift, 0.01), 0.99)
                a.append(pred(match_id, pa if won else 1 - pa, league_id=t,
                              series_id=sid, fold_id=t))
                b.append(pred(match_id, pb if won else 1 - pb, league_id=t,
                              series_id=sid, fold_id=t))
                match_id += 1
            sid += 1
    return a, b, rows


def _gate_fixture_from_diff(diff, tournament, series):
    """Build two prediction sets whose per-map log-loss difference matches
    `diff` exactly (up to floating point), by fixing model A's probability
    and solving for model B's. This sidesteps the nonlinearity of going
    through a probability shift: log-loss's asymmetric penalty for
    confident wrongness can bias a probability-shift fixture's mean margin
    in ways unrelated to the between-cluster noise actually being tested
    (see test_gate_isolates_the_margin_condition /
    test_gate_isolates_the_ci_condition for why this matters).
    """
    rows, a, b = [], [], []
    c_a = 0.6  # A's fixed, moderately confident probability of being right
    for i, (d, t, s) in enumerate(zip(diff.tolist(), tournament.tolist(), series.tolist())):
        p_b = min(max(c_a * math.exp(d), 1e-6), 1.0 - 1e-6)
        rows.append(row(i, i, league_id=int(t), radiant_win=True))
        a.append(pred(i, c_a, league_id=int(t), series_id=int(s), fold_id=int(t)))
        b.append(pred(i, p_b, league_id=int(t), series_id=int(s), fold_id=int(t)))
    return a, b, rows


def test_gate_requires_both_conditions_margin_and_significance():
    # Consistent small edge to B, low between-series noise -> PASS.
    a, b, rows = gate_fixture(edge=0.05, jitter=0.005, seed=9)
    result = evaluate_gate(a, b, rows, config())
    assert result.passed is True
    assert result.reasons == []
    assert result.n_maps == len(rows)


def test_gate_isolates_the_margin_condition():
    """A small but statistically clear edge: the CI excludes zero (real,
    precisely-measured effect) while the mean margin sits below the
    pre-registered threshold. Exactly one reason -- margin -- must fire.
    """
    diff, tour, ser = clustered(40, 12, 3, effect=0.001, noise=0.0003, seed=3)
    a, b, rows = _gate_fixture_from_diff(diff, tour, ser)
    result = evaluate_gate(a, b, rows, config())
    assert result.passed is False
    assert result.reasons == [
        f"margin {result.margin:.5f} < pre-registered {config().min_margin_nats} nats/map"
    ]


def test_gate_isolates_the_ci_condition():
    """A margin comfortably above the pre-registered threshold, but with
    enough between-tournament noise that the CI straddles zero. Exactly one
    reason -- CI -- must fire; the earlier fixture for this
    (edge=0.02, jitter=0.60 through a probability shift) actually tripped
    BOTH conditions, and for the wrong reason: the jitter clipped B's
    probabilities and made it confidently wrong about half the time,
    giving margin=-0.745 (B being far worse, not "a real edge swamped by
    noise"). Building the diff distribution directly sidesteps that.
    """
    diff, tour, ser = clustered(15, 6, 3, effect=0.01, noise=0.08, seed=11)
    a, b, rows = _gate_fixture_from_diff(diff, tour, ser)
    result = evaluate_gate(a, b, rows, config())
    assert result.margin >= config().min_margin_nats
    assert result.passed is False
    assert len(result.reasons) == 1
    assert "CI" in result.reasons[0]


def test_gate_reads_the_margin_from_config_not_a_literal():
    """Pre-registration is meaningless if the threshold is hard-coded in two
    places and only one of them is the registered one."""
    a, b, rows = gate_fixture(edge=0.05, jitter=0.005, seed=13)
    assert evaluate_gate(a, b, rows, config(min_margin_nats=0.003)).passed is True
    assert evaluate_gate(a, b, rows, config(min_margin_nats=10.0)).passed is False


def test_gate_records_which_bootstrap_method_it_used():
    """The report prints this; a silently-swapped method would change the CI
    without changing anything a reader can see."""
    a, b, rows = gate_fixture(edge=0.05, jitter=0.005, seed=14)
    assert "tournaments" in evaluate_gate(a, b, rows, config()).method


def test_gate_reports_a_ci_entirely_below_zero_distinctly_from_including_zero():
    """A confidently negative margin (B far worse than A) must not be
    reported as "CI includes 0" -- that phrase is false when the whole
    interval sits below zero, and the gate's reasons exist to be read and
    trusted."""
    a, b, rows = gate_fixture(edge=0.02, jitter=0.60, seed=11)
    result = evaluate_gate(a, b, rows, config())
    assert result.ci_high < 0.0
    assert any("entirely negative" in r for r in result.reasons)
    assert not any("includes 0" in r for r in result.reasons)


def test_gate_result_exposes_excluded_prediction_counts():
    a, b, rows = gate_fixture(edge=0.05, jitter=0.005, seed=9)
    result = evaluate_gate(a, b, rows, config())
    assert result.excluded == {}


class _CountingModel:
    """A model whose only job is to prove `run_model`'s wiring: state
    (`updates`) that a fresh instance always starts at zero (to catch state
    leaking across folds), and a `flush()` so the hasattr-guarded flush call
    can be observed. Predicts a constant, so log-loss maths never enters
    into these structural checks.
    """

    def __init__(self):
        self.updates = 0
        self.flushed = False

    def update(self, row):
        self.updates += 1

    def predict(self, row):
        return 0.5

    def flush(self):
        self.flushed = True


def test_run_model_refits_from_scratch_per_fold():
    """State from one fold's training set must not leak into the next
    fold's model -- each fold gets its OWN freshly constructed model."""
    rows = (
        [row(i, i * 100, league_id=1) for i in range(600)]
        + [row(1000 + i, 10_000_000 + i * 100, league_id=2) for i in range(50)]
        + [row(2000 + i, 20_000_000 + i * 100, league_id=3) for i in range(30)]
    )
    folds = rolling_folds(rows, min_train=500)
    assert len(folds) == 2  # league 2 and league 3 both clear min_train

    instances = []

    def factory():
        model = _CountingModel()
        instances.append(model)
        return model

    run_model(rows, factory, folds)
    assert len(instances) == 2  # one fresh model per fold
    # If state leaked across folds, fold 1's model would start counting from
    # fold 0's updates instead of zero.
    assert instances[0].updates == folds[0].n_train
    assert instances[1].updates == folds[1].n_train


def test_run_model_calls_flush_on_models_that_have_it():
    rows = [row(i, i * 100, league_id=1) for i in range(600)] + [
        row(1000 + i, 10_000_000 + i * 100, league_id=2) for i in range(50)
    ]
    folds = rolling_folds(rows, min_train=500)
    instances = []

    def factory():
        model = _CountingModel()
        instances.append(model)
        return model

    run_model(rows, factory, folds)
    assert len(instances) == 1
    assert instances[0].flushed is True


def test_run_model_predictions_are_scoped_to_the_folds_own_league():
    """Also exercises a model WITHOUT flush (a real production model, not a
    fake): `hasattr(model, "flush")` must not raise when it's absent."""
    rows = (
        [row(i, i * 100, league_id=1) for i in range(600)]
        + [row(1000 + i, 10_000_000 + i * 100, league_id=2) for i in range(50)]
        + [row(2000 + i, 20_000_000 + i * 100, league_id=3) for i in range(30)]
    )
    folds = rolling_folds(rows, min_train=500)
    preds = run_model(rows, ConstantModel, folds)
    assert len(preds) == sum(f.n_test for f in folds)
    for fold in folds:
        fold_preds = [p for p in preds if p.fold_id == fold.fold_id]
        assert len(fold_preds) == fold.n_test
        assert {p.league_id for p in fold_preds} == {fold.league_id}


def test_run_model_populates_rated_and_reason_for_a_skipped_row():
    rows = [row(i, i * 100, league_id=1) for i in range(600)]
    good_test_rows = [row(1000 + i, 10_000_000 + i * 100, league_id=2) for i in range(49)]
    bad_row = MapRow(
        match_id=1049, start_time=10_000_000 + 49 * 100, duration=2000, radiant_win=True,
        league_id=2, tier="professional", radiant_team_id=10, dire_team_id=20,
        series_id=7, series_type=1, patch="7.41",
        radiant_accounts=(1, 2, 3, 4, -1), dire_accounts=(6, 7, 8, 9, 10),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=True,
    )
    all_rows = rows + good_test_rows + [bad_row]
    folds = rolling_folds(all_rows, min_train=500)
    preds = run_model(all_rows, ConstantModel, folds)

    by_id = {p.match_id: p for p in preds}
    bad = by_id[1049]
    assert bad.rated is False
    assert bad.reason == "bad_roster"
    assert bad.fold_id == folds[0].fold_id
    assert bad.league_id == 2
    assert bad.series_id == 7

    clean = by_id[1000]
    assert clean.rated is True
    assert clean.reason is None


def test_run_model_invokes_assert_no_leakage_with_the_folds_as_of(monkeypatch):
    """`assert_no_leakage` is spec IV's blocking check; this pins that
    `run_model` actually calls it (with the fold's own train slice and
    as_of) rather than relying on a hand-filtered `train` that happens to
    already satisfy it -- which would let a future refactor silently drop
    the safety net."""
    rows = [row(i, i * 100, league_id=1) for i in range(600)] + [
        row(1000 + i, 10_000_000 + i * 100, league_id=2) for i in range(50)
    ]
    folds = rolling_folds(rows, min_train=500)
    calls = []

    def spy(train_rows, as_of):
        calls.append((len(train_rows), as_of))

    monkeypatch.setattr("ti26.backtest.assert_no_leakage", spy)
    run_model(rows, ConstantModel, folds)
    assert calls == [(folds[0].n_train, folds[0].as_of)]
