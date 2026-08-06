import math

import pytest

from ti26.data.schema import MapRow
from ti26.ratings.glicko import GlickoModel
from ti26.roster import RosterIndex, roster_version_id

WEEK = 604800


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


A, B, C = [1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12, 13, 14, 15]


def test_glickman_reference_example_reproduces_published_values():
    """Glickman's Glicko-2 worked example (glicko.net/glicko/glicko2.pdf).

    Player r=1500 RD=200 vol=0.06 vs three opponents (1400/30 W, 1550/100 L,
    1700/300 L) with tau=0.5 gives r'=1464.06, RD'=151.52, vol'=0.05999.
    Reproducing a published fixture is the only test here that can catch an
    algebra error in the volatility iteration; everything else would pass
    with a plausible-but-wrong update rule.
    """
    from ti26.ratings.glicko import GlickoRating, update_rating

    result = update_rating(
        GlickoRating(1500.0, 200.0, 0.06),
        [
            (GlickoRating(1400.0, 30.0, 0.06), 1.0),
            (GlickoRating(1550.0, 100.0, 0.06), 0.0),
            (GlickoRating(1700.0, 300.0, 0.06), 0.0),
        ],
        tau=0.5,
    )
    assert result.rating == pytest.approx(1464.06, abs=0.02)
    assert result.rd == pytest.approx(151.52, abs=0.02)
    assert result.volatility == pytest.approx(0.05999, abs=0.0001)


def test_unrated_rosters_predict_even():
    model = GlickoModel()
    assert model.predict(row(1, 0, A, B)) == pytest.approx(0.5)


def test_rating_deviation_shrinks_with_evidence():
    """The RD is the whole reason spec V prefers Glicko over Elo here."""
    model = GlickoModel()
    before = model.rating_of(roster_version_id(A)).rd
    for week in range(8):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.flush()
    assert model.rating_of(roster_version_id(A)).rd < before


def test_uncertain_favourite_is_predicted_less_confidently_than_a_certain_one():
    """Two rosters with identical point ratings but different RD must NOT
    receive the same prediction. If they do, the RD is decorative and Glicko
    reduces to Elo with extra steps.
    """
    from ti26.ratings.glicko import GlickoRating, expected_score

    certain = expected_score(GlickoRating(1700.0, 30.0, 0.06), GlickoRating(1500.0, 30.0, 0.06))
    uncertain = expected_score(GlickoRating(1700.0, 30.0, 0.06), GlickoRating(1500.0, 350.0, 0.06))
    assert certain > uncertain
    assert uncertain > 0.5, "still a favourite, just less emphatically"


def test_results_only_take_effect_after_the_period_closes():
    """Within-period results must not leak into a same-period prediction --
    that is a miniature version of the leakage the spec IV cutoff prevents."""
    model = GlickoModel(period_seconds=WEEK)
    baseline = model.predict(row(0, 0, A, B))
    model.update(row(1, 100, A, B, radiant_win=True))
    assert model.predict(row(2, 200, A, B)) == pytest.approx(baseline)
    model.update(row(3, 2 * WEEK, C, B, radiant_win=True))  # crosses the boundary
    assert model.predict(row(4, 2 * WEEK + 1, A, B)) > baseline


def test_new_roster_inherits_without_the_test_wiring_the_index_by_hand():
    """Spec III: without continuity blending a re-branded org looks brand new.

    The model owns the index and calls `observe` itself. If a future change
    moves observation back out to the caller, this test fails -- which is the
    point: a test that wires collaborators the runner does not wire proves
    nothing about the shipped system.
    """
    index = RosterIndex()
    model = GlickoModel(roster_index=index, period_seconds=WEEK)
    for week in range(12):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.flush()

    swapped = [1, 2, 3, 4, 99]
    model.predict(row(99, 12 * WEEK, swapped, B))  # registers the new roster
    inherited = model.rating_of(roster_version_id(swapped))
    assert inherited.rating > 1500.0, "4/5 continuity carries most of the history"
    assert inherited.rd >= model.rating_of(roster_version_id(A)).rd, (
        "but the new roster is no more certain than the one that earned the rating"
    )


