"""What does the simulation add over sorting teams by strength?

The card is produced by fitting ratings, simulating the Swiss stage 250,000
times, and solving a capacity-constrained assignment over the resulting
marginals. The naive alternative skips all of that: sort the teams by strength,
cut the ranking into the category capacities, done. No simulation, no optimiser.

D4 already compared the two on TI 2025, where the naive ladder scored 2/16 and
the full pipeline scored 1/16. This asks the prior question on the 2026 field:
do they even DISAGREE?

Two quantities matter, and they are different questions:

  SLOT AGREEMENT   how many of the 16 assignments the two methods share.
                   Measured per seed, because the simulation's own sampling
                   noise already moves assignments.
  OBJECTIVE GAP    what the ladder card scores on the OPTIMISER'S OWN objective
                   -- the sum of simulated marginals -- against what the
                   optimiser achieved. If the gap is inside Monte Carlo
                   resolution, the optimiser found nothing the sort did not.

A high slot agreement is not proof the pipeline is worthless: both methods read
the same strengths, so agreement is expected wherever the strength ordering is
decisive. It bounds the pipeline's CONTRIBUTION, not its correctness. What would
be damning is agreement at one seed and disagreement at another, because that
makes the pipeline's departures from the ladder sampling noise rather than
information.

DIAGNOSTIC. No threshold, gates nothing, cannot alter the shipping card.
"""

import argparse
import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from ti26.montecarlo import category_marginals, monte_carlo_stderr
from ti26.optimize import naive_strength_ladder, solve_card
from ti26.rules import load_rules
from ti26.types import Category


def _value(category: object) -> str:
    return category.value if isinstance(category, Category) else str(category)


def objective_of(
    card: Mapping[str, object], marginals: Mapping[str, Mapping[Category, float]]
) -> float:
    """Sum of the model's own marginals under an arbitrary assignment."""
    lookup = {c.value: c for c in Category}
    return sum(marginals[team][lookup[_value(cat)]] for team, cat in card.items())


def run(strengths_path: str, rules_path: str, n_sims: int, seeds: Sequence[int]) -> dict:
    with Path(strengths_path).open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    missing = {"team", "team_id", "strength"} - set(rows[0] if rows else {})
    if missing:
        raise SystemExit(f"{strengths_path} is missing column(s): {sorted(missing)}")
    strengths = {r["team"]: float(r["strength"]) for r in rows}
    team_ids = {r["team"]: str(r["team_id"]) for r in rows}
    rules = load_rules(rules_path)

    ladder = {
        team: _value(cat)
        for team, cat in naive_strength_ladder(
            strengths, rules.category_capacities, team_ids=team_ids
        ).items()
    }

    per_seed = []
    for seed in seeds:
        marginals = category_marginals(
            strengths, rules, n_sims=n_sims, seed=seed, team_ids=team_ids
        )
        solved, objective = solve_card(
            marginals,
            rules.category_capacities,
            tie_tolerance=monte_carlo_stderr(0.5, n_sims),
            team_ids=team_ids,
        )
        card = {t: _value(c) for t, c in solved.items()}
        disagreements = sorted(t for t in card if card[t] != ladder[t])
        per_seed.append(
            {
                "seed": seed,
                "slots_agreeing": len(card) - len(disagreements),
                "slots_total": len(card),
                "disagreements": disagreements,
                "optimizer_objective": round(objective, 6),
                "ladder_objective_on_same_marginals": round(
                    objective_of(ladder, marginals), 6
                ),
                "objective_gap": round(objective - objective_of(ladder, marginals), 6),
            }
        )

    gaps = [s["objective_gap"] for s in per_seed]
    agreements = [s["slots_agreeing"] for s in per_seed]
    return {
        "status": "DIAGNOSTIC -- no threshold, gates nothing, cannot alter the card",
        "n_sims": n_sims,
        "single_marginal_stderr": monte_carlo_stderr(0.5, n_sims),
        "naive_ladder_card": ladder,
        "per_seed": per_seed,
        "min_slots_agreeing": min(agreements),
        "max_slots_agreeing": max(agreements),
        "max_objective_gap": max(gaps),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simulation versus a naive strength sort")
    parser.add_argument("--strengths", required=True)
    parser.add_argument("--rules", default="config/ti2026_rules.yaml")
    parser.add_argument("--sims", type=int, default=250000)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    payload = run(args.strengths, args.rules, args.sims, seeds)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "ladder_check.json").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
