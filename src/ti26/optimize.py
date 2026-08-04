import numpy as np
from scipy.optimize import linear_sum_assignment

from ti26.types import Category


def _break_ties(
    assignment: dict[str, Category],
    order: list[str],
    marginals: dict[str, dict[Category, float]],
    capacities: dict[Category, int],
    weight: dict[Category, float],
    optimum: float,
    tolerance: float,
) -> dict[str, Category]:
    """Improve the scarcity rule over swaps that stay within `tolerance` of `optimum`.

    THE STATED TIE-BREAK: a scarce category goes to whoever most likely lands
    there. `gain` below weights each team's marginal by 1/capacity, which makes
    the one-wide 4-0 and 0-4 slots outrank the five-wide pools -- so a tie is
    settled by the extreme slots, the ones a card is most conspicuously wrong
    about, rather than by whatever order the solver happened to iterate in.

    Swapping two teams' categories always preserves every capacity, so every
    state visited is a legal card, and both swapped categories are occupied and
    therefore have capacity >= 1. `tolerance` is measured against the TRUE
    optimum and applied to the running total, so a chain of individually-free
    swaps can never drift further than one tolerance below the best assignment.

    This is hill-climbing over pairwise swaps, so it reaches a LOCAL optimum of
    the tie-break rule, not a global one. That is enough for its purpose: it
    replaces an arbitrary choice among near-tied assignments with a stated and
    reproducible one. Terminates because each accepted swap strictly increases a
    bounded quantity. `order` is the caller's name-independent team order, so
    which of several equally-good swaps is taken does not depend on display
    names.
    """
    current = dict(assignment)
    total = sum(marginals[t][c] * weight[c] for t, c in current.items())
    floor = optimum - tolerance

    while True:
        best: tuple[float, float, str, str] | None = None
        for i, a in enumerate(order):
            for b in order[i + 1 :]:
                ca, cb = current[a], current[b]
                if ca == cb:
                    continue
                delta = (
                    marginals[a][cb] * weight[cb]
                    + marginals[b][ca] * weight[ca]
                    - marginals[a][ca] * weight[ca]
                    - marginals[b][cb] * weight[cb]
                )
                if total + delta < floor:
                    continue
                gain = (
                    marginals[a][cb] / capacities[cb]
                    + marginals[b][ca] / capacities[ca]
                    - marginals[a][ca] / capacities[ca]
                    - marginals[b][cb] / capacities[cb]
                )
                if gain > 1e-12 and (best is None or gain > best[0]):
                    best = (gain, delta, a, b)
        if best is None:
            return current
        _, delta, a, b = best
        current[a], current[b] = current[b], current[a]
        total += delta


def solve_card(
    marginals: dict[str, dict[Category, float]],
    capacities: dict[Category, int],
    weights: dict[Category, float] | None = None,
    tie_tolerance: float | None = None,
) -> tuple[dict[str, Category], float]:
    """Assign every team to exactly one category, respecting slot capacities.

    Returns the card and the model-implied expected score. That score is
    computed from the model's own probabilities and is therefore descriptive
    only -- never evidence of forecast quality (see spec section II).

    `tie_tolerance` is how far below the optimum an assignment may sit and
    still count as tied with it. Pass the Monte Carlo standard error of the
    marginals (see `montecarlo.monte_carlo_stderr`); pass None to rank strictly
    on the raw values, which is the plain expected-score optimum.

    It exists because the raw objective silently separated assignments by less
    than its own estimation error: on the 2026-08-04 production run the 0-4
    slot turned on a 4.2e-4 difference in expected points while a single
    marginal carried 6.5e-4 of Monte Carlo error, so which team took the card's
    most extreme slot was decided by simulation noise. This does not remove
    that noise -- it stops the solver acting on differences it cannot resolve,
    and hands those choices to `_break_ties`' stated rule instead.

    Note it is the ASSIGNMENT TOTALS that must be compared at this tolerance,
    not the individual marginals. Rounding each marginal to the error instead
    is a no-op here: the cells that make up two near-tied totals differ from
    each other by far more than the error (0.148 vs 0.122 against a 6.5e-4
    error), so they survive rounding untouched and the totals stay just as
    separated as before.
    """
    # Row order decides among equal-cost optima inside `linear_sum_assignment`,
    # so it must not depend on display names either -- ordering by the marginal
    # vector keeps the whole solve a function of the probabilities. The name is
    # the last resort only for byte-identical rows, which are interchangeable.
    teams = sorted(marginals, key=lambda t: ([-marginals[t][c] for c in Category], t))
    slots: list[Category] = [c for c in Category for _ in range(capacities[c])]
    if len(slots) != len(teams):
        raise ValueError(f"{len(teams)} teams cannot fill {len(slots)} slots")

    weight = weights or dict.fromkeys(Category, 1.0)
    payoff = np.array(
        [[marginals[t][c] * weight[c] for c in slots] for t in teams], dtype=float
    )

    rows, cols = linear_sum_assignment(-payoff)
    card = {teams[r]: slots[c] for r, c in zip(rows, cols, strict=True)}
    optimum = float(payoff[rows, cols].sum())

    if tie_tolerance is not None and tie_tolerance > 0.0:
        card = _break_ties(
            card, teams, marginals, capacities, weight, optimum, tie_tolerance
        )

    # Always scored on the raw payoff so the reported expected score stays
    # comparable to earlier runs and to the random baseline. After a tie-break
    # this is at or just below `optimum`, by at most `tie_tolerance`.
    score = sum(marginals[t][c] * weight[c] for t, c in card.items())
    return card, float(score)
