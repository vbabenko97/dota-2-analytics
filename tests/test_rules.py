import pytest
import yaml

from ti26.optimize import solve_card
from ti26.rules import (
    category_for_terminal_record,
    derive_category_capacities,
    derive_record_capacities,
    load_rules,
)
from ti26.tiebreak import TIEBREAK_ORDER
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


def test_category_capacities_include_zero_count_categories():
    """The 8/3/3/3 fixture genuinely produces zero W4_1 and zero L1_4 (every
    undecided team reaches (3,0)/(0,3) or stays undecided at (2,1)/(1,2), no
    record maps to W4_1/L1_4), so this exercises the real omission bug rather
    than a synthetic capacities dict."""
    records = derive_record_capacities(n_teams=8, advance_at=3, eliminate_at=3, total_rounds=3)
    caps = derive_category_capacities(records, advance_at=3, eliminate_at=3)
    assert set(caps) == set(Category)
    assert caps[Category.W4_1] == 0
    assert caps[Category.L1_4] == 0


def test_solve_card_handles_a_zero_count_category_without_a_key_error():
    records = derive_record_capacities(n_teams=8, advance_at=3, eliminate_at=3, total_rounds=3)
    caps = derive_category_capacities(records, advance_at=3, eliminate_at=3)
    teams = [f"z{i}" for i in range(8)]
    marginals = {t: {c: 1.0 / len(Category) for c in Category} for t in teams}
    card, _ = solve_card(marginals, caps)
    assert sorted(card) == sorted(teams)


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


def test_tiebreak_order_is_the_published_six():
    """Was `..._the_official_seven`, and asserted an order with two defects.

    The seventh entry, `avg_duration`, is in no published rules text, and
    `opponent_series_wins` sat ahead of `game_win_pct`. Both are corrected
    against docs/ti26/2026-08-08-published-format-rules.md.
    """
    rules = load_rules(RULES_PATH)
    assert rules.tiebreak_order == [
        "series_wins",
        "series_losses",
        "game_win_pct",
        "opponent_series_wins",
        "opponent_game_win_pct",
        "coin_toss",
    ]


def test_tiebreak_order_matches_what_tiebreak_py_implements():
    """Guards against the config and the implementation silently diverging --
    `rules.tiebreak_order` is otherwise loaded, tested, and never consumed."""
    rules = load_rules(RULES_PATH)
    assert rules.tiebreak_order == TIEBREAK_ORDER


def test_mutated_tiebreak_order_raises(tmp_path):
    with open(RULES_PATH) as fh:
        raw = yaml.safe_load(fh)
    raw["tiebreak_order"] = list(reversed(raw["tiebreak_order"]))
    mutated = tmp_path / "mutated_rules.yaml"
    with open(mutated, "w") as fh:
        yaml.safe_dump(raw, fh)
    with pytest.raises(ValueError, match="tiebreak_order"):
        load_rules(str(mutated))


def test_round_constraints():
    rules = load_rules(RULES_PATH)
    assert rules.within_group_rounds == [2, 3]
    assert rules.cross_group_rounds == [4]
    # Round 5 is deliberately absent: the published text gives it no special
    # modifications. Distance maximisation belongs to the elimination round.
    assert rules.elimination_maximizes_ranking_distance is True


def test_every_rule_carries_a_provenance_tag_and_none_claims_official():
    """Kills mutation: retag a secondhand format value as `official`.

    Nothing in this repository can check Valve's published rules. The design
    spec records that the page is JavaScript-rendered and that two fetch
    attempts returned no body, reproduced again on 2026-08-07, and
    `explorer_query` is the only network path here.

    The evidence improved twice on 2026-08-08 and `official` still is not the
    right word. The owner transcribed TI 2025's published rules text, and
    supplied a screenshot of the TI 2026 compendium card labelling its own six
    categories. Both are relayed by a human; neither is a fetch this repository
    can repeat, and neither can be re-verified by any test here. So the tags say
    which relay they came from -- `compendium_ui_2026`,
    `owner_transcript_2025_inherited` -- rather than borrowing the authority of
    the source behind it.

    The second assertion is not redundant with the first: it is what fails if
    someone restores `official` to the allowed set.
    """
    rules = load_rules(RULES_PATH)
    # "empirical" added in D2: the duration model is now fitted from real
    # match durations (reports/duration_fit.json) rather than guessed.
    allowed = {
        # Read off the TI 2026 compendium's own card UI, which labels its six
        # categories in the product's own words. Not `official`: a screenshot
        # relayed by the owner, not a fetch this repository can repeat.
        "compendium_ui_2026",
        # From the owner's transcript of TI 2025's published rules, assumed to
        # carry to 2026 because 2026 has published no pairing section.
        "owner_transcript_2025_inherited",
        "reported_official",
        "logically_forced",
        "inferred",
        "inferred_unvalidated",
        # A rule tested against TI 2025, found not to reproduce it, and then
        # measured to make no difference to any marginal. Kept because removing
        # it would need a replacement that is no better evidenced.
        "refuted_immaterial",
        "arbitrary",
        "empirical",
    }
    assert rules.provenance
    assert set(rules.provenance.values()) <= allowed
    assert "official" not in set(rules.provenance.values())


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
