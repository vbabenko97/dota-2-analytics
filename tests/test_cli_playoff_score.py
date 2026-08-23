"""Tests for the playoff scorer.

The scorer applies a criterion that was registered before any card was frozen,
so every test here defends the criterion against being bent by the code that
applies it -- not against being wrong, which is no longer available.
"""

from pathlib import Path

import pytest
import yaml

from ti26.bracket import SLOTS, all_brackets, coherent_coin_null
from ti26.cli_playoff_cards import PlayoffCardError, coherent_picks
from ti26.cli_playoff_score import (
    conditional_null_mean,
    exact_null_tail,
    hit_counts,
    load_outcome,
    main,
    tail_at_least,
)

CARDS_PATH = Path("data/ti2026_playoff_cards.yaml")
OUTCOME_PATH = Path("data/ti2026_playoff_outcome.yaml")
FROZEN = yaml.safe_load(CARDS_PATH.read_text())
SEEDS = list(FROZEN["seeds"])
OUTCOME_BLOB = yaml.safe_load(OUTCOME_PATH.read_text())


def _outcome_file(tmp_path: Path, mutate) -> Path:
    """A copy of the real outcome file with `mutate` applied to its results."""
    blob = yaml.safe_load(OUTCOME_PATH.read_text())
    mutate(blob["results"])
    path = tmp_path / "outcome.yaml"
    path.write_text(yaml.safe_dump(blob))
    return path


def _cards_file(tmp_path: Path, mutate) -> Path:
    blob = yaml.safe_load(CARDS_PATH.read_text())
    mutate(blob)
    path = tmp_path / "cards.yaml"
    path.write_text(yaml.safe_dump(blob))
    return path


def test_a_winner_contradicting_its_series_score_is_rejected(tmp_path):
    """Kills trusting the `winner` field over the `score` beside it.

    Drop the `implied != winner` check in `load_outcome` and a transcription
    that names the losing team still scores: every card is then graded against
    a result that never happened, and the mistake is invisible because the
    scores in the file look right.
    """

    def flip(results):
        results["Grand Final"]["winner"] = "Team Vision"  # score is [2, 3]

    with pytest.raises(PlayoffCardError, match="implies"):
        load_outcome(_outcome_file(tmp_path, flip))


def test_a_winner_who_did_not_play_the_series_is_rejected(tmp_path):
    """Kills dropping the `winner not in matchup` check.

    Without it a typo in a team name silently becomes a slot no card can hit,
    which lowers every card's score by one and reads as fourteen forecasts all
    getting unlucky in the same place.
    """

    def rename(results):
        results["LB SF"]["winner"] = "Team Falcons"

    with pytest.raises(PlayoffCardError, match="is not in"):
        load_outcome(_outcome_file(tmp_path, rename))


def test_a_drawn_series_score_is_rejected(tmp_path):
    """Kills dropping the `score[0] == score[1]` guard.

    With the guard gone a `[1, 1]` transcription falls through to the `>`
    comparison, silently implies the second team, and agrees with `winner`
    whenever the second team is the one recorded -- so a corrupt score is
    accepted exactly half the time.
    """

    def draw(results):
        results["UB SF1"]["score"] = [1, 1]

    with pytest.raises(PlayoffCardError, match="no winner"):
        load_outcome(_outcome_file(tmp_path, draw))


def test_an_outcome_missing_a_slot_is_rejected(tmp_path):
    """Kills scoring thirteen slots as though they were fourteen.

    A missing slot would otherwise raise nothing until a card looked it up, and
    the registered metric is a count out of fourteen: a card scored out of
    thirteen is not comparable to one scored out of fourteen.
    """

    def drop(results):
        del results["LB QF2"]

    with pytest.raises(PlayoffCardError, match="missing slots"):
        load_outcome(_outcome_file(tmp_path, drop))


def test_the_realised_bracket_is_coherent_under_cross_feed_only(tmp_path):
    """Kills hardcoding the feed instead of reading it from the frozen artifact.

    The cards are frozen under cross-feed on the strength of a locked-client
    screenshot, and the realised bracket replays under cross-feed while
    refusing to replay under direct-feed -- which is what makes the topology an
    observation of the event rather than an assumption restated. Replace the
    producer's `frozen["topology"] == "cross-feed"` with a literal `True` and a
    cards file declaring the other feed would score without complaint, over a
    bracket space the cards were never frozen in.
    """
    outcome = load_outcome(OUTCOME_PATH)
    assert coherent_picks(outcome, SEEDS, True) == outcome
    with pytest.raises(PlayoffCardError, match="the match is"):
        coherent_picks(outcome, SEEDS, False)

    def relabel(blob):
        blob["topology"] = "direct-feed"

    with pytest.raises(PlayoffCardError, match="the match is"):
        main(["--cards", str(_cards_file(tmp_path, relabel)), "--outcome", str(OUTCOME_PATH)])


