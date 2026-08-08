"""The elimination round, which TI 2026 runs differently from TI 2025.

TWO RULES LIVE HERE, deliberately, because two events used two of them and this
repository has to model one while validating against the other.

`run_elimination` implements TI 2026's published rule, fetched 2026-08-08 (see
docs/ti26/2026-08-08-ti2026-rules-fetched.md): the best 3-2 team CHOOSES any of
the five 2-3 teams, then the next best chooses from those remaining, and so on.
That is a sequential decision, not a pairing computation, and it needs an
assumption about how a team chooses -- `ChoicePolicy` names the candidates.

`pair_elimination` implements TI 2025's, where the round was paired by maximum
ranking distance with no choice involved. Nothing in the 2026 simulation calls
it; it exists for `cli_pairing_check`, which validates the engine against TI
2025's real bracket and therefore needs TI 2025's rule.

Keeping both is not indecision. Deleting the 2025 rule would leave the only
event we can check against unmodellable, and reusing the 2026 rule to
"validate" against 2025 would be validating against the wrong tournament.
"""

import math
import random
from enum import Enum
from functools import lru_cache
from itertools import permutations

from ti26.rules import Rules, category_for_terminal_record
from ti26.series import map_win_prob, series_win_prob, simulate_series
from ti26.tiebreak import rank_teams
from ti26.types import Category, EliminationMatch, EliminationRun, SwissRun


class ChoicePolicy(str, Enum):
    """How a 3-2 team picks its opponent. The rules do not say.

    Valve's text fixes the ORDER of choosing and says nothing about the basis,
    so any implementation is an assumption about team behaviour rather than a
    reading of the rules. Naming the assumptions makes them priceable: the
    schedule-sensitivity diagnostic runs all three and reports what the card
    does in response.
    """

    RATIONAL = "rational"
    """Take the opponent this team is most likely to beat, by our own ratings.

    Assumes teams scout accurately, agree with our model, and act on it. The
    strongest assumption of the three, and the one a reader would guess.
    """

    NOISY = "noisy"
    """Softmax over series win probability: usually the weakest, not always.

    One free parameter. If it is ever used for the shipping card its
    temperature must be registered in advance, not tuned until the card looks
    right.
    """

    RANDOM = "random"
    """Uniform among those still available.

    Certainly wrong as a model of intent, and the only one that cannot be
    accused of encoding our own ratings twice -- once in the strengths and
    again in the choice.
    """


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


def _select_opponent(
    chooser: str,
    available: list[str],
    strengths: dict[str, float],
    rng: random.Random,
    policy: ChoicePolicy,
    softmax_temp: float,
) -> str:
    if policy is ChoicePolicy.RANDOM:
        return rng.choice(available)

    win_probs = [
        series_win_prob(map_win_prob(strengths[chooser], strengths[opp])) for opp in available
    ]
    if policy is ChoicePolicy.RATIONAL:
        return available[win_probs.index(max(win_probs))]

    weights = [math.exp(p / softmax_temp) for p in win_probs]
    return rng.choices(available, weights=weights, k=1)[0]


def run_elimination(
    run: SwissRun,
    strengths: dict[str, float],
    rules: Rules,
    rng: random.Random,
    policy: ChoicePolicy = ChoicePolicy.RATIONAL,
    softmax_temp: float = 1.0,
) -> EliminationRun:
    """Resolve the elimination matches and assign every team a category.

    TI 2026's published rule, verbatim: "Starting with the best 3-2 team, they
    will choose any of the five 2-3 teams as their opponent. The next best 3-2
    team will then choose any of the remaining 2-3 teams as their opponent.
    Repeat the above until all teams have chosen an opponent."

    So the ORDER of choosing is fixed by the Swiss ranking and the BASIS of the
    choice is not specified anywhere. `policy` is that gap, made explicit.

    Between 2026-08-08 and this commit, this function instead paired the round
    by maximum ranking distance with no choice at all. That was TI 2025's rule,
    adopted while TI 2026's pairing section was still unpublished, and it
    decided the category of ten of the sixteen teams.
    """
    if softmax_temp <= 0:
        raise ValueError(f"softmax_temp must be positive, got {softmax_temp}")

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
            "expected exactly two undecided record groups (choosers and pool), "
            f"found {len(undecided_records)}: {counts}"
        )

    ranking = rank_teams(list(run.states.values()), rng, duration_fn=run.resolver.bind(run.states))
    order = {tid: i for i, tid in enumerate(ranking)}

    top_record = max(run.states[t].record for t in undecided)
    choosers = sorted(
        (t for t in undecided if run.states[t].record == top_record),
        key=lambda t: order[t],
    )
    available = sorted(
        (t for t in undecided if run.states[t].record != top_record),
        key=lambda t: order[t],
    )
    if len(choosers) != len(available):
        raise ValueError(
            f"chooser count {len(choosers)} for record {top_record} != "
            f"pool count {len(available)} for the other undecided record"
        )

    matches: list[EliminationMatch] = []
    for chooser in choosers:
        snapshot = list(available)
        opponent = _select_opponent(chooser, available, strengths, rng, policy, softmax_temp)
        available.remove(opponent)
        wins_c, wins_o = simulate_series(strengths[chooser], strengths[opponent], rng)
        if wins_c > wins_o:
            categories[chooser] = Category.ELIM_WIN
            categories[opponent] = Category.ELIM_LOSS
        else:
            categories[chooser] = Category.ELIM_LOSS
            categories[opponent] = Category.ELIM_WIN
        matches.append(
            EliminationMatch(
                chooser=chooser,
                opponent=opponent,
                available_when_choosing=snapshot,
                wins_chooser=wins_c,
                wins_opponent=wins_o,
            )
        )

    return EliminationRun(categories=categories, matches=matches)
