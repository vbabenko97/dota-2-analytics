"""The series-scoring producer, pinned where it could silently flatter itself."""

import math

import pytest

from ti26.cli_series_score import (
    best_of_for,
    metrics_for,
    one_sided_p_value,
    score_series,
)
from ti26.series import series_win_prob


def _entry(series_id, teams, wins, start=0):
    return {
        "series_id": series_id,
        "start": start,
        "maps": sum(wins.values()),
        "wins": dict(wins),
        "teams": set(teams),
    }


def test_best_of_is_read_from_the_maps_played_not_assumed():
    """Kills mutation: hardcode best_of=3 for every series.

    The population is 57 Bo3 and one Bo5 grand final. Scoring the Bo5 as a Bo3
    understates how much a favourite is helped by the longer format, and the
    grand final is the single most-watched prediction in the event.
    """
    assert best_of_for(_entry(1, ("a", "b"), {"a": 2, "b": 0})) == 3
    assert best_of_for(_entry(2, ("a", "b"), {"a": 2, "b": 1})) == 3
    assert best_of_for(_entry(3, ("a", "b"), {"a": 3, "b": 2})) == 5
    assert best_of_for(_entry(4, ("a", "b"), {"a": 1, "b": 0})) == 1


def test_longer_series_favour_the_favourite():
    """Kills mutation: return p_map unchanged instead of the series formula.

    A Bo5 converts a per-map edge into a bigger series edge than a Bo3, which
    is the whole reason series length has to be read from the data.
    """
    p = 0.60
    assert series_win_prob(p, 1) == pytest.approx(p)
    assert series_win_prob(p, 3) > series_win_prob(p, 1)
    assert series_win_prob(p, 5) > series_win_prob(p, 3)
    # The Bo3 closed form this function used to hardcode, preserved exactly.
    assert series_win_prob(p, 3) == pytest.approx(p**2 * (3 - 2 * p))
    assert series_win_prob(0.5, 5) == pytest.approx(0.5)


def test_orientation_is_the_smaller_team_id_not_the_models_favourite():
    """Kills mutation: orient each series on whichever side the model prefers.

    Orienting on the favourite forces every predicted probability above 0.5 and
    every outcome into 'favourite won or not'. Brier and log loss would then be
    computed on a quantity the model itself chose, and a model that always said
    0.99 for its favourite could look calibrated on a coin-flip population.
    Here 'b1' is much stronger, so a favourite-oriented implementation would
    report p > 0.5; the registered orientation reports p < 0.5 for 'a1'.
    """
    entries = [_entry(1, ("a1", "b1"), {"b1": 2, "a1": 0})]
    strengths = {"A": -1.0, "B": 1.0}
    ids = {"A": "a1", "B": "b1"}
    scored, excluded = score_series(entries, strengths, ids)
    assert not excluded
    assert scored[0]["team_a"] == "a1"
    assert scored[0]["p_a"] < 0.5
    assert scored[0]["a_won"] is False


def test_a_series_with_an_unrated_team_is_excluded_not_scored_at_even_odds():
    """Kills mutation: default a missing strength to 0.0.

    Defaulting silently scores the series at 50/50, which drags every metric
    toward the baseline and hides the gap. The spec caps exclusions at two and
    requires the count be reported, which is only possible if they are counted.
    """
    entries = [_entry(1, ("a1", "ghost"), {"a1": 2, "ghost": 1})]
    scored, excluded = score_series(entries, {"A": 0.5}, {"A": "a1"})
    assert scored == []
    assert len(excluded) == 1
    assert excluded[0]["missing"] == ["ghost"]


def test_metrics_recover_a_known_calibration_slope():
    """Kills mutation: report the intercept, or 1/slope, as the slope.

    Builds outcomes from a known logistic relationship: the truth is twice the
    predicted logit, so a correct refit returns about 2.0 and an inverted one
    about 0.5.

    There is no sampling here at all. Each predicted logit is replicated `reps`
    times and the wins among them are set to the EXACT expected proportion, so
    the fit is solving a noiseless problem and the test cannot flake. An earlier
    version assigned outcomes with `(i * 997) % 1000`, which looks scrambled but
    is monotone in the logit over each cycle and biased the slope to 2.82.
    """
    reps = 40
    scored = []
    for i in range(40):
        logit = -3.0 + 6.0 * i / 39
        p = 1.0 / (1.0 + math.exp(-logit))
        true_p = 1.0 / (1.0 + math.exp(-2.0 * logit))
        wins = round(true_p * reps)
        scored += [{"p_a": p, "a_won": j < wins} for j in range(reps)]
    m = metrics_for(scored)
    assert m["calibration_slope"] == pytest.approx(2.0, abs=0.1)
    assert m["calibration_slope_stderr"] > 0
    lo, hi = m["calibration_slope_ci95"]
    assert lo < m["calibration_slope"] < hi


def test_a_perfectly_calibrated_coin_flip_scores_the_baseline():
    """A model that always says 0.5 must tie the 0.5 baseline exactly."""
    scored = [{"p_a": 0.5, "a_won": i % 2 == 0} for i in range(20)]
    m = metrics_for(scored)
    assert m["brier"] == pytest.approx(m["baseline_brier_constant_half"])
    assert m["log_loss"] == pytest.approx(m["baseline_log_loss_constant_half"])


def test_the_p_value_is_the_upper_binomial_tail():
    """Kills mutation: use the two-sided or the lower tail.

    The spec asks how surprising this many CORRECT predictions would be under a
    coin flip, which is the upper tail. A two-sided value would roughly double
    the headline and a lower tail would invert it.
    """
    assert one_sided_p_value(10, 10) == pytest.approx(1 / 1024)
    assert one_sided_p_value(0, 10) == pytest.approx(1.0)
    assert one_sided_p_value(5, 10) > 0.5
    # The exact critical value the spec quotes for the registered population.
    assert one_sided_p_value(36, 58) <= 0.05
    assert one_sided_p_value(35, 58) > 0.05