def test_inheritance_weight_tracks_measured_overlap():
    """A one-player swap must inherit MORE than a three-player rebuild.

    A fixed weight passes any single-scenario test; only comparing two
    different overlaps can catch it.
    """
    def build(new_roster):
        index = RosterIndex()
        model = GlickoModel(roster_index=index, period_seconds=WEEK)
        for week in range(12):
            model.update(row(week, week * WEEK, A, B, radiant_win=True))
        model.flush()
        model.predict(row(99, 12 * WEEK, new_roster, B))
        return model.rating_of(roster_version_id(new_roster)).rating

    one_swap = build([1, 2, 3, 4, 99])
    rebuild = build([1, 2, 97, 98, 99])
    assert one_swap > rebuild > 1500.0


def test_a_roster_with_no_shared_players_gets_the_global_prior():
    index = RosterIndex()
    model = GlickoModel(roster_index=index, period_seconds=WEEK)
    for week in range(12):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.flush()
    fresh = [91, 92, 93, 94, 95]
    model.predict(row(99, 12 * WEEK, fresh, B))
    assert model.rating_of(roster_version_id(fresh)).rating == pytest.approx(1500.0)


def test_idle_rosters_lose_certainty_every_empty_period():
    """Spec III measured recent volume collapsing. A team last seen months
    before TI must NOT arrive carrying a tight RD -- that error lands exactly
    in the tails where the 4-0 and 0-4 slots live.
    """
    model = GlickoModel(period_seconds=WEEK)
    for week in range(12):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.flush()
    active_rd = model.rating_of(roster_version_id(A)).rd

    after_10 = model.rating_of(roster_version_id(A), at_period=22).rd
    after_40 = model.rating_of(roster_version_id(A), at_period=52).rd
    assert after_10 > active_rd
    assert after_40 > after_10, "RD must keep growing across MULTIPLE idle periods"


def test_consecutive_periods_charge_exactly_one_glicko2_inflation():
    """Kills mutation: feed `rating_of(rvid)` to `update_rating` inside `flush`.

    `rating_of` inflates by the whole elapsed gap and `update_rating` then
    applies Glicko-2's own step-6 increment on top of it, so a roster playing
    in consecutive periods took two variance increments where Glickman
    specifies one, and a roster returning after k idle periods took k+1. The
    reference below is the repository's own `update_rating` applied once per
    period with NO inflation in between, which is what two consecutive rating
    periods mean. A fresh opponent in the second period keeps the comparison
    on the roster's own inflation rather than on how opponent RDs are read.
    """
    from ti26.ratings.glicko import GlickoRating, update_rating

    model = GlickoModel(period_seconds=WEEK)
    model.update(row(1, 0, A, B, radiant_win=True))
    model.update(row(2, WEEK, A, C, radiant_win=True))
    model.flush()

    initial = GlickoRating(1500.0, 350.0, 0.06)
    first = update_rating(initial, [(initial, 1.0)], tau=0.5)
    second = update_rating(first, [(initial, 1.0)], tau=0.5)

    observed = model.rating_of(roster_version_id(A), at_period=1)
    assert observed.rd == pytest.approx(second.rd, abs=1e-9)
    assert observed.rating == pytest.approx(second.rating, abs=1e-9)


def test_idle_inflation_never_exceeds_the_never_seen_prior():
    """Otherwise a long-idle roster becomes more uncertain than one that has
    never played, which is incoherent."""
    model = GlickoModel(period_seconds=WEEK, initial_rd=350.0)
    for week in range(12):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.flush()
    assert model.rating_of(roster_version_id(A), at_period=100_000).rd <= 350.0


def test_idle_inflation_does_not_move_the_point_rating():
    """Uncertainty grows; the estimate itself does not drift."""
    model = GlickoModel(period_seconds=WEEK)
    for week in range(12):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.flush()
    before = model.rating_of(roster_version_id(A)).rating
    assert model.rating_of(roster_version_id(A), at_period=60).rating == pytest.approx(before)


def test_a_long_idle_favourite_is_predicted_less_confidently():
    """The end-to-end consequence of inflation, through `predict` rather than
    through internals -- this is what actually reaches the card."""
    model = GlickoModel(period_seconds=WEEK)
    for week in range(12):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.flush()
    fresh = model.predict(row(500, 12 * WEEK, A, B))
    model.update(row(501, 60 * WEEK, C, [21, 22, 23, 24, 25], radiant_win=True))
    model.flush()
    stale = model.predict(row(502, 60 * WEEK, A, B))
    assert 0.5 < stale < fresh, "idle time pulls the forecast back toward even"


