import math
import random
from collections import Counter

from ti26.elimination import ChoicePolicy, run_elimination
from ti26.rules import Rules
from ti26.swiss import run_swiss
from ti26.types import Category


def monte_carlo_stderr(p: float, n: int) -> float:
    return math.sqrt(max(p * (1.0 - p), 0.0) / n)


def canonical_labels(strengths: dict[str, float]) -> dict[str, str]:
    """Map team names to strength-ranked internal ids, `t00`-style.

    The simulation sorts its team ids before every RNG draw it makes
    (`run_swiss` for the initial groups, `random_round_one_schedule` and
    `pair_bucket` for the schedules), so running it directly on display names
    makes the card depend on those names. Renaming "1win" to "Iron Wing" moved
    one team from first to seventh in alphabetical order and flipped a card
    slot with no strength change at all -- the two candidate assignments were
    4.2e-4 expected points apart, well inside this estimator's own Monte Carlo
    error, so the reshuffle alone decided it.

    Ranking by strength makes the labels a function of the model's numbers
    rather than of its labels. Zero-padding keeps lexicographic order equal to
    rank order, so the downstream `sorted()` calls need no changes. The name is
    the final tie-break only among exactly-equal strengths, where the teams are
    interchangeable and the choice cannot matter.
    """
    order = sorted(strengths, key=lambda t: (-strengths[t], t))
    width = max(len(str(len(order) - 1)), 2)
    return {team: f"t{i:0{width}d}" for i, team in enumerate(order)}


def card_score_distribution(
    card: dict[str, Category],
    strengths: dict[str, float],
    rules: Rules,
    n_sims: int,
    seed: int,
    policy: ChoicePolicy = ChoicePolicy.RATIONAL,
) -> Counter[int]:
    """Score one FIXED card against n_sims simulated outcomes; return score -> count.

    The card is held constant rather than re-solved per simulation. Re-solving
    would measure how well the PROCEDURE adapts to each outcome, which is a
    different and much easier question than how this one published card fares
    against outcomes the model itself considers plausible.

    Use a `seed` independent of the one that produced the marginals the card was
    solved from. The card was chosen to maximise expected score over those
    specific draws, so scoring it against them again rewards it for noise it was
    fitted to.
    """
    labels = canonical_labels(strengths)
    internal = {labels[team]: strength for team, strength in strengths.items()}
    target = {labels[team]: category for team, category in card.items()}
    scores: Counter[int] = Counter()
    for i in range(n_sims):
        rng = random.Random(seed * 1_000_003 + i)
        run = run_swiss(internal, rules, rng)
        outcome = run_elimination(run, internal, rules, rng, policy=policy)
        hits = sum(1 for label, c in outcome.categories.items() if target[label] == c)
        scores[hits] += 1
    return scores


def category_marginals(
    strengths: dict[str, float],
    rules: Rules,
    n_sims: int,
    seed: int,
    policy: ChoicePolicy = ChoicePolicy.RATIONAL,
) -> dict[str, dict[Category, float]]:
    """Run n_sims tournaments and return P[team][category]."""
    labels = canonical_labels(strengths)
    internal = {labels[team]: strength for team, strength in strengths.items()}
    tally: dict[str, Counter[Category]] = {label: Counter() for label in internal}
    for i in range(n_sims):
        rng = random.Random(seed * 1_000_003 + i)
        run = run_swiss(internal, rules, rng)
        outcome = run_elimination(run, internal, rules, rng, policy=policy)
        for label, category in outcome.categories.items():
            tally[label][category] += 1
    return {
        team: {c: tally[labels[team]][c] / n_sims for c in Category} for team in strengths
    }
