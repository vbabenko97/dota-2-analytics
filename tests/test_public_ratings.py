import math
from datetime import UTC, datetime

import pytest

from ti26.data.schema import MapRow
from ti26.public_ratings import (
    LOGIT_PER_ELO,
    PublicRating,
    classify_form_verdict,
    observed_recent_form,
    parse_ratings,
    scale_sensitivity_sweep,
    strengths_from_ratings,
    wilson_interval,
)
from ti26.roster import roster_version_id


def test_parse_ratings_casts_bigint_strings_defensively():
    """OpenDota's explorer serialises bigint columns (team_id,
    last_match_time) as JSON strings. A parser that does `row["team_id"]`
    without casting would leave a str team_id, silently breaking every
    downstream `team_id in by_id` / dict-key lookup in cli_rung3 (a str key
    never matches an int team_id from `ti2026_teams.yaml`). Also pins that
    wins/losses/rating land in the right fields -- a transposed
    wins<->losses assignment would pass a "just parses without crashing"
    test but fail this one's exact-value checks.
    """
    rows = [
        {
            "team_id": "9572001",  # bigint -> JSON string
            "rating": 1553.33,  # real -> native float
            "wins": 329,  # integer -> native int
            "losses": 172,
            "last_match_time": "1782408313",  # bigint -> JSON string
        }
    ]
    parsed = parse_ratings(rows)
    assert set(parsed) == {9572001}
    assert isinstance(next(iter(parsed)), int)
    r = parsed[9572001]
    assert isinstance(r, PublicRating)
    assert r.team_id == 9572001 and isinstance(r.team_id, int)
    assert r.rating == pytest.approx(1553.33)
    assert r.wins == 329
    assert r.losses == 172
    assert r.last_match_time == 1782408313 and isinstance(r.last_match_time, int)


def test_is_thin_boundary_exactly_at_the_threshold():
    """A test sitting entirely above or below the threshold never exercises
    the boundary branch (the documented trap in this codebase). Fixture:
    `wins` is IDENTICAL (100) on both sides and only `losses` differs (99 vs
    100), so `games = wins + losses` is what must separate them -- a buggy
    `is_thin` that checked `wins < threshold` alone would return the SAME
    (True) answer for both and fail this test's second assertion.
    """
    just_under = PublicRating(team_id=1, rating=1200.0, wins=100, losses=99, last_match_time=0)
    exactly_at = PublicRating(team_id=2, rating=1200.0, wins=100, losses=100, last_match_time=0)
    assert just_under.games == 199
    assert exactly_at.games == 200
    assert just_under.is_thin() is True, "199 < 200 must be thin"
    assert exactly_at.is_thin() is False, (
        "200 is NOT under 200 -- a <= mutation would wrongly flag this thin"
    )


def test_stale_days_conversion_and_is_stale_boundary():
    """Pins the seconds-per-day divisor (a wrong constant, e.g. 3600, would
    fail the exact-value assertion by roughly 24x) and the boundary
    direction of `is_stale` (a `>` mutation instead of `>=` would flip the
    second case, since 30.0 days lands exactly on the threshold).
    """
    now = datetime(2026, 8, 2, tzinfo=UTC)
    ten_days_ago = PublicRating(
        team_id=1, rating=1300.0, wins=10, losses=10,
        last_match_time=int(now.timestamp()) - 10 * 86400,
    )
    assert ten_days_ago.stale_days(now) == pytest.approx(10.0, abs=1e-6)

    just_under = PublicRating(
        team_id=2, rating=1300.0, wins=10, losses=10,
        last_match_time=int(now.timestamp()) - 29 * 86400,
    )
    exactly_at = PublicRating(
        team_id=3, rating=1300.0, wins=10, losses=10,
        last_match_time=int(now.timestamp()) - 30 * 86400,
    )
    assert just_under.is_stale(now) is False, "29 days must not be stale (threshold is 30)"
    assert exactly_at.is_stale(now) is True, (
        "30 days meets the threshold -- a strict > mutation would wrongly clear this"
    )


