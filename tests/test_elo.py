import math

import pytest

from ti26.data.schema import MapRow
from ti26.ratings import load_gate_config
from ti26.ratings.elo import EloModel


def row(match_id, start_time, radiant, dire, radiant_win=True, **kw):
    base = {
        "duration": 2000, "league_id": 1, "tier": "professional",
        "radiant_team_id": 10, "dire_team_id": 20, "series_id": 1, "series_type": 1,
        "patch": "7.41",
        "radiant_heroes": (1, 2, 3, 4, 5), "dire_heroes": (6, 7, 8, 9, 10),
        "has_null_team": False, "has_bad_roster": False,
    }
    base.update(kw)
    return MapRow(
        match_id=match_id, start_time=start_time, radiant_win=radiant_win,
        radiant_accounts=tuple(radiant), dire_accounts=tuple(dire), **base
    )


A = [1, 2, 3, 4, 5]
B = [6, 7, 8, 9, 10]


def test_unseen_rosters_predict_exactly_even():
    model = EloModel()
    assert model.predict(row(1, 100, A, B)) == pytest.approx(0.5)


def test_winner_gains_exactly_what_the_loser_loses():
    from ti26.roster import roster_version_id

    model = EloModel(k=20.0)
    model.update(row(1, 100, A, B, radiant_win=True))
    ra = model.rating(roster_version_id(A))
    rb = model.rating(roster_version_id(B))
    assert ra == pytest.approx(1510.0)
    assert rb == pytest.approx(1490.0)
    assert (ra - 1500.0) == pytest.approx(-(rb - 1500.0)), "Elo is zero-sum"


def test_repeated_wins_increase_predicted_probability_monotonically():
    model = EloModel()
    seen = []
    for i in range(5):
        seen.append(model.predict(row(i, 100 + i, A, B)))
        model.update(row(i, 100 + i, A, B, radiant_win=True))
    assert seen == sorted(seen)
    assert seen[0] == pytest.approx(0.5)
    assert seen[-1] > 0.55


def test_null_team_rows_are_not_rated_and_say_why():
    """Spec III: never silently dropped. The row is skipped for rating
    updates, but the skip is counted with a reason."""
    model = EloModel()
    model.update(row(1, 100, A, B, radiant_win=True, has_null_team=True))
    from ti26.roster import roster_version_id
    assert model.rating(roster_version_id(A)) == 1500.0
    assert model.skipped == {"null_team": 1}


def test_bad_roster_rows_are_not_rated():
    model = EloModel()
    model.update(row(1, 100, A, B, radiant_win=True, has_bad_roster=True))
    assert model.skipped == {"bad_roster": 1}


def test_strengths_are_logit_scale_and_centred():
    """montecarlo.category_marginals consumes logit-scale strengths where a
    difference of 1.0 means ~73% map win probability. Handing it raw Elo
    points (difference of 400) would produce a degenerate simulation."""
    model = EloModel()
    for i in range(10):
        model.update(row(i, 100 + i, A, B, radiant_win=True))
    strengths = model.strengths()
    from ti26.roster import roster_version_id
    gap = strengths[roster_version_id(A)] - strengths[roster_version_id(B)]
    elo_gap = model.rating(roster_version_id(A)) - model.rating(roster_version_id(B))
    assert gap == pytest.approx(elo_gap * math.log(10) / 400.0)


def test_strengths_stay_consistent_with_predict_at_a_non_default_scale():
    """`strengths()` must derive its logit conversion from the model's own
    `scale`, not a hardcoded 400 -- otherwise a non-default scale would make
    `strengths()` disagree with this same instance's `predict()`, which is
    exactly the degenerate-simulation failure the logit-scale contract
    exists to prevent."""
    from ti26.roster import roster_version_id

    model = EloModel(scale=200.0)
    for i in range(10):
        model.update(row(i, 100 + i, A, B, radiant_win=True))
    strengths = model.strengths()
    gap = strengths[roster_version_id(A)] - strengths[roster_version_id(B)]
    implied_p = 1.0 / (1.0 + math.exp(-gap))
    assert implied_p == pytest.approx(model.predict(row(999, 999, A, B)))


def test_strengths_centring_point_is_stable_across_differently_sized_fits():
    """Elo is zero-sum: every update adds +delta to the winner and -delta to
    the loser, so the mean of every rated roster is always exactly the
    initial rating (1500), no matter how many other rosters have played or
    how asymmetric their histories are. This is what makes strengths from
    two differently-sized fits comparable at all: if a model's centring
    point drifted with population size, the same roster A/B result would be
    assigned a different strength depending on what else happened to be fit
    alongside it."""
    from ti26.roster import roster_version_id

    small = EloModel()
    small.update(row(1, 100, A, B, radiant_win=True))

    large = EloModel()
    large.update(row(1, 100, A, B, radiant_win=True))
    other_rosters = [
        ([11, 12, 13, 14, 15], [16, 17, 18, 19, 20]),
        ([21, 22, 23, 24, 25], [26, 27, 28, 29, 30]),
        ([31, 32, 33, 34, 35], [36, 37, 38, 39, 40]),
    ]
    match_id = 2
    for x, y in other_rosters:
        for i in range(5):
            large.update(row(match_id, 100 + match_id, x, y, radiant_win=(i % 2 == 0)))
            match_id += 1

    rvid_a = roster_version_id(A)
    assert small.strengths()[rvid_a] == pytest.approx(large.strengths()[rvid_a])


def test_gate_config_loads_the_preregistered_margin():
    config = load_gate_config("config/d2_gate.yaml")
    assert config.min_margin_nats == 0.003
    assert config.bootstrap_ci == 0.95
