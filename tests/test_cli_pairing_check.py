"""The bracket-validation producer, pinned where I actually got it wrong."""

import random
from pathlib import Path

import pytest

from ti26.cli_pairing_check import (
    ELIMINATION_RULE_YEAR,
    KNOWN_DEVIATIONS,
    TIEBREAK_ORDER_YEAR,
    _allowed_matchings,
    _is_fold,
    _mean_duration,
    _states_before,
    check_elimination_pairing,
    check_round,
    infer_groups,
    split_rounds,
    summarise,
)
from ti26.elimination import pair_elimination
from ti26.pairing import choose_pairing
from ti26.rules import load_rules
from ti26.tiebreak import DurationUnavailableError, rank_teams


def _series(start, teams):
    return {"start": start, "teams": set(teams), "map_wins": {}, "durations": []}


def test_allowed_matchings_always_contains_what_choose_pairing_samples():
    """Kills mutation: filter on distance before repeats in `_allowed_matchings`.

    This module re-derives the engine's candidate set instead of calling it,
    because `choose_pairing` returns one random sample. That is only sound if
    the two apply the same filters in the same ORDER -- repeats first, then
    distance. Swap them and the sampled pairing escapes the set, which would
    silently turn every 'the real bracket disagrees with the engine' finding
    into an artifact of this file.
    """
    members = ["a", "b", "c", "d"]
    rank_index = {"a": 0, "b": 1, "c": 2, "d": 3}
    # Make the repeat filter and the distance filter disagree: the closest
    # pairing by rank is exactly the one that repeats.
    prior = {"a": {"b"}, "b": {"a"}, "c": {"d"}, "d": {"c"}}
    groups = dict.fromkeys(members, "A")

    allowed = _allowed_matchings(
        members, rank_index, prior, groups, cross_group=False, maximize_distance=False
    )
    as_sets = [{frozenset(p) for p in m} for m in allowed]
    for seed in range(40):
        sampled = choose_pairing(members, rank_index, prior, random.Random(seed))
        assert {frozenset(p) for p in sampled.matching} in as_sets


def test_groups_need_every_within_group_round_to_come_out_right():
    """Kills mutation: infer groups from rounds 2-3 only, dropping round 1.

    After round 1 a group's winners and losers never meet again inside it, so
    connectivity over rounds 2-3 alone yields components of HALF the true
    group size -- four groups of four instead of two of eight. That silently
    weakens the round-4 cross-group check into a much easier test, which is
    exactly the error this producer made on its first run.
    """
    # One group of eight, paired the way a Swiss group really is: round 1 by
    # seeding, then winners with winners and losers with losers. That is what
    # makes rounds 2-3 close into two four-cycles instead of spanning the group.
    rounds = [
        [_series(1, p) for p in (("t1", "t2"), ("t3", "t4"), ("t5", "t6"), ("t7", "t8"))],
        [_series(2, p) for p in (("t1", "t3"), ("t5", "t7"), ("t2", "t4"), ("t6", "t8"))],
        [_series(3, p) for p in (("t1", "t5"), ("t3", "t7"), ("t2", "t6"), ("t4", "t8"))],
    ]
    full = infer_groups(rounds, within_rounds=3)
    assert len(set(full.values())) == 1, "round 1 binds the group into one component"
    assert len(full) == 8

    partial = infer_groups(rounds[1:], within_rounds=2)
    assert len(set(partial.values())) == 2, "without round 1 the group splits in half"
    assert partial["t1"] != partial["t2"], "winners and losers never meet in rounds 2-3"


def test_rounds_are_cut_on_a_repeated_team_not_a_fixed_size():
    """Kills mutation: split rounds into fixed-size chunks.

    Swiss rounds shrink as teams finish -- TI 2025 ran 8, 8, 8, 8, 7 then 5 --
    so any fixed chunk size mis-assigns every round after the first shrink and
    corrupts the standings fed to the ranking.
    """
    series = [
        _series(1, ("a", "b")), _series(2, ("c", "d")),
        _series(3, ("a", "c")), _series(4, ("b", "d")),
        _series(5, ("a", "d")),
    ]
    rounds = split_rounds(series)
    assert [len(r) for r in rounds] == [2, 2, 1]


def test_fold_pairing_is_the_top_half_against_the_bottom_half():
    """Kills mutation: implement the fold as adjacent seeds (1v2, 3v4).

    The fold is the competing hypothesis for what the real bracket does, so
    getting it wrong would make the comparison meaningless. With four seeds it
    is 1v3 and 2v4, never 1v2 and 3v4.
    """
    members = ["w", "x", "y", "z"]
    rank_index = {"w": 0, "x": 1, "y": 2, "z": 3}
    assert _is_fold(members, rank_index, [("w", "y"), ("x", "z")])
    assert not _is_fold(members, rank_index, [("w", "x"), ("y", "z")])
    assert not _is_fold(members, rank_index, [("w", "z"), ("x", "y")])


