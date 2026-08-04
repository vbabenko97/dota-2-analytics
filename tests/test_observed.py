import pytest
import yaml

from ti26.data.schema import MapRow
from ti26.observed import (
    OutcomeError,
    _category_for,
    derive_outcome,
    load_backtest_truth,
    playoff_teams,
    score_card,
    series_results,
)
from ti26.types import Category

LEAGUE = 18324
SWISS_END = 1757289600


def row(match_id, start_time, radiant, dire, radiant_win, series_id, league_id=LEAGUE):
    return MapRow(
        match_id=match_id, start_time=start_time, duration=2000, radiant_win=radiant_win,
        league_id=league_id, tier="premium", radiant_team_id=radiant, dire_team_id=dire,
        series_id=series_id, series_type=1, patch="7.39",
        radiant_accounts=(1, 2, 3, 4, 5), dire_accounts=(6, 7, 8, 9, 10),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


def sweep(series_id, winner, loser, start_time=1_000, first_match=None):
    """A 2-0 Bo3 series: two maps, same series_id, `winner` takes both."""
    base = first_match if first_match is not None else series_id * 10
    return [
        row(base, start_time, winner, loser, True, series_id),
        row(base + 1, start_time + 60, winner, loser, True, series_id),
    ]


# --- the record -> category rule -------------------------------------------


@pytest.mark.parametrize(
    ("wins", "losses", "advanced", "expected"),
    [
        (4, 0, True, Category.W4_0),
        (4, 1, True, Category.W4_1),
        (4, 2, True, Category.ELIM_WIN),
        (4, 3, True, Category.ELIM_WIN),
        (3, 4, False, Category.ELIM_LOSS),
        (2, 4, False, Category.ELIM_LOSS),
        (1, 4, False, Category.L1_4),
        (0, 4, False, Category.L0_4),
    ],
)
def test_ti2026_records_map_without_consulting_advancement(wins, losses, advanced, expected):
    """Under TI 2026's own format every team resolves to 4 wins or 4 losses.

    `advanced` must not be consulted for these: a 4-2 team advanced by
    definition, and a 2-4 team did not, so reading the flag here would let a
    data error in playoff detection silently rewrite a record-determined slot.
    """
    assert _category_for(wins, losses, advanced) == expected
    assert _category_for(wins, losses, not advanced) == expected


def test_three_three_splits_on_advancement_only():
    """TI 2025's 6-round cap left records the 2026 card cannot express."""
    assert _category_for(3, 3, True) == Category.ELIM_WIN
    assert _category_for(3, 3, False) == Category.ELIM_LOSS


def test_an_impossible_record_raises_instead_of_bucketing():
    """A silent fallback here would redefine the target being scored against."""
    with pytest.raises(OutcomeError, match="no card category"):
        _category_for(5, 5, True)


# --- series reconstruction --------------------------------------------------


def test_series_are_counted_once_not_per_map():
    rows = sweep(1, 100, 200) + sweep(2, 100, 300)
    records, n_maps, n_series = series_results(rows, LEAGUE, SWISS_END)
    assert n_maps == 4, "four maps"
    assert n_series == 2, "but only two series"
    assert records[100] == (2, 0)
    assert records[200] == (0, 1)


def test_a_three_map_series_counts_as_one_win():
    rows = [
        row(1, 1_000, 100, 200, True, 7),
        row(2, 1_060, 100, 200, False, 7),
        row(3, 1_120, 100, 200, True, 7),
    ]
    records, _, n_series = series_results(rows, LEAGUE, SWISS_END)
    assert n_series == 1
    assert records[100] == (1, 0)
    assert records[200] == (0, 1)


def test_a_null_series_id_is_refused_not_treated_as_its_own_series():
    """The tempting fallback silently inflates the series count AND the records.

    A map with no series_id, bucketed under its own match_id, becomes a phantom
    one-map series and hands somebody a free win. Refusing is the only safe
    reading, because a Bo3 map genuinely missing its series cannot be placed.
    """
    rows = sweep(1, 100, 200) + [row(99, 2_000, 100, 300, True, 0)]
    with pytest.raises(OutcomeError, match="no series_id"):
        series_results(rows, LEAGUE, SWISS_END)


def test_a_tied_series_is_refused():
    rows = [
        row(1, 1_000, 100, 200, True, 5),
        row(2, 1_060, 100, 200, False, 5),
    ]
    with pytest.raises(OutcomeError, match="tied"):
        series_results(rows, LEAGUE, SWISS_END)


def test_maps_outside_the_league_or_after_the_swiss_cutoff_are_ignored():
    rows = (
        sweep(1, 100, 200)
        + sweep(2, 100, 200, start_time=SWISS_END + 1, first_match=500)
        + sweep(3, 100, 200, first_match=600)
    )
    rows[-1] = MapRow(**{**rows[-1].__dict__, "league_id": 999})
    rows[-2] = MapRow(**{**rows[-2].__dict__, "league_id": 999})
    records, n_maps, n_series = series_results(rows, LEAGUE, SWISS_END)
    assert (n_maps, n_series) == (2, 1), "only the in-league pre-cutoff series counts"
    assert records[100] == (1, 0)


def test_playoff_teams_are_exactly_those_playing_after_the_cutoff():
    rows = sweep(1, 100, 200) + sweep(2, 100, 300, start_time=SWISS_END + 1, first_match=500)
    assert playoff_teams(rows, LEAGUE, SWISS_END) == {100, 300}


# --- the frozen cross-check -------------------------------------------------


def frozen(tmp_path, **overrides):
    """A minimal 2-team frozen truth, so a mismatch can be injected precisely."""
    doc = {
        "event": {
            "league_id": LEAGUE, "swiss_end": SWISS_END, "training_cutoff": 900,
            "expected_swiss_maps": 2, "expected_swiss_series": 1,
            # 2, not 1: `outcome_rows` gives team 100 a post-cutoff map against
            # team 400, which is outside this two-team Swiss field. That keeps
            # the fixture at three maps while still making 100 advanced and 200
            # not -- the asymmetry the cross-check tests need.
            "expected_playoff_teams": 2,
        },
        "teams": [
            {"name": "Winner", "team_id": 100, "record": "1-0", "advanced": True,
             "category": "4-0"},
            {"name": "Loser", "team_id": 200, "record": "0-1", "advanced": False,
             "category": "0-4"},
        ],
    }
    for key, value in overrides.items():
        if key.startswith("team__"):
            doc["teams"][0][key.removeprefix("team__")] = value
        else:
            if key not in doc["event"]:
                raise KeyError(f"{key} is not an event field; typo would void the test")
            doc["event"][key] = value
    path = tmp_path / "truth.yaml"
    path.write_text(yaml.safe_dump(doc))
    return load_backtest_truth(path)


def outcome_rows():
    """1-0 vs 0-1, plus a post-cutoff map so team 100 counts as advanced."""
    return sweep(1, 100, 200) + [row(90, SWISS_END + 1, 100, 400, True, 42)]


def test_derive_outcome_accepts_a_store_that_matches_the_frozen_truth(tmp_path):
    """Guards the negative tests below: they must fail for their stated reason.

    A 1-0 record is not reachable at a real event; it is used here because it
    makes the fixture two maps instead of a hundred, and `_category_for` is
    tested separately against the real records.
    """
    truth = frozen(tmp_path)
    # 1-0 / 0-1 are not 4-win records, so pin the categories the rule yields.
    truth.categories[100] = _category_for(1, 0, True)
    truth.categories[200] = _category_for(0, 1, False)
    truth.records[100], truth.records[200] = "1-0", "0-1"
    result = derive_outcome(outcome_rows(), truth)
    assert result[100].category == Category.ELIM_WIN
    assert result[200].category == Category.ELIM_LOSS


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"expected_swiss_maps": 3}, "Swiss maps"),
        ({"expected_swiss_series": 2}, "Swiss series"),
        ({"expected_playoff_teams": 3}, "playoff teams"),
    ],
)
def test_derive_outcome_refuses_a_reconciliation_mismatch(tmp_path, override, message):
    truth = frozen(tmp_path, **override)
    with pytest.raises(OutcomeError, match=message):
        derive_outcome(outcome_rows(), truth)


