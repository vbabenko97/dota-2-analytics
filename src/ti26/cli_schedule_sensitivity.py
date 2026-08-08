"""How much does the pairing rule actually move the card?

`cli_pairing_check` established that the engine's within-bucket pairing
preference does not reproduce TI 2025's real pairings: it matched 4 of the 11
buckets where it had a choice, which is about what indifference gives. That
tells you the rule is wrong. It does not tell you whether being wrong costs
anything, and the spec's `schedule_sensitivity.csv` deliverable -- which was
supposed to answer exactly that -- was never built.

This builds it. The method is a signal-to-noise comparison, because an absolute
difference in a category probability means nothing on its own:

  NOISE  -- re-run the shipping rule under different simulation seeds. Whatever
            the marginals move by is what Monte Carlo sampling alone does.
  SIGNAL -- re-run under a different pairing rule at a fixed seed. Whatever the
            marginals move by is what the rule choice does.

If signal sits inside noise, the pairing rule is not worth arguing about and
`cli_pairing_check`'s negative result is harmless. If signal exceeds noise, the
published marginals depend on a rule that demonstrably does not match reality,
and the card inherits that.

The variants deliberately include "random", which ignores ranking distance
altogether. That is the no-information floor: if the shipping rule cannot be
distinguished from ignoring the criterion entirely, the criterion is decorative.

Group and repeat constraints hold under every variant, because those ARE
corroborated by TI 2025 -- only the distance preference is in question.

DIAGNOSTIC. No threshold, gates nothing, cannot alter the shipping card.
"""

import argparse
import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from ti26.montecarlo import category_marginals, monte_carlo_stderr
from ti26.optimize import solve_card
from ti26.rules import Rules, load_rules
from ti26.types import Category

VARIANTS = ("random", "min", "max", "fold")

# TI 2026's elimination round is a sequential choice whose BASIS the rules do
# not state, so unlike the pairing preference there is no "shipping rule" to
# compare against -- only three assumptions, one of which has to be chosen.
# Measuring all three is what makes that choice evidence-led rather than a
# guess dressed as a default.
ELIMINATION_POLICIES = ("rational", "noisy", "random")


def load_strengths(path: str) -> tuple[dict[str, float], dict[str, str]]:
    with Path(path).open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    missing = {"team", "team_id", "strength"} - set(rows[0] if rows else {})
    if missing:
        raise SystemExit(f"{path} is missing column(s): {sorted(missing)}")
    return (
        {r["team"]: float(r["strength"]) for r in rows},
        {r["team"]: str(r["team_id"]) for r in rows},
    )


def spread(
    a: Mapping[str, Mapping[Category, float]], b: Mapping[str, Mapping[Category, float]]
) -> dict[str, float]:
    """Absolute marginal differences between two probability tables."""
    deltas = [abs(a[t][c] - b[t][c]) for t in a for c in Category]
    return {
        "max_abs_delta": max(deltas),
        "mean_abs_delta": sum(deltas) / len(deltas),
    }


def _card(
    marginals: Mapping[str, Mapping[Category, float]],
    rules: Rules,
    n_sims: int,
    team_ids: Mapping[str, str],
) -> tuple[dict[str, str], float]:
    card, objective = solve_card(
        marginals,
        rules.category_capacities,
        tie_tolerance=monte_carlo_stderr(0.5, n_sims),
        team_ids=team_ids,
    )
    return {t: c.value for t, c in card.items()}, objective


def run(
    strengths_path: str,
    rules_path: str,
    n_sims: int,
    seeds: Sequence[int],
) -> dict:
    strengths, team_ids = load_strengths(strengths_path)
    rules = load_rules(rules_path)

    baselines = {
        seed: category_marginals(strengths, rules, n_sims=n_sims, seed=seed, team_ids=team_ids)
        for seed in seeds
    }
    reference_seed = seeds[0]
    reference = baselines[reference_seed]
    reference_card, reference_objective = _card(reference, rules, n_sims, team_ids)

    noise = []
    for seed in seeds[1:]:
        card, objective = _card(baselines[seed], rules, n_sims, team_ids)
        noise.append(
            {
                "seed": seed,
                **spread(reference, baselines[seed]),
                "assignments_changed": sum(
                    1 for t in reference_card if reference_card[t] != card[t]
                ),
                "objective": round(objective, 4),
            }
        )

    signal = []
    for preference in VARIANTS:
        marginals = category_marginals(
            strengths,
            rules,
            n_sims=n_sims,
            seed=reference_seed,
            team_ids=team_ids,
            pairing_preference=preference,
        )
        card, objective = _card(marginals, rules, n_sims, team_ids)
        signal.append(
            {
                "preference": preference,
                **spread(reference, marginals),
                "assignments_changed": sum(
                    1 for t in reference_card if reference_card[t] != card[t]
                ),
                "objective": round(objective, 4),
                "changed_teams": sorted(
                    t for t in reference_card if reference_card[t] != card[t]
                ),
            }
        )

    # The elimination CHOICE policy, measured the same way and reported
    # separately. It is a different kind of uncertainty from the pairing
    # preference: the pairing rule is published and we are asking whether our
    # reading of it matters, whereas TI 2026 publishes no basis for the choice
    # at all, so every policy here is an assumption and one of them has to ship.
    policies = []
    for policy in ELIMINATION_POLICIES:
        marginals = category_marginals(
            strengths,
            rules,
            n_sims=n_sims,
            seed=reference_seed,
            team_ids=team_ids,
            elimination_policy=policy,
        )
        card, objective = _card(marginals, rules, n_sims, team_ids)
        policies.append(
            {
                "policy": policy,
                "is_configured": policy == rules.elimination_choice_policy,
                **spread(reference, marginals),
                "assignments_changed": sum(
                    1 for t in reference_card if reference_card[t] != card[t]
                ),
                "objective": round(objective, 4),
                "changed_teams": sorted(
                    t for t in reference_card if reference_card[t] != card[t]
                ),
            }
        )

    worst_noise = max((n["max_abs_delta"] for n in noise), default=0.0)
    worst_signal = max(s["max_abs_delta"] for s in signal)
    worst_policy = max(p["max_abs_delta"] for p in policies)
    return {
        "status": "DIAGNOSTIC -- no threshold, gates nothing, cannot alter the card",
        "n_sims": n_sims,
        "seeds": list(seeds),
        "reference_seed": reference_seed,
        "reference_objective": round(reference_objective, 4),
        "reference_card": reference_card,
        "configured_elimination_policy": rules.elimination_choice_policy,
        "single_marginal_stderr": monte_carlo_stderr(0.5, n_sims),
        "noise_reruns_of_the_shipping_rule": noise,
        "signal_alternative_pairing_rules": signal,
        "signal_alternative_elimination_policies": policies,
        "worst_noise_max_abs_delta": worst_noise,
        "worst_signal_max_abs_delta": worst_signal,
        "worst_elimination_policy_max_abs_delta": worst_policy,
        "signal_to_noise": (worst_signal / worst_noise) if worst_noise else None,
        "elimination_policy_signal_to_noise": (
            (worst_policy / worst_noise) if worst_noise else None
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Schedule sensitivity of the card")
    parser.add_argument("--strengths", required=True)
    parser.add_argument("--rules", default="config/ti2026_rules.yaml")
    parser.add_argument("--sims", type=int, default=250000)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    if len(seeds) < 2:
        raise SystemExit("need at least two seeds: one reference and one to measure noise")
    payload = run(args.strengths, args.rules, args.sims, seeds)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "schedule_sensitivity.json").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
