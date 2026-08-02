import csv
import json
import math

import pytest

from ti26.cli_d2 import FLOOR_REFUSED_EXIT, floor_check
from ti26.cli_d2 import main as d2_main
from ti26.data.schema import MapRow
from ti26.data.store import insert_rows, open_store

WEEK = 604800


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


def seeded_store(path, n_teams=16, n_series=1200, maps_per_series=3):
    """Deterministic ladder: lower-indexed rosters are genuinely stronger.

    Team ids are `1000 + index` so `config/ti2026_teams.yaml` fixtures can
    reference them; `hash()` would vary with PYTHONHASHSEED. Maps are grouped
    into real series so the clustered bootstrap has clusters to resample, and
    tournaments are spread across many league ids so the single-stage path is
    the one actually exercised.
    """
    import random

    rng = random.Random(4)
    rosters = [[t * 5 + p for p in range(5)] for t in range(n_teams)]
    strength = {t: (n_teams - t) * 0.2 for t in range(n_teams)}
    rows, match_id = [], 0
    for s in range(n_series):
        a, b = rng.sample(range(n_teams), 2)
        p = 1 / (1 + pow(2.718281828, -(strength[a] - strength[b])))
        # First 900 series are history; the rest are spread over 40 tournaments
        # so `rolling_folds` produces enough folds for tournament clustering.
        league = 1 if s < 900 else 100 + (s % 40)
        for _ in range(maps_per_series):
            rows.append(
                row(match_id, match_id * 600, league, rosters[a], rosters[b],
                    rng.random() < p, r_team=1000 + a, d_team=1000 + b, series_id=s,
                    duration=int(rng.lognormvariate(7.55, 0.33)))
            )
            match_id += 1
    conn = open_store(path)
    insert_rows(conn, rows)
    return conn


def noise_store(path, n_teams=16, n_series=1200, maps_per_series=3):
    """Same shape as `seeded_store`, but with ZERO true skill signal.

    Every pairing is an exact coin flip regardless of matchup, so any model
    that reacts to noisy outcomes (Elo, Glicko) will systematically predict
    away from 0.5 and pay for it in expected log loss, while the constant
    model pays exactly ln(2) by construction. This is what makes a rating
    model lose to the spec V floor without hand-tuning a "bad" model --
    empirically confirmed for this exact seed: elo log loss 0.7185 vs
    constant's 0.6931 (see task-8-report.md), a ~0.025 nat/map gap, far
    above float noise.
    """
    import random

    rng = random.Random(4)
    rosters = [[t * 5 + p for p in range(5)] for t in range(n_teams)]
    rows, match_id = [], 0
    for s in range(n_series):
        a, b = rng.sample(range(n_teams), 2)
        league = 1 if s < 900 else 100 + (s % 40)
        for _ in range(maps_per_series):
            rows.append(
                row(match_id, match_id * 600, league, rosters[a], rosters[b],
                    rng.random() < 0.5, r_team=1000 + a, d_team=1000 + b, series_id=s,
                    duration=int(rng.lognormvariate(7.55, 0.33)))
            )
            match_id += 1
    conn = open_store(path)
    insert_rows(conn, rows)
    return conn


def write_team_config(path, n_teams=16):
    lines = ["teams:"]
    for t in range(n_teams):
        lines.append(f"  - {{name: Team{t:02d}, team_id: {1000 + t}}}")
    path.write_text("\n".join(lines) + "\n")
    return path


def test_end_to_end_produces_a_gate_report_and_metrics(tmp_path):
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    assert d2_main(
        ["--store", str(store), "--out", str(out), "--min-train", "200", "--skip-card"]
    ) == 0

    report = (out / "d2_gate.md").read_text()
    assert "**Verdict:" in report
    assert "0.003" in report, "the pre-registered margin must appear in the report"
    assert "cluster" in report.lower(), "the interval method must be stated"

    with (out / "backtest_metrics.csv").open() as fh:
        metrics = {r["model"]: r for r in csv.DictReader(fh)}
    assert set(metrics) == {"constant", "ewma", "elo", "glicko"}
    # ConstantModel always predicts exactly 0.5, so its aggregate log loss
    # over ANY rated population is the exact constant ln(2) -- not a
    # statistical estimate, so a tight tolerance costs nothing. This is now
    # the spec V floor value itself (see floor_check), so pin it precisely:
    # a bug that let even a few rows see a non-0.5 prediction, or that
    # aggregated over the wrong population, would move this measurably
    # above float-summation noise but still hide under the old abs=1e-3.
    assert float(metrics["constant"]["log_loss"]) == pytest.approx(math.log(2), abs=1e-9)