def test_the_tail_is_inclusive_of_the_score_itself():
    """Kills the off-by-one that turns `P(X >= s)` into `P(X > s)`.

    The exclusive form is the same arithmetic one step over and reports every
    card as more significant than it is -- the model's 11/14 would print
    0.0016 instead of 0.0045. Nothing in the output would look wrong.
    """
    tail = {0: 0.25, 1: 0.5, 2: 0.25}
    assert tail_at_least(tail) == {0: 1.0, 1: 0.75, 2: 0.25}


def test_the_tail_covers_every_score_up_to_a_perfect_bracket():
    """Kills an off-by-one that drops 14 from the distribution.

    `range(len(SLOTS))` instead of `range(len(SLOTS) + 1)` loses the perfect
    bracket, and with it every `P(X >= s)` becomes short by 1/16384. The head
    of the distribution is where the model's own p-value lives, so a missing
    top row is a systematic understatement of exactly the number being quoted.
    """
    outcome = load_outcome(OUTCOME_PATH)
    tail = exact_null_tail(SEEDS, True, outcome)
    at_least = tail_at_least(tail)
    assert set(tail) == set(range(len(SLOTS) + 1))
    assert tail[len(SLOTS)] == pytest.approx(1 / 2 ** len(SLOTS))
    assert at_least[0] == pytest.approx(1.0)
    assert sum(tail.values()) == pytest.approx(1.0)
    # No cell is empty against this outcome, so no p-value quoted from this
    # table rests on a score the null cannot reach.
    assert all(p > 0.0 for p in tail.values())


def test_the_conditional_null_mean_equals_the_registered_null_for_any_outcome():
    """Kills quoting 3.75 beside a tail conditioned on one bracket without checking.

    The two are different constructions -- `sum p**2` over outcomes versus
    `sum 1/n` against a fixed one -- and the project has twice rejected placing
    a conditional number next to a marginal. They coincide here only because
    the coin is fair, so the identity is checked on four unrelated brackets:
    weight the coin and this is the test that notices.
    """
    registered = coherent_coin_null(SEEDS, True)
    assert registered == pytest.approx(FROZEN["null_expected_hits"], abs=5e-5)
    brackets = all_brackets(SEEDS, True)
    for index in (0, 7777, 9999, 16383):
        assert conditional_null_mean(SEEDS, True, brackets[index]) == pytest.approx(
            registered, abs=1e-9
        )


def test_the_tail_shape_depends_on_the_outcome():
    """Kills reusing one outcome's tail as a lookup table for another.

    The mean cannot move but the shape does, so a p-value read off a stored
    table is a p-value for a bracket that did not happen. Two brackets with
    identical null means here have `P(X >= 11)` differing by a third.
    """
    brackets = all_brackets(SEEDS, True)
    a = tail_at_least(exact_null_tail(SEEDS, True, brackets[0]))[11]
    b = tail_at_least(exact_null_tail(SEEDS, True, brackets[9999]))[11]
    assert a != b


def test_the_frozen_cards_score_exactly_this_against_the_realised_bracket():
    """Kills any drift in the hit count itself.

    The registered metric is one number per card and these eight are the whole
    result. A comparison against the wrong slot, a card read from the wrong
    key, or an `==` that became an `is` would move them, and every one of those
    mutations still prints a plausible table.
    """
    outcome = load_outcome(OUTCOME_PATH)
    assert hit_counts(FROZEN["cards"], outcome) == {
        "A-model": 11,
        "B-override-iron-wing": 8,
        "C-override-liquid": 8,
        "D-override-both": 5,
        "E-owner": 4,
        "F-gpt-5-6-xhigh": 5,
        "G-gemini-3-1-pro": 3,
        "H-owner-final": 7,
    }


