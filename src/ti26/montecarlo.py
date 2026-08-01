import math
import random
from collections import Counter

from ti26.elimination import ChoicePolicy, run_elimination
from ti26.rules import Rules
from ti26.swiss import run_swiss
from ti26.types import Category


def monte_carlo_stderr(p: float, n: int) -> float:
    return math.sqrt(max(p * (1.0 - p), 0.0) / n)


def category_marginals(
    strengths: dict[str, float],
    rules: Rules,
    n_sims: int,
    seed: int,
    policy: ChoicePolicy = ChoicePolicy.RATIONAL,
) -> dict[str, dict[Category, float]]:
    """Run n_sims tournaments and return P[team][category]."""
    tally: dict[str, Counter[Category]] = {t: Counter() for t in strengths}
    for i in range(n_sims):
        rng = random.Random(seed * 1_000_003 + i)
        run = run_swiss(strengths, rules, rng)
        outcome = run_elimination(run, strengths, rules, rng, policy=policy)
        for team, category in outcome.categories.items():
            tally[team][category] += 1
    return {t: {c: tally[t][c] / n_sims for c in Category} for t in strengths}