def test_the_card_is_built_from_fitted_strengths_not_the_synthetic_ladder(tmp_path):
    """THE end-to-end test for this task.

    D1's `cli.py` falls back to a synthetic ladder when `--strengths` is
    absent, so a runner that forgets to pass it still writes a plausible card
    and every other assertion here would pass. Pinning the card to the
    strengths file is what makes the pipeline real.
    """
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    teams = write_team_config(tmp_path / "teams.yaml")

    assert d2_main([
        "--store", str(store), "--out", str(out), "--min-train", "200",
        "--teams", str(teams), "--card-sims", "3000", "--card-seed", "7",
    ]) == 0

    with (out / "strengths.csv").open() as fh:
        strengths = list(csv.DictReader(fh))
    assert len(strengths) == 16
    assert {r["team"] for r in strengths} == {f"Team{t:02d}" for t in range(16)}
    assert len({r["strength"] for r in strengths}) > 1, "a flat vector means nothing was fitted"

    card = json.loads((out / "recommended_card.json").read_text())
    assert set(card["assignments"]) == {f"Team{t:02d}" for t in range(16)}, (
        "the card must name OUR teams; the synthetic ladder would emit t00..t15"
    )


def test_missing_teams_fail_loudly_rather_than_shipping_a_partial_card(tmp_path):
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    teams = write_team_config(tmp_path / "teams.yaml", n_teams=9)
    with pytest.raises(SystemExit, match="9 teams"):
        d2_main([
            "--store", str(store), "--out", str(tmp_path / "reports"),
            "--min-train", "200", "--teams", str(teams),
        ])


def test_duration_sensitivity_is_reported(tmp_path):
    """Spec XII requires reporting how far the card moves with the duration
    parameter, not just fitting it."""
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    teams = write_team_config(tmp_path / "teams.yaml")
    d2_main([
        "--store", str(store), "--out", str(out), "--min-train", "200",
        "--teams", str(teams), "--card-sims", "3000",
    ])
    sweep = json.loads((out / "duration_sensitivity.json").read_text())
    assert sweep[0]["is_baseline"] is True
    assert len(sweep) >= 3
    assert all("max_abs_delta" in s for s in sweep)


def test_rating_models_beat_the_constant_floor_on_separable_data(tmp_path):
    """If Elo cannot beat 50/50 on a deterministic ladder, the harness is
    broken -- this is the sanity check that the wiring works at all, and it
    is distinct from the gate, which compares Elo against Glicko.

    `--skip-card`: this test cares only about backtest_metrics.csv. Without
    it, `d2_main` falls back to the real `config/ti2026_teams.yaml`, whose
    real OpenDota team_ids can never match this fixture's synthetic
    `1000+i` ids -- deviation from the brief, see task-8-report.md.
    """
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    d2_main(["--store", str(store), "--out", str(out), "--min-train", "200", "--skip-card"])
    with (out / "backtest_metrics.csv").open() as fh:
        metrics = {r["model"]: float(r["log_loss"]) for r in csv.DictReader(fh)}
    assert metrics["elo"] < metrics["constant"]
    assert metrics["glicko"] < metrics["constant"]


