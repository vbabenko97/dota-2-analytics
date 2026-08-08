import random

from ti26.rules import Rules, category_for_terminal_record
from ti26.series import simulate_series
from ti26.tiebreak import rank_teams
from ti26.types import Category, EliminationMatch, EliminationRun, SwissRun


def run_elimination(
    run: SwissRun,
    strengths: dict[str, float],
    rules: Rules,
    rng: random.Random,
) -> EliminationRun:
    """Resolve the elimination matches and assign every team a category.

    The published rule is two sentences: teams with a 3-2 record are paired
    against teams with a 2-3 record, and distance in ranking between them is
    maximised where possible. Both are deterministic given the ranking, so
    nothing here chooses anything.

    Because every 3-2 team outranks every 2-3 team on the first criterion, the
    TOTAL ranking distance across the matching is the same whatever the
    pairing -- each team contributes its own rank exactly once either way. So
    "maximised" cannot mean the sum, and is read here per pair, from the top:
    best 3-2 against worst 2-3, second-best against second-worst, and so on.

    Until 2026-08-08 this function instead had each 3-2 team SELECT the
    opponent it was most likely to beat, under a configurable policy. That
    model came from the design spec, which cited nothing for it, and it decided
    the category of ten of the sixteen teams.
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

    matches: list[EliminationMatch] = []
    for i, team in enumerate(higher):
        # Maximum distance pairs best-against-worst; the general Swiss rule
        # this falls back to minimises it, pairing best against best. The
        # fallback exists so the sensitivity diagnostic can price the rule.
        opponent = lower[len(lower) - 1 - i] if rules.elimination_maximizes_ranking_distance else lower[i]
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
