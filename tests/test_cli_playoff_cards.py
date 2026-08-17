from pathlib import Path

import pytest
import yaml

from ti26.bracket import SLOTS
from ti26.cli_playoff_cards import PlayoffCardError, coherent_picks

FROZEN = yaml.safe_load(Path("data/ti2026_playoff_cards.yaml").read_text())
SEEDS = list(FROZEN["seeds"])


def test_every_frozen_card_is_a_coherent_bracket():
    """Kills accepting a pick the same card never advanced.

    A hand-transcribed bracket's most likely error is naming a team that lost
    earlier in its own card. The hit count would absorb that as an ordinary
    miss, so the malformed input would score as a merely bad forecast and
    nobody would learn the card was invalid.
    """
    assert len(FROZEN["cards"]) == 5
    for entry in FROZEN["cards"]:
        replayed = coherent_picks(entry["picks"], SEEDS, True)
        assert replayed == entry["picks"], entry["id"]


def test_a_pick_naming_a_team_not_in_the_match_is_rejected():
    """Kills the coherence check itself.

    Team Vision cannot appear in UB QF1: that match is Iron Wing vs Team
    Spirit. Without the check this reads as a normal pick.
    """
    picks = dict(FROZEN["cards"][0]["picks"])
    picks["UB QF1"] = "Team Vision"
    with pytest.raises(PlayoffCardError, match="the match is"):
        coherent_picks(picks, SEEDS, True)


def test_a_card_missing_a_slot_is_rejected_not_partially_scored():
    """Kills scoring a thirteen-slot card as though it were complete.

    A missing slot would otherwise contribute nothing and the card would look
    merely unlucky rather than truncated.
    """
    picks = {slot: team for slot, team in FROZEN["cards"][0]["picks"].items() if slot != "LB SF"}
    with pytest.raises(PlayoffCardError, match="missing slots"):
        coherent_picks(picks, SEEDS, True)


def test_the_headline_pair_is_designated_and_is_exactly_two_cards():
    """Kills quietly re-designating the headline after the outcomes.

    Five frozen cards offer five stories once the playoff is played, and the
    flattering one is available to whichever side lost. The registration fixes
    the headline as A vs E; this binds that to the data file.
    """
    headline = sorted(e["id"] for e in FROZEN["cards"] if e["role"] == "headline")
    assert headline == ["A-model", "E-owner"]
    attribution = {e["id"] for e in FROZEN["cards"] if e["role"] == "attribution"}
    assert attribution == {"B-override-iron-wing", "C-override-liquid", "D-override-both"}


def test_owner_and_reviewer_probabilities_stay_in_separate_blocks():
    """Kills collapsing two different people's forecasts into one.

    Both are now stated and they differ: owner 0.60/0.55, reviewer 0.53/0.48.
    Copying one into the other's block -- the tempting move when a field looks
    empty -- would manufacture a judgement that was never made, and afterwards
    nothing in the file could distinguish it from a real one.
    """
    owner = FROZEN["owner_probabilities"]
    reviewer = FROZEN["external_reviewer_probabilities"]
    assert owner["elicited"] is True
    assert reviewer["elicited"] is True
    assert (owner["liquid_beats_yandex"], owner["iron_wing_beats_spirit"]) == (0.60, 0.55)
    assert (reviewer["liquid_beats_yandex"], reviewer["iron_wing_beats_spirit"]) == (0.53, 0.48)
    assert owner["liquid_beats_yandex"] != reviewer["liquid_beats_yandex"]
    assert owner["iron_wing_beats_spirit"] != reviewer["iron_wing_beats_spirit"]
    for block in (owner, reviewer):
        provenance = block["provenance"].lower()
        assert "not independent" in provenance
        assert "before any playoff outcome" in provenance


def test_owner_probabilities_are_not_labelled_with_a_single_card():
    """Kills claiming these two numbers identify the owner's bracket.

    0.60 Liquid and 0.55 Iron Wing pin BOTH root decisions, which cards D and E
    share. They are separated only by six downstream slots that these two
    probabilities say nothing about. An `implied_card: E-owner` label would
    assert the numbers determine a card they cannot determine.
    """
    owner = FROZEN["owner_probabilities"]
    assert "implied_card" not in owner
    assert owner["consistent_with_cards"] == ["D-override-both", "E-owner"]
    assert owner["card_actually_submitted"] == "E-owner"

    cards = {entry["id"]: entry["picks"] for entry in FROZEN["cards"]}
    roots = owner["implied_root_decisions"]
    matching = [
        name
        for name, picks in cards.items()
        if all(picks[slot] == team for slot, team in roots.items())
    ]
    assert sorted(matching) == ["D-override-both", "E-owner"]


def test_the_reviewer_position_maps_onto_an_already_frozen_card():
    """Kills a drift between the stated probabilities and the card they imply.

    Taken as picks, 0.53 Liquid and 0.48 Iron Wing mean Liquid and Spirit --
    one root override, not both -- which is card C. If either number ever
    crossed 0.5 the implied card would change and `implied_card` would quietly
    become a false label on a frozen artifact.
    """
    reviewer = FROZEN["external_reviewer_probabilities"]
    picks_liquid = reviewer["liquid_beats_yandex"] > 0.5
    picks_iron_wing = reviewer["iron_wing_beats_spirit"] > 0.5
    assert picks_liquid and not picks_iron_wing
    assert reviewer["implied_card"] == "C-override-liquid"

    card = next(e for e in FROZEN["cards"] if e["id"] == reviewer["implied_card"])
    assert card["picks"]["UB QF3"] == "Team Liquid"
    assert card["picks"]["UB QF1"] == "Team Spirit"


def test_owner_card_is_not_the_model_optimum_under_its_own_two_overrides():
    """Kills reconstructing card E from the two root decisions.

    D and E share both root picks, so a reader may assume E is D. It is not:
    the model still routes Team Yandex deep through the lower bracket and the
    owner's card removes Yandex from every branch. If these ever coincided, D
    would be redundant and the attribution split would be meaningless.
    """
    cards = {entry["id"]: entry["picks"] for entry in FROZEN["cards"]}
    d, e = cards["D-override-both"], cards["E-owner"]
    assert d["UB QF1"] == e["UB QF1"] == "Iron Wing"
    assert d["UB QF3"] == e["UB QF3"] == "Team Liquid"
    differing = [slot for slot in SLOTS if d[slot] != e[slot]]
    assert len(differing) == 6
    assert "Team Yandex" not in e.values()
