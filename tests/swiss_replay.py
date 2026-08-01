"""Independent recomputation helpers shared by test_swiss.py and test_invariants.py.

These replay a SwissRun's log to rebuild per-round records and prior-opponent
sets, then brute-force the minimum achievable repeat count via
`perfect_matchings`. Nothing here reads `PairingChoice.repeat_count` or
`.min_possible_repeats`, so it is independent of the code under test.
"""

from collections import defaultdict

from ti26.pairing import perfect_matchings
from ti26.rules import Rules
from ti26.types import SwissRun, TeamState


def opponents_before_round(run: SwissRun, round_no: int) -> dict[str, set[str]]:
    """Replay the log to recover each team's opponent set entering a round."""
    seen: dict[str, set[str]] = {t: set() for t in run.states}
    for round_log in run.rounds:
        if round_log.round_no >= round_no:
            break
        for result in round_log.results:
            seen[result.team_a].add(result.team_b)
            seen[result.team_b].add(result.team_a)
    return seen


def records_before_round(run: SwissRun, round_no: int) -> dict[str, tuple[int, int]]:
    """Replay the log to recover each team's (wins, losses) entering a round."""
    tally = {t: [0, 0] for t in run.states}
    for round_log in run.rounds:
        if round_log.round_no >= round_no:
            break
        for result in round_log.results:
            winner, loser = (
                (result.team_a, result.team_b)
                if result.wins_a > result.wins_b
                else (result.team_b, result.team_a)
            )
            tally[winner][0] += 1
            tally[loser][1] += 1
    return {t: tuple(v) for t, v in tally.items()}


def independent_min_repeats_for_bucket(
    members: list[str],
    prior: dict[str, set[str]],
    cross_group: bool,
    group_of: dict[str, str],
) -> int:
    """Brute-force the minimum achievable repeat count for a record bucket.

    Uses only `perfect_matchings` (pure enumeration) and the replayed prior-
    opponent sets -- never reads `PairingChoice.repeat_count` or
    `.min_possible_repeats`, so it is independent of the code under test.
    """
    candidates = list(perfect_matchings(sorted(members)))
    if cross_group:
        candidates = [m for m in candidates if all(group_of[a] != group_of[b] for a, b in m)]

    def repeats(matching: list[tuple[str, str]]) -> int:
        return sum(1 for a, b in matching if b in prior[a])

    return min(repeats(m) for m in candidates)


def assert_rounds_hit_independent_repeat_minimum(run: SwissRun, rules: Rules) -> None:
    """Assert every round after Round 1 hits the independently recomputed minimum.

    Rebuilds each round's buckets and the independently-minimal repeat count
    from the replayed log, rather than trusting `PairingChoice`'s own
    self-reported fields (which are equal by construction and prove nothing).
    """
    for round_log in run.rounds[1:]:  # round 1 has no prior history
        round_no = round_log.round_no
        records = records_before_round(run, round_no)
        prior = opponents_before_round(run, round_no)
        active_teams = [
            t
            for t, rec in records.items()
            if rules.is_active(
                TeamState(
                    team_id=t,
                    initial_group=run.groups[t],
                    series_wins=rec[0],
                    series_losses=rec[1],
                )
            )
        ]
        buckets: dict[tuple, list[str]] = defaultdict(list)
        for t in active_teams:
            rec = records[t]
            key = (rec, run.groups[t]) if round_no in rules.within_group_rounds else (rec,)
            buckets[key].append(t)

        for members in buckets.values():
            min_repeats = independent_min_repeats_for_bucket(
                members, prior, round_no in rules.cross_group_rounds, run.groups
            )
            actual_pairs = [p for p in round_log.pairings if set(p) <= set(members)]
            actual_repeats = sum(1 for a, b in actual_pairs if b in prior[a])
            assert actual_repeats == min_repeats
