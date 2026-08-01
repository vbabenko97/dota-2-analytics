import pytest
import yaml

from ti26.rules import (
    category_for_terminal_record,
    derive_category_capacities,
    derive_record_capacities,
    load_rules,
)
from ti26.types import Category, TeamState

RULES_PATH = "config/ti2026_rules.yaml"


def test_record_capacities_are_derived_not_configured():
    caps = derive_record_capacities(n_teams=16, advance_at=4, eliminate_at=4, total_rounds=5)
    assert caps == {(4, 0): 1, (4, 1): 2, (3, 2): 5, (2, 3): 5, (1, 4): 2, (0, 4): 1}


def test_record_capacities_generalise_to_a_smaller_bracket():
    """8 teams, 3 wins advance / 3 losses out, 3 rounds.

    Round count matters: at 5 rounds this format reaches a (2,1) group of
    size 3 and correctly raises, because an odd record group cannot be
    paired without a bye. Three rounds keeps every interior group even.
    """
    caps = derive_record_capacities(n_teams=8, advance_at=3, eliminate_at=3, total_rounds=3)
    assert sum(caps.values()) == 8
    assert caps[(3, 0)] == 1
    assert caps[(0, 3)] == 1
    assert caps[(2, 1)] == 3
    assert caps[(1, 2)] == 3


def test_odd_record_group_is_rejected():
    with pytest.raises(ValueError, match="odd"):
        derive_record_capacities(n_teams=6, advance_at=4, eliminate_at=4, total_rounds=5)


def test_category_for_terminal_record():
    assert category_for_terminal_record((4, 0), 4, 4) is Category.W4_0
    assert category_for_terminal_record((4, 1), 4, 4) is Category.W4_1
    assert category_for_terminal_record((0, 4), 4, 4) is Category.L0_4
    assert category_for_terminal_record((1, 4), 4, 4) is Category.L1_4
    # 3-2 and 2-3 are undecided until the elimination round.
    assert category_for_terminal_record((3, 2), 4, 4) is None
    assert category_for_terminal_record((2, 3), 4, 4) is None


def test_category_capacities_are_derived():
    records = derive_record_capacities(16, 4, 4, 5)
    caps = derive_category_capacities(records, advance_at=4, eliminate_at=4)
    assert caps == {
        Category.W4_0: 1,
        Category.W4_1: 2,
        Category.ELIM_WIN: 5,
        Category.ELIM_LOSS: 5,
        Category.L1_4: 2,
        Category.L0_4: 1,
    }
    assert sum(caps.values()) == 16


def test_advancing_teams_equal_eight():
    rules = load_rules(RULES_PATH)
    caps = rules.category_capacities
    advancing = caps[Category.W4_0] + caps[Category.W4_1] + caps[Category.ELIM_WIN]
    assert advancing == 8


def test_random_baseline_is_derived():
    rules = load_rules(RULES_PATH)
    expected = sum(k**2 for k in rules.category_capacities.values()) / rules.n_teams
    assert rules.random_baseline == pytest.approx(expected)
    assert rules.random_baseline == pytest.approx(3.75)


def test_config_declares_no_capacity_values():
    """Capacities must be derived, never configured — no divergent sources.

    The provenance block may *name* capacities; it must mark them derived.
    """
    with open(RULES_PATH) as fh:
        raw = yaml.safe_load(fh)
    assert "capacities" not in raw
    assert "category_capacities" not in raw
    assert raw["provenance"]["record_capacities"] == "logically_forced"
    assert raw["provenance"]["category_capacities"] == "logically_forced"


def test_tiebreak_order_is_the_official_seven():
    rules = load_rules(RULES_PATH)
    assert rules.tiebreak_order == [
        "series_wins",
        "series_losses",
        "opponent_series_wins",
        "game_win_pct",
        "opponent_game_win_pct",
        "avg_duration",
        "coin_toss",
    ]


def test_round_constraints():
    rules = load_rules(RULES_PATH)
    assert rules.within_group_rounds == [2, 3]
    assert rules.cross_group_rounds == [4]
    assert rules.max_distance_elimination_rounds == [5]


def test_every_rule_carries_a_provenance_tag():
    rules = load_rules(RULES_PATH)
    allowed = {"official", "logically_forced", "inferred", "arbitrary"}
    assert rules.provenance
    assert set(rules.provenance.values()) <= allowed


def test_team_state_properties():
    t = TeamState(team_id="alpha", initial_group="A")
    assert t.record == (0, 0)
    assert t.maps_played == 0
    t.series_wins, t.map_wins, t.map_losses = 4, 8, 3
    assert t.record == (4, 0)
    assert t.maps_played == 11


def test_is_active_uses_configured_thresholds():
    rules = load_rules(RULES_PATH)
    assert rules.is_active(TeamState(team_id="a", initial_group="A")) is True
    assert rules.is_active(TeamState(team_id="b", initial_group="A", series_wins=4)) is False
    assert rules.is_active(TeamState(team_id="c", initial_group="B", series_losses=4)) is False
    assert rules.is_active(TeamState(team_id="d", initial_group="B", series_wins=3, series_losses=2)) is True
