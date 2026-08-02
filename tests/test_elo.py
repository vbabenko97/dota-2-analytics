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
    assert sum(strengths.values()) == pytest.approx(0.0, abs=1e-9), "centred at zero"


def test_gate_config_loads_the_preregistered_margin():
    config = load_gate_config("config/d2_gate.yaml")
    assert config.min_margin_nats == 0.003
    assert config.bootstrap_ci == 0.95
