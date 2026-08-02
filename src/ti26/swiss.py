import random
from collections import defaultdict

from ti26.pairing import choose_pairing
from ti26.rules import Rules
from ti26.series import simulate_series
from ti26.tiebreak import DurationResolver, rank_teams
from ti26.types import RoundLog, SeriesResult, SwissRun, TeamState


def random_initial_groups(team_ids: list[str], rng: random.Random) -> dict[str, str]:
    shuffled = list(team_ids)
    rng.shuffle(shuffled)
    half = len(shuffled) // 2
    return {t: ("A" if i < half else "B") for i, t in enumerate(shuffled)}


def random_round_one_schedule(
    groups: dict[str, str], rng: random.Random
) -> list[tuple[str, str]]:
    schedule: list[tuple[str, str]] = []
    for label in sorted(set(groups.values())):
        members = sorted(t for t, g in groups.items() if g == label)
        rng.shuffle(members)
        schedule.extend((members[i], members[i + 1]) for i in range(0, len(members), 2))
    return schedule


def _play(
    states: dict[str, TeamState],
    pair: tuple[str, str],
    strengths: dict[str, float],
    rng: random.Random,
    round_no: int,
) -> SeriesResult:
    a, b = pair
    sa, sb = states[a], states[b]
    was_repeat = b in sa.opponents
    wins_a, wins_b = simulate_series(strengths[a], strengths[b], rng)
    sa.map_wins += wins_a
    sa.map_losses += wins_b
    sb.map_wins += wins_b
    sb.map_losses += wins_a
    if wins_a > wins_b:
        sa.series_wins += 1
        sb.series_losses += 1
    else:
        sb.series_wins += 1
        sa.series_losses += 1
    sa.opponents.append(b)
    sb.opponents.append(a)
    return SeriesResult(
        round_no=round_no,
        team_a=a,
        team_b=b,
        wins_a=wins_a,
        wins_b=wins_b,
        was_repeat=was_repeat,
    )


def run_swiss(
    strengths: dict[str, float],
    rules: Rules,
    rng: random.Random,
    groups: dict[str, str] | None = None,
    round_one: list[tuple[str, str]] | None = None,
) -> SwissRun:
    """Run all Swiss rounds, returning final states plus a full round log."""
    team_ids = sorted(strengths)
    if groups is None:
        groups = random_initial_groups(team_ids, rng)
    if round_one is None:
        round_one = random_round_one_schedule(groups, rng)

    states = {t: TeamState(team_id=t, initial_group=groups[t]) for t in team_ids}
    resolver = DurationResolver(rng, rules.duration_log_mean, rules.duration_log_sigma)
    logs: list[RoundLog] = []

    results = [_play(states, pair, strengths, rng, 1) for pair in round_one]
    logs.append(
        RoundLog(
            round_no=1,
            ranking=list(team_ids),
            pairings=list(round_one),
            repeat_count=0,
            min_possible_repeats=0,
            results=results,
        )
    )

    for round_no in range(2, rules.total_rounds + 1):
        active = [s for s in states.values() if rules.is_active(s)]
        if not active:
            break
        ranking = rank_teams(
            list(states.values()), rng, duration_fn=resolver.bind(states)
        )
        rank_index = {tid: i for i, tid in enumerate(ranking)}
        prior = {s.team_id: set(s.opponents) for s in states.values()}

        buckets: dict[tuple, list[str]] = defaultdict(list)
        for state in active:
            key = (
                (state.record, state.initial_group)
                if round_no in rules.within_group_rounds
                else (state.record,)
            )
            buckets[key].append(state.team_id)

        pairings: list[tuple[str, str]] = []
        results = []
        repeat_count = min_possible = 0
        for key in sorted(buckets, key=str):
            record = key[0]
            loser_out = record[1] + 1 >= rules.eliminate_at_losses
            choice = choose_pairing(
                sorted(buckets[key]),
                rank_index,
                prior,
                rng,
                group_of=groups,
                cross_group=round_no in rules.cross_group_rounds,
                maximize_distance=(
                    loser_out and round_no in rules.max_distance_elimination_rounds
                ),
            )
            repeat_count += choice.repeat_count
            min_possible += choice.min_possible_repeats
            pairings.extend(choice.matching)
            results.extend(
                _play(states, pair, strengths, rng, round_no) for pair in choice.matching
            )

        logs.append(
            RoundLog(
                round_no=round_no,
                ranking=ranking,
                pairings=pairings,
                repeat_count=repeat_count,
                min_possible_repeats=min_possible,
                results=results,
            )
        )

    return SwissRun(states=states, groups=groups, rounds=logs, resolver=resolver)
