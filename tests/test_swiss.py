import random
from collections import Counter

from swiss_replay import (
    assert_rounds_hit_independent_repeat_minimum,
    opponents_before_round,
    records_before_round,
)

from ti26.pairing import perfect_matchings
from ti26.rules import load_rules
from ti26.swiss import random_initial_groups, random_round_one_schedule, run_swiss

RULES = load_rules("config/ti2026_rules.yaml")
TEAMS = [f"t{i:02d}" for i in range(16)]


def flat(value=0.0):
    return dict.fromkeys(TEAMS, value)


def test_initial_groups_split_eight_and_eight():
    groups = random_initial_groups(TEAMS, random.Random(0))
    assert Counter(groups.values()) == {"A": 8, "B": 8}


def test_round_one_schedule_pairs_within_groups():
    rng = random.Random(1)
    groups = random_initial_groups(TEAMS, rng)
    schedule = random_round_one_schedule(groups, rng)
    assert len(schedule) == 8
    assert all(groups[a] == groups[b] for a, b in schedule)
    flat_ids = [x for pair in schedule for x in pair]
    assert sorted(flat_ids) == sorted(TEAMS)


def test_final_record_distribution_matches_derived_capacities():
    for seed in range(20):
        run = run_swiss(flat(), RULES, random.Random(seed))
        records = Counter(s.record for s in run.states.values())
        assert dict(records) == RULES.record_capacities


def test_round_log_has_one_entry_per_played_round():
    run = run_swiss(flat(), RULES, random.Random(3))
    assert [r.round_no for r in run.rounds] == [1, 2, 3, 4, 5]


def test_round_log_pairings_match_recorded_results():
    run = run_swiss(flat(), RULES, random.Random(4))
    for round_log in run.rounds:
        assert len(round_log.pairings) == len(round_log.results)
        logged = {frozenset(p) for p in round_log.pairings}
        played = {frozenset((r.team_a, r.team_b)) for r in round_log.results}
        assert logged == played
        for result in round_log.results:
            assert max(result.wins_a, result.wins_b) == 2


def test_every_round_achieves_the_minimum_possible_repeat_count():
    """Repeats are minimised, not assumed to be zero.

    Rebuilds each round's buckets and the independently-minimal repeat count
    from the replayed log, rather than trusting `PairingChoice`'s own
    self-reported fields (which are equal by construction and prove nothing).
    """
    for seed in range(20):
        run = run_swiss(flat(), RULES, random.Random(seed))
        assert_rounds_hit_independent_repeat_minimum(run, RULES)


def test_repeat_flags_agree_with_prior_opponents():
    run = run_swiss(flat(), RULES, random.Random(5))
    seen: dict[str, set[str]] = {t: set() for t in TEAMS}
    for round_log in run.rounds:
        for result in round_log.results:
            assert result.was_repeat == (result.team_b in seen[result.team_a])
            seen[result.team_a].add(result.team_b)
            seen[result.team_b].add(result.team_a)


def test_rankings_are_logged_and_cover_every_team():
    run = run_swiss(flat(), RULES, random.Random(6))
    for round_log in run.rounds[1:]:  # round 1 uses the organiser schedule
        assert sorted(round_log.ranking) == sorted(TEAMS)


def test_round_two_pairs_within_record_and_initial_group():
    rng = random.Random(8)
    groups = random_initial_groups(TEAMS, rng)
    schedule = random_round_one_schedule(groups, rng)
    run = run_swiss(flat(), RULES, rng, groups=groups, round_one=schedule)
    before = records_before_round(run, 2)
    for a, b in run.rounds[1].pairings:
        assert before[a] == before[b], "round 2 pairs equal records"
        assert groups[a] == groups[b], "round 2 stays within the initial group"


def test_no_team_ever_plays_itself():
    run = run_swiss(flat(), RULES, random.Random(3))
    for state in run.states.values():
        assert state.team_id not in state.opponents


def test_rounds_two_and_three_stay_within_initial_groups():
    rng = random.Random(4)
    groups = random_initial_groups(TEAMS, rng)
    schedule = random_round_one_schedule(groups, rng)
    run = run_swiss(flat(), RULES, rng, groups=groups, round_one=schedule)
    for state in run.states.values():
        for opponent in state.opponents[:3]:
            assert groups[opponent] == groups[state.team_id]


def test_round_four_is_cross_group():
    rng = random.Random(5)
    groups = random_initial_groups(TEAMS, rng)
    schedule = random_round_one_schedule(groups, rng)
    run = run_swiss(flat(), RULES, rng, groups=groups, round_one=schedule)
    for state in run.states.values():
        if len(state.opponents) >= 4:
            assert groups[state.opponents[3]] != groups[state.team_id]


def spread(matching, rank_index):
    return sum(abs(rank_index[a] - rank_index[b]) for a, b in matching)


