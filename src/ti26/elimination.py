import random
from functools import lru_cache
from itertools import permutations

from ti26.rules import Rules, category_for_terminal_record
from ti26.series import simulate_series
from ti26.tiebreak import rank_teams
from ti26.types import Category, EliminationMatch, EliminationRun, SwissRun


@lru_cache(maxsize=8)
def _permutations_of(n: int) -> tuple[tuple[int, ...], ...]:
    return tuple(permutations(range(n)))


@lru_cache(maxsize=16)
def _by_distance(n: int, maximize: bool) -> tuple[tuple[tuple[int, ...], ...], ...]:
    """Permutations grouped by total seed distance, best group first.

    Distance depends only on the permutation, never on the teams, so it is
    computed once per size instead of once per simulated tournament. Grouping
    lets the common case stop at the first group rather than scoring all n!.
    """
    groups: dict[int, list[tuple[int, ...]]] = {}
    for perm in _permutations_of(n):
        groups.setdefault(sum(abs(i - j) for i, j in enumerate(perm)), []).append(perm)
    order = sorted(groups, reverse=maximize)
    return tuple(tuple(groups[d]) for d in order)


def pair_elimination(
    higher: list[str],
    lower: list[str],
    prior: dict[str, set[str]],
    rng: random.Random,
    maximize: bool = True,
) -> list[tuple[str, str]]:
    """Pair 3-2 against 2-3 by the published rule, as it is actually scored.

    "Distance in ranking" is measured on SEED WITHIN EACH RECORD CLASS, not on
    overall ranking position, and the objective is the SUM over the matching.
    On TI 2025 the real bracket's pairs were seeds (1,5), (2,1), (3,3), (4,4)
    and (5,2), summing to 8; the rematch-free optimum was 10.

    Overall ranking position cannot be the metric: every 3-2 team outranks
    every 2-3 team, so each contributes its rank exactly once whatever the
    matching and the total is constant. This function used to read the rule
    per-pair for that reason, which was the wrong conclusion from a correct
    observation.

    Repeat avoidance comes FIRST, matching the general Swiss rule and the
    Swiss-round engine: the unconstrained optimum on TI 2025 scored 12 and was
    unreachable because it required rematches. Ties are broken uniformly at
    random, as everywhere else here.

    The distance groups are built by walking `_permutations_of` in order, so a
    group lists its members in that same order and the candidate list handed to
    `rng.choice` is the one an exhaustive filter would have produced. That is
    what makes the fast path below an optimisation rather than a silent change
    of tie-breaking, and therefore of the card.
    """
    if len(higher) != len(lower):
        raise ValueError(f"cannot pair {len(higher)} against {len(lower)}")

    n = len(higher)
    blocked = tuple(
        tuple(lower[j] in prior.get(higher[i], ()) for j in range(n)) for i in range(n)
    )

    def repeats(perm: tuple[int, ...]) -> int:
        return sum(1 for i, j in enumerate(perm) if blocked[i][j])

    # Fast path. Zero is the least achievable repeat count, so the FIRST
    # distance group containing a rematch-free permutation holds the whole
    # optimum -- no need to score the rest. Usually that is the very first
    # group, since few 3-2 teams have already met the 2-3 team at the opposite
    # seed. Falls through only when every permutation forces a rematch, which
    # is the case the slow path below exists for.
    for group in _by_distance(n, maximize):
        legal = [p for p in group if not repeats(p)]
        if legal:
            chosen = rng.choice(legal)
            return [(higher[i], lower[j]) for i, j in enumerate(chosen)]

    fewest = min(repeats(p) for p in _permutations_of(n))
    survivors = {p for p in _permutations_of(n) if repeats(p) == fewest}
    for group in _by_distance(n, maximize):
        legal = [p for p in group if p in survivors]
        if legal:
            chosen = rng.choice(legal)
            return [(higher[i], lower[j]) for i, j in enumerate(chosen)]
    raise AssertionError("every permutation was filtered out, which cannot happen")


def run_elimination(
    run: SwissRun,
    strengths: dict[str, float],
    rules: Rules,
    rng: random.Random,
) -> EliminationRun:
    """Resolve the elimination matches and assign every team a category.

    The published rule is two sentences: teams with a 3-2 record are paired
    against teams with a 2-3 record, and distance in ranking between them is
    maximised where possible. It is deterministic given the ranking, so nothing
    here chooses anything -- `pair_elimination` scores it.

    Until 2026-08-08 this function had each 3-2 team SELECT the opponent it was
    most likely to beat, under a configurable policy. That model came from the
    design spec, which cited nothing for it, and it decided the category of ten
    of the sixteen teams.
    """
    categories: dict[str, Category] = {}
    undecided: list[str] = []
    for tid, state in run.states.items():
        fixed = category_for_terminal_record(
            state.record, rules.advance_at_wins, rules.eliminate_at_losses
        )
        if fixed is None:
            undecided.append(tid)
        else:
            categories[tid] = fixed

    undecided_records = sorted({run.states[t].record for t in undecided})
    if len(undecided_records) != 2:
        counts = {
            record: sum(1 for t in undecided if run.states[t].record == record)
            for record in undecided_records
        }
        raise ValueError(
            "expected exactly two undecided record groups (higher and lower), "
            f"found {len(undecided_records)}: {counts}"
        )

    ranking = rank_teams(list(run.states.values()), rng)
    order = {tid: i for i, tid in enumerate(ranking)}

    top_record = max(run.states[t].record for t in undecided)
    higher = sorted(
        (t for t in undecided if run.states[t].record == top_record),
        key=lambda t: order[t],
    )
    lower = sorted(
        (t for t in undecided if run.states[t].record != top_record),
        key=lambda t: order[t],
    )
    if len(higher) != len(lower):
        raise ValueError(
            f"higher-record count {len(higher)} for {top_record} != "
            f"lower-record count {len(lower)} for the other undecided record"
        )

    prior = {t: set(run.states[t].opponents) for t in higher}
    pairs = pair_elimination(
        higher, lower, prior, rng,
        maximize=rules.elimination_maximizes_ranking_distance,
    )

    matches: list[EliminationMatch] = []
    for team, opponent in pairs:
        wins_h, wins_l = simulate_series(strengths[team], strengths[opponent], rng)
        if wins_h > wins_l:
            categories[team] = Category.ELIM_WIN
            categories[opponent] = Category.ELIM_LOSS
        else:
            categories[team] = Category.ELIM_LOSS
            categories[opponent] = Category.ELIM_WIN
        matches.append(
            EliminationMatch(
                higher=team,
                lower=opponent,
                wins_higher=wins_h,
                wins_lower=wins_l,
            )
        )

    return EliminationRun(categories=categories, matches=matches)