def test_strengths_from_ratings_centres_scales_and_preserves_order():
    """Zero-centring makes strengths sum to ~0 for ANY correct or broken
    scale/centring implementation (a mean-subtracted vector always sums to
    zero) -- asserting that would be the documented tautology trap. Instead:
    the MIDDLE team's rating equals the field mean, so its strength must
    land at exactly 0.0 -- this fails if centring is skipped (raw
    rating*factor would not be 0 for a middling rating of 1400). The
    top-vs-middle SPACING must equal exactly 200 * LOGIT_PER_ELO -- this
    fails under any wrong divisor (e.g. /380, /500). The three-way ORDER
    check fails under a sign error.
    """
    ratings = {
        "A": PublicRating(team_id=1, rating=1200.0, wins=500, losses=500, last_match_time=0),
        "B": PublicRating(team_id=2, rating=1400.0, wins=500, losses=500, last_match_time=0),
        "C": PublicRating(team_id=3, rating=1600.0, wins=500, losses=500, last_match_time=0),
    }
    strengths = strengths_from_ratings(ratings)

    assert strengths["B"] == pytest.approx(0.0, abs=1e-9), (
        "B's rating (1400) equals the 3-team mean -- centring must zero it exactly"
    )
    # Hardcoded independently of the module's own LOGIT_PER_ELO constant --
    # comparing against the imported constant would make this assertion
    # tautologically true under ANY wrong divisor, since both sides would
    # shift together (confirmed by mutation: mutating LOGIT_PER_ELO to
    # ln(10)/380 left this exact comparison passing when it referenced the
    # imported name instead of this literal).
    assert strengths["C"] - strengths["B"] == pytest.approx(200.0 * math.log(10) / 400.0), (
        "the 200-point gap must convert through exactly ln(10)/400 per point"
    )
    assert strengths["A"] < strengths["B"] < strengths["C"], "strength order must track rating order"


def test_strengths_from_ratings_empty_input_does_not_divide_by_zero():
    """A naive `sum(...) / len(...)` centring step raises ZeroDivisionError
    on an empty mapping instead of returning {}; this fails on that bug."""
    assert strengths_from_ratings({}) == {}


def test_strengths_from_ratings_accepts_an_overridden_divisor():
    """The scale sweep depends on `logit_per_elo` actually being honoured as
    an override rather than the function silently always using the module
    constant -- if the parameter were ignored, this would equal the
    default-divisor result instead of the doubled one asserted here."""
    ratings = {
        "A": PublicRating(team_id=1, rating=1000.0, wins=1, losses=1, last_match_time=0),
        "B": PublicRating(team_id=2, rating=1200.0, wins=1, losses=1, last_match_time=0),
    }
    default = strengths_from_ratings(ratings)
    doubled = strengths_from_ratings(ratings, logit_per_elo=LOGIT_PER_ELO * 2.0)
    assert doubled["B"] == pytest.approx(default["B"] * 2.0)


@pytest.mark.slow
def test_scale_sensitivity_sweep_reports_a_noise_floor_and_resolvability():
    """Mirrors ti26.duration.sensitivity_sweep's own test of the same shape:
    a magnitude assertion here would measure Monte Carlo noise, not an
    effect, so check the structural contract instead -- a hardcoded-zero
    noise_floor would make every delta look resolvable, and computing it
    fresh per multiplier instead of once from the baseline would break the
    "one shared value" contract.
    """
    from ti26.rules import load_rules

    rules = load_rules("config/ti2026_rules.yaml")
    ratings = {
        f"t{i:02d}": PublicRating(
            team_id=i, rating=1500.0 + (i - 7.5) * 40.0, wins=500, losses=400, last_match_time=0
        )
        for i in range(16)
    }
    result = scale_sensitivity_sweep(ratings, rules, [1.0, 0.5, 2.0], n_sims=3000, seed=3)

    assert result[0]["is_baseline"] is True
    assert result[0]["max_abs_delta"] == 0.0
    assert result[0]["resolvable"] is False

    floors = {entry["noise_floor"] for entry in result}
    assert len(floors) == 1, "noise_floor must be one value shared by every entry"
    assert next(iter(floors)) > 0.0, "a hardcoded-zero floor would make every delta look resolvable"

    expected_keys = {
        "divisor_multiplier", "divisor", "max_abs_delta", "is_baseline", "noise_floor", "resolvable",
    }
    for entry in result:
        assert set(entry) == expected_keys


