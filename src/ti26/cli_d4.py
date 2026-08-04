"""D4: score the production card pipeline against TI 2025's real Swiss outcome.

A DIAGNOSTIC, not a gate. Spec section II ("D4") registered that before this file
existed and before any score was computed: one event is one sample, so a high
score here would not establish forecast value and a low one would not refute it.
Nothing in this module promotes, demotes or alters the shipping card.

What it does, all under a strict `start_time < training_cutoff` filter:

1. Re-derives TI 2025's observed Swiss outcome from the store and asserts it
   matches the frozen `config/ti2025_backtest.yaml`.
2. Re-measures the Glicko calibration slope from pre-cutoff maps ONLY. Re-using
   the production slope (0.4023, measured over the full store) would leak the
   event's own maps into the correction being applied to it.
3. Fits Glicko on pre-cutoff maps, resolves the 16 teams' rosters as of the
   cutoff, applies the slope, and builds a card through the SAME functions
   `cli_card` uses -- imported, not reimplemented, so this measures the shipping
   pipeline rather than a lookalike.
4. Reports the score, the random baseline, the score's percentile in the model's
   own predictive distribution, and the per-slot hit/miss table -- the four
   things the registration named in advance.
"""

import argparse
import csv
import json
from pathlib import Path

from ti26.cli_card import apply_correction, derive_glicko_calibration_slope
from ti26.data.store import load_rows, open_store
from ti26.montecarlo import card_score_distribution, category_marginals, monte_carlo_stderr
from ti26.observed import derive_outcome, load_backtest_truth, score_card
from ti26.optimize import solve_card
from ti26.ratings import load_gate_config
from ti26.ratings.glicko import GlickoModel
from ti26.roster import RosterIndex, load_aliases
from ti26.rules import load_rules
from ti26.teams import load_teams, resolve_rosters, team_strengths


def percentile_of(scores: dict[int, int], observed: int) -> tuple[float, float]:
    """Return (share strictly below, share at or below) `observed`, as percents.

    Both bounds are reported because the score distribution is discrete and
    lumpy: with 17 possible integer scores a single value can hold several
    percent of the mass, and quoting one side alone would overstate precision.
    """
    total = sum(scores.values())
    below = sum(n for s, n in scores.items() if s < observed)
    at = scores.get(observed, 0)
    return 100.0 * below / total, 100.0 * (below + at) / total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", default="config/ti2025_backtest.yaml")
    parser.add_argument("--aliases", default="config/team_aliases.yaml")
    parser.add_argument("--rules", default="config/ti2026_rules.yaml")
    parser.add_argument("--store", default="data/processed/d2.sqlite")
    parser.add_argument("--gate-config", default="config/d2_gate.yaml")
    parser.add_argument("--min-train", type=int, default=500)
    parser.add_argument("--card-sims", type=int, default=250_000)
    parser.add_argument("--card-seed", type=int, default=1)
    parser.add_argument(
        "--eval-seed",
        type=int,
        default=90_001,
        help=(
            "Seed for the outcomes the card is SCORED against. Deliberately "
            "independent of --card-seed: the card was solved to maximise "
            "expected score over the card-seed draws, so re-using them would "
            "credit it for noise it was fitted to."
        ),
    )
    parser.add_argument("--out", default="reports")
    args = parser.parse_args(argv)

    truth = load_backtest_truth(args.truth)
    rules = load_rules(args.rules)
    aliases = load_aliases(args.aliases)
    gate_config = load_gate_config(args.gate_config)

    all_rows = load_rows(open_store(args.store))
    if not all_rows:
        raise SystemExit(f"{args.store} is empty; run `python -m ti26.cli_ingest` first")

    # --- 1. The observed outcome, re-derived and cross-checked ---------------
    outcome = derive_outcome(all_rows, truth)

    # --- 2. The strict cutoff. Everything below sees only these rows ---------
    train = [r for r in all_rows if r.start_time < truth.training_cutoff]
    if not train:
        raise SystemExit("no maps before the training cutoff")
    if max(r.start_time for r in train) >= truth.training_cutoff:
        raise SystemExit("training rows include a map at or after the cutoff")

    # --- 3. Refit the correction on pre-cutoff data only ---------------------
    slope, _intercept = derive_glicko_calibration_slope(
        train, aliases, gate_config.glicko_tau, args.min_train
    )

    # --- 4. The card, through cli_card's own path ----------------------------
    model = GlickoModel(tau=gate_config.glicko_tau, roster_index=RosterIndex(aliases))
    for row in train:
        model.update(row)
    model.flush()
    fitted = model.strengths()

    teams = load_teams(args.truth)
    resolved = resolve_rosters(train, teams, aliases)
    raw_strengths, prior_driven = team_strengths(resolved, fitted)
    strengths = apply_correction(raw_strengths, slope)

    marginals = category_marginals(
        strengths, rules, n_sims=args.card_sims, seed=args.card_seed
    )
    card, model_expected = solve_card(
        marginals,
        rules.category_capacities,
        tie_tolerance=monte_carlo_stderr(0.5, args.card_sims),
    )

    # --- 5. Score plus the three companions the registration demanded -------
    score, table = score_card(card, outcome, truth.names)
    baseline = sum(c * c for c in rules.category_capacities.values()) / len(teams)
    dist = card_score_distribution(
        card, strengths, rules, n_sims=args.card_sims, seed=args.eval_seed
    )
    below, at_or_below = percentile_of(dist, score)
    sim_mean = sum(s * n for s, n in dist.items()) / sum(dist.values())

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "DIAGNOSTIC -- not a gate; does not alter the shipping card",
        "league_id": truth.league_id,
        "training_maps": len(train),
        "observed_score": score,
        "random_baseline": baseline,
        "model_expected_score_from_marginals": model_expected,
        "model_expected_score_from_eval_sims": sim_mean,
        "percentile_strictly_below": below,
        "percentile_at_or_below": at_or_below,
        "calibration_slope_refit_precutoff": slope,
        "calibration_slope_production_full_store": 0.4023,
        "prior_driven_teams": prior_driven,
        "n_sims": args.card_sims,
        "card_seed": args.card_seed,
        "eval_seed": args.eval_seed,
        "score_distribution": {str(k): v for k, v in sorted(dist.items())},
        "card": {name: c.value for name, c in sorted(card.items())},
        "per_slot": [
            {"team": n, "predicted": p.value, "observed": o.value, "hit": h}
            for n, p, o, h in table
        ],
    }
    (out / "d4_card_backtest.json").write_text(json.dumps(payload, indent=2) + "\n")

    with (out / "d4_per_slot.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["team", "predicted", "observed", "hit"])
        for name, predicted, observed_c, hit in table:
            writer.writerow([name, predicted.value, observed_c.value, int(hit)])

    hits = sum(1 for r in table if r[3])
    print(f"d4: DIAGNOSTIC (not a gate). trained on {len(train)} maps before cutoff")
    print(f"d4: refit calibration slope {slope:.4f} (production, full store: 0.4023)")
    print(
        f"d4: observed score {score}/16 | random baseline {baseline:.2f} | "
        f"model expected {sim_mean:.4f}"
    )
    print(f"d4: percentile {below:.1f}% strictly below, {at_or_below:.1f}% at or below")
    print(f"d4: {hits} hits, {16 - hits} misses")
    if prior_driven:
        print(f"d4: WARNING prior-driven (unrated) rosters: {prior_driven}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
