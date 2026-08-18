from pathlib import Path

import pytest
import yaml

from ti26.bracket import SLOTS
from ti26.cli_playoff_cards import PlayoffCardError, coherent_picks, verify_source_digest

FROZEN = yaml.safe_load(Path("data/ti2026_playoff_cards.yaml").read_text())
SEEDS = list(FROZEN["seeds"])


def test_every_frozen_card_is_a_coherent_bracket():
    """Kills accepting a pick the same card never advanced.

    A hand-transcribed bracket's most likely error is naming a team that lost
    earlier in its own card. The hit count would absorb that as an ordinary
    miss, so the malformed input would score as a merely bad forecast and
    nobody would learn the card was invalid.
    """
    assert len(FROZEN["cards"]) == 8
    for entry in FROZEN["cards"]:
        replayed = coherent_picks(entry["picks"], SEEDS, True)
        assert replayed == entry["picks"], entry["id"]


def test_external_cards_are_bound_to_their_raw_source_bytes():
    """Kills a transcription nobody can check against its source.

    The 14 picks are read out of a long prose document by hand. Without a
    digest the document could be edited after the matches to agree with
    whatever happened, and the card would still look frozen.
    """
    external = [e for e in FROZEN["cards"] if e["role"] == "external"]
    assert {e["id"] for e in external} == {"F-gpt-5-6-xhigh", "G-gemini-3-1-pro"}
    for entry in external:
        verify_source_digest(entry)


def test_external_cards_claim_no_topology_evidence():
    """Kills promoting an assumed topology to a corroborating observation.

    Both sources produced cross-feed brackets, and one says outright that it
    simulated "the standard eight-team double-elimination feed". That is an
    assumption about the standard bracket, not an observation of the locked
    client. Recording it as evidence would manufacture two extra witnesses for
    a fact that rests entirely on the owner's client screenshot.
    """
    for entry in FROZEN["cards"]:
        if entry["role"] != "external":
            continue
        assert entry["topology_used"] == "cross-feed"
        assert entry["topology_evidence"] == "none"
    assert FROZEN["topology_provenance"] == "owner_supplied_locked_client_screenshot"


def test_external_cards_cannot_become_the_headline():
    """Kills promoting whichever external card happens to win.

    Seven frozen cards offer seven stories after the playoff. The headline was
    designated as A vs E before any of them was played, and an external entrant
    scoring highest is not a reason to re-designate it.
    """
    roles = {e["id"]: e["role"] for e in FROZEN["cards"]}
    assert sorted(k for k, v in roles.items() if v == "headline") == ["A-model", "H-owner-final"]
    assert sorted(k for k, v in roles.items() if v == "external") == [
        "F-gpt-5-6-xhigh",
        "G-gemini-3-1-pro",
    ]


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
    assert headline == ["A-model", "H-owner-final"]
    attribution = {e["id"] for e in FROZEN["cards"] if e["role"] == "attribution"}
    assert attribution == {
        "B-override-iron-wing",
        "C-override-liquid",
        "D-override-both",
        "E-owner",
    }


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


def test_the_submitted_card_contradicts_the_owners_stated_probability():
    """Kills quietly reconciling a stated forecast with a later action.

    The owner put 0.55 on Iron Wing at UB QF1 and then submitted Team Spirit.
    The tempting repair is to nudge the probability to match the pick, which
    would erase the only evidence in this repository that a stated forecast and
    a submitted action came apart. The contradiction is recorded instead, and
    the submitted card is deliberately absent from the consistent set.
    """
    owner = FROZEN["owner_probabilities"]
    cards = {entry["id"]: entry["picks"] for entry in FROZEN["cards"]}
    submitted = owner["card_actually_submitted"]
    assert submitted == "H-owner-final"
    assert submitted not in owner["consistent_with_cards"]

    clash = owner["contradicted_by_submitted_card"]
    slot = clash["slot"]
    assert cards[submitted][slot] == clash["submitted_pick"]
    assert owner["implied_root_decisions"][slot] == clash["stated_probability_favours"]
    assert clash["submitted_pick"] != clash["stated_probability_favours"]


def test_the_superseded_owner_card_is_kept_and_linked():
    """Kills deleting or overwriting a forecast because it was revised.

    E was the owner's position on 2026-08-17 and H is the position on 08-18.
    Overwriting E -- the obvious tidy-up, and forbidden by the registration --
    would hide that the 'frozen' human card moved within a day, which is itself
    a result about the stability of judgemental forecasts.
    """
    entries = {entry["id"]: entry for entry in FROZEN["cards"]}
    assert entries["E-owner"]["superseded_by"] == "H-owner-final"
    assert entries["H-owner-final"]["supersedes"] == "E-owner"
    assert entries["E-owner"]["role"] == "attribution"
    assert entries["H-owner-final"]["role"] == "headline"
    differing = [s for s in SLOTS if entries["E-owner"]["picks"][s] != entries["H-owner-final"]["picks"][s]]
    assert len(differing) == 6


def test_the_submitted_card_declares_its_randomisation():
    """Kills scoring a partly coin-flipped card as a pure human forecast.

    The owner states some picks were decided by a coin. Those slots carry no
    judgement, so counting them as human signal measures noise this experiment
    introduced itself. The declaration is mandatory even while the slot list is
    still unrecorded.
    """
    submitted = next(e for e in FROZEN["cards"] if e["id"] == "H-owner-final")
    assert submitted["randomisation"] == "partial_coin_flip_owner_stated"
    assert "coin_flipped_slots" in submitted


def test_stated_probabilities_list_every_card_they_are_consistent_with():
    """Kills a stale `consistent_with_cards` set after new cards are frozen.

    The reviewer's pair was unique to card C until the external entrants
    arrived; F shares the same two roots, and G shares the owner's. A set left
    at its old value would silently become a false claim about which frozen
    cards a stated position actually picks out -- and the failure is invisible,
    because the listed card is still genuinely consistent.
    """
    cards = {entry["id"]: entry["picks"] for entry in FROZEN["cards"]}
    for key, liquid_pick, iron_wing_pick in (
        ("external_reviewer_probabilities", True, False),
        ("owner_probabilities", True, True),
    ):
        block = FROZEN[key]
        assert (block["liquid_beats_yandex"] > 0.5) is liquid_pick
        assert (block["iron_wing_beats_spirit"] > 0.5) is iron_wing_pick
        assert "implied_card" not in block, f"{key}: a single card cannot be implied"
        roots = block["implied_root_decisions"]
        matching = sorted(
            name
            for name, picks in cards.items()
            if all(picks[slot] == team for slot, team in roots.items())
        )
        assert matching == sorted(block["consistent_with_cards"]), key


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
