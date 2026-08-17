"""What the shipped TI 2026 group card's own model implied, after the fact.

Registered in `docs/superpowers/specs/2026-08-16-group-card-postmortem.md`
before this producer existed.

DIAGNOSTIC. It gates nothing, alters no card, and may not be cited as grounds
to change the pending playoff slate. The card it scores was submitted days
before this file was written.

It exists because the shipped card's `optimizer_marginal_objective` (4.5903) is
the sum the optimizer MAXIMISED over its own draws -- the card's own note says
it "is NOT the evaluation-simulation mean score" -- so nobody has ever computed
what the model actually expected to score. Without that, 5/16 can only be
compared to the random null, which answers "was this better than chance" and
not "was this the sort of run the model itself anticipated".

It reads no store and fits nothing. Every input is a frozen artifact, and the
simulation configuration is read back out of the shipped card's own metadata
rather than re-chosen here.
"""

import argparse
import collections
import csv
import json
import math
import sys
from pathlib import Path

import yaml

from ti26.montecarlo import card_score_distribution, monte_carlo_stderr
from ti26.proper_scores import (
    brier_skill_score,
    capacity_marginal_reference,
    expected_hits,
    multiclass_brier,
    multiclass_log_loss,
)
from ti26.rules import load_rules

# The card's six categories, in the order the frozen marginals CSV writes them.
CATEGORIES: tuple[str, ...] = ("4-0", "4-1", "elim_win", "elim_loss", "1-4", "0-4")

# Registered in the spec before this producer existed. `cli_d4` chose 90001
# against card seed 1 long before TI 2026 was played.
EVAL_SEED = 90001


class PostmortemError(RuntimeError):
    """An input that would make the numbers mean something other than they say."""


