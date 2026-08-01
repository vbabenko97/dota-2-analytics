import math
import random
from enum import Enum

from ti26.rules import Rules, category_for_terminal_record
from ti26.series import map_win_prob, series_win_prob, simulate_series
from ti26.tiebreak import rank_teams
from ti26.types import Category, EliminationMatch, EliminationRun, SwissRun


class ChoicePolicy(str, Enum):
    RATIONAL = "rational"
    NOISY = "noisy"
    RANDOM = "random"


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
        series_win_prob(map_win_prob(strengths[chooser], strengths[opp]))
        for opp in available
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
    """Resolve the elimination matches and assign every team a category."""
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

    ranking = rank_teams(
        list(run.states.values()), rng, duration_fn=run.resolver.bind(run.states)
    )
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
        opponent = _select_opponent(
            chooser, available, strengths, rng, policy, softmax_temp
        )
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
