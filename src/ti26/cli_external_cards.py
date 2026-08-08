"""Score expert cards published before TI 2025 against the frozen truth.

Every other benchmark here is internal. D4 compares the pipeline to a random
card and to a strength sort; the seed sweep compares it to itself. None of them
answers the prior question: **is a sixteen-slot card a measurable task at all?**

An expert card answers it, because it is the strongest realistic attempt
available. It was published in advance by someone with a rating model and domain
knowledge this project does not have, and it costs nothing to score. If such a
card also lands inside the random distribution, then a single card cannot
separate skill from luck for anyone, and a pipeline that fails to beat a
strength sort on one event is not evidence of a weak pipeline -- it is evidence
of an underpowered measurement.

THE NULL IS COMPUTED EXACTLY, not sampled. A random card here is a uniformly
random arrangement of the six category labels at their fixed capacities, and the
distribution of its hit count depends only on those capacities -- so it has a
closed form and needs no seed. Sampling it would make this report's numbers
depend on an RNG stream for no reason, and a diagnostic whose output moves when
nothing moved is a diagnostic people learn to ignore.

The exact distribution also carries its own check: the mean of the hit count is
forced to sum(c^2)/n over the capacities, which for this card's 1/2/5/5/2/1 is
exactly 3.75 -- the random baseline quoted everywhere else in this project. If
the computation below did not reproduce that, it would be wrong.

DIAGNOSTIC. No threshold, gates nothing, cannot alter the shipping card.
"""

import argparse
import json
from collections import Counter
from fractions import Fraction
from math import comb, factorial
from pathlib import Path

import yaml

SCHEMA = "ti26.external-cards.v1"
STATUS = "DIAGNOSTIC -- no threshold, gates nothing, cannot alter the card"


class ExternalCardError(ValueError):
    """A published card cannot be scored as written."""


def load_truth(path: str | Path) -> dict[str, str]:
    payload = yaml.safe_load(Path(path).read_text())
    return {team["name"]: team["category"] for team in payload["teams"]}


def resolve(card: dict, truth: dict[str, str]) -> dict[str, str]:
    """Map a card's own team names onto the truth file's labels.

    External cards use the names the orgs carried at the time; the truth file
    uses OpenDota's current ones. The alias map is checked for completeness in
    both directions -- an unused alias means the card was edited without its
    map, and an unmapped name means the reverse.
    """
    aliases = card.get("aliases", {}) or {}
    unused = set(aliases) - set(card["assignments"])
    if unused:
        raise ExternalCardError(f"{card['id']}: aliases for teams not on the card: {sorted(unused)}")

    resolved: dict[str, str] = {}
    for name, category in card["assignments"].items():
        target = aliases.get(name, name)
        if target not in truth:
            raise ExternalCardError(
                f"{card['id']}: '{name}' resolves to '{target}', which is not in the truth file"
            )
        if target in resolved:
            raise ExternalCardError(f"{card['id']}: '{target}' appears twice after aliasing")
        resolved[target] = category
    return resolved


def check_capacities(resolved: dict[str, str], truth: dict[str, str], card_id: str) -> None:
    """A card that does not respect the capacities is not the same task.

    The compendium fixes how many teams may go in each category. A card with
    three teams in `4-0` is not a better or worse forecast, it is an unplayable
    one, and scoring it against a null built from the real capacities would
    compare two different games.
    """
    if set(resolved) != set(truth):
        missing = sorted(set(truth) - set(resolved))
        extra = sorted(set(resolved) - set(truth))
        raise ExternalCardError(
            f"{card_id}: card covers a different field (missing {missing}, unexpected {extra})"
        )
    want, got = Counter(truth.values()), Counter(resolved.values())
    if want != got:
        raise ExternalCardError(
            f"{card_id}: category counts {dict(sorted(got.items()))} do not match the "
            f"format's capacities {dict(sorted(want.items()))}"
        )


