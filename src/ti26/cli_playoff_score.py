"""Score the eight frozen playoff cards against the actual TI 2026 result.

Registered in `docs/superpowers/specs/2026-08-17-playoff-card-comparison.md`
before any card was frozen and before any match was played. The metric, the
null, the headline pair and the roles all come from that document and from
`data/ti2026_playoff_cards.yaml`; nothing here may choose any of them.

Written after the outcome, deliberately and permissibly: the criterion was
fixed in advance, so the code that applies it cannot bend it. What this producer
must not do is invent a comparison, and the guards below enforce that -- it
reads the headline pair out of the frozen roles rather than naming it, so a
card that scored well cannot be promoted by editing this file.

The null is the registered coherent-coin null: a player obliged to submit a
coherent bracket in advance with every match a coin flip. Its exact
distribution is enumerated here over all 2**14 brackets rather than restated
from the spec's table, so the reported tail is computed by the code that prints
it.

The registered 3.75 needed checking against the tail it is quoted beside, since
one averages over outcomes and the other conditions on the one that happened.
They agree exactly, and not by luck: a fair coin makes each slot's winner
uniform over the teams that can reach it, so the registered `sum p**2` and the
conditional mean are both `sum 1/n` over slots, for ANY coherent outcome. The
producer asserts the two agree rather than assuming it.

The tail's SHAPE does depend on the outcome even though its mean cannot, so the
p-values are computed against the realised bracket and not read off a table.
"""

import argparse
import collections
from pathlib import Path

import yaml

from ti26.bracket import SLOTS, all_brackets, coherent_coin_null, slot_distributions
from ti26.cli_playoff_cards import TOLERANCE, PlayoffCardError, coherent_picks


def load_outcome(path: Path) -> dict[str, str]:
    """Realised winner per slot, with the series scores checked against it.

    A transcription that named the wrong winner while carrying the right score
    would silently move a hit from one card to another, so the two are required
    to agree rather than trusted to.
    """
    blob = yaml.safe_load(path.read_text())
    results = blob["results"]
    missing = [slot for slot in SLOTS if slot not in results]
    if missing:
        raise PlayoffCardError(f"outcome is missing slots: {missing}")
    winners = {}
    for slot in SLOTS:
        entry = results[slot]
        matchup, score, winner = entry["matchup"], entry["score"], entry["winner"]
        if winner not in matchup:
            raise PlayoffCardError(f"{slot}: winner {winner!r} is not in {matchup}")
        if score[0] == score[1]:
            raise PlayoffCardError(f"{slot}: series score {score} has no winner")
        implied = matchup[0] if score[0] > score[1] else matchup[1]
        if implied != winner:
            raise PlayoffCardError(
                f"{slot}: score {score} on {matchup} implies {implied}, not {winner}"
            )
        winners[slot] = winner
    return winners


def exact_null_tail(seeds: list[str], cross_feed: bool, outcome: dict[str, str]) -> dict[int, float]:
    """`score -> P(a random coherent bracket scores exactly that)`, for every score 0..14.

    Enumerated over all 2**14 coherent brackets against the ONE realised
    outcome. The null is the registered one -- a pre-committed coin-flipping
    player, not a per-match oracle -- but this distribution is conditional on
    the realised outcome, so its mean is not the registered 3.75.

    The mapping is total over `range(15)` rather than built from the counter's
    keys. Against the realised bracket all fifteen scores are in fact reachable,
    so this is a totality guarantee and not a correction: it makes the `>= s`
    sums below complete by construction, so `P(X >= 0)` is 1 and the top score's
    tail is its own probability, with no lookup default to absorb a gap.
    """
    counts: collections.Counter[int] = collections.Counter()
    brackets = all_brackets(seeds, cross_feed)
    for bracket in brackets:
        counts[sum(1 for slot in SLOTS if bracket[slot] == outcome[slot])] += 1
    total = len(brackets)
    return {score: counts[score] / total for score in range(len(SLOTS) + 1)}


def tail_at_least(tail: dict[int, float]) -> dict[int, float]:
    """`score -> P(a random coherent bracket scores at least that)`.

    Inclusive of the score itself: `P(X >= s)`, not `P(X > s)`. The exclusive
    form is the same arithmetic one step to the left and would report every
    card as more significant than it is.
    """
    return {s: sum(p for k, p in tail.items() if k >= s) for s in tail}


def conditional_null_mean(seeds: list[str], cross_feed: bool, outcome: dict[str, str]) -> float:
    """Expected hits of a random coherent bracket against THIS outcome.

    Computed from the coin's slot marginals rather than from the enumeration in
    `exact_null_tail`, so the two paths cross-check each other in `main`. Under
    a fair coin this equals the registered null for every coherent outcome,
    because each slot's winner is uniform over the teams that can reach it. The
    equality is asserted, not assumed -- it is what licenses quoting 3.75 next
    to a tail conditioned on one bracket.
    """
    dist = slot_distributions(seeds, lambda a, b, best_of: 0.5, cross_feed)
    return sum(dist[slot][outcome[slot]] for slot in SLOTS)