def test_derive_outcome_refuses_a_frozen_category_that_disagrees(tmp_path):
    """The whole point of the frozen file: a disagreement means one side is wrong.

    Without this the runner would score against whatever the code derived,
    making the frozen file decorative.
    """
    truth = frozen(tmp_path)
    truth.records[100], truth.records[200] = "1-0", "0-1"
    truth.categories[100] = Category.W4_0  # derived is ELIM_WIN
    truth.categories[200] = _category_for(0, 1, False)
    with pytest.raises(OutcomeError, match="derived elim_win, frozen 4-0"):
        derive_outcome(outcome_rows(), truth)


def test_derive_outcome_refuses_a_field_mismatch(tmp_path):
    truth = frozen(tmp_path)
    truth.categories[999] = Category.W4_0
    with pytest.raises(OutcomeError, match="field mismatch"):
        derive_outcome(outcome_rows(), truth)


# --- scoring ---------------------------------------------------------------


def test_score_card_counts_only_exact_category_matches(tmp_path):
    truth = frozen(tmp_path)
    truth.records[100], truth.records[200] = "1-0", "0-1"
    truth.categories[100] = _category_for(1, 0, True)
    truth.categories[200] = _category_for(0, 1, False)
    outcome = derive_outcome(outcome_rows(), truth)

    perfect = {"Winner": Category.ELIM_WIN, "Loser": Category.ELIM_LOSS}
    score, table = score_card(perfect, outcome, truth.names)
    assert score == 2
    assert all(hit for *_, hit in table)

    half = {"Winner": Category.ELIM_WIN, "Loser": Category.L0_4}
    score, table = score_card(half, outcome, truth.names)
    assert score == 1
    assert [r[0] for r in table] == ["Loser", "Winner"], "misses sort first"