def test_the_two_expected_score_forms_are_deliberately_different():
    """Glickman specifies opponent-only RD for the UPDATE step and combined
    RD for outcome PREDICTION. Both are correct in their place. This pins the
    distinction so neither gets 'simplified' into the other.
    """
    from ti26.ratings.glicko import SCALE, GlickoRating, _e, expected_score

    player = GlickoRating(1700.0, 350.0, 0.06)   # strong but very uncertain
    opponent = GlickoRating(1500.0, 30.0, 0.06)  # average and well known

    combined = expected_score(player, opponent)
    opponent_only = _e(
        (player.rating - 1500.0) / SCALE,
        (opponent.rating - 1500.0) / SCALE,
        opponent.rd / SCALE,
    )
    assert combined < opponent_only, (
        "the prediction form must discount for the PLAYER's own uncertainty; "
        "the update form deliberately does not"
    )


def test_activity_report_gives_maps_per_roster_per_period():
    model = GlickoModel(period_seconds=WEEK)
    for week in range(3):
        for i in range(2):
            model.update(row(week * 10 + i, week * WEEK + i, A, B, radiant_win=True))
    model.flush()
    report = {r["roster_version_id"]: r for r in model.activity_report()}
    entry = report[roster_version_id(A)]
    assert entry["total_maps"] == 6
    assert entry["active_periods"] == 3
    assert entry["maps_by_period"] == {0: 2, 1: 2, 2: 2}


def test_prior_driven_rosters_are_reported():
    """Spec III measured finding: thin recent samples are the DEFAULT, so the
    report must name which teams are running on the prior."""
    model = GlickoModel(period_seconds=WEEK)
    for week in range(15):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.update(row(99, 16 * WEEK, C, B, radiant_win=True))
    model.flush()
    flagged = model.prior_driven(min_maps=10)
    assert roster_version_id(C) in flagged
    assert roster_version_id(A) not in flagged


def test_skipped_rows_are_counted_with_a_reason():
    model = GlickoModel()
    model.update(row(1, 0, A, B, has_null_team=True))
    assert model.skipped == {"null_team": 1}


def test_strengths_are_logit_scale_and_centred():
    model = GlickoModel(period_seconds=WEEK)
    for week in range(8):
        model.update(row(week, week * WEEK, A, B, radiant_win=True))
    model.flush()
    strengths = model.strengths()
    assert sum(strengths.values()) == pytest.approx(0.0, abs=1e-9)
    assert strengths[roster_version_id(A)] > strengths[roster_version_id(B)]
    assert abs(strengths[roster_version_id(A)]) < 10.0, "logit scale, not rating points"


def test_predict_does_not_register_a_bad_roster_row_in_the_index():
    """Task 3 reviewer fix: `predict` must apply the same `skip_reason` guard
    `update` applies before calling `observe`. Without it, a row flagged
    `has_bad_roster` -- whose accounts contain the -1 missing-player sentinel
    -- would still register in the RosterIndex and pollute its stored account
    sets and predecessor chain via the prediction path alone.
    """
    index = RosterIndex()
    model = GlickoModel(roster_index=index, period_seconds=WEEK)
    p = model.predict(row(1, 0, A, B, has_bad_roster=True))
    assert 0.0 < p < 1.0, "a skipped row must still get a forecast"
    assert index.accounts(roster_version_id(A)) == ()
    assert index.accounts(roster_version_id(B)) == ()
    assert index.predecessor(roster_version_id(A)) is None


