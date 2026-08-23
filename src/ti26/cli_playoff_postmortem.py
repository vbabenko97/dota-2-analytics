"""Model-implied postmortem of the eight frozen playoff cards.

Registered in `docs/superpowers/specs/2026-08-23-playoff-card-postmortem.md`,
which was written and merged before this file existed and before any number
here had been computed. Everything this producer may report, and everything it
may not, comes from that document.

DIAGNOSTIC. It gates nothing, cannot be converted into a gate, and cannot
promote, demote, reorder or alter any card. Every card it scores was frozen and
merge-anchored before the first Main Event match.

Two questions, deliberately kept apart because they have different references:

1. the exact distribution of each card's hit count under the MODEL's own frozen
   pre-event probabilities -- an internal-consistency diagnostic, not a p-value.
   The no-skill question is already answered against the coin by
   `cli_playoff_score`, and adding the two would count one event twice;
2. per-slot proper scores of the model's stated slot marginals against the
   coin's, which reads the probabilities the hit count throws away.

No seed appears anywhere below. The 2**14 outcome space is enumerated exactly,
so there is no Monte Carlo error to report and no generator stream to pin --
the reason the group card postmortem's `eval_seed` machinery has no analogue
here, and a structural fact rather than a relaxation.
"""

import argparse
import collections
import math
from pathlib import Path

import yaml

from ti26.bracket import SLOTS, slot_distributions, weighted_brackets
from ti26.cli_playoff_cards import TOLERANCE, PlayoffCardError, coherent_picks, fit_strengths
from ti26.cli_playoff_score import load_outcome
from ti26.proper_scores import brier_skill_score, multiclass_brier, multiclass_log_loss
from ti26.series import map_win_prob, series_win_prob

# Card A is the exact argmax of E[hits] over all 16384 coherent brackets, so its
# distribution is the most favourable any card can have. That is a fact about
# how it was built, not noise it was fitted to -- an exact optimum over a full
# outcome space has no sampling noise to overfit, which is why no held-out seed
# is needed. It still means A is not exchangeable with the other seven, and the
# report says so wherever A's numbers appear.
IN_SAMPLE_OPTIMUM = "A-model"


def hit_count_distributions(
    seeds: list[str],
    prob,
    cross_feed: bool,
    cards: list[dict],
) -> dict[str, dict[int, float]]:
    """`card id -> {hit count: probability}`, exact, over all 2**14 leaves.

    One walk serves every card: the leaves are the same for all of them and
    re-enumerating per card would be eight times the work for identical
    numbers. Every score in `range(15)` is present so downstream tail sums are
    complete by construction rather than through a lookup default.
    """
    picks = [(entry["id"], entry["picks"]) for entry in cards]
    tables: dict[str, collections.defaultdict[int, float]] = {
        card_id: collections.defaultdict(float) for card_id, _ in picks
    }
    for winners, weight in weighted_brackets(seeds, prob, cross_feed):
        for card_id, card in picks:
            hits = sum(1 for slot in SLOTS if card[slot] == winners[slot])
            tables[card_id][hits] += weight
    return {
        card_id: {score: table.get(score, 0.0) for score in range(len(SLOTS) + 1)}
        for card_id, table in tables.items()
    }


def moments(table: dict[int, float]) -> tuple[float, float]:
    """`(mean, standard deviation)` of a hit-count distribution."""
    mean = math.fsum(score * p for score, p in table.items())
    variance = math.fsum(p * (score - mean) ** 2 for score, p in table.items())
    return mean, math.sqrt(variance)


def three_terms(table: dict[int, float], observed: int) -> tuple[float, float, float]:
    """`P(S < s)`, `P(S = s)`, `P(S > s)` -- reported separately, as registered.

    For a discrete `S` the cumulative tails `P(S <= s)` and `P(S >= s)` are not
    complements. Deriving both from these three terms is the only way to quote
    either without the off-by-one that treating them as complements produces.
    """
    below = math.fsum(p for score, p in table.items() if score < observed)
    at = table[observed]
    above = math.fsum(p for score, p in table.items() if score > observed)
    return below, at, above