def test_split_rounds_rejects_nothing_and_returns_empty_for_no_series():
    assert split_rounds([]) == []


@pytest.mark.parametrize("size", [3, 5])
def test_fold_needs_an_even_bucket(size):
    members = [str(i) for i in range(size)]
    rank_index = {t: i for i, t in enumerate(members)}
    assert not _is_fold(members, rank_index, [])


def _swiss_five_rounds():
    """Six teams over five Swiss rounds, ending 3-2 for a/b/c and 2-3 for x/y/z.

    Constructed so that the final ranking is forced by game-win percentage
    within each record class: a > b > c and x > y > z.
    """
    rounds = []
    # Each round pits one of a/b/c against one of x/y/z, so the record classes
    # separate cleanly. Map scores set the game-win percentages.
    schedule = [
        [("a", "x", 2, 0), ("b", "y", 2, 1), ("c", "z", 2, 1)],
        [("a", "y", 2, 0), ("b", "z", 2, 1), ("c", "x", 2, 1)],
        [("a", "z", 2, 1), ("b", "x", 2, 1), ("c", "y", 2, 1)],
        [("x", "a", 2, 1), ("y", "b", 2, 1), ("z", "c", 2, 1)],
        [("x", "b", 2, 1), ("y", "c", 2, 1), ("z", "a", 2, 1)],
    ]
    start = 0
    for rnd in schedule:
        entries = []
        for winner, loser, wins, losses in rnd:
            start += 1000
            entries.append(
                {
                    "start": start,
                    "teams": {winner, loser},
                    "map_wins": {winner: wins, loser: losses},
                    "durations": [],
                }
            )
        rounds.append(entries)
    return rounds


def test_elimination_check_scores_a_rule_following_bracket_as_reproduced():
    """Kills mutation: score the real bracket on overall rank, not class seed.

    Overall ranking position is invariant across matchings here -- every 3-2
    team outranks every 2-3 team -- so a check that used it would report the
    same distance for a rule-following bracket and a rule-breaking one, and
    `real_bracket_distance` would equal `best_reachable_distance` no matter
    what was fed in. This builds the bracket the engine itself would pair and
    asserts the check calls it reproduced; the companion test below feeds a
    deliberately worse bracket and asserts it does not.
    """
    rules = load_rules("config/ti2026_rules.yaml")
    groups = dict.fromkeys("abcxyz", "A")
    rounds = _swiss_five_rounds()

    # Derive the ranking rather than assume it: the fixture's game-win
    # percentages are not in alphabetical order.
    states = _states_before(rounds, rules.total_rounds + 1, groups)
    order = {t: i for i, t in enumerate(rank_teams(list(states.values()), random.Random(1)))}
    high = sorted((t for t in states if states[t].record == (3, 2)), key=order.get)
    low = sorted((t for t in states if states[t].record == (2, 3)), key=order.get)
    assert len(high) == len(low) == 3

    engine = pair_elimination(
        high, low, {t: set(states[t].opponents) for t in high}, random.Random(1)
    )
    bracket = [
        {"start": 90000 + i, "teams": set(pair), "map_wins": {}, "durations": []}
        for i, pair in enumerate(engine)
    ]
    result = check_elimination_pairing(rounds + [bracket], groups, rules, seeds=[1, 2, 3])
    assert result["status"] == "checked"
    assert result["higher_record"] == "3-2"
    assert result["lower_record"] == "2-3"
    assert result["engine_reproduces_the_real_bracket"] == [True, True, True]
    assert result["real_bracket_distance"] == result["best_reachable_distance"]


def test_elimination_check_notices_a_bracket_that_breaks_the_rule():
    """The companion to the test above: a worse bracket must score worse."""
    rules = load_rules("config/ti2026_rules.yaml")
    groups = dict.fromkeys("abcxyz", "A")
    rounds = _swiss_five_rounds()
    states = _states_before(rounds, rules.total_rounds + 1, groups)
    order = {t: i for i, t in enumerate(rank_teams(list(states.values()), random.Random(1)))}
    high = sorted((t for t in states if states[t].record == (3, 2)), key=order.get)
    low = sorted((t for t in states if states[t].record == (2, 3)), key=order.get)

    minimised = [
        {"start": 90000 + i, "teams": {h, low[i]}, "map_wins": {}, "durations": []}
        for i, h in enumerate(high)
    ]
    result = check_elimination_pairing(rounds + [minimised], groups, rules, seeds=[1])
    assert result["engine_reproduces_the_real_bracket"] == [False]
    assert result["real_bracket_distance"][0] < result["best_reachable_distance"][0]