def test_volatility_solution_satisfies_glickmans_published_equation():
    """The Glickman fixture alone cannot catch an algebra error here: three
    independently plausible transcription bugs in `_solve_volatility`'s
    `f(x)` -- `tau` instead of `tau**2` in the denominator, dropping the
    square on `2*(phi_sq+v+ex)**2`, and flipping the numerator's sign -- were
    verified by mutation to all stay within that fixture's tolerances (see
    the report for the resulting f-values). The reason is arithmetic: for
    that fixture's inputs `ex = exp(a)` is negligible next to `phi_sq + v`,
    so near the root `f(x)` is dominated by the `(x - a)/tau**2` term and the
    delicate part barely matters.

    This test instead checks that the volatility the real solver returns
    actually SOLVES Glickman's published root equation (2013 paper, step 5),
    transcribed fresh here as `f_published` -- not imported from, nor
    sharing any code with, `_solve_volatility`'s own `f`. The scenario -- a
    modest favourite (1600/30) losing 100 times running to an evenly rated,
    equally certain opponent (1500/30) -- is chosen so the exponential term
    is material at the root: repeating an IDENTICAL result leaves `delta`
    unchanged (Glicko-2's `v` and `delta_sum` scale oppositely with repeat
    count) while `v` shrinks by a factor of the repeat count, which pushes
    `delta_sq` far enough above `phi_sq + v` that `ex` at the converged root
    ends up the same order of magnitude as `phi_sq + v` -- unlike the
    Glickman fixture, where it never is.

    This also exercises `_solve_volatility`'s `delta_sq > phi_sq + v`
    BRACKET branch (`B = log(delta_sq - phi_sq - v)`), which nothing else in
    this file pins directly -- confirmed by the `delta_sq > phi_sq + v`
    assertion below, taken on the same values the solver itself computes.

    Mutation-verified: reintroducing any of the three bugs above into
    `_solve_volatility` makes `abs(f_published(x_root))` jump to order 1-10
    (measured: 8.59, 2.24, 3.21) while leaving the Glickman fixture green.
    """
    from ti26.ratings.glicko import SCALE, GlickoRating, _e, _g, update_rating

    player = GlickoRating(1600.0, 30.0, 0.06)
    opponent = GlickoRating(1500.0, 30.0, 0.06)
    tau = 0.5
    n = 100

    mu = (player.rating - 1500.0) / SCALE
    phi = player.rd / SCALE
    mu_j = (opponent.rating - 1500.0) / SCALE
    phi_j = opponent.rd / SCALE
    g_j = _g(phi_j)
    e_j = _e(mu, mu_j, phi_j)
    v_single = 1.0 / (g_j * g_j * e_j * (1.0 - e_j))
    v = v_single / n
    delta = v_single * g_j * (0.0 - e_j)
    delta_sq, phi_sq = delta * delta, phi * phi
    assert delta_sq > phi_sq + v, "scenario must exercise the bracket branch"

    result = update_rating(player, [(opponent, 0.0)] * n, tau)

    a = math.log(player.volatility**2)

    def f_published(x: float) -> float:
        """Glickman 2013 eq. for volatility, retyped independently of
        `_solve_volatility`'s own `f` -- a bug in that copy cannot also be
        baked into this one."""
        ex = math.exp(x)
        numerator = ex * (delta_sq - phi_sq - v - ex)
        denominator = 2.0 * (phi_sq + v + ex) ** 2
        return numerator / denominator - (x - a) / (tau * tau)

    x_root = math.log(result.volatility**2)
    assert abs(f_published(x_root)) < 1e-9


def test_strengths_mid_period_fragments_the_rating_period():
    """`strengths()`, like `rating_deviations()` and `activity_report()`,
    calls `flush()` internally. Every current caller flushes first, so this
    is latent today -- but a future caller invoking one of these mid-period
    for diagnostics (their own docstring purpose) would force that period's
    PARTIAL results through `update_rating` early, and a later match still
    inside the same nominal period would then be processed as a SEPARATE
    subsequent update rather than being combined with the first batch. That
    silently splits one rating period into two, violating this task's first
    constraint that updates happen in rating periods, not per match.

    This pins the observable consequence: flushing the period in two pieces
    (via a mid-period `strengths()` call) must not produce the same rating
    as flushing it once with both results combined.
    """

    def final_rating(call_strengths_mid_period: bool) -> float:
        model = GlickoModel(period_seconds=WEEK)
        model.update(row(0, 0, A, B, radiant_win=False))
        if call_strengths_mid_period:
            model.strengths()  # forces a premature flush mid-period
        model.update(row(1, 1, A, B, radiant_win=False))
        model.flush()
        return model.rating_of(roster_version_id(A)).rating

    fragmented = final_rating(call_strengths_mid_period=True)
    combined = final_rating(call_strengths_mid_period=False)
    assert fragmented != pytest.approx(combined), (
        "a mid-period strengths() call must not silently change the rating "
        "by splitting one period's results into two sequential updates"
    )
