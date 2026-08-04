import csv
import re

import pytest

from ti26.cli_d3 import GATE_FAIL_EXIT
from ti26.cli_d3 import main as d3_main
from ti26.data.schema import MapRow
from ti26.data.store import insert_rows, open_store


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


def seeded_store(path, n_teams=16, n_series=600, maps_per_series=3):
    """Deterministic ladder: lower-indexed rosters are genuinely stronger.

    Smaller than test_cli_d2's fixture (which runs a 4-model x ~40-fold
    backtest): D3 refits TWO model instances per fold per candidate (the
    80% calibration fit plus the 100% final fit), for two candidates
    (Elo, Glicko), so the same tournament count costs roughly twice what
    D2's per-model refit did. Kept just large enough for the single-stage
    bootstrap path (>=30 tournaments) while staying fast.
    """
    import random

    rng = random.Random(4)
    rosters = [[t * 5 + p for p in range(5)] for t in range(n_teams)]
    strength = {t: (n_teams - t) * 0.2 for t in range(n_teams)}
    rows, match_id = [], 0
    for s in range(n_series):
        a, b = rng.sample(range(n_teams), 2)
        p = 1 / (1 + pow(2.718281828, -(strength[a] - strength[b])))
        league = 1 if s < 400 else 100 + (s % 32)
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


@pytest.mark.slow
def test_end_to_end_produces_a_gate_report_and_metrics(tmp_path):
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    rc = d3_main(["--store", str(store), "--out", str(out), "--min-train", "150"])
    assert rc in (0, GATE_FAIL_EXIT)

    report = (out / "d3_gate.md").read_text()
    assert "**Verdict:" in report
    assert "0.003" in report, "the pre-registered margin must appear in the report"
    assert "[0.9, 1.1]" in report, "the pre-registered slope band must appear in the report"
    assert "cluster" in report.lower(), "the interval method must be stated"
    assert "| condition | measured | required | result |" in report

    with (out / "d3_metrics.csv").open() as fh:
        rows = {r["model"]: r for r in csv.DictReader(fh)}
    assert set(rows) == {"constant", "elo_calibrated", "glicko_calibrated_diagnostic"}


@pytest.mark.slow
def test_reported_verdict_agrees_with_the_three_measured_conditions(tmp_path):
    """Mirrors D2's own internal-consistency test: rather than asserting a
    specific PASS/FAIL (brittle -- the actual outcome on synthetic data is
    not something this task should predict), re-derive the expected verdict
    from the three measured numbers the report itself prints and require
    them to agree.
    """
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    d3_main(["--store", str(store), "--out", str(out), "--min-train", "150"])
    report = (out / "d3_gate.md").read_text()

    verdict = re.search(r"\*\*Verdict: (PASS|FAIL)\*\*", report).group(1)
    margin = float(re.search(r"mean\(LL_constant - LL_calibrated\) \| (-?[\d.]+)", report).group(1))
    ci_low, ci_high = (
        float(x) for x in re.search(r"CI excludes 0 \| \[(-?[\d.]+), (-?[\d.]+)\]", report).groups()
    )
    slope = float(re.search(r"\| calibration slope \| (-?[\d.]+) \|", report).group(1))

    margin_ok = margin >= 0.003
    ci_ok = not (ci_low <= 0.0 <= ci_high)
    slope_ok = 0.9 <= slope <= 1.1
    expected = "PASS" if (margin_ok and ci_ok and slope_ok) else "FAIL"
    assert verdict == expected, (
        f"report says {verdict} but margin={margin} ci=[{ci_low},{ci_high}] slope={slope} "
        f"implies {expected}"
    )
    if verdict == "FAIL":
        assert "D3 stops here" in report
        assert "rung-3 public-ratings card ships" in report
    else:
        assert "Proceed to D3" in report


@pytest.mark.slow
def test_gate_failure_states_the_rung_3_consequence_plainly(tmp_path):
    """An unreachable margin forces FAIL regardless of the data, so the
    'rung-3 ships, D3 stops' consequence text is exercised deterministically
    rather than depending on which way the synthetic ladder happens to fall.
    """
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"

    gate_config = tmp_path / "gate.yaml"
    gate_config.write_text(
        "gate:\n"
        "  min_margin_nats: 5.0\n"  # unreachable on any data -- forces FAIL
        "  bootstrap_draws: 500\n"
        "  bootstrap_ci: 0.95\n"
        "  seed: 20260802\n"
        "hyperparameters:\n"
        "  elo_k: 20.0\n"
        "  glicko_tau: 0.5\n"
        "  ewma_half_life_maps: 30.0\n"
    )

    rc = d3_main([
        "--store", str(store), "--out", str(out), "--min-train", "150",
        "--gate-config", str(gate_config),
    ])
    assert rc == GATE_FAIL_EXIT

    report = (out / "d3_gate.md").read_text()
    assert "**Verdict: FAIL**" in report
    assert "**D3 stops here.**" in report
    assert "rung-3 public-ratings card ships" in report
    assert "no custom Bradley-Terry model is built" in report


@pytest.mark.slow
def test_glicko_is_reported_as_a_diagnostic_and_never_gates(tmp_path, monkeypatch):
    """Spec (registered 2026-08-03): Elo is the primary and ONLY gated
    candidate; calibrated Glicko is computed and reported but never gated or
    substituted. Spies on the actual call into `evaluate_d3_gate` and proves
    the slope passed in is Elo's, not Glicko's -- catches an accidental
    swap, not just wording in the report.
    """
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"

    from ti26 import cli_d3

    calls = []
    original = cli_d3.evaluate_d3_gate

    def spy(predictions_constant, predictions_candidate, rows, config, slope, intercept, **kw):
        calls.append(slope)
        return original(predictions_constant, predictions_candidate, rows, config, slope, intercept, **kw)

    monkeypatch.setattr(cli_d3, "evaluate_d3_gate", spy)

    d3_main(["--store", str(store), "--out", str(out), "--min-train", "150"])
    assert len(calls) == 1, "the gate must be evaluated exactly once, not once per candidate"

    with (out / "d3_metrics.csv").open() as fh:
        metrics = {r["model"]: r for r in csv.DictReader(fh)}
    elo_slope = float(metrics["elo_calibrated"]["calibration_slope"])
    glicko_slope = float(metrics["glicko_calibrated_diagnostic"]["calibration_slope"])

    assert calls[0] == pytest.approx(elo_slope)
    assert elo_slope != pytest.approx(glicko_slope), (
        "elo and glicko slopes must differ meaningfully, or a swap could pass this "
        "test by coincidence"
    )
    assert calls[0] != pytest.approx(glicko_slope)

    report = (out / "d3_gate.md").read_text()
    assert "diagnostic" in report.lower()
    assert "never gated" in report.lower() or "never gates" in report.lower()


def test_empty_store_fails_loudly(tmp_path):
    store = tmp_path / "empty.sqlite"
    open_store(store)
    with pytest.raises(SystemExit, match="empty"):
        d3_main(["--store", str(store), "--out", str(tmp_path / "reports")])


def test_no_qualifying_folds_fails_loudly(tmp_path):
    store = tmp_path / "d2.sqlite"
    conn = open_store(store)
    insert_rows(conn, [row(1, 100, 1, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10], True,
                            r_team=10, d_team=20, series_id=1)])
    with pytest.raises(SystemExit, match="min-train"):
        d3_main(["--store", str(store), "--out", str(tmp_path / "reports"), "--min-train", "500"])