def _symmetric_two_rounds():
    """Four teams, two rounds, built so two pairs tie through all five criteria.

    a and b both go 2-0 beating c and d 2-0; c and d both go 0-2. Series record,
    game-win percentage, opponents' series wins and opponents' game-win
    percentage are then identical within each pair, so ranking them requires the
    sixth criterion -- average game duration -- and nothing above it can help.

    Durations differ inside each pair, so a correct ranking is determined rather
    than a coin toss.
    """
    schedule = [
        [("a", "c", [1800, 1900]), ("b", "d", [2600, 2700])],
        [("a", "d", [1700, 1850]), ("b", "c", [2500, 2800])],
    ]
    rounds, start = [], 0
    for rnd in schedule:
        entries = []
        for winner, loser, durations in rnd:
            start += 1000
            entries.append(
                {
                    "start": start,
                    "teams": {winner, loser},
                    "map_wins": {winner: 2, loser: 0},
                    "durations": durations,
                }
            )
        rounds.append(entries)
    # The round under test: the two record classes each pair internally.
    rounds.append(
        [
            {"start": 9000, "teams": {"a", "b"}, "map_wins": {"a": 2, "b": 0}, "durations": [1]},
            {"start": 9001, "teams": {"c", "d"}, "map_wins": {"c": 2, "d": 0}, "durations": [1]},
        ]
    )
    return rounds


def test_a_tie_through_five_criteria_is_ranked_from_the_stores_own_durations():
    """Kills mutation: drop `duration_fn` from `check_round`'s `rank_teams` calls.

    Average game duration is the published sixth criterion, and `rank_teams`
    refuses to rank a block still tied after five rather than skipping to a coin
    toss. This producer replays a real event, so it must supply the real
    durations from the store.

    This is not hypothetical. The criterion was deleted on 2026-08-08 and
    restored on 2026-08-09; in between, this producer's duration source stayed
    deleted, and it raised `DurationUnavailableError` on the TI 2025 store --
    three teams tie through five criteria in that bracket. Nothing caught it,
    because `cli_pairing_check` is not a release producer and no test until this
    one built a bracket with a surviving tie.
    """
    rules = load_rules("config/ti2026_rules.yaml")
    groups = dict.fromkeys("abcd", "A")
    rounds = _symmetric_two_rounds()

    states = _states_before(rounds, 3, groups)
    assert states["a"].record == states["b"].record
    with pytest.raises(DurationUnavailableError):
        rank_teams(list(states.values()), random.Random(1))

    result = check_round(rounds, 3, groups, rules, seeds=[1, 2])
    assert result["round"] == 3
    assert result["equal_record_pairing"] is True


def test_mean_duration_averages_maps_and_stops_before_the_round_being_paired():
    """Kills mutation: average over series, or include the round being paired.

    A pairing decision is made BEFORE the round is played, so a duration source
    that included that round would rank teams on a result the organiser did not
    have. Averaging per series rather than per map would also weight a 2-0 the
    same as a 2-1.
    """
    rounds = _symmetric_two_rounds()
    durations = _mean_duration(rounds, 3)
    assert durations["a"] == pytest.approx((1800 + 1900 + 1700 + 1850) / 4)
    assert durations["b"] == pytest.approx((2600 + 2700 + 2500 + 2800) / 4)
    # Round 3's one-second maps would drag every mean down if they leaked in.
    assert min(durations.values()) > 100


def test_summary_separates_buckets_that_test_the_rule_from_ones_that_cannot():
    """Kills mutation: count every bucket, or drop the discriminating split.

    Two ways to overstate the same result. A bucket the engine could not have
    paired differently agrees trivially, so counting `not_self_contained` rows
    inflates both sides of the ratio. And a bucket where every legal matching
    scores the same distance cannot refute a distance preference, so folding it
    into the headline does the same thing more quietly. On TI 2025 the two
    denominators give visibly different verdicts -- see
    `reports/pairing_check/pairing_check.json` -- and the provenance comment in
    `config/ti2026_rules.yaml` cites the discriminating one.
    """
    per_round = [
        {
            "buckets": [
                {"bucket": "x", "teams": 6, "status": "not_self_contained"},
                {
                    "seeds_agreeing": 2, "status": "always", "actual_is_min": True,
                    "actual_is_max": False, "matches_fold_pairing": False,
                    "min_distance": 2, "max_distance": 6,
                },
                {
                    "seeds_agreeing": 0, "status": "never", "actual_is_min": False,
                    "actual_is_max": True, "matches_fold_pairing": True,
                    "min_distance": 3, "max_distance": 7,
                },
                # Every legal matching scores the same, so the rule could not
                # have been wrong here and agreement proves nothing.
                {
                    "seeds_agreeing": 2, "status": "always", "actual_is_min": True,
                    "actual_is_max": True, "matches_fold_pairing": True,
                    "min_distance": 4, "max_distance": 4,
                },
            ]
        }
    ]
    summary = summarise(per_round)
    assert summary["buckets_with_a_choice"] == 3
    assert summary["buckets_agreeing_on_every_seed"] == 2
    assert summary["buckets_agreeing_on_no_seed"] == 1
    assert summary["real_pairing_matches_fold"] == 2

    # The denominator that tests the rule excludes the undiscriminating bucket,
    # which is what stops the headline reading better than the evidence.
    deciding = summary["where_distance_discriminates"]
    assert deciding["buckets"] == 2
    assert deciding["agreeing_on_every_seed"] == 1
    assert deciding["real_pairing_matches_fold"] == 1