def coin_reference(seeds: list[str], cross_feed: bool) -> dict[str, dict[str, float]]:
    """The reference forecast: the fair coin's slot marginals.

    Uniform over the teams that can reach each slot -- the same fact that makes
    the registered 3.75 null equal to the outcome-conditional mean, asserted on
    every `cli_playoff_score` run. Being uniform is what makes this reference
    STRUCTURAL: its proper scores depend on the topology and the seeding only,
    never on who won. A reference that moved with the outcome would be a moving
    target a skill score could be improved against by luck.
    """
    return slot_distributions(seeds, lambda a, b, best_of: 0.5, cross_feed)


def assert_reproduces_frozen(card_id: str, stated: float, mean: float, marginal: float) -> None:
    """Refuse to report on a distribution that is not the frozen one.

    `mean` comes from enumerating hit counts; `marginal` from summing the slot
    probabilities the card bet on. Both must equal the literal frozen before the
    event: the first proves the enumeration is right, the second proves the
    refitted strengths are the ones the card was solved from. A distribution
    failing either is not the pre-event distribution and every tail derived from
    it would describe a different model, so this raises rather than warning.
    """
    drift = max(abs(mean - stated), abs(marginal - stated))
    if drift > TOLERANCE:
        raise PlayoffCardError(
            f"{card_id}: frozen literal {stated} but the enumeration gives {mean:.6f} "
            f"and the slot marginals give {marginal:.6f}; this is not the distribution "
            "the card was frozen under, so nothing is reported"
        )


