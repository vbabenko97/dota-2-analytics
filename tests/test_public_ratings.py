import math
from datetime import UTC, datetime

import pytest

from ti26.public_ratings import (
    LOGIT_PER_ELO,
    PublicRating,
    parse_ratings,
    scale_sensitivity_sweep,
    strengths_from_ratings,
)


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
