import sqlite3
from pathlib import Path

import pytest
import yaml

from ti26.cli_ti2026_outcome import OutcomeError, assert_matches_frozen, derive, read_series, score

LEAGUE = 19719
NAMES = {1: "Alpha", 2: "Beta", 3: "Gamma", 4: "Delta", 5: "Epsilon", 6: "Zeta"}


def build_store(path, series):
    """Write a minimal store. `series` is (series_id, start, a, b, a_map_wins, maps)."""
    conn = sqlite3.connect(path)
    conn.execute(
        "create table maps (match_id integer, start_time integer, league_id integer, "
        "radiant_team_id integer, dire_team_id integer, radiant_win integer, series_id integer)"
    )
    match_id = 0
    for series_id, start, a, b, a_wins, maps in series:
        for i in range(maps):
            match_id += 1
            conn.execute(
                "insert into maps values (?,?,?,?,?,?,?)",
                (match_id, start + i, LEAGUE, a, b, 1 if i < a_wins else 0, series_id),
            )
    conn.commit()
    return path


def alpha_sweeps(tmp_path):
    """Alpha wins four straight, then plays once more after becoming terminal."""
    return build_store(
        tmp_path / "s.sqlite",
        [
            (1, 100, 1, 2, 2, 2),
            (2, 200, 1, 3, 2, 2),
            (3, 300, 1, 4, 2, 2),
            (4, 400, 1, 5, 2, 2),
            (5, 500, 2, 3, 2, 2),
            (6, 600, 1, 6, 2, 2),
        ],
    )


def test_boundary_comes_from_the_published_facts_not_from_a_timestamp():
    """Kills dropping the 4-win / 4-loss terminal test and keeping only "played 5 series".

    Alpha is terminal after four wins, so its fifth appearance is an elimination
    series. Under a series-count-only rule Alpha is still active at four, that
    series counts as Swiss, and the split becomes 6/0 instead of 5/1.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        series, _ = read_series(alpha_sweeps(Path(tmp)), LEAGUE)
    out = derive(series, NAMES)
    assert (out["swiss_series"], out["elimination_series"]) == (5, 1)
    assert out["swiss_records"]["Alpha"] == [4, 0]
    assert out["elimination_round"] == [{"winner": "Alpha", "loser": "Zeta"}]
    assert out["categories"]["Alpha"] == "elim_win"


def test_unknown_team_id_is_refused(tmp_path):
    """Kills skipping a team_id that maps to no configured name.

    Iron Wing played a real elimination series under an id in no config. Silently
    dropping it would delete a series from the event and still look coherent.
    """
    series, _ = read_series(alpha_sweeps(tmp_path), LEAGUE)
    with pytest.raises(OutcomeError, match="maps to no configured name"):
        derive(series, {k: v for k, v in NAMES.items() if k != 6})


def test_derivation_must_equal_the_frozen_file(tmp_path):
    """Kills trusting the frozen file instead of re-deriving and comparing.

    Two independent statements of the same fact are the point: a transcription
    error here and a reconstruction error there are only caught together.
    """
    series, _ = read_series(alpha_sweeps(tmp_path), LEAGUE)
    out = derive(series, NAMES)
    frozen = {
        "event": {"swiss_series": 5, "elimination_series": 1},
        "swiss_records": out["swiss_records"],
        "elimination_round": out["elimination_round"],
        "categories": out["categories"],
    }
    assert_matches_frozen(out, frozen)

    frozen["swiss_records"] = dict(out["swiss_records"], Alpha=[3, 1])
    with pytest.raises(OutcomeError, match="swiss record Alpha"):
        assert_matches_frozen(out, frozen)


def test_card_must_cover_the_exact_field():
    """Kills scoring the intersection when a card omits or invents a team."""
    categories = {"Alpha": "4-0", "Beta": "0-4"}
    assert score({"Alpha": "4-0", "Beta": "4-0"}, categories) == ["Alpha"]
    with pytest.raises(OutcomeError, match="do not match the event field"):
        score({"Alpha": "4-0"}, categories)


def test_shipped_outcome_file_is_internally_consistent():
    """Kills a frozen file whose categories disagree with its own recorded results.

    The file is transcription, and the runner only checks it against a store the
    test suite does not have. This checks it against itself.
    """
    frozen = yaml.safe_load(Path("data/ti2026_outcome.yaml").read_text())
    counts: dict[str, int] = {}
    for category in frozen["categories"].values():
        counts[category] = counts.get(category, 0) + 1
    assert sorted(counts.values()) == [1, 1, 2, 2, 5, 5]
    for match in frozen["elimination_round"]:
        assert frozen["categories"][match["winner"]] == "elim_win"
        assert frozen["categories"][match["loser"]] == "elim_loss"
    for team, (wins, losses) in frozen["swiss_records"].items():
        assert wins + losses in (4, 5), team
        if wins == 4:
            assert frozen["categories"][team] == ("4-0" if losses == 0 else "4-1")
        elif losses == 4:
            assert frozen["categories"][team] == ("0-4" if wins == 0 else "1-4")
