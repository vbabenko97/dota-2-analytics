import argparse
import csv
import json
from pathlib import Path

from ti26.elimination import ChoicePolicy
from ti26.montecarlo import category_marginals
from ti26.optimize import solve_card
from ti26.rules import load_rules
from ti26.types import Category


def _load_strengths(path: str | None, n_teams: int) -> dict[str, float]:
    if path is None:
        # Synthetic ladder: D1 has no ingestion, so strengths are an input.
        return {f"t{i:02d}": (i - (n_teams - 1) / 2) * 0.15 for i in range(n_teams)}
    with open(path) as fh:
        return {row["team"]: float(row["strength"]) for row in csv.DictReader(fh)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TI 2026 Swiss card generator")
    parser.add_argument("--strengths", default=None, help="CSV with team,strength")
    parser.add_argument("--rules", default="config/ti2026_rules.yaml")
    parser.add_argument("--n-sims", type=int, default=250_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--policy", default=ChoicePolicy.RATIONAL.value)
    parser.add_argument("--out", default="reports")
    args = parser.parse_args(argv)

    rules = load_rules(args.rules)
    strengths = _load_strengths(args.strengths, rules.n_teams)
    if len(strengths) != rules.n_teams:
        raise ValueError(
            f"loaded {len(strengths)} strengths but rules.n_teams requires {rules.n_teams}"
        )
    marginals = category_marginals(
        strengths,
        rules,
        n_sims=args.n_sims,
        seed=args.seed,
        policy=ChoicePolicy(args.policy),
    )
    card, score = solve_card(marginals, rules.category_capacities)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with (out / "category_probabilities.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["team", *(c.value for c in Category)])
        for team in sorted(marginals):
            writer.writerow([team, *(f"{marginals[team][c]:.6f}" for c in Category)])

    payload = {
        "assignments": {t: c.value for t, c in sorted(card.items())},
        "model_implied_expected_score": round(score, 4),
        "random_baseline": rules.random_baseline,
        "n_sims": args.n_sims,
        "seed": args.seed,
        "policy": args.policy,
        "note": (
            "model_implied_expected_score is computed from the model's own "
            "probabilities and is descriptive only, never evidence of skill"
        ),
    }
    (out / "recommended_card.json").write_text(json.dumps(payload, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