def exact_null_distribution(capacities: list[int]) -> list[Fraction]:
    """P(hits = k) for a uniformly random card, exactly, for k = 0..n.

    A random card is a uniformly random arrangement of the category multiset.
    Counting arrangements with exactly k positions matching a fixed target is
    the classic multiset-derangement problem, solved here by inclusion-exclusion:

        A_m = (n-m)! * [t^m] prod_j sum_{i<=c_j} C(c_j, i) / (c_j - i)! * t^i

    counts arrangements with a chosen set of m forced matches, and the exact
    counts follow from sum_m A_m (x-1)^m = sum_k E_k x^k.

    Fractions throughout: the intermediate coefficients are rational even though
    every A_m and E_k is a whole number, and floating point would quietly turn a
    provable identity into an approximate one.
    """
    n = sum(capacities)

    # Per-category generating polynomial in t, coefficients as Fractions.
    poly = [Fraction(1)]
    for capacity in capacities:
        factor = [
            Fraction(comb(capacity, i), factorial(capacity - i)) for i in range(capacity + 1)
        ]
        product = [Fraction(0)] * (len(poly) + len(factor) - 1)
        for i, a in enumerate(poly):
            for j, b in enumerate(factor):
                product[i + j] += a * b
        poly = product

    a_terms = [factorial(n - m) * poly[m] if m < len(poly) else Fraction(0) for m in range(n + 1)]

    # sum_m A_m (x-1)^m -> coefficients in x.
    exact = [Fraction(0)] * (n + 1)
    for m, a_m in enumerate(a_terms):
        if not a_m:
            continue
        for k in range(m + 1):
            exact[k] += a_m * comb(m, k) * (-1) ** (m - k)

    total = sum(exact)
    return [value / total for value in exact]


def run(truth_path: str, cards_path: str) -> dict:
    truth = load_truth(truth_path)
    capacities = sorted(Counter(truth.values()).values(), reverse=True)
    null = exact_null_distribution(capacities)
    n = sum(capacities)

    mean = sum(k * float(p) for k, p in enumerate(null))
    tail = [float(sum(null[k:])) for k in range(n + 1)]

    payload_cards = []
    for card in yaml.safe_load(Path(cards_path).read_text())["cards"]:
        resolved = resolve(card, truth)
        check_capacities(resolved, truth, card["id"])
        hits = sorted(team for team in resolved if truth[team] == resolved[team])
        payload_cards.append(
            {
                "id": card["id"],
                "author": card.get("author"),
                "source": card.get("source"),
                "published": str(card.get("published")),
                "score": len(hits),
                "hits": hits,
                "p_random_at_least": tail[len(hits)],
                "per_team": [
                    {
                        "team": team,
                        "predicted": resolved[team],
                        "actual": truth[team],
                        "hit": truth[team] == resolved[team],
                    }
                    for team in sorted(resolved)
                ],
            }
        )

    return {
        "schema": SCHEMA,
        "status": STATUS,
        "truth": truth_path,
        "cards_input": cards_path,
        "null": {
            "method": "exact, by inclusion-exclusion over the category capacities",
            "capacities": capacities,
            "mean": mean,
            "pmf": [float(p) for p in null],
            "tail_at_least": tail,
        },
        "cards": payload_cards,
    }


def render_markdown(payload: dict) -> str:
    null = payload["null"]
    lines: list[str] = []
    add = lines.append

    add("# External cards, scored against TI 2025")
    add("")
    add(f"**{payload['status']}**")
    add("")
    add(
        f"Truth: `{payload['truth']}`. Null: {null['method']}, "
        f"capacities {null['capacities']}, mean **{null['mean']:.4f}**."
    )
    add("")
    add("## Scores")
    add("")
    add("| card | author | published | score | P(random card scores at least this) |")
    add("|---|---|---|---|---|")
    for card in payload["cards"]:
        add(
            f"| {card['id']} | {card['author']} | {card['published']} | "
            f"**{card['score']}/16** | {card['p_random_at_least']:.4f} |"
        )

    add("")
    add("## The null, in full")
    add("")
    add("| score | P(exactly) | P(at least) |")
    add("|---|---|---|")
    for k, p in enumerate(null["pmf"]):
        if p < 1e-6 and k > int(null["mean"]):
            continue
        add(f"| {k} | {p:.4f} | {null['tail_at_least'][k]:.4f} |")

    for card in payload["cards"]:
        add("")
        add(f"## {card['id']}")
        add("")
        add(f"Source: {card['source']}")
        add("")
        add("| team | predicted | actual | |")
        add("|---|---|---|---|")
        for row in card["per_team"]:
            add(
                f"| {row['team']} | {row['predicted']} | {row['actual']} | "
                f"{'HIT' if row['hit'] else ''} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", default="config/ti2025_backtest.yaml")
    parser.add_argument("--cards", default="config/ti2025_external_cards.yaml")
    parser.add_argument("--out", default="reports/external_cards")
    args = parser.parse_args(argv)

    payload = run(args.truth, args.cards)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "external_cards.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (out / "external_cards.md").write_text(render_markdown(payload), encoding="utf-8")
    print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