def test_score_card_refuses_a_team_missing_from_the_card(tmp_path):
    """A silently absent team would lower the score without appearing as a miss."""
    truth = frozen(tmp_path)
    truth.records[100], truth.records[200] = "1-0", "0-1"
    truth.categories[100] = _category_for(1, 0, True)
    truth.categories[200] = _category_for(0, 1, False)
    outcome = derive_outcome(outcome_rows(), truth)
    with pytest.raises(OutcomeError, match="not on the card"):
        score_card({"Winner": Category.ELIM_WIN}, outcome, truth.names)


# --- the real event --------------------------------------------------------


def test_the_shipped_frozen_truth_is_internally_consistent():
    """Checks the committed file itself, independent of the store.

    Catches a hand-edit that breaks the mapping without touching any code: the
    counts must equal the card's capacities, and every 3-3 team's category must
    follow its own advanced flag.
    """
    truth = load_backtest_truth("config/ti2025_backtest.yaml")
    assert len(truth.categories) == 16
    counts = {c: sum(1 for v in truth.categories.values() if v == c) for c in Category}
    assert counts == {
        Category.W4_0: 1, Category.W4_1: 2, Category.ELIM_WIN: 5,
        Category.ELIM_LOSS: 5, Category.L1_4: 2, Category.L0_4: 1,
    }
    assert sum(truth.advanced.values()) == truth.expected_playoff_teams == 8
    for team_id, record in truth.records.items():
        wins, losses = (int(x) for x in record.split("-"))
        assert truth.categories[team_id] == _category_for(
            wins, losses, truth.advanced[team_id]
        ), f"team {team_id}"
    wins = sum(int(r.split("-")[0]) for r in truth.records.values())
    losses = sum(int(r.split("-")[1]) for r in truth.records.values())
    assert wins == losses == truth.expected_swiss_series == 44


def test_the_training_cutoff_is_strictly_before_the_event(tmp_path):
    """The leakage guard, checked on the shipped constants rather than assumed."""
    truth = load_backtest_truth("config/ti2025_backtest.yaml")
    assert truth.training_cutoff < truth.swiss_end
    # 2025-09-04 vs 2025-09-08: four days of Swiss play sit between them.
    assert truth.swiss_end - truth.training_cutoff == 4 * 86_400