def test_floor_check_disqualifies_a_worse_model_and_clears_a_better_one():
    """Spec V, tested in isolation from any backtest: a model with a HIGHER
    (worse) log loss than the constant floor must not clear it, and one with
    a LOWER (better) log loss must. Margins here (0.70 vs 0.6931, 0.65 vs
    0.6931 -- roughly 0.007 and 0.043 nats) are far above float precision on
    purpose, per the coordinator's warning: a fixture where models tie, or
    where the "worse" model is worse by less than float noise, would pass
    under a broken (`<=`, inverted, or no-op) comparison. This test catches
    exactly those: an inverted `>` would flip both assertions; a `<=` would
    wrongly clear an exact tie (checked separately below).
    """
    metrics = {
        "constant": {"log_loss": 0.693147},
        "elo": {"log_loss": 0.70},
        "glicko": {"log_loss": 0.65},
    }
    floor = floor_check(metrics)

    assert floor["elo"]["cleared"] is False, "0.70 > 0.693147: elo is worse, must not clear"
    assert floor["glicko"]["cleared"] is True, "0.65 < 0.693147: glicko is better, must clear"
    assert floor["elo"]["diff"] == pytest.approx(0.70 - 0.693147)
    assert floor["glicko"]["diff"] == pytest.approx(0.65 - 0.693147)
    # The floor model can never clear its own bar -- a model "beating" itself
    # is not a beat, and a bug that compared floor_name == floor_name loosely
    # (e.g. `<=`) would wrongly mark this True.
    assert floor["constant"]["cleared"] is False

    # Exact tie: a `<=` comparison would wrongly clear this.
    tied = floor_check({"constant": {"log_loss": 0.6931}, "elo": {"log_loss": 0.6931}})
    assert tied["elo"]["cleared"] is False, "an exact tie is not a beat"


def test_disqualified_final_model_writes_no_card_and_exits_with_the_floor_code(tmp_path):
    """End-to-end: on data with zero true skill signal, Elo's out-of-sample
    log loss is measurably worse than the constant floor (confirmed for this
    fixture: 0.7185 vs 0.6931). `--final-model elo` pins the disqualified
    model directly rather than relying on which model "auto" happens to pick.

    Catches a runner that computes the floor table but never enforces it
    (the bug this whole fix round exists to close): if `cli_d2` still wrote
    `strengths.csv`/`recommended_card.json` and returned 0, this test fails.
    """
    store = tmp_path / "d2.sqlite"
    noise_store(store)
    out = tmp_path / "reports"
    teams = write_team_config(tmp_path / "teams.yaml")

    rc = d2_main([
        "--store", str(store), "--out", str(out), "--min-train", "200",
        "--teams", str(teams), "--final-model", "elo",
    ])

    assert rc == FLOOR_REFUSED_EXIT
    assert rc != 0
    assert not (out / "strengths.csv").exists()
    assert not (out / "recommended_card.json").exists()
    assert not (out / "duration_sensitivity.json").exists()

    report = (out / "d2_gate.md").read_text()
    assert "REFUSED" in report
    assert "does not beat the constant floor" in report
    assert "No card ships from our fit" in report
    # The old bug this fix closes: Card and Consequence sections must not
    # disagree about whether a card was produced.
    assert "generated from elo strengths" not in report


def test_duration_fit_is_written_and_differs_from_the_placeholder(tmp_path):
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    d2_main(["--store", str(store), "--out", str(out), "--min-train", "200", "--skip-card"])
    fit = json.loads((out / "duration_fit.json").read_text())
    assert fit["n"] > 500
    assert abs(fit["log_sigma"] - 0.25) > 0.02, "fitted, not the placeholder"


def test_empty_store_fails_loudly(tmp_path):
    store = tmp_path / "empty.sqlite"
    open_store(store)
    with pytest.raises(SystemExit, match="empty"):
        d2_main(["--store", str(store), "--out", str(tmp_path / "reports")])


def test_reported_verdict_agrees_with_the_reported_numbers(tmp_path):
    """A report that says PASS regardless is worse than no report.

    Asserting a specific verdict on synthetic data would be brittle -- which
    model wins on a toy ladder is not something this plan should predict.
    What must ALWAYS hold is internal consistency: the verdict printed has to
    follow from the margin and CI printed beside it, under the two
    pre-registered conditions. A hardcoded verdict fails this on some run.
    """
    import re

    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    d2_main(["--store", str(store), "--out", str(out), "--min-train", "200", "--skip-card"])
    report = (out / "d2_gate.md").read_text()

    verdict = re.search(r"\*\*Verdict: (PASS|FAIL)\*\*", report).group(1)
    margin = float(re.search(r"Observed margin: \*\*(-?[\d.]+)\*\*", report).group(1))
    ci_low = float(re.search(r"CI \[(-?[\d.]+),", report).group(1))

    expected = "PASS" if (margin >= 0.003 and ci_low > 0.0) else "FAIL"
    assert verdict == expected, (
        f"report says {verdict} but margin={margin} ci_low={ci_low} implies {expected}"
    )
    if verdict == "FAIL":
        assert "Do not proceed to D3" in report
    else:
        assert "Proceed to D3" in report