def hit_counts(cards: list[dict], outcome: dict[str, str]) -> dict[str, int]:
    """`card id -> slots where the card's pick is the realised winner`."""
    return {
        entry["id"]: sum(1 for slot in SLOTS if entry["picks"][slot] == outcome[slot])
        for entry in cards
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score the frozen playoff cards (diagnostic)")
    parser.add_argument("--cards", default="data/ti2026_playoff_cards.yaml")
    parser.add_argument("--outcome", default="data/ti2026_playoff_outcome.yaml")
    args = parser.parse_args(argv)

    frozen = yaml.safe_load(Path(args.cards).read_text())
    seeds = list(frozen["seeds"])
    outcome = load_outcome(Path(args.outcome))
    cross_feed = frozen["topology"] == "cross-feed"

    # The realised bracket must itself be coherent under the registered
    # topology. If it is not, the topology was wrong and every null in this
    # report is computed over the wrong space.
    coherent_picks(outcome, seeds, cross_feed)

    null_mean = coherent_coin_null(seeds, cross_feed)
    registered = frozen["null_expected_hits"]
    if abs(null_mean - registered) > TOLERANCE:
        raise PlayoffCardError(
            f"the registered null is {registered} but this topology gives {null_mean:.6f}; "
            "the cards were scored against a different bracket than they were frozen under"
        )

    tail = exact_null_tail(seeds, cross_feed, outcome)
    at_least = tail_at_least(tail)
    conditional = conditional_null_mean(seeds, cross_feed, outcome)
    from_tail = sum(score * p for score, p in tail.items())
    if max(abs(from_tail - conditional), abs(conditional - null_mean)) > 1e-9:
        raise PlayoffCardError(
            f"the enumerated tail has mean {from_tail:.9f}, the coin's slot marginals give "
            f"{conditional:.9f} and the registered null is {null_mean:.9f}; these must be one "
            "number and are not"
        )

    scored = []
    for entry in frozen["cards"]:
        # A card that is not coherent under this topology cannot be scored: the
        # hit count would absorb an unreachable pick as an ordinary miss.
        coherent_picks(entry["picks"], seeds, cross_feed)
        hits = hit_counts([entry], outcome)[entry["id"]]
        scored.append((entry["id"], entry["role"], hits, entry["model_implied_expected"]))

    headline = sorted(e["id"] for e in frozen["cards"] if e["role"] == "headline")
    if len(headline) != 2:
        raise PlayoffCardError(f"the frozen roles name {len(headline)} headline cards, not 2")

    print("# TI 2026 playoff cards, scored")
    print()
    print("**DIAGNOSTIC. Every card, the metric, the null and the headline pair were frozen")
    print("before the first match. Nothing here may alter any of them.**")
    print()
    print(
        f"Champion: **{outcome['Grand Final']}**. Registered null mean: "
        f"**{null_mean:.4f}** / {len(SLOTS)}."
    )
    print()
    print(f"Headline, designated in advance: **{headline[0]} vs {headline[1]}**.")
    print()
    print("| card | role | score | model-implied E | P(random >= score) |")
    print("|---|---|---|---|---|")
    for card_id, role, hits, expected in sorted(scored, key=lambda row: -row[2]):
        mark = "**" if role == "headline" else ""
        print(
            f"| {mark}{card_id}{mark} | {role} | {mark}{hits}/{len(SLOTS)}{mark} "
            f"| {expected:.4f} | {at_least[hits]:.4f} |"
        )
    print()

    print("## Exact null distribution against this outcome")
    print()
    print(
        f"Conditional on the realised bracket a coin-flipping entrant expects "
        f"**{conditional:.4f}**, which is the registered **{null_mean:.4f}** exactly: a fair coin "
        "leaves each slot's winner uniform over the teams that can reach it, so conditioning on "
        "the outcome cannot move the mean. It does move the shape, which is why the tail below "
        "is enumerated against this outcome rather than quoted from the registration."
    )
    print()
    # All fifteen rows, including the ones that round to zero at four decimals.
    # Truncating the head of the distribution is what makes an extreme score
    # look like the edge of the table rather than the tail of one.
    total = 2 ** len(SLOTS)
    print(f"| score | count / {total} | P(exactly) | P(at least) |")
    print("|---|---|---|---|")
    for score in sorted(tail, reverse=True):
        print(
            f"| {score} | {round(tail[score] * total)} | {tail[score]:.6f} "
            f"| {at_least[score]:.6f} |"
        )
    print()

    by_id = {row[0]: row for row in scored}
    if {"A-model", "C-override-liquid", "H-owner-final"} <= set(by_id):
        a, c, h = (by_id[k][2] for k in ("A-model", "C-override-liquid", "H-owner-final"))
        print("## Attribution, as registered")
        print()
        print("```")
        print(f"A model            {a}/14")
        print(f"C + Liquid only    {c}/14")
        print(f"H owner submitted  {h}/14")
        print("```")
        print()

    submitted = frozen["owner_probabilities"]["card_actually_submitted"]
    entry = next(e for e in frozen["cards"] if e["id"] == submitted)
    flipped = entry.get("coin_flipped_slots") or []
    if flipped:
        won = [s for s in flipped if entry["picks"][s] == outcome[s]]
        print(
            f"Of the submitted card's {len(flipped)} coin-flipped slots "
            f"({', '.join(flipped)}), the coin landed correctly on **{len(won)}**. "
            "Those slots carry no judgement either way, and the list is a lower bound "
            f"(`coin_flipped_slots_complete: {entry.get('coin_flipped_slots_complete')}`)."
        )
        print()
    print(
        "One event. A score above the null does not establish predictive skill and a score "
        "below it does not retire a model, exactly as registered before any of this was known."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