@pytest.mark.slow
def test_scale_sensitivity_sweep_each_entry_carries_its_own_divisor():
    """A loop that reused the baseline's divisor label for every entry (a
    real bug class: duration.py's own test guards the equivalent mistake
    for `log_sigma`) would report 400 for the 0.5x and 2.0x rows too."""
    from ti26.rules import load_rules

    rules = load_rules("config/ti2026_rules.yaml")
    ratings = {
        f"t{i:02d}": PublicRating(
            team_id=i, rating=1500.0 + (i - 7.5) * 40.0, wins=500, losses=400, last_match_time=0
        )
        for i in range(16)
    }
    result = scale_sensitivity_sweep(ratings, rules, [1.0, 0.5, 2.0], n_sims=2000, seed=3)
    assert result[0]["divisor"] == pytest.approx(400.0)
    assert result[1]["divisor"] == pytest.approx(200.0)
    assert result[2]["divisor"] == pytest.approx(800.0)


def test_logit_per_elo_matches_the_repo_own_elo_convention():
    """Pins the constant itself against ti26.ratings.elo's own /400
    convention, so a future edit to either side that silently diverges them
    is caught here rather than only by inspection."""
    assert LOGIT_PER_ELO == pytest.approx(math.log(10) / 400.0)


def _row(match_id, start_time, r_acc, d_acc, radiant_win, r_team, d_team):
    return MapRow(
        match_id=match_id, start_time=start_time, duration=1800, radiant_win=radiant_win,
        league_id=None, tier=None, radiant_team_id=r_team, dire_team_id=d_team,
        series_id=None, series_type=1, patch=None,
        radiant_accounts=tuple(r_acc), dire_accounts=tuple(d_acc),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


def test_wilson_interval_matches_hand_verified_values():
    """Literals, not a re-run of this module's own formula: n=100/wins=50 is
    the textbook worked example for the 95% Wilson interval (~0.404, ~0.596);
    n=80/wins=61 is the exact Team Vision figures from the rung-3 brief's
    reference table (implied 0.778 vs the reported CI [0.659, 0.842]).
    Dropping the continuity terms (naive `phat +/- z*sqrt(phat*(1-phat)/n)`)
    or mutating `z` moves both bounds well past this tolerance -- see the
    build report's mutation section for the actual mutated-and-reverted run.
    """
    low, high = wilson_interval(50, 100)
    assert low == pytest.approx(0.4038298286, abs=1e-9)
    assert high == pytest.approx(0.5961701714, abs=1e-9)

    low2, high2 = wilson_interval(61, 80)
    assert low2 == pytest.approx(0.6585901503, abs=1e-9)
    assert high2 == pytest.approx(0.8423544882, abs=1e-9)


def test_classify_form_verdict_boundary_and_label_swap():
    """Exact-boundary fixture (implied == ci_low, and separately implied ==
    ci_high): the boundary case must be "consistent", since the rule is
    implied < ci_low / implied > ci_high (strict). A `<`/`>` -> `<=`/`>=`
    mutation would flip these two exact-boundary assertions from
    "consistent" to a verdict. The off-boundary cases pin the exact STRING
    on each side, so a label-swap mutation (returning BELOW where ABOVE is
    correct, or vice versa) is caught, not just "differs from consistent".
    """
    assert classify_form_verdict(0.60, 0.60, 0.80, n=10) == "consistent"
    assert classify_form_verdict(0.80, 0.60, 0.80, n=10) == "consistent"
    assert classify_form_verdict(0.599, 0.60, 0.80, n=10) == "form ABOVE implied"
    assert classify_form_verdict(0.801, 0.60, 0.80, n=10) == "form BELOW implied"
    assert classify_form_verdict(0.5, 0.4, 0.6, n=0) == "no data"


def test_observed_recent_form_counts_by_roster_version_id_not_team_id():
    """The team's CURRENT roster (accounts X) played under TWO team_ids
    across an org rename (99 -> 100): 2 wins under the OLD id, then 1 loss
    under the NEW/configured id. A DIFFERENT, older roster (Y) also played
    under the CURRENT id (100) -- e.g. the lineup this org fielded before X
    existed -- and must be EXCLUDED, since `resolved` names roster X
    specifically as current, not "whatever played under team_id 100".

    A count-by-team_id implementation (filter `radiant_team_id == 100 or
    dire_team_id == 100`, ignore the roster hash) would MISS both wins under
    the old id 99 and WRONGLY include roster Y's two losses under id 100 --
    flipping the result from the correct 2W/1L to 0W/3L. See the build
    report's mutation section for the actual mutated-and-reverted proof.
    """
    roster_x = (11, 12, 13, 14, 15)
    roster_y = (21, 22, 23, 24, 25)
    opponent = (91, 92, 93, 94, 95)
    rvid_x = roster_version_id(roster_x)

    rows = [
        _row(1, 1_000, roster_x, opponent, radiant_win=True, r_team=99, d_team=200),
        _row(2, 1_100, roster_x, opponent, radiant_win=True, r_team=99, d_team=200),
        _row(3, 1_200, opponent, roster_x, radiant_win=True, r_team=200, d_team=100),
        _row(4, 900, opponent, roster_y, radiant_win=True, r_team=200, d_team=100),
        _row(5, 950, opponent, roster_y, radiant_win=True, r_team=200, d_team=100),
    ]
    resolved = {"Foo": rvid_x}
    strengths = {"Foo": 0.0, "Bar": 0.0}
    result = observed_recent_form(rows, resolved, strengths, reference_time=2_000, window_days=90.0)

    foo = result["Foo"]
    assert (foo.wins, foo.losses, foo.n) == (2, 1, 3), (
        "must count roster X's maps under BOTH team_ids and exclude roster Y's "
        "maps played under the current team_id"
    )


def test_observed_recent_form_respects_the_window_cutoff():
    """Two maps for the SAME roster: one 89 days back (inside a 90-day
    window), one 91 days back (outside it). A cutoff bug that ignores
    `window_days`/`reference_time` (counts every map regardless of date)
    would count both, reporting 2W/0L/n=2 instead of the correct 1W/0L/n=1.
    """
    roster_x = (11, 12, 13, 14, 15)
    opponent = (91, 92, 93, 94, 95)
    rvid_x = roster_version_id(roster_x)
    reference_time = 90 * 86400
    inside = reference_time - 89 * 86400
    outside = reference_time - 91 * 86400

    rows = [
        _row(1, inside, roster_x, opponent, radiant_win=True, r_team=100, d_team=200),
        _row(2, outside, roster_x, opponent, radiant_win=True, r_team=100, d_team=200),
    ]
    resolved = {"Foo": rvid_x}
    strengths = {"Foo": 0.0, "Bar": 0.0}
    result = observed_recent_form(rows, resolved, strengths, reference_time, window_days=90.0)

    foo = result["Foo"]
    assert (foo.wins, foo.losses, foo.n) == (1, 0, 1), (
        "the map 91 days back must be excluded by the 90-day window cutoff"
    )


def test_observed_recent_form_reports_no_data_when_the_roster_has_no_maps():
    """A resolved rvid that never appears on either side of any row (e.g. a
    roster with zero maps in the local store's window) must report n=0,
    rate/ci_low/ci_high as None, and verdict "no data" -- never a
    divide-by-zero and never a misleading "consistent"."""
    rows = [_row(1, 1000, (1, 2, 3, 4, 5), (6, 7, 8, 9, 10), radiant_win=True, r_team=1, d_team=2)]
    resolved = {"Ghost": "deadbeefdeadbeef"}
    strengths = {"Ghost": 0.0, "Other": 1.0}
    result = observed_recent_form(rows, resolved, strengths, reference_time=2000, window_days=90.0)

    ghost = result["Ghost"]
    assert (ghost.wins, ghost.losses, ghost.n) == (0, 0, 0)
    assert ghost.rate is None and ghost.ci_low is None and ghost.ci_high is None
    assert ghost.verdict == "no data"


def test_observed_recent_form_implied_averages_over_other_teams_excluding_self():
    """`implied` must be the mean of `map_win_prob` over every OTHER team,
    excluding self. Literal expected value computed independently (not by
    calling `map_win_prob` again in this test): for self=0.5 against
    others=[0.0, 1.5, -1.0], the three probabilities are 0.622459331,
    0.268941421, 0.817574476 -> mean 0.569658410. A bug that included self
    (an extra term at strength-difference 0.0, i.e. p=0.5) would instead
    average four terms and land on 0.552243807.
    """
    rows: list[MapRow] = []
    resolved = {"Self": "aaaa", "Other1": "bbbb", "Other2": "cccc", "Other3": "dddd"}
    strengths = {"Self": 0.5, "Other1": 0.0, "Other2": 1.5, "Other3": -1.0}
    result = observed_recent_form(rows, resolved, strengths, reference_time=0, window_days=90.0)
    assert result["Self"].implied == pytest.approx(0.5696584096, abs=1e-9)
