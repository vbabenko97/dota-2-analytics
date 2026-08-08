import math
import random
from collections import Counter
from collections.abc import Mapping, Sequence

from ti26.elimination import run_elimination
from ti26.identity import order_key
from ti26.rules import Rules
from ti26.swiss import run_swiss
from ti26.types import Category


def monte_carlo_stderr(p: float, n: int) -> float:
    return math.sqrt(max(p * (1.0 - p), 0.0) / n)


def canonical_labels(
    strengths: dict[str, float], team_ids: Mapping[str, object] | None = None
) -> dict[str, str]:
    """Map team names to strength-ranked internal ids, `t00`-style.

    The simulation sorts its team ids before every RNG draw it makes
    (`run_swiss` for the initial groups, `random_round_one_schedule` and
    `pair_bucket` for the schedules), so running it directly on display names
    makes the card depend on those names. Renaming "1win" to "Iron Wing" moved
    one team from first to seventh in alphabetical order and flipped a card
    slot with no strength change at all.

    Ranking by strength makes the labels a function of the model's numbers
    rather than of its labels. Zero-padding keeps lexicographic order equal to
    rank order, so the downstream `sorted()` calls need no changes.

    Exactly-equal strengths still need an order, and that order is `team_ids`
    when supplied. It was previously the display name, described as harmless
    because tied teams are interchangeable. They are not: equal strength does
    not mean equal simulation stream, so swapping two tied teams' labels swaps
    their marginal rows. Production callers pass the configured team ids;
    callers whose keys are already stable identifiers may omit them.
    """
    tie_break = order_key(strengths, team_ids)
    order = sorted(strengths, key=lambda t: (-strengths[t], tie_break(t)))
    width = max(len(str(len(order) - 1)), 2)
    return {team: f"t{i:0{width}d}" for i, team in enumerate(order)}


def card_score_distribution(
    card: dict[str, Category],
    strengths: dict[str, float],
    rules: Rules,
    n_sims: int,
    seed: int,
    team_ids: Mapping[str, object] | None = None,
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
    labels = canonical_labels(strengths, team_ids)
    internal = {labels[team]: strength for team, strength in strengths.items()}
    target = {labels[team]: category for team, category in card.items()}
    scores: Counter[int] = Counter()
    for i in range(n_sims):
        rng = random.Random(seed * 1_000_003 + i)
        run = run_swiss(internal, rules, rng)
        outcome = run_elimination(run, internal, rules, rng)
        hits = sum(1 for label, c in outcome.categories.items() if target[label] == c)
        scores[hits] += 1
    return scores


def category_marginals(
    strengths: dict[str, float],
    rules: Rules,
    n_sims: int,
    seed: int,
    team_ids: Mapping[str, object] | None = None,
    pairing_preference: str | None = None,
    groups: Mapping[str, str] | None = None,
    round_one: Sequence[tuple[str, str]] | None = None,
) -> dict[str, dict[Category, float]]:
    """Run n_sims tournaments and return P[team][category].

    `pairing_preference` reaches `choose_pairing` unchanged and is only for the
    schedule-sensitivity diagnostic; `None` is the shipping rule.

    `groups` and `round_one` are the organiser's own draw, keyed by the SAME
    team names as `strengths`, and are translated to internal labels here.
    Rounds 2 and 3 pair inside the initial group and round 4 pairs across it, so
    the split is not cosmetic: with it unset every simulation invents its own,
    which averages over a fact that will be known before the lock. `None` keeps
    that averaging behaviour and is byte-identical to not passing them at all.
    """
    labels = canonical_labels(strengths, team_ids)
    internal = {labels[team]: strength for team, strength in strengths.items()}
    internal_groups = {labels[t]: g for t, g in groups.items()} if groups else None
    internal_round_one = (
        [(labels[a], labels[b]) for a, b in round_one] if round_one else None
    )
    tally: dict[str, Counter[Category]] = {label: Counter() for label in internal}
    for i in range(n_sims):
        rng = random.Random(seed * 1_000_003 + i)
        run = run_swiss(
            internal,
            rules,
            rng,
            groups=dict(internal_groups) if internal_groups else None,
            round_one=list(internal_round_one) if internal_round_one else None,
            pairing_preference=pairing_preference,
        )
        outcome = run_elimination(run, internal, rules, rng)
        for label, category in outcome.categories.items():
            tally[label][category] += 1
    return {
        team: {c: tally[labels[team]][c] / n_sims for c in Category} for team in strengths
    }
