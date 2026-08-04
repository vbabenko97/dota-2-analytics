import re

import pytest

from ti26.cli_d3b import GATE_FAIL_EXIT
from ti26.cli_d3b import main as d3b_main
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
    """Same shape/rationale as test_cli_d3's fixture: kept small since D3b
    also refits Glicko twice per fold (80% calibration fit + 100% final
    fit), but large enough for the single-stage bootstrap path (>=30
    tournaments)."""
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
def test_end_to_end_produces_a_d3b_report_with_the_required_framing(tmp_path):
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    rc = d3b_main(["--store", str(store), "--out", str(out), "--min-train", "150"])
    assert rc in (0, GATE_FAIL_EXIT)

    report = (out / "d3b_gate.md").read_text()
    assert "D3b" in report
    assert "ONE-condition test" in report
    assert "97.5%" in report
    assert "already measured" in report.lower() or "already known" in report.lower()
    assert "margin of compliance" in report.lower()
    assert "Bonferroni" in report

    if "**Verdict: FAIL**" in report:
        assert "no D3c" in report.lower() or "no d3c" in report.lower()
    else:
        assert "separate decision" in report.lower()


@pytest.mark.slow
def test_reported_verdict_agrees_with_the_measured_conditions(tmp_path):
    """Mirrors D2/D3's own internal-consistency precedent: rather than
    asserting a specific PASS/FAIL for the CI on synthetic data (brittle),
    re-derive the expected verdict from the three numbers the report itself
    prints and require them to agree."""
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    d3b_main(["--store", str(store), "--out", str(out), "--min-train", "150"])
    report = (out / "d3b_gate.md").read_text()

    verdict = re.search(r"\*\*Overall D3b verdict: (PASS|FAIL)\*\*", report).group(1)
    margin = float(
        re.search(r"mean\(LL_constant - LL_glicko_calibrated\) \| (-?[\d.]+)", report).group(1)
    )
    slope = float(re.search(r"\| calibration slope \| (-?[\d.]+) \|", report).group(1))
    ci_low, ci_high = (
        float(x) for x in re.search(r"CI excludes 0 \| \[(-?[\d.]+), (-?[\d.]+)\]", report).groups()
    )

    margin_ok = margin >= 0.003
    slope_ok = 0.9 <= slope <= 1.1
    ci_ok = not (ci_low <= 0.0 <= ci_high)
    expected = "PASS" if (margin_ok and slope_ok and ci_ok) else "FAIL"
    assert verdict == expected, (
        f"report says {verdict} but margin={margin} slope={slope} ci=[{ci_low},{ci_high}] "
        f"implies {expected}"
    )


@pytest.mark.slow
def test_cli_d3b_passes_the_975_ci_level_through_not_hardcoded_or_ignored(tmp_path, monkeypatch):
    """The required test for the code path computing the 97.5% interval.

    Asserting "the 97.5% interval is wider than the 95% one" would be true
    by construction for any correct implementation and would not catch much.
    This instead spies on the ACTUAL `ci` argument `paired_cluster_bootstrap`
    receives (via `calibrate.evaluate_d3_gate`'s call into it) and pins it to
    0.975 -- catches both "forgot to override config.bootstrap_ci" (which
    would silently pass 0.95, the D2/D3 level, straight through) and a
    hardcoded 97.5% literal that never actually reaches the bootstrap call.
    """
    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"

    from ti26 import calibrate as calibrate_module

    calls = []
    original = calibrate_module.paired_cluster_bootstrap

    def spy(diff, tournament, series, draws, ci, seed, **kw):
        calls.append(ci)
        return original(diff, tournament, series, draws, ci, seed, **kw)

    monkeypatch.setattr(calibrate_module, "paired_cluster_bootstrap", spy)

    d3b_main(["--store", str(store), "--out", str(out), "--min-train", "150"])

    assert len(calls) == 1, "the bootstrap must run exactly once for this gate"
    assert calls[0] == pytest.approx(0.975)
    assert calls[0] != pytest.approx(0.95)


@pytest.mark.slow
def test_d2_gate_config_on_disk_is_never_modified(tmp_path):
    """The 97.5% level must be applied only in memory. Reads the real
    `config/d2_gate.yaml` bytes before and after a run and requires them
    identical -- D2's own gate result must stay reproducible from that file
    untouched."""
    from pathlib import Path

    gate_config_path = Path("config/d2_gate.yaml")
    before = gate_config_path.read_bytes()

    store = tmp_path / "d2.sqlite"
    seeded_store(store)
    out = tmp_path / "reports"
    d3b_main(["--store", str(store), "--out", str(out), "--min-train", "150"])

    after = gate_config_path.read_bytes()
    assert after == before
    assert b"bootstrap_ci: 0.95" in after


def test_empty_store_fails_loudly(tmp_path):
    store = tmp_path / "empty.sqlite"
    open_store(store)
    with pytest.raises(SystemExit, match="empty"):
        d3b_main(["--store", str(store), "--out", str(tmp_path / "reports")])


def test_no_qualifying_folds_fails_loudly(tmp_path):
    store = tmp_path / "d2.sqlite"
    conn = open_store(store)
    insert_rows(conn, [row(1, 100, 1, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10], True,
                            r_team=10, d_team=20, series_id=1)])
    with pytest.raises(SystemExit, match="min-train"):
        d3b_main(["--store", str(store), "--out", str(tmp_path / "reports"), "--min-train", "500"])
