import numpy as np
from scipy.optimize import linear_sum_assignment

from ti26.types import Category


def solve_card(
    marginals: dict[str, dict[Category, float]],
    capacities: dict[Category, int],
    weights: dict[Category, float] | None = None,
) -> tuple[dict[str, Category], float]:
    """Assign every team to exactly one category, respecting slot capacities.

    Returns the card and the model-implied expected score. That score is
    computed from the model's own probabilities and is therefore descriptive
    only -- never evidence of forecast quality (see spec section II).
    """
    teams = sorted(marginals)
    slots: list[Category] = [c for c in Category for _ in range(capacities[c])]
    if len(slots) != len(teams):
        raise ValueError(f"{len(teams)} teams cannot fill {len(slots)} slots")

    weight = weights or dict.fromkeys(Category, 1.0)
    payoff = np.array(
        [[marginals[t][c] * weight[c] for c in slots] for t in teams], dtype=float
    )
    rows, cols = linear_sum_assignment(-payoff)
    card = {teams[r]: slots[c] for r, c in zip(rows, cols, strict=True)}
    return card, float(payoff[rows, cols].sum())
