import json
import math
import random
from collections import Counter

import pytest

import ti26.cli_d4 as cli_d4_module
from ti26.cli_d4 import (
    main as d4_main,
)
from ti26.cli_d4 import (
    naive_strength_ladder,
    random_card_control,
    rank_diagnostics,
    render_markdown,
)
from ti26.data.schema import MapRow
from ti26.data.store import insert_rows, load_rows, open_store
from ti26.observed import SwissOutcome
from ti26.types import Category

CAPACITIES = {
    Category.W4_0: 1,
    Category.W4_1: 2,
    Category.ELIM_WIN: 5,
    Category.ELIM_LOSS: 5,
    Category.L1_4: 2,
    Category.L0_4: 1,
}

_SIXTEEN_CATEGORIES = (
    [Category.W4_0]
    + [Category.W4_1] * 2
    + [Category.ELIM_WIN] * 5
    + [Category.ELIM_LOSS] * 5
    + [Category.L1_4] * 2
    + [Category.L0_4]
)


def _outcome_for(categories) -> dict[int, SwissOutcome]:
    return {
        i: SwissOutcome(team_id=i, wins=0, losses=0, advanced=False, category=c)
        for i, c in enumerate(categories)
    }


def row(match_id, start_time, league_id, radiant, dire, radiant_win,
        r_team, d_team, series_id, duration=2000):
    return MapRow(
        match_id=match_id, start_time=start_time, duration=duration,
        radiant_win=radiant_win, league_id=league_id, tier="professional",
        radiant_team_id=r_team, dire_team_id=d_team,
        series_id=series_id, series_type=1, patch="7.41",
        radiant_accounts=tuple(radiant), dire_accounts=tuple(dire),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


# --- Pure, unit-testable helpers (no store) ---------------------------------


def test_random_card_control_is_seeded_and_reproducible():
    """Mutation: replace `random.Random(seed)` with `random.Random()` (an
    unseeded generator) -- two calls with the SAME seed would then almost
    certainly disagree, since each draws from fresh OS entropy instead of a
    shared, reproducible stream.
    """
    outcome = _outcome_for(_SIXTEEN_CATEGORIES)
    first = random_card_control(outcome, CAPACITIES, samples=500, seed=7)
    second = random_card_control(outcome, CAPACITIES, samples=500, seed=7)
    assert first == second

    total = sum(first["score_counts"].values())
    assert total == 500
    mean_from_histogram = sum(int(k) * v for k, v in first["score_counts"].items()) / 500
    assert first["mean_score"] == pytest.approx(mean_from_histogram)


def test_random_card_control_respects_fixed_capacities(monkeypatch):
    """Mutation: sample each slot's category label independently (e.g. drop
    the fixed-multiset shuffle for a per-slot weighted `rng.choice`) instead
    of shuffling one fixed multiset built from `capacities`. An independent
    draw would never call `random.Random.shuffle` at all, and would not be
    constrained to reproduce the exact capacities [1,2,5,5,2,1] every time --
    both caught here by recording every list actually handed to `shuffle`.
    """
    outcome = _outcome_for(_SIXTEEN_CATEGORIES)
    seen: list[Counter] = []
    original_shuffle = random.Random.shuffle

    def spy_shuffle(self, x, *a, **kw):
        seen.append(Counter(x))
        return original_shuffle(self, x, *a, **kw)

    monkeypatch.setattr(random.Random, "shuffle", spy_shuffle)
    random_card_control(outcome, CAPACITIES, samples=5, seed=1)

    expected = Counter(c for c in Category for _ in range(CAPACITIES[c]))
    assert len(seen) == 5
    for counter in seen:
        assert counter == expected


def test_naive_strength_ladder_breaks_exact_ties_by_stable_id_not_name():
    """Mutation: break the tie by display name instead of configured id (drop
    `team_ids` when building the tie-break, e.g. `order_key(strengths, None)`)
    -- "Alpha" would then outrank "Zulu" alphabetically despite Zulu holding
    the LOWER configured id, flipping which team gets the scarce "4-0" slot.
    """
    strengths = {"Zulu": 10.0, "Alpha": 10.0}  # exact tie for the top strength
    for i in range(14):
        strengths[f"Filler{i:02d}"] = 9.0 - i
    team_ids = {"Zulu": "100", "Alpha": "500"}
    team_ids.update({f"Filler{i:02d}": str(1000 + i) for i in range(14)})

    card = naive_strength_ladder(strengths, CAPACITIES, team_ids=team_ids)

    assert card["Zulu"] == Category.W4_0
    assert card["Alpha"] == Category.W4_1


def test_rank_diagnostics_partitions_every_team_by_ordinal_displacement():
    """Mutation: count an ordinal displacement of two as off_by_one (e.g.
    `elif d <= 2:` instead of `elif d == 1:`) -- the team two categories away
    would then land in the wrong bucket.
    """
    order = list(Category)  # W4_0=0, W4_1=1, ELIM_WIN=2, ELIM_LOSS=3, L1_4=4, L0_4=5
    card = {"Exact": Category.W4_1, "OffByOne": Category.ELIM_WIN, "OffByTwo": Category.W4_0}
    observed = {"Exact": Category.W4_1, "OffByOne": Category.ELIM_LOSS, "OffByTwo": Category.ELIM_WIN}

    result = rank_diagnostics(card, observed, order)

    assert result["exact"] == ["Exact"]
    assert result["off_by_one"] == ["OffByOne"]
    assert result["off_by_two_or_more"] == ["OffByTwo"]
    assert (
        len(result["exact"]) + len(result["off_by_one"]) + len(result["off_by_two_or_more"])
        == len(card)
    )


def test_rank_diagnostics_spearman_handles_tied_ranks_correctly():
    """Hand-computed against the average-tied-rank formula. Predicted ordinal
    positions [0,1,1,3] vs observed [1,1,0,3] (teams A,B,C,D respectively)
    give average-tie ranks [1, 2.5, 2.5, 4] vs [2.5, 2.5, 1, 4], and Pearson
    correlation of those ranks is 2.25 / sqrt(4.5*4.5) = 0.5.

    Mutation: compute the correlation directly on the raw ordinal positions
    (skip tie-averaged ranking entirely, e.g. a plain Pearson `np.corrcoef`
    on `predicted_ord`/`observed_ord`) -- for this exact fixture that gives
    3.75/4.75 ~= 0.7895, not 0.5, so a rank-blind implementation is caught.
    """
    order = list(Category)
    card = {"A": Category.W4_0, "B": Category.W4_1, "C": Category.W4_1, "D": Category.ELIM_LOSS}
    observed = {"A": Category.W4_1, "B": Category.W4_1, "C": Category.W4_0, "D": Category.ELIM_LOSS}

    result = rank_diagnostics(card, observed, order)

    assert result["spearman_rho"] == pytest.approx(0.5, abs=1e-9)


def _sample_payload() -> dict:
    return {
        "status": "DIAGNOSTIC -- not a gate; does not alter the shipping card",
        "league_id": 1,
        "training_maps": 100,
        "observed_score": 3,
        "random_baseline": 3.75,
        "optimizer_marginal_objective": 4.5,
        "evaluation_simulation_mean_score": 4.1,
        "percentile_strictly_below": 10.0,
        "percentile_at_or_below": 20.0,
        "calibration_slope_refit_precutoff": 0.25,
        "calibration_slope_production_full_store": 0.4,
        "prior_driven_teams": [],
        "sweep": {
            "entries": [
                {"n_sims": 10, "seed": 1, "optimizer_marginal_objective": 4.0, "observed_score": 2},
            ],
        },
        "random_control": {"samples": 100, "seed": 1, "mean_score": 3.7},
        "naive_ladder": {"score": 2},
        "rank_diagnostics": {
            "spearman_rho": 0.5,
            "exact": ["A"],
            "off_by_one": ["B", "C"],
            "off_by_two_or_more": [],
            "mean_absolute_displacement": 0.6,
        },
        "per_slot": [{"team": "A", "predicted": "4-0", "observed": "4-1", "hit": False}],
    }


def test_render_markdown_opens_with_the_diagnostic_disclaimer_and_follows_the_payload():
    """The JSON payload's `status` marks D4 a diagnostic, and the Markdown is
    rendered from the payload alone: mutating a payload value must change the
    rendered text.

    Mutation: hardcode the "Observed score" line's number (e.g. always print
    the value this fixture happened to start with) instead of reading
    `payload['observed_score']` -- the second render below, after mutating
    the payload to a different score, would then still show the old number.
    """
    payload = _sample_payload()
    markdown = render_markdown(payload)
    assert markdown.startswith("# D4: TI 2025 card backtest\n\n**D4 is a diagnostic.")
    assert "cannot promote, demote or alter the shipping card" in markdown
    assert f"{payload['observed_score']}/16" in markdown
    assert f"{payload['calibration_slope_refit_precutoff']:.4f}" in markdown

    payload["observed_score"] = 9
    payload["calibration_slope_refit_precutoff"] = 0.9999
    changed = render_markdown(payload)
    assert "9/16" in changed
    assert "0.9999" in changed
    assert "3/16" not in changed


# --- End-to-end: the strict cutoff, over a real store -----------------------

TEAM_ID_BASE = 3000
N_TEAMS = 16
CUTOFF = 2_000_000
SWISS_END = 3_000_000
TRUTH_LEAGUE = 555555
DUMMY_LEAGUE = 42

BEFORE_MATCH_ID = 900_001
AT_MATCH_ID = 900_002
AFTER_MATCH_ID = 900_003
PROBE_TEAM_A = 9001
PROBE_TEAM_B = 9002


def _history_rows(n_teams=N_TEAMS, n_series=600, maps_per_series=3, seed=4):
    """Pre-cutoff history: gives every configured team a resolvable roster
    and enough rolling-backtest folds for `derive_glicko_calibration_slope`
    at `--min-train 150` (same shape as `test_cli_card.card_store`: one big
    early league plus small tail leagues so `rolling_folds` finds folds
    quickly). All timestamps stay far below `CUTOFF`.
    """
    rng = random.Random(seed)
    rosters = [[t * 5 + p for p in range(5)] for t in range(n_teams)]
    strength = {t: (n_teams - t) * 0.2 for t in range(n_teams)}
    rows_, match_id = [], 0
    for s in range(n_series):
        a, b = rng.sample(range(n_teams), 2)
        p = 1.0 / (1.0 + math.exp(-(strength[a] - strength[b])))
        league = 1 if s < 400 else 100 + (s % 32)
        for _ in range(maps_per_series):
            rows_.append(
                row(match_id, match_id * 600, league, rosters[a], rosters[b],
                    rng.random() < p, r_team=TEAM_ID_BASE + a, d_team=TEAM_ID_BASE + b,
                    series_id=s)
            )
            match_id += 1
    return rows_


def _event_and_playoff_rows():
    """The Swiss event itself: 8 winners (t=0..7, record 1-0) vs 8 losers
    (t=8..15, record 0-1), all AT OR AFTER `CUTOFF` -- i.e. never part of
    training, mirroring the real event's own maps never being in `train`.
    Winners then meet again in single playoff maps AFTER `SWISS_END`, which
    is what `observed.playoff_teams` uses to mark them `advanced=True`.
    """
    rows_, match_id = [], 500_000
    for i in range(8):
        winner_id, loser_id = TEAM_ID_BASE + i, TEAM_ID_BASE + 8 + i
        w_acc = [1000 + i * 5 + p for p in range(5)]
        l_acc = [2000 + i * 5 + p for p in range(5)]
        for g in range(2):
            rows_.append(
                row(match_id, CUTOFF + 1_000 + i * 100 + g, TRUTH_LEAGUE, w_acc, l_acc, True,
                    r_team=winner_id, d_team=loser_id, series_id=700_000 + i)
            )
            match_id += 1
    match_id = 600_000
    for i in (0, 2, 4, 6):
        a_id, b_id = TEAM_ID_BASE + i, TEAM_ID_BASE + i + 1
        a_acc = [1000 + i * 5 + p for p in range(5)]
        b_acc = [1000 + (i + 1) * 5 + p for p in range(5)]
        rows_.append(
            row(match_id, SWISS_END + 1_000 + i * 10, TRUTH_LEAGUE, a_acc, b_acc, True,
                r_team=a_id, d_team=b_id, series_id=710_000 + i)
        )
        match_id += 1
    return rows_


def _probe_rows():
    """Three rows in an UNRELATED league, one strictly before, one EXACTLY AT,
    and one strictly after `CUTOFF` -- the boundary the strict-cutoff filter
    must get right. Membership in the row lists passed to
    `derive_glicko_calibration_slope` and `resolve_rosters` is checked by
    `match_id`, independent of anything the observed-outcome derivation does
    (a different league_id, so `derive_outcome` ignores them entirely).
    """
    acc_a, acc_b = [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]
    return [
        row(BEFORE_MATCH_ID, CUTOFF - 1, DUMMY_LEAGUE, acc_a, acc_b, True,
            r_team=PROBE_TEAM_A, d_team=PROBE_TEAM_B, series_id=800_001),
        row(AT_MATCH_ID, CUTOFF, DUMMY_LEAGUE, acc_a, acc_b, True,
            r_team=PROBE_TEAM_A, d_team=PROBE_TEAM_B, series_id=800_002),
        row(AFTER_MATCH_ID, CUTOFF + 1, DUMMY_LEAGUE, acc_a, acc_b, True,
            r_team=PROBE_TEAM_A, d_team=PROBE_TEAM_B, series_id=800_003),
    ]


def _build_store(path):
    conn = open_store(path)
    insert_rows(conn, _history_rows() + _event_and_playoff_rows() + _probe_rows())
    return conn


def _truth_yaml() -> str:
    lines = [
        "event:",
        f"  league_id: {TRUTH_LEAGUE}",
        f"  swiss_end: {SWISS_END}",
        f"  training_cutoff: {CUTOFF}",
        "  expected_swiss_maps: 16",
        "  expected_swiss_series: 8",
        "  expected_playoff_teams: 8",
        "",
        "teams:",
    ]
    for t in range(8):
        lines.append(
            f'  - {{name: Team{t:02d}, team_id: {TEAM_ID_BASE + t}, record: "1-0", '
            "advanced: true, category: elim_win}"
        )
    for t in range(8, 16):
        lines.append(
            f'  - {{name: Team{t:02d}, team_id: {TEAM_ID_BASE + t}, record: "0-1", '
            "advanced: false, category: elim_loss}"
        )
    return "\n".join(lines) + "\n"


@pytest.mark.slow
def test_train_from_bounds_the_window_below_as_well_as_above(tmp_path, monkeypatch):
    """Kills mutation: accept `--train-from` and never apply it.

    The cutoff is an upper bound only. On a snapshot deeper than the one the
    backtest was designed against, that alone hands the backtest MORE history
    than production has, which flatters the score by exactly the mechanism the
    matched-window spec exists to correct. A silently ignored lower bound would
    report a matched window while running an unmatched one.

    The spy captures what calibration actually received, so this fails if the
    bound is dropped, applied to the wrong side, or applied only to the report.
    """
    store = tmp_path / "d2.sqlite"
    _build_store(store)
    truth_path = tmp_path / "truth.yaml"
    truth_path.write_text(_truth_yaml())
    aliases_path = tmp_path / "aliases.yaml"
    aliases_path.write_text("aliases: []\n")
    out = tmp_path / "reports"

    train_from = 300_000
    calls: list[list[int]] = []
    original = cli_d4_module.derive_glicko_calibration_slope

    def spy(rows, *a, **kw):
        calls.append([r.start_time for r in rows])
        return original(rows, *a, **kw)

    monkeypatch.setattr(cli_d4_module, "derive_glicko_calibration_slope", spy)

    rc = d4_main([
        "--truth", str(truth_path), "--aliases", str(aliases_path), "--store", str(store),
        "--out", str(out), "--min-train", "150", "--card-sims", "300", "--card-seed", "1",
        "--eval-seed", "2", "--sweep-sims", "50,80", "--sweep-seeds", "1",
        "--random-samples", "300", "--random-seed", "3",
        "--train-from", str(train_from),
    ])
    assert rc == 0

    all_rows = load_rows(open_store(str(store)))
    unbounded = [r for r in all_rows if r.start_time < CUTOFF]
    expected = [r for r in unbounded if r.start_time >= train_from]
    assert len(expected) < len(unbounded), "the fixture must have rows the bound removes"

    refit = min(calls, key=len)
    assert min(refit) >= train_from, "a row older than --train-from reached calibration"
    assert len(refit) == len(expected)

    payload = json.loads((out / "d4_card_backtest.json").read_text())
    assert payload["training_from"] == train_from
    assert payload["training_maps"] == len(expected)


def test_strict_cutoff_only_pre_cutoff_rows_reach_calibration_and_roster_resolution(
    tmp_path, monkeypatch
):
    """THE IMPORTANT ONE. The store contains a row exactly at the training
    cutoff, plus one strictly before and one strictly after. Spies on
    `derive_glicko_calibration_slope` and `resolve_rosters` (as imported into
    `cli_d4`) capture the exact row lists each call actually receives.

    Mutation (i): change the cutoff filter's `<` to `<=` -- the at-cutoff
    probe row must then appear in the pre-cutoff refit call's rows (it will
    also trip `main`'s own redundant leakage assertion, but either way the
    test must fail rather than pass).
    Mutation (ii): pass `all_rows` instead of `train` to `resolve_rosters` --
    the at- and after-cutoff probe rows must then appear in its captured rows.
    """
    store = tmp_path / "d2.sqlite"
    _build_store(store)
    truth_path = tmp_path / "truth.yaml"
    truth_path.write_text(_truth_yaml())
    aliases_path = tmp_path / "aliases.yaml"
    aliases_path.write_text("aliases: []\n")
    out = tmp_path / "reports"

    calib_calls: list[list[int]] = []
    original_calib = cli_d4_module.derive_glicko_calibration_slope

    def calib_spy(rows, *a, **kw):
        calib_calls.append([r.match_id for r in rows])
        return original_calib(rows, *a, **kw)

    monkeypatch.setattr(cli_d4_module, "derive_glicko_calibration_slope", calib_spy)

    roster_calls: list[list[int]] = []
    original_resolve = cli_d4_module.resolve_rosters

    def resolve_spy(rows, *a, **kw):
        roster_calls.append([r.match_id for r in rows])
        return original_resolve(rows, *a, **kw)

    monkeypatch.setattr(cli_d4_module, "resolve_rosters", resolve_spy)

    rc = d4_main([
        "--truth", str(truth_path), "--aliases", str(aliases_path), "--store", str(store),
        "--out", str(out), "--min-train", "150", "--card-sims", "300", "--card-seed", "1",
        "--eval-seed", "2", "--sweep-sims", "50,80", "--sweep-seeds", "1",
        "--random-samples", "300", "--random-seed", "3",
    ])
    assert rc == 0

    assert len(calib_calls) == 2, "expected exactly two calibration measurements (refit + full-store)"
    refit_call = next(c for c in calib_calls if AFTER_MATCH_ID not in c)
    full_store_call = next(c for c in calib_calls if AFTER_MATCH_ID in c)
    assert BEFORE_MATCH_ID in refit_call
    assert AT_MATCH_ID not in refit_call
    assert AFTER_MATCH_ID not in refit_call
    # The full-store production slope is DELIBERATELY unfiltered -- it is
    # cli_card.py's own production measurement, not a training input to the
    # thing being backtested.
    assert BEFORE_MATCH_ID in full_store_call
    assert AT_MATCH_ID in full_store_call
    assert AFTER_MATCH_ID in full_store_call

    assert len(roster_calls) == 1
    resolved_rows = roster_calls[0]
    assert BEFORE_MATCH_ID in resolved_rows
    assert AT_MATCH_ID not in resolved_rows
    assert AFTER_MATCH_ID not in resolved_rows

    # The same run's real payload/report satisfy test 7's property too.
    payload = json.loads((out / "d4_card_backtest.json").read_text())
    assert "diagnostic" in payload["status"].lower()
    assert "not a gate" in payload["status"].lower()
    markdown = (out / "d4_card_backtest.md").read_text()
    assert "D4 is a diagnostic. It cannot promote, demote or alter the shipping card." in markdown
    assert f"{payload['observed_score']}/16" in markdown
    assert f"{payload['calibration_slope_refit_precutoff']:.4f}" in markdown
    assert f"{payload['calibration_slope_production_full_store']:.4f}" in markdown
