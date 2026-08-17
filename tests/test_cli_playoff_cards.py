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


def test_owner_probabilities_are_null_until_elicited():
    """Kills shipping an invented subjective probability.

    A number the assistant made up would be indistinguishable in the file from
    one the owner stated, and would then be scored as though it were a human
    forecast.
    """
    owner = FROZEN["owner_probabilities"]
    assert owner["elicited"] is False
    assert owner["liquid_beats_yandex"] is None
    assert owner["iron_wing_beats_spirit"] is None
    assert "not independent of the model" in owner["provenance"].lower()


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
