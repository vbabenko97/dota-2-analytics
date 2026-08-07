"""The simulation-versus-sort diagnostic."""

import csv

import pytest

from ti26.cli_ladder_check import objective_of, run
from ti26.types import Category

STRENGTHS = [
    ("Alpha", "1", 0.9), ("Bravo", "2", 0.8), ("Charlie", "3", 0.7), ("Delta", "4", 0.6),
    ("Echo", "5", 0.5), ("Foxtrot", "6", 0.4), ("Golf", "7", 0.3), ("Hotel", "8", 0.2),
    ("India", "9", 0.1), ("Juliet", "10", 0.0), ("Kilo", "11", -0.1), ("Lima", "12", -0.2),
    ("Mike", "13", -0.3), ("November", "14", -0.4), ("Oscar", "15", -0.5),
    ("Papa", "16", -0.6),
]


@pytest.fixture
def strengths_csv(tmp_path):
    path = tmp_path / "strengths.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["team", "team_id", "strength"])
        writer.writerows(STRENGTHS)
    return str(path)


def test_objective_reads_the_assigned_category_not_the_best_one():
    """Kills mutation: score each team at its most likely category instead.

    The whole point is comparing two ASSIGNMENTS on the same marginals. Scoring
    every team at its argmax ignores the assignment entirely, makes both cards
    score identically by construction, and would report a gap of zero for any
    input -- which is also the headline result, so it would look right.
    """
    marginals = {
        "x": {c: 0.0 for c in Category},
        "y": {c: 0.0 for c in Category},
    }
    marginals["x"][Category.W4_0] = 0.1
    marginals["x"][Category.ELIM_WIN] = 0.9
    marginals["y"][Category.L0_4] = 0.25
    marginals["y"][Category.ELIM_LOSS] = 0.75

    assigned = objective_of({"x": "4-0", "y": "0-4"}, marginals)
    assert assigned == pytest.approx(0.35)
    assert assigned != pytest.approx(0.9 + 0.75), "must not read the argmax"


def test_a_card_scores_at_least_as_well_as_any_other_on_its_own_marginals(strengths_csv):
    """The optimiser cannot lose to the ladder on the objective it maximises.

    A negative gap would mean the assignment solver returned something the
    naive sort beats under the solver's own criterion, which is a solver bug
    rather than a finding about simulation value.
    """
    payload = run(strengths_csv, "config/ti2026_rules.yaml", n_sims=200, seeds=[1, 2])
    for entry in payload["per_seed"]:
        assert entry["objective_gap"] >= 0.0
        assert entry["slots_agreeing"] <= entry["slots_total"]


def test_the_ladder_fills_every_capacity_exactly(strengths_csv):
    """Kills mutation: build the ladder by argmax rather than by capacity.

    An unconstrained ladder would pile teams into the wide categories and leave
    4-0 and 0-4 empty, so it would not be a legal card and could not be
    compared with one.
    """
    payload = run(strengths_csv, "config/ti2026_rules.yaml", n_sims=100, seeds=[1])
    counts: dict[str, int] = {}
    for category in payload["naive_ladder_card"].values():
        counts[category] = counts.get(category, 0) + 1
    assert counts == {"4-0": 1, "4-1": 2, "elim_win": 5, "elim_loss": 5, "1-4": 2, "0-4": 1}
    # The strongest team tops the ladder and the weakest bottoms it.
    assert payload["naive_ladder_card"]["Alpha"] == "4-0"
    assert payload["naive_ladder_card"]["Papa"] == "0-4"
