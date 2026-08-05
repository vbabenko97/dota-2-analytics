import argparse
import csv
import json
from pathlib import Path

from ti26.elimination import ChoicePolicy
from ti26.montecarlo import category_marginals, monte_carlo_stderr
from ti26.optimize import solve_card
from ti26.rules import load_rules
from ti26.types import Category


def _load_strengths(
    path: str | None, n_teams: int
) -> tuple[dict[str, float], dict[str, str] | None]:
    """Return `(strengths, team_ids)`; `team_ids` is None only for the ladder.

    The CSV must carry `team_id`. Accepting a file without one and falling back
    to the display name would silently reintroduce name-dependence at exactly
    the boundary this argument exists to close, and the caller would have no
    way to tell.
    """
    if path is None:
        # Synthetic ladder: D1 has no ingestion, so strengths are an input. Its
        # keys are generated stable identifiers, so there is no separate id.
        return {f"t{i:02d}": (i - (n_teams - 1) / 2) * 0.15 for i in range(n_teams)}, None
    with open(path) as fh:
        reader = csv.DictReader(fh)
        missing = {"team", "team_id", "strength"}.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"{path} must have columns team, team_id and strength; "
                f"missing {sorted(missing)}"
            )
        strengths: dict[str, float] = {}
        team_ids: dict[str, str] = {}
        for row in reader:
            team = row["team"]
            team_id = (row["team_id"] or "").strip()
            if not team_id:
                raise ValueError(f"{path}: team {team!r} has a blank team_id")
            strengths[team] = float(row["strength"])
            team_ids[team] = team_id
    return strengths, team_ids


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
    strengths, team_ids = _load_strengths(args.strengths, rules.n_teams)
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
        team_ids=team_ids,
    )
    # `tie_magnitude` is the largest standard error ONE marginal can carry at
    # this simulation count (p=0.5 maximises p(1-p)). It is a magnitude
    # heuristic, not the standard error of the quantity actually compared --
    # see `solve_card` for what it is and, more importantly, what it is not.
    # Its purpose is to stop the solver ranking differences it cannot resolve
    # and hand those to the stated scarcity tie-break instead.
    tie_magnitude = monte_carlo_stderr(0.5, args.n_sims)
    card, score = solve_card(
        marginals,
        rules.category_capacities,
        tie_tolerance=tie_magnitude,
        team_ids=team_ids,
    )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with (out / "category_probabilities.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["team", *(c.value for c in Category)])
        for team in sorted(marginals):
            writer.writerow([team, *(f"{marginals[team][c]:.6f}" for c in Category)])

    payload = {
        "assignments": {t: c.value for t, c in sorted(card.items())},
        "team_ids": dict(sorted(team_ids.items())) if team_ids else None,
        "optimizer_marginal_objective": round(score, 4),
        "random_baseline": rules.random_baseline,
        "n_sims": args.n_sims,
        "seed": args.seed,
        "policy": args.policy,
        "tie_magnitude_heuristic": tie_magnitude,
        "note": (
            "optimizer_marginal_objective is the sum of the model's own "
            "estimated category marginals under this assignment. It is "
            "descriptive only, never evidence of skill, and it is NOT the "
            "evaluation-simulation mean score, which is estimated by scoring "
            "this card against independently seeded simulated outcomes"
        ),
    }
    (out / "recommended_card.json").write_text(json.dumps(payload, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