def _round_five_buckets(seed):
    """Every Round 5 record bucket that had a real choice, for one seed.

    Yields (record, chosen_matching, all_matchings, repeat_count, rank_index).
    Round 5 has no group constraint and no cross-group constraint, so a bucket
    is just a record class -- which is why the defect lived here and why this
    is the round worth checking exhaustively.
    """
    run = run_swiss(flat(), RULES, random.Random(seed))
    round_five = run.rounds[4]
    before = records_before_round(run, 5)
    prior = opponents_before_round(run, 5)
    rank_index = {t: i for i, t in enumerate(round_five.ranking)}

    for record in sorted({rec for rec in before.values()}):
        group = sorted(t for t, rec in before.items() if rec == record)
        if len(group) < 4 or len(group) % 2:
            continue
        chosen = [p for p in round_five.pairings if set(p) <= set(group)]
        if len(chosen) * 2 != len(group):
            continue

        def repeat_count(matching, _prior=prior):
            return sum(1 for a, b in matching if b in _prior[a])

        yield record, chosen, list(perfect_matchings(group)), repeat_count, rank_index


def test_no_swiss_round_maximises_ranking_distance():
    """Kills mutation: restore max-distance at Round 5 where a loss eliminates.

    The published rules give Round 5 "no special modifications" and put
    distance maximisation in the Elimination Round. Until 2026-08-08 `swiss.py`
    maximised distance in every Round 5 bucket whose loser was eliminated --
    the 1-3 bucket -- which is precisely who ends up 1-4 rather than 2-3.

    Asserted across a seed sweep rather than one hand-picked seed, and the
    sweep is required to actually reach an eliminating bucket, so this cannot
    pass vacuously the way a single-seed version did while asserting the
    opposite rule.
    """
    saw_eliminating_bucket = False
    for seed in range(40):
        for record, chosen, matchings, repeats, ranks in _round_five_buckets(seed):
            if record[1] + 1 >= RULES.eliminate_at_losses:
                saw_eliminating_bucket = True
            fewest = min(repeats(m) for m in matchings)
            tied = [m for m in matchings if repeats(m) == fewest]
            assert spread(chosen, ranks) == min(spread(m, ranks) for m in tied), (
                f"seed {seed}, record {record}: Round 5 must minimise ranking "
                "distance among repeat-minimal matchings, in every bucket"
            )
    assert saw_eliminating_bucket, (
        "precondition: the sweep must reach at least one Round 5 bucket whose "
        "loser is eliminated, or it never tests the case that was wrong"
    )


def test_round_five_repeat_minimisation_wins_over_distance_when_they_conflict():
    """Repeat minimisation is applied FIRST, distance only among the survivors.

    Most seeds give repeat_count == 0 in every Round 5 bucket, where the two
    preferences cannot conflict. This sweeps for a bucket whose minimum
    achievable repeat count is non-zero and asserts on that, so a
    `choose_pairing` that preferred distance over repeats would be caught.
    The sweep asserts it found such a bucket rather than passing vacuously.
    """
    conflicts = 0
    for seed in range(200):
        for record, chosen, matchings, repeats, ranks in _round_five_buckets(seed):
            fewest = min(repeats(m) for m in matchings)
            if fewest == 0:
                continue
            conflicts += 1
            assert repeats(chosen) == fewest, (
                f"seed {seed}, record {record}: repeats must be minimised first"
            )
            tied = [m for m in matchings if repeats(m) == fewest]
            assert spread(chosen, ranks) == min(spread(m, ranks) for m in tied), (
                "distance preference must apply only among matchings tied on repeats"
            )
    assert conflicts, (
        "precondition: the sweep must find at least one genuine repeat "
        "conflict, or it proves nothing about the ordering"
    )


def test_stronger_teams_finish_higher_on_average():
    strengths = {t: (i - 7.5) * 0.4 for i, t in enumerate(TEAMS)}
    totals = Counter()
    for seed in range(200):
        run = run_swiss(strengths, RULES, random.Random(seed))
        for tid, state in run.states.items():
            totals[tid] += state.series_wins
    assert totals["t15"] > totals["t00"]


def test_run_is_seed_reproducible():
    a = run_swiss(flat(), RULES, random.Random(9))
    b = run_swiss(flat(), RULES, random.Random(9))
    assert {k: v.record for k, v in a.states.items()} == {
        k: v.record for k, v in b.states.items()
    }
    assert [r.pairings for r in a.rounds] == [r.pairings for r in b.rounds]


def test_map_counts_are_consistent_with_series_counts():
    run = run_swiss(flat(), RULES, random.Random(2))
    for state in run.states.values():
        played = state.series_wins + state.series_losses
        assert played == len(state.opponents)
        assert 2 * played <= state.maps_played <= 3 * played