def slot_scores(
    forecast: dict[str, dict[str, float]],
    outcome: dict[str, str],
    teams: list[str],
) -> tuple[float, float]:
    """`(multiclass Brier, log loss in nats)` of stated slot marginals.

    Subjects are the 14 slots and categories are the 8 teams. A team that
    cannot reach a slot simply carries no mass there, which is a forecast of
    zero and is scored as one.
    """
    rows = {slot: dict(forecast[slot]) for slot in SLOTS}
    return (
        multiclass_brier(rows, outcome, teams),
        multiclass_log_loss(rows, outcome, teams),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Playoff card postmortem (diagnostic)")
    parser.add_argument("--store", required=True)
    parser.add_argument("--cards", default="data/ti2026_playoff_cards.yaml")
    parser.add_argument("--outcome", default="data/ti2026_playoff_outcome.yaml")
    parser.add_argument("--teams", default="config/ti2026_teams.yaml")
    parser.add_argument("--aliases", default="config/team_aliases.yaml")
    parser.add_argument("--gate-config", default="config/d2_gate.yaml")
    parser.add_argument("--min-train", type=int, default=500)
    args = parser.parse_args(argv)

    frozen = yaml.safe_load(Path(args.cards).read_text())
    seeds = list(frozen["seeds"])
    cross_feed = frozen["topology"] == "cross-feed"
    cards = frozen["cards"]
    outcome = load_outcome(Path(args.outcome))
    coherent_picks(outcome, seeds, cross_feed)

    strengths = fit_strengths(
        args.store, args.teams, args.aliases, args.gate_config, args.min_train
    )

    def prob(a: str, b: str, best_of: int) -> float:
        return series_win_prob(map_win_prob(strengths[a], strengths[b]), best_of)

    dist = slot_distributions(seeds, prob, cross_feed)
    tables = hit_count_distributions(seeds, prob, cross_feed, cards)

    # PRECONDITION, as registered: a distribution whose mean does not reproduce
    # the frozen literal is not the pre-event distribution, and every tail from
    # it would describe a different model. Checked for every card BEFORE
    # anything is printed, so a failure reports nothing rather than reporting
    # numbers with a warning attached. There is no fallback.
    rows = []
    for entry in cards:
        card_id, picks = entry["id"], entry["picks"]
        coherent_picks(picks, seeds, cross_feed)
        mean, sd = moments(tables[card_id])
        stated = entry["model_implied_expected"]
        marginal = math.fsum(dist[slot][picks[slot]] for slot in SLOTS)
        assert_reproduces_frozen(card_id, stated, mean, marginal)
        observed = sum(1 for slot in SLOTS if picks[slot] == outcome[slot])
        below, at, above = three_terms(tables[card_id], observed)
        rows.append((card_id, entry["role"], stated, mean, sd, observed, below, at, above))

    coin = coin_reference(seeds, cross_feed)
    bs_model, ll_model = slot_scores(dist, outcome, seeds)
    bs_coin, ll_coin = slot_scores(coin, outcome, seeds)

    print("# TI 2026 playoff card postmortem")
    print()
    print("**DIAGNOSTIC.** It gates nothing and alters no card. Registered in")
    print("`docs/superpowers/specs/2026-08-23-playoff-card-postmortem.md`, merged before")
    print("this producer existed and before any number below had been computed.")
    print()
    print(
        "Exact over all 2**14 coherent brackets. No seed, no Monte Carlo error: the leaves "
        "carry structure and probability on the same walk, so there is no generator whose "
        "stream would have to be pinned and no replicate count to report."
    )
    print()
    print(f"Store: `{args.store}`. Cards: `{args.cards}`. Outcome: `{args.outcome}`.")
    print(f"Topology **{frozen['topology']}**, read from the cards file.")
    print()

    print("## 1. Hit-count distribution under the model's own probabilities")
    print()
    print("| card | role | E[S] frozen | E[S] enumerated | SD[S] | realised | P(S<s) | P(S=s) | P(S>s) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for card_id, role, stated, mean, sd, observed, below, at, above in rows:
        mark = "**" if role == "headline" else ""
        print(
            f"| {mark}{card_id}{mark} | {role} | {stated:.4f} | {mean:.4f} | {sd:.4f} "
            f"| {mark}{observed}/{len(SLOTS)}{mark} | {below:.6f} | {at:.6f} | {above:.6f} |"
        )
    print()
    print(
        "`P(S < s)`, `P(S = s)` and `P(S > s)` are reported separately because for a discrete "
        "`S` the cumulative tails are **not** complements. Derive either from these three; do "
        "not treat one as the other's complement."
    )
    print()
    print(f"`{IN_SAMPLE_OPTIMUM}` is the exact argmax of `E[S]` over all 16384 coherent")
    print("brackets, so its distribution is the most favourable available and is not")
    print("exchangeable with the other seven.")
    print()

    print("## Full distributions")
    print()
    header = " | ".join(str(score) for score in range(len(SLOTS) + 1))
    print(f"| card | {header} |")
    print("|---" * (len(SLOTS) + 2) + "|")
    for card_id, *_rest in rows:
        cells = " | ".join(f"{tables[card_id][score]:.4f}" for score in range(len(SLOTS) + 1))
        print(f"| {card_id} | {cells} |")
    print()
    print(
        "Printed in full so no single tail can be quoted without its distribution visible "
        "beside it."
    )
    print()

    print("## 2. Per-slot proper scores, model against the coin")
    print()
    print("| forecast | Brier (unscaled sum) | log loss (nats) |")
    print("|---|---|---|")
    print(f"| model slot marginals | {bs_model:.6f} | {ll_model:.6f} |")
    print(f"| coin slot marginals (reference) | {bs_coin:.6f} | {ll_coin:.6f} |")
    print()
    print(f"`BSS = {brier_skill_score(bs_model, bs_coin):+.6f}`, ", end="")
    print(f"`dLL = {ll_coin - ll_model:+.6f}` nats (positive favours the model).")
    print()
    print(
        "Brier here is the UNSCALED sum form, twice `backtest.brier`'s binary convention. "
        "The two are on different scales and must never be compared. The reference is "
        "structural: it depends on the topology and the seeding, not on who won."
    )
    print()
    print(
        "This scores the 14 stated slot MARGINALS and says nothing about the joint "
        "distribution over brackets. The slots are DEPENDENT -- not 14 independent "
        "observations -- so no standard error over slots is reported."
    )
    print()

    print("## What these numbers do not license")
    print()
    print(
        "Neither family establishes predictive skill, alone or together. The no-skill "
        "question was already answered against the coin by `cli_playoff_score`; the "
        "probabilities here are against the model's own distribution, so adding them to "
        "that result would count one event twice."
    )
    print()
    print(
        "A small `P(S > s)` admits two readings this event cannot separate: the model was "
        "underconfident and understated a card it had got right, or the outcome was a "
        "favourable draw from a correctly-specified distribution. Both were registered in "
        "advance and neither may be presented as the finding."
    )
    print()
    print(
        "The group card expected 4.5879 and realised 5; this card expected 4.3615 and "
        "realised 11. That pair is not two independent measurements -- same model, same "
        "store, overlapping teams, and the group results are inputs to these strengths. No "
        "composite statistic over the two is registered."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
