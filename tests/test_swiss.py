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


def test_round_five_maximises_distance_when_the_loser_is_eliminated():
    """The 1-3 group's Round 5 loser goes to 1-4 and is out, so pair furthest.

    Seed 12 is used because this bucket happens to have zero repeat
    opponents entering round 5, so distance-maximisation is the only
    preference in play; that precondition is asserted explicitly (rather
    than silently relied on) so a future seed change or repeat-minimisation
    conflict here would fail loudly instead of passing by coincidence.
    """
    run = run_swiss(flat(), RULES, random.Random(12))
    round_five = run.rounds[4]
    before = records_before_round(run, 5)
    prior = opponents_before_round(run, 5)
    rank_index = {t: i for i, t in enumerate(round_five.ranking)}

    group = sorted(t for t, rec in before.items() if rec == (1, 3))
    assert len(group) == 4
    chosen = [p for p in round_five.pairings if set(p) <= set(group)]
    assert len(chosen) == 2
    assert sum(1 for a, b in chosen if b in prior[a]) == 0, (
        "precondition: seed 12's (1,3) bucket has no repeat opponents to "
        "conflict with distance maximisation"
    )

    best = max(spread(m, rank_index) for m in perfect_matchings(group))
    assert spread(chosen, rank_index) == best


def test_round_five_minimises_distance_when_the_loser_survives():
    """The 3-1 group's Round 5 loser drops to 3-2 and plays on, so pair closest.

    Seed 12 is used because this bucket happens to have zero repeat
    opponents entering round 5, so distance-minimisation is the only
    preference in play; that precondition is asserted explicitly (rather
    than silently relied on) so a future seed change or repeat-minimisation
    conflict here would fail loudly instead of passing by coincidence.
    """
    run = run_swiss(flat(), RULES, random.Random(12))
    round_five = run.rounds[4]
    before = records_before_round(run, 5)
    prior = opponents_before_round(run, 5)
    rank_index = {t: i for i, t in enumerate(round_five.ranking)}

    group = sorted(t for t, rec in before.items() if rec == (3, 1))
    assert len(group) == 4
    chosen = [p for p in round_five.pairings if set(p) <= set(group)]
    assert len(chosen) == 2
    assert sum(1 for a, b in chosen if b in prior[a]) == 0, (
        "precondition: seed 12's (3,1) bucket has no repeat opponents to "
        "conflict with distance minimisation"
    )

    smallest = min(spread(m, rank_index) for m in perfect_matchings(group))
    assert spread(chosen, rank_index) == smallest


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
