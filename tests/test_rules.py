from pathlib import Path

import pytest
import yaml

from ti26.evidence import (
    RELEASE_SUBJECTS,
    extract_ti2026_rules,
    load_release_evidence,
    reconcile_rules_facts,
)
from ti26.optimize import solve_card
from ti26.rules import (
    category_for_terminal_record,
    derive_category_capacities,
    derive_record_capacities,
    load_rules,
    shipping_rules_facts,
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


def test_tiebreak_order_is_ti_2026s_seven_not_ti_2025s_six():
    """Kills mutation: apply TI 2025's ranking criteria to TI 2026.

    This test has now asserted three different orders and the history matters,
    because the failure it guards is not a typo -- it is applying the right
    rules from the wrong year.

    TI 2026, fetched from Valve's page on 2026-08-08 and archived in
    docs/ti26/2026-08-08-ti2026-rules-fetched.md, ranks on SEVEN criteria with
    opponents' match wins THIRD and average game duration SIXTH. TI 2025 ranked
    on six, with percentage of games won third and no duration at all. Earlier
    on 2026-08-08, while the 2026 page still had no pairing section, this file
    asserted TI 2025's order on the assumption that the format carried over.

    Both differences are load-bearing. The transposition changes the ranking
    that drives every pairing, and dropping duration sends genuinely tied teams
    to a coin toss the rules do not reach yet.
    """
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
    """Kills mutation: drop TI 2026's Round 5 modification.

    TI 2026 gives Round 5 one: "For matches where the loser is eliminated,
    maximize the distance in ranking between the teams." TI 2025 gave it none,
    which is why this assertion was deleted earlier on 2026-08-08 and why it is
    back. It shapes who finishes 1-4 rather than 2-3.
    """
    rules = load_rules(RULES_PATH)
    assert rules.within_group_rounds == [2, 3]
    assert rules.cross_group_rounds == [4]
    assert rules.max_distance_elimination_rounds == [5]


def test_the_elimination_choice_policy_is_configured_and_marked_as_an_assumption():
    """Kills mutation: tag the choice policy as if the rules specified it.

    TI 2026 fixes the ORDER in which 3-2 teams choose and says nothing about
    how any of them decides. A policy tagged as published would let a
    behavioural assumption that drives ten of sixteen slots pass as a rule.
    """
    rules = load_rules(RULES_PATH)
    assert rules.elimination_choice_policy in {"rational", "noisy", "random"}
    assert rules.provenance["elimination_choice_policy"] == "unspecified_by_published_rules"


def test_every_rule_carries_a_provenance_tag_and_none_claims_official():
    """Kills mutation: retag a relayed or assumed format value as `official`.

    Valve's rules page was finally READ on 2026-08-08, with a headless browser,
    and archived verbatim in docs/ti26/2026-08-08-ti2026-rules-fetched.md. It is
    JavaScript-rendered, which is why every prior attempt in this project got a
    heading with no body and why these values spent a week tagged as hearsay.

    `official` is still not the word, for two reasons that outlived the fetch.
    No test here can re-read the page -- tests never touch the network -- so
    nothing in this suite can detect the page changing under it. And it demonstrably
    does change: the pairing section was absent when the owner checked earlier
    the same day and present hours later.

    So the tag continues to name the relay and now also the date --
    `valve_rules_page_2026_08_08` -- which is a claim this repository can
    actually stand behind, unlike `official`.

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
        # Read from Valve's own TI 2026 rules page with a headless browser on
        # 2026-08-08 and archived verbatim. The date is in the tag because the
        # page changed during that day and no test here can re-read it.
        "valve_rules_page_2026_08_08",
        # The rules fix the order in which 3-2 teams choose their elimination
        # opponent and say nothing about the basis. This names that gap so a
        # behavioural assumption cannot pass as a published rule.
        "unspecified_by_published_rules",
        # From the owner's transcript of TI 2025's published rules, assumed to
        # carry to 2026 because 2026 had published no pairing section.
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


def test_shipping_rules_facts_reconciles_with_the_rendered_group_stage_page():
    """Kills mutation: omit max_distance_when_loser_eliminated from shipping_rules_facts.

    `shipping_rules_facts` never calls `load_rules` and exposes no
    model-facing behavior -- it only projects `config/ti2026_rules.yaml`
    into the same normalized vocabulary `extract_ti2026_rules` derives from
    the rendered Valve page, so the two must reconcile to nothing.
    """
    rendered = (
        "Number of Matches Won\nNumber of Matches Lost\n"
        "Total Number of Matches Won by Opponents Played\nPercentage of Games Won\n"
        "Average Percentage of Games Won by Opponents Played\n"
        "Average Game Duration (Shorter is Better)\nCoin Toss\n"
        "Round 2\nTeams are only matched against other members of their initial group\n"
        "Round 3\nTeams are only matched against other members of their initial group\n"
        "Round 4\nTeams are only matched against members of the other group\n"
        "Round 5\nFor matches where the loser is eliminated, maximize the distance in ranking between the teams\n"
        "Elimination Round\nStarting with the best 3-2 team, they will choose any of the five 2-3 teams as their opponent.\n"
    )
    extracted = extract_ti2026_rules(rendered)
    assert reconcile_rules_facts(shipping_rules_facts(RULES_PATH), extracted) == []


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


def predictive_config_projection(parsed: object) -> object:
    """Return the complete parsed configuration, provenance included.

    Parsing already drops YAML comments, so the projection is the whole
    mapping and nothing else. A field whitelist here would let an unlisted
    predictive value change unnoticed under a comment-only audit, which is
    the failure this comparison exists to catch.
    """
    return parsed


def test_rules_config_comments_do_not_restate_empirical_measurements():
    """Kills mutation: reintroduce a hand-written measured quantity into shipping rules comments."""
    text = Path(RULES_PATH).read_text(encoding="utf-8")
    comments = "\n".join(line for line in text.splitlines() if line.lstrip().startswith("#"))
    prohibited = (
        "Fitted in",
        "MARGINAL",
        "rating-gap coefficient",
        "Signal-to-noise",
        "marginals by",
        "standard error",
    )
    assert not [fragment for fragment in prohibited if fragment in comments]
    before = yaml.safe_load(
        Path("tests/fixtures/ti2026_rules_predictive_pre_comment_audit.yaml").read_text(
            encoding="utf-8"
        )
    )
    after = yaml.safe_load(text)
    assert predictive_config_projection(after) == predictive_config_projection(before)


def test_morning_rules_transcript_has_a_superseded_banner_and_preserves_its_body():
    """Kills mutation: silently replace the earlier owner transcript instead of retaining superseded evidence."""
    text = Path("docs/ti26/2026-08-08-published-format-rules.md").read_text(encoding="utf-8")
    assert any("Superseded" in line for line in text.splitlines()[:8])
    assert "## TI 2025" in text
    assert "## TI 2026, as published on 2026-08-08" in text
    catalog = load_release_evidence(Path("data/evidence"))
    linked = [record for record in catalog.records if record.subject_key == RELEASE_SUBJECTS["rules"]]
    assert any(str(record.root / "manifest.json") in text for record in linked)