def test_the_model_card_beat_the_owner_card_on_the_frozen_picks():
    """Kills editing a frozen card's picks after the outcome is known.

    A vs H is the pair designated before the playoff and the gap is the whole
    headline. Change one pick in `H-owner-final` towards the realised bracket --
    the single edit that would flatter the human card, and the reason the
    artifact is anchored to a merge commit -- and this margin moves. The card
    file is the evidence; this pins the number that is read out of it.
    """
    outcome = load_outcome(OUTCOME_PATH)
    counts = hit_counts(FROZEN["cards"], outcome)
    null = coherent_coin_null(SEEDS, True)
    assert counts["A-model"] - counts["H-owner-final"] == 4
    assert counts["A-model"] == max(counts.values())
    assert counts["A-model"] > null
    assert counts["H-owner-final"] > null
    assert counts["G-gemini-3-1-pro"] < null


def test_the_coin_flipped_slots_are_reported_as_misses_not_as_judgement(capsys):
    """Kills inverting the coin-flip tally in the report.

    Both flipped slots missed. Flip the producer's `==` to `!=` when counting
    them and it reports 2 of 2, so the submitted card's 7/14 reads as seven
    judgements when at most five of the hits can be -- and the other two slots
    are noise the exercise introduced itself.
    """
    outcome = load_outcome(OUTCOME_PATH)
    submitted = next(e for e in FROZEN["cards"] if e["id"] == "H-owner-final")
    flipped = submitted["coin_flipped_slots"]
    won = [slot for slot in flipped if submitted["picks"][slot] == outcome[slot]]
    assert won == []
    judgement_slots = [slot for slot in SLOTS if slot not in flipped]
    hits = sum(1 for slot in judgement_slots if submitted["picks"][slot] == outcome[slot])
    assert hits == hit_counts([submitted], outcome)["H-owner-final"]

    assert main(["--cards", str(CARDS_PATH), "--outcome", str(OUTCOME_PATH)]) == 0
    out = capsys.readouterr().out
    assert f"{len(flipped)} coin-flipped slots" in out
    assert "landed correctly on **0**" in out


def test_a_null_that_disagrees_with_the_frozen_literal_stops_the_run(tmp_path):
    """Kills printing the frozen null literal instead of recomputing it.

    `null_expected_hits: 3.75` is the registered comparator every p-value is
    quoted against. If the producer echoed the literal it would agree with
    itself under any topology, including one the cards were never frozen under.
    """

    def weaken(blob):
        blob["null_expected_hits"] = 4.0  # the direct-feed null

    with pytest.raises(PlayoffCardError, match="registered null"):
        main(["--cards", str(_cards_file(tmp_path, weaken)), "--outcome", str(OUTCOME_PATH)])


def test_the_headline_pair_must_come_from_the_frozen_roles(tmp_path):
    """Kills naming the headline in the producer after seeing the scores.

    Eight scored cards offer eight stories. The producer reads the pair out of
    the frozen roles and refuses to run unless exactly two carry it, so
    promoting the winner requires editing the artifact that was anchored to a
    merge commit before the first match -- not this file.
    """

    def promote(blob):
        for entry in blob["cards"]:
            if entry["id"] == "B-override-iron-wing":
                entry["role"] = "headline"

    with pytest.raises(PlayoffCardError, match="headline"):
        main(["--cards", str(_cards_file(tmp_path, promote)), "--outcome", str(OUTCOME_PATH)])


def test_an_incoherent_card_is_refused_rather_than_scored(tmp_path):
    """Kills absorbing an unreachable pick as an ordinary miss.

    A card naming a team its own bracket eliminated is malformed input, not a
    bad forecast. Scoring it anyway would publish a hit count for a bracket
    that could not be entered.
    """

    def corrupt(blob):
        blob["cards"][0]["picks"]["Grand Final"] = "Iron Wing"

    with pytest.raises(PlayoffCardError, match="the match is"):
        main(["--cards", str(_cards_file(tmp_path, corrupt)), "--outcome", str(OUTCOME_PATH)])


def test_the_producer_prints_the_registered_caveat(capsys):
    """Kills quietly dropping the one-event caveat from a favourable result.

    The caveat was registered before the outcome and is the reason a 0.0045
    tail is not a claim of skill. A report that omits it says something the
    registration does not license, and omitting it is a one-line edit.
    """
    assert main(["--cards", str(CARDS_PATH), "--outcome", str(OUTCOME_PATH)]) == 0
    out = capsys.readouterr().out
    assert "does not establish predictive skill" in out
    assert "does not retire a model" in out
    assert "DIAGNOSTIC" in out