def read_marginals(path: Path) -> dict[str, dict[str, float]]:
    """`team -> {category -> probability}` from the frozen marginals CSV."""
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise PostmortemError(f"{path} holds no marginals")
    out = {}
    for row in rows:
        team = row["team"]
        out[team] = {category: float(row[category]) for category in CATEGORIES}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TI 2026 group card postmortem (diagnostic)")
    parser.add_argument("--card", default="reports/card_ti2026_rules/recommended_card.json")
    parser.add_argument("--marginals", default="reports/card_ti2026_rules/category_probabilities.csv")
    parser.add_argument(
        "--strengths", default="reports/card_ti2026_rules/strengths_calibrated.csv"
    )
    parser.add_argument("--rules", default="config/ti2026_rules.yaml")
    parser.add_argument("--outcome", default="data/ti2026_outcome.yaml")
    parser.add_argument("--eval-seed", type=int, default=EVAL_SEED)
    args = parser.parse_args(argv)

    card_blob = json.loads(Path(args.card).read_text())
    card = card_blob["assignments"]
    card_seed = card_blob["seed"]
    n_sims = card_blob["n_sims"]

    # The registered failure this guards: scoring the card against the very
    # draws it was solved on rewards it for the noise it was fitted to, and
    # inflates every number below. The spec forbids it; this refuses it.
    if args.eval_seed == card_seed:
        raise PostmortemError(
            f"eval seed {args.eval_seed} equals the card's own seed: the card was chosen to "
            "maximise its score on those draws, so scoring it against them measures the fit, "
            "not the forecast"
        )

    frozen = yaml.safe_load(Path(args.outcome).read_text())
    actual = frozen["categories"]
    rules = load_rules(args.rules)
    marginals = read_marginals(Path(args.marginals))

    with Path(args.strengths).open(newline="") as handle:
        strength_rows = list(csv.DictReader(handle))
    strengths = {row["team"]: float(row["strength"]) for row in strength_rows}
    team_ids = {row["team"]: row["team_id"] for row in strength_rows}

    observed = sum(1 for team, category in card.items() if actual.get(team) == category)
    capacities = collections.Counter(actual.values())
    reference = capacity_marginal_reference(capacities, sorted(actual))

    dist = card_score_distribution(
        card, strengths, rules, n_sims=n_sims, seed=args.eval_seed, team_ids=team_ids
    )
    total = sum(dist.values())
    mean = math.fsum(score * count for score, count in dist.items()) / total
    variance = math.fsum(count * (score - mean) ** 2 for score, count in dist.items()) / total

    def share(predicate) -> tuple[float, float]:
        hits = sum(count for score, count in dist.items() if predicate(score))
        p = hits / total
        return p, monte_carlo_stderr(p, total)

    below, below_se = share(lambda s: s < observed)
    equal, equal_se = share(lambda s: s == observed)
    above, above_se = share(lambda s: s > observed)

    bs_model = multiclass_brier(marginals, actual, CATEGORIES)
    bs_ref = multiclass_brier(reference, actual, CATEGORIES)
    ll_model = multiclass_log_loss(marginals, actual, CATEGORIES)
    ll_ref = multiclass_log_loss(reference, actual, CATEGORIES)

    print("# TI 2026 group card postmortem")
    print()
    print("**DIAGNOSTIC -- gates nothing, alters no card. The card it scores was already")
    print("submitted, and nothing here may be used to change the pending playoff slate.**")
    print()
    print(f"Card: `{args.card}`, observed score **{observed}/{len(actual)}**.")
    print(
        f"Evaluation: {total} simulations at eval seed **{args.eval_seed}**, "
        f"card seed {card_seed} (they must differ, and the producer refuses if they do not)."
    )
    print(
        f"RNG: `random.Random(seed * 1_000_003 + i)` per replicate -- CPython "
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} "
        "Mersenne Twister. numpy is not on this path."
    )
    print()

    print("## What the model expected of itself")
    print()
    print(
        f"`E_model[S]` = **{mean:.4f}** +/- {math.sqrt(variance / total):.4f} "
        "(MC standard error), against the registered random-card mean of 3.75."
    )
    print()
    print("| tail | P | MC SE |")
    print("|---|---|---|")
    print(f"| `P_model(S < {observed})` | {below:.4f} | {below_se:.4f} |")
    print(f"| `P_model(S = {observed})` | {equal:.4f} | {equal_se:.4f} |")
    print(f"| `P_model(S > {observed})` | {above:.4f} | {above_se:.4f} |")
    print()
    print(
        f"Derived: `P_model(S <= {observed})` = {below + equal:.4f}, "
        f"`P_model(S >= {observed})` = {equal + above:.4f}. These are **not** complements."
    )
    print()
    print(
        "This family is an INTERNAL CONSISTENCY diagnostic. It asks how surprising "
        f"{observed} is to the model that produced the card, using that model's own "
        "probabilities. If the model is misspecified its own distribution is a poor judge "
        "of its own error, so this measures no skill and must not be reported as if it did."
    )
    print()

    print("## Realized proper-score comparison against the registered reference")
    print()
    print(
        "Reference `q = capacity / 16` -- the team-level MARGINAL induced by the "
        "preregistered capacity-constrained null, not that null's joint distribution. "
        "It reproduces the null's expected hit count exactly: "
        f"**{expected_hits(reference, card):.4f}**."
    )
    print()
    print("| score | model | reference | comparison |")
    print("|---|---|---|---|")
    print(
        f"| multiclass Brier (unscaled) | {bs_model:.6f} | {bs_ref:.6f} | "
        f"BSS **{brier_skill_score(bs_model, bs_ref):+.4f}** |"
    )
    print(
        f"| multiclass log loss (nats) | {ll_model:.6f} | {ll_ref:.6f} | "
        f"dLL **{ll_ref - ll_model:+.4f}** |"
    )
    print()
    print(
        "Brier here is the unscaled sum form `mean_i sum_k (p_ik - y_ik)^2`. "
        "`backtest.brier` is the BINARY `mean((p - y)^2)`, exactly half this for two "
        "classes; the two are on different scales and may not be compared."
    )
    print()
    print(
        "A positive BSS licenses one sentence -- the model achieved a better realized "
        "Brier score than the reference on TI 2026 -- and not 'predictive skill "
        "demonstrated'. Skill is a property of expected repeated out-of-sample "
        "behaviour, and one event still contains variance. The reverse is registered "
        "with equal force: a negative BSS on one event does not retire the model."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