def test_distance_shortfall_is_how_far_the_real_bracket_fell_short():
    """Kills mutation: compute the shortfall as real minus reachable.

    The sign carries the meaning. A rule-following bracket scores its reachable
    optimum and the shortfall is zero; a bracket that deviated scores less, and
    the shortfall is what a documented external cause has to account for. With
    the operands swapped, every deviation reports as a negative number and reads
    like the real bracket beat an optimum it cannot beat.
    """
    rules = load_rules("config/ti2026_rules.yaml")
    groups = dict.fromkeys("abcxyz", "A")
    rounds = _swiss_five_rounds()
    states = _states_before(rounds, rules.total_rounds + 1, groups)
    order = {t: i for i, t in enumerate(rank_teams(list(states.values()), random.Random(1)))}
    high = sorted((t for t in states if states[t].record == (3, 2)), key=order.get)
    low = sorted((t for t in states if states[t].record == (2, 3)), key=order.get)

    minimised = [
        {"start": 90000 + i, "teams": {h, low[i]}, "map_wins": {}, "durations": []}
        for i, h in enumerate(high)
    ]
    result = check_elimination_pairing(rounds + [minimised], groups, rules, seeds=[1])
    assert result["distance_shortfall"][0] > 0
    assert result["distance_shortfall"][0] == (
        result["best_reachable_distance"][0] - result["real_bracket_distance"][0]
    )


def test_the_report_says_which_years_rules_each_check_models():
    """Kills mutation: report one rule year for the whole report.

    The elimination check models TI 2025's rule, which TI 2026 replaced outright
    with a sequential choice, while the ranking uses TI 2026's tiebreak order.
    Collapsing those into a single year is what makes
    `engine_reproduces_the_real_bracket: false` read as a verdict on the
    shipping engine -- an inference two entries in the strengthening plan
    already drew, twice, wrongly.
    """
    rules = load_rules("config/ti2026_rules.yaml")
    groups = dict.fromkeys("abcxyz", "A")
    rounds = _swiss_five_rounds()
    result = check_elimination_pairing(rounds, groups, rules, seeds=[1])
    assert result["rule_year"] == ELIMINATION_RULE_YEAR
    assert ELIMINATION_RULE_YEAR != TIEBREAK_ORDER_YEAR


def test_known_deviations_travel_with_the_report_and_cite_a_file_that_exists():
    """Kills mutation: delete the deviations, or cite a source path that is gone.

    The two-series-per-day constraint is the documented reason the real bracket
    differs from the rule, and a reader without it will read that difference as
    evidence against the rule. An unciteable claim is no better: the source is
    the only thing separating this from an anecdote, so a path that no longer
    resolves has to fail here rather than in a reader's hands.

    Deliberately NOT asserted: that the entries carry no measured numbers. That
    is the property I want -- the figures moved once already when the ranking
    was corrected -- but I could not write an assertion that fails when a number
    is added, so it is enforced by review and stated here rather than claimed.
    """
    assert KNOWN_DEVIATIONS, "the documented deviation must travel with the report"
    for deviation in KNOWN_DEVIATIONS:
        assert set(deviation) >= {"id", "applies_to", "what", "why_it_matters", "source"}
        assert Path(deviation["source"]).is_file()


def test_elimination_pairing_avoids_rematches_before_maximising_distance():
    """Kills mutation: maximise distance without the repeat filter.

    The furthest pairing here is blocked by a rematch, so a repeat-blind
    implementation picks the higher score and is caught. TI 2025's own bracket
    had the same shape; the figures for it are in
    `reports/pairing_check/pairing_check.json` rather than restated here,
    because they moved when the ranking was corrected on 2026-08-09.
    """
    high, low = ["h0", "h1"], ["l0", "l1"]
    prior = {"h0": {"l1"}, "h1": set()}
    pairs = pair_elimination(high, low, prior, random.Random(0), maximize=True)
    assert set(map(frozenset, pairs)) == {frozenset(("h0", "l0")), frozenset(("h1", "l1"))}

    unblocked = pair_elimination(high, low, {}, random.Random(0), maximize=True)
    assert set(map(frozenset, unblocked)) == {
        frozenset(("h0", "l1")),
        frozenset(("h1", "l0")),
    }
