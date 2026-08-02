import math

import numpy as np
import pytest

from ti26.backtest import (
    FoldIntegrityError,
    MisalignedPredictionsError,
    accuracy,
    assert_fold_integrity,
    brier,
    calibration,
    evaluate_gate,
    log_loss,
    paired_cluster_bootstrap,
    paired_differences,
    rolling_folds,
)
from ti26.data.schema import MapRow
from ti26.ratings import GateConfig, Prediction


def row(match_id, start_time, league_id, radiant_win=True):
    return MapRow(
        match_id=match_id, start_time=start_time, duration=2000, radiant_win=radiant_win,
        league_id=league_id, tier="professional", radiant_team_id=10, dire_team_id=20,
        series_id=1, series_type=1, patch="7.41",
        radiant_accounts=(1, 2, 3, 4, 5), dire_accounts=(6, 7, 8, 9, 10),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


def pred(match_id, p, league_id=1, series_id=0, fold_id=0):
    return Prediction(
        fold_id=fold_id, match_id=match_id, start_time=match_id, league_id=league_id,
        series_id=series_id, p_radiant=p, rated=True,
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
    dupes = [
        Fold(fold_id=0, league_id=7, as_of=1_000, first_match=5_000, n_train=1, n_test=1),
        Fold(fold_id=1, league_id=7, as_of=2_000, first_match=5_000, n_train=1, n_test=1),
    ]
    with pytest.raises(FoldIntegrityError, match="more than one fold"):
        assert_fold_integrity(dupes, rows)


def test_fold_integrity_rejects_a_miscounted_test_set():
    from ti26.backtest import Fold

    rows = [row(1, 5_000, league_id=7), row(2, 6_000, league_id=7)]
    wrong = [Fold(fold_id=0, league_id=7, as_of=1_000, first_match=5_000, n_train=9, n_test=5)]
    with pytest.raises(FoldIntegrityError, match="n_test=5"):
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
    """THE test for this task. When correlation lives between series, an iid
    map-level bootstrap sees 3x more independent evidence than exists and
    reports a CI that is too narrow -- which is how a gate passes on noise.

    If this fails, the clustering is cosmetic.
    """
    diff, tour, ser = clustered(40, 12, 3, effect=0.0, noise=0.05, seed=5)
    _, c_lo, c_hi, _ = paired_cluster_bootstrap(diff, tour, ser, 2000, 0.95, seed=1)

    rng = np.random.default_rng(1)
    idx = rng.integers(0, len(diff), size=(2000, len(diff)))
    iid = diff[idx].mean(axis=1)
    i_lo, i_hi = np.quantile(iid, [0.025, 0.975])

    assert (c_hi - c_lo) > 1.5 * (i_hi - i_lo)


def test_two_stage_path_engages_when_tournaments_are_few():
    """With a handful of tournaments, single-stage resampling has too few
    distinct draws; the second stage keeps the distribution usable."""
    diff, tour, ser = clustered(4, 30, 3, effect=0.01, noise=0.02, seed=6)
    _mean, lo, hi, method = paired_cluster_bootstrap(diff, tour, ser, 1000, 0.95, seed=1)
    assert "two-stage" in method
    assert np.isfinite(lo) and np.isfinite(hi) and lo < hi


def test_bootstrap_memory_budget_does_not_change_the_answer():
    """Batching is an implementation detail; a tiny budget must give the same
    interval as a large one, or the batching is wrong."""
    diff, tour, ser = clustered(40, 6, 3, effect=0.01, noise=0.02, seed=7)
    big = paired_cluster_bootstrap(diff, tour, ser, 1000, 0.95, seed=1, memory_budget=2_000_000)
    small = paired_cluster_bootstrap(diff, tour, ser, 1000, 0.95, seed=1, memory_budget=50)
    assert big[:3] == pytest.approx(small[:3])


def test_bootstrap_is_seed_reproducible():
    diff, tour, ser = clustered(40, 6, 3, effect=0.01, noise=0.02, seed=8)
    first = paired_cluster_bootstrap(diff, tour, ser, 500, 0.95, seed=42)
    second = paired_cluster_bootstrap(diff, tour, ser, 500, 0.95, seed=42)
    assert first == second


def test_losses_align_by_match_id_not_by_position():
    """If one model's prediction list is reordered, the paired difference must
    be unchanged. Positional zipping would silently compare unrelated maps.
    """
    rows = [row(i, i, 1, radiant_win=i % 3 == 0) for i in range(50)]
    a = [pred(i, 0.4 + 0.004 * i) for i in range(50)]
    b = [pred(i, 0.5) for i in range(50)]
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


def test_gate_requires_both_conditions_margin_and_significance():
    # Consistent small edge to B, low between-series noise -> PASS.
    a, b, rows = gate_fixture(edge=0.05, jitter=0.005, seed=9)
    result = evaluate_gate(a, b, rows, config())
    assert result.passed is True
    assert result.reasons == []
    assert result.n_maps == len(rows)

    # No edge at all -> margin condition fails.
    a, b, rows = gate_fixture(edge=0.0, jitter=0.005, seed=10)
    result = evaluate_gate(a, b, rows, config())
    assert result.passed is False
    assert any("margin" in r for r in result.reasons)

    # Real average edge, but swamped by between-series noise -> CI fails.
    a, b, rows = gate_fixture(edge=0.02, jitter=0.60, seed=11)
    result = evaluate_gate(a, b, rows, config())
    assert result.passed is False
    assert any("CI" in r for r in result.reasons)


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
