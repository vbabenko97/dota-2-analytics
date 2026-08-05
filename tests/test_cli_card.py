import csv
import json
import math
import random
import re

import pytest

from ti26.backtest import calibration as backtest_calibration
from ti26.cli_card import apply_correction, derive_glicko_calibration_slope, seed_stability
from ti26.cli_card import main as card_main
from ti26.data.schema import MapRow
from ti26.data.store import insert_rows, load_rows, open_store
from ti26.ratings.glicko import GlickoModel
from ti26.roster import RosterIndex
from ti26.rules import load_rules
from ti26.teams import TeamEntry, resolve_rosters, team_strengths

TEAM_ID_BASE = 1000
N_CONFIGURED = 16
N_TEAMS = 20  # 16 configured + 4 unconfigured "filler" rosters


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


def _true_strength(t: int) -> float:
    """Configured teams (0..15) span -1.875..+1.875 with two deliberate
    near-ties (5/6 and 10/11) so seed-to-seed Monte Carlo noise has a real
    chance of swapping a boundary slot. Unconfigured "filler" rosters
    (16..19) are deliberately MUCH stronger (+6.0ish) than every configured
    team -- fitting Glicko over the FULL store (all 20 rosters) then
    subsetting to just the 16 configured teams must therefore leave a
    NON-ZERO mean over that subset, which is what makes the re-centring
    step in `apply_correction` a real, falsifiable transformation rather
    than a tautology (a subset of a zero-mean vector is not itself
    zero-mean in general).
    """
    if t == 6:
        t = 5
    if t == 11:
        t = 10
    if t < N_CONFIGURED:
        return (t - 7.5) * 0.25
    return 6.0 + (t - N_CONFIGURED) * 0.1


def card_store(path, n_teams=N_TEAMS, n_series=600, maps_per_series=3, seed=4):
    """Same rolling-backtest-friendly shape as `test_cli_d3b.seeded_store`
    (one big early "history" league plus 32 small tournaments packed into
    the tail, so `rolling_folds` finds many usable folds quickly) -- extended
    with 4 unconfigured filler rosters that skew the configured subset's mean
    away from zero (see `_true_strength`).
    """
    rng = random.Random(seed)
    rosters = [[t * 5 + p for p in range(5)] for t in range(n_teams)]
    strength = {t: _true_strength(t) for t in range(n_teams)}
    rows_, match_id = [], 0
    for s in range(n_series):
        a, b = rng.sample(range(n_teams), 2)
        p = 1.0 / (1.0 + math.exp(-(strength[a] - strength[b])))
        league = 1 if s < 400 else 100 + (s % 32)
        for _ in range(maps_per_series):
            rows_.append(
                row(match_id, match_id * 600, league, rosters[a], rosters[b],
                    rng.random() < p, r_team=TEAM_ID_BASE + a, d_team=TEAM_ID_BASE + b,
                    series_id=s, duration=int(rng.lognormvariate(7.55, 0.33)))
            )
            match_id += 1
    conn = open_store(path)
    insert_rows(conn, rows_)
    return conn


def write_team_config(path, n_teams=N_CONFIGURED):
    lines = ["teams:"]
    for t in range(n_teams):
        lines.append(f"  - {{name: Team{t:02d}, team_id: {TEAM_ID_BASE + t}}}")
    path.write_text("\n".join(lines) + "\n")
    return path


def _configured_teams():
    return [TeamEntry(name=f"Team{t:02d}", team_id=TEAM_ID_BASE + t) for t in range(N_CONFIGURED)]


# --- Fast, pure-function unit tests (no store, no argparse) -----------------


def test_apply_correction_scales_by_the_exact_slope():
    """Catches: omitting the correction entirely (slope silently treated as
    1.0), or applying a different/hardcoded slope. Pins the exact ratio
    against the slope passed in, per this project's own warning that
    "calibrated strengths are smaller than raw" is nearly vacuous for any
    slope < 1 -- this instead checks the precise multiplicative relationship.
    """
    raw = {"A": 2.0, "B": 0.0, "C": -1.0}
    slope = 0.4023
    out = apply_correction(raw, slope)
    mean_raw_scaled = sum(v * slope for v in raw.values()) / len(raw)
    for name, value in raw.items():
        expected = value * slope - mean_raw_scaled
        assert out[name] == pytest.approx(expected, abs=1e-12)


def test_apply_correction_recentres_a_non_zero_mean_subset():
    """The re-centring step is NOT a tautology here: unlike a full zero-sum
    fit, a SUBSET of strengths (e.g. 16 configured teams out of a larger
    store) is not guaranteed to already be zero-mean. This fixture's raw
    strengths deliberately have a non-zero mean (+3.0), so a correct
    implementation must move the mean back to ~0 -- an implementation that
    skips re-centring (just `s * slope`) would leave the mean at
    `slope * 3.0 = 1.2069`, which this test would catch.
    """
    raw = {"A": 5.0, "B": 3.0, "C": 1.0}  # mean = 3.0, deliberately non-zero
    out = apply_correction(raw, slope=0.4023)
    assert sum(out.values()) / len(out) == pytest.approx(0.0, abs=1e-9)


def test_apply_correction_empty_input():
    assert apply_correction({}, 0.5) == {}


@pytest.mark.slow
def test_derive_calibration_slope_matches_a_direct_backtest_calibration_call(tmp_path):
    """`derive_glicko_calibration_slope` must be a thin wrapper around the
    same `rolling_folds` / `run_model` / `backtest.calibration` machinery
    `cli_d2` uses -- not a reimplementation and not a hardcoded literal.
    Reproduces the identical measurement independently in this test (same
    fold construction, same model factory) and requires an exact match.
    A hardcoded 0.4023 would fail this the moment the fixture's true
    measured slope differs from it (verified below: it does).
    """
    store = tmp_path / "d2.sqlite"
    card_store(store)
    rows = load_rows(open_store(store))

    from ti26.backtest import rolling_folds, run_model

    slope, intercept = derive_glicko_calibration_slope(
        rows, aliases={}, glicko_tau=0.5, min_train=150
    )

    folds = rolling_folds(rows, min_train=150)
    predictions = run_model(
        rows, lambda: GlickoModel(tau=0.5, roster_index=RosterIndex({})), folds
    )
    expected_slope, expected_intercept = backtest_calibration(predictions, rows)

    assert slope == pytest.approx(expected_slope, abs=1e-9)
    assert intercept == pytest.approx(expected_intercept, abs=1e-9)
    # Sanity: this fixture's own measured slope must not coincidentally equal
    # D2's real-store literal -- otherwise a hardcoded 0.4023 could slip
    # through the exact-match assertions above undetected.
    assert slope != pytest.approx(0.4023, abs=1e-3)


def test_derive_calibration_slope_refuses_when_no_fold_qualifies(tmp_path):
    store = tmp_path / "d2.sqlite"
    conn = open_store(store)
    insert_rows(conn, [
        row(1, 100, 1, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10], True, r_team=10, d_team=20, series_id=1)
    ])
    rows = load_rows(open_store(store))
    with pytest.raises(SystemExit, match="min-train"):
        derive_glicko_calibration_slope(rows, aliases={}, glicko_tau=0.5, min_train=500)


# --- End-to-end tests (slow: full rolling backtest + card generation) -------


@pytest.mark.slow
def test_writes_16_row_csv_and_a_card_from_our_team_names(tmp_path):
    """The 16-row CSV contract. Catches a runner that writes every roster in
    the store (not just the 16 configured teams), drops a team, or keys rows
    by roster_version_id instead of the configured team name -- and catches
    a runner that omits `--strengths` when invoking `ti26.cli.main`, which
    would fall back to D1's synthetic `t00..t15` ladder.
    """
    store = tmp_path / "d2.sqlite"
    card_store(store)
    teams_path = write_team_config(tmp_path / "teams.yaml")
    out = tmp_path / "reports"

    rc = card_main([
        "--teams", str(teams_path), "--store", str(store), "--out", str(out),
        "--min-train", "150", "--card-sims", "2000", "--card-seed", "1",
        "--stability-seeds", "1,2,3",
    ])
    assert rc == 0

    with (out / "strengths_calibrated.csv").open() as fh:
        csv_rows = list(csv.DictReader(fh))
    assert len(csv_rows) == N_CONFIGURED
    assert {r["team"] for r in csv_rows} == {f"Team{t:02d}" for t in range(N_CONFIGURED)}

    card = json.loads((out / "recommended_card.json").read_text())
    assert set(card["assignments"]) == {f"Team{t:02d}" for t in range(N_CONFIGURED)}, (
        "the card must name OUR teams, not D1's synthetic t00..t15 fallback ladder"
    )


@pytest.mark.slow
def test_correction_is_actually_applied_with_the_measured_slope_not_hardcoded(tmp_path):
    """Proves BOTH mutation classes at once: (a) omitting the correction
    (strengths written unmodified, equivalent to slope=1.0), and (b) a
    hardcoded constant (e.g. literal 0.4023) standing in for a real
    measurement. Spies on `backtest.calibration` to capture the ACTUAL slope
    `cli_card` measured this run, independently refits Glicko over the full
    store exactly as `cli_card` does to get raw strengths, and requires the
    written CSV to equal `raw * measured_slope`, re-centred.
    """
    store = tmp_path / "d2.sqlite"
    card_store(store)
    teams_path = write_team_config(tmp_path / "teams.yaml")
    out = tmp_path / "reports"

    from ti26 import cli_card as cli_card_module

    calls = []
    original = cli_card_module.calibration

    def spy(predictions, rows):
        result = original(predictions, rows)
        calls.append(result)
        return result

    import importlib
    monkeypatch_targets = [cli_card_module]
    for mod in monkeypatch_targets:
        mod.calibration = spy
    try:
        rc = card_main([
            "--teams", str(teams_path), "--store", str(store), "--out", str(out),
            "--min-train", "150", "--card-sims", "2000", "--card-seed", "1",
            "--stability-seeds", "1,2,3",
        ])
    finally:
        for mod in monkeypatch_targets:
            mod.calibration = original
        importlib.reload(cli_card_module)  # restore a clean module for later tests
    assert rc == 0
    assert len(calls) == 1, "the raw-Glicko calibration measurement must run exactly once"
    measured_slope, _measured_intercept = calls[0]

    # This fixture's filler rosters (see _true_strength) guarantee the
    # measured slope differs meaningfully from 1.0 (no correction) and from
    # D2's real-store literal 0.4023 (a hardcoded stand-in).
    assert measured_slope != pytest.approx(1.0, abs=1e-2)
    assert measured_slope != pytest.approx(0.4023, abs=1e-2)

    rows = load_rows(open_store(store))
    model = GlickoModel(tau=0.5, roster_index=RosterIndex({}))
    for r in rows:
        model.update(r)
    model.flush()
    resolved = resolve_rosters(rows, _configured_teams(), {})
    raw_strengths, _prior_driven = team_strengths(resolved, model.strengths())
    scaled = {name: s * measured_slope for name, s in raw_strengths.items()}
    mean = sum(scaled.values()) / len(scaled)
    expected = {name: s - mean for name, s in scaled.items()}

    with (out / "strengths_calibrated.csv").open() as fh:
        written = {r["team"]: float(r["strength"]) for r in csv.DictReader(fh)}

    for name, value in expected.items():
        assert written[name] == pytest.approx(value, abs=1e-5), name


@pytest.mark.slow
def _frozen_gate_artifact(path, *, d3b_slope):
    """A frozen-gate artifact whose numbers no real run of this fixture produces."""
    from ti26.gate_artifacts import gate_result_payload, write_frozen_gate_artifact

    result_paths = {}
    for gate, verdict in (("d2", "FAIL"), ("d3", "FAIL"), ("d3b", "PASS")):
        result_path = path.parent / f"{gate}_gate.json"
        result_path.write_text(
            json.dumps(
                gate_result_payload(
                    gate=gate,
                    verdict=verdict,
                    exit_code=0 if verdict == "PASS" else 1,
                    registration=f"spec section {gate}",
                    conditions={
                        "slope": {
                            "value": d3b_slope if gate == "d3b" else 0.4321,
                            "band": [0.9, 1.1],
                            "passed": verdict == "PASS",
                        },
                    },
                    method="clustered bootstrap",
                    n_maps=12345,
                    excluded={},
                    config={"bootstrap_ci": 0.975},
                )
            )
        )
        result_paths[gate] = result_path
    write_frozen_gate_artifact(result_paths, path, source_revision="b" * 40)
    return path


def test_gate_lineage_is_read_from_the_artifact_not_restated_from_a_literal(tmp_path):
    """Kills mutation: restore the D2/D3/D3b summary literals in the report.

    The module used to carry three hand-written gate summaries. They were
    accurate when written and nothing kept them accurate. The slope below is a
    value no run of this fixture produces, so it can only appear in the report
    if the report actually read the artifact -- and 0.9049, the historical
    literal, must not appear at all.
    """
    store = tmp_path / "d2.sqlite"
    card_store(store)
    teams_path = write_team_config(tmp_path / "teams.yaml")
    out = tmp_path / "reports"
    artifact = _frozen_gate_artifact(tmp_path / "frozen.json", d3b_slope=0.98765)

    rc = card_main([
        "--teams", str(teams_path), "--store", str(store), "--out", str(out),
        "--min-train", "150", "--card-sims", "2000", "--card-seed", "1",
        "--stability-seeds", "1,2,3", "--frozen-gates", str(artifact),
    ])
    assert rc == 0

    report = (out / "card_provenance.md").read_text()
    assert "0.98765" in report, "the report must render the artifact's own slope"
    assert "D3B PASS" in report
    assert "D2 FAIL" in report and "D3 FAIL" in report
    assert "b" * 40 in report, "the artifact's source revision must be named"
    for historical_literal in ("0.9049", "0.00671", "-0.00383", "0.6569"):
        assert historical_literal not in report, (
            f"{historical_literal} is a historical literal with no producer in this run"
        )


def test_card_report_refuses_to_restate_gate_lineage_without_an_artifact(tmp_path):
    """Kills mutation: fall back to the hardcoded summaries when no artifact is given.

    Silently printing remembered gate numbers is exactly the defect the
    artifact replaces, and it would be invisible in a report that looks
    complete.
    """
    store = tmp_path / "d2.sqlite"
    card_store(store)
    teams_path = write_team_config(tmp_path / "teams.yaml")
    out = tmp_path / "reports"

    rc = card_main([
        "--teams", str(teams_path), "--store", str(store), "--out", str(out),
        "--min-train", "150", "--card-sims", "2000", "--card-seed", "1",
        "--stability-seeds", "1,2,3",
    ])
    assert rc == 0

    report = (out / "card_provenance.md").read_text()
    assert "Gate lineage: not supplied for this run" in report
    for historical_literal in ("0.9049", "0.00671", "-0.00383", "0.6569"):
        assert historical_literal not in report


def test_approximation_caveat_reports_measured_ranges_and_disclaims_the_rest(tmp_path):
    """Kills mutation: infer close probability tracking from the g(phi) range alone.

    The run measures an RD attenuation range. It does not measure the
    discrepancy between the scalar strengths' implied pairwise probabilities
    and expected_score's, which is the quantity that would justify a tracking
    claim. The report must state the range it computed and disclaim the one it
    did not.
    """
    store = tmp_path / "d2.sqlite"
    card_store(store)
    teams_path = write_team_config(tmp_path / "teams.yaml")
    out = tmp_path / "reports"

    rc = card_main([
        "--teams", str(teams_path), "--store", str(store), "--out", str(out),
        "--min-train", "150", "--card-sims", "2000", "--card-seed", "1",
        "--stability-seeds", "1,2,3",
    ])
    assert rc == 0

    report = (out / "card_provenance.md").read_text()
    assert "## Approximation caveat" in report
    assert "What is NOT measured" in report
    assert "tracks the raw model's own" not in report, (
        "the report must not infer probability tracking from an attenuation range"
    )
    m = re.search(r"spans\s+\*\*([\d.]+) to ([\d.]+)\*\*", report)
    assert m is not None, "the report must state a real, computed g(phi) range"
    g_lo, g_hi = float(m.group(1)), float(m.group(2))

    from ti26.cli_card import rd_attenuation_range

    rows = load_rows(open_store(store))
    model = GlickoModel(tau=0.5, roster_index=RosterIndex({}))
    for r in rows:
        model.update(r)
    model.flush()
    resolved = resolve_rosters(rows, _configured_teams(), {})
    _expected_rd_lo, _expected_rd_hi, expected_g_lo, expected_g_hi = rd_attenuation_range(
        model, resolved
    )
    assert g_lo == pytest.approx(expected_g_lo, abs=1e-4)
    assert g_hi == pytest.approx(expected_g_hi, abs=1e-4)
    assert 0.0 < g_lo <= g_hi <= 1.0


def test_seed_stability_detects_a_genuine_tie_across_seeds():
    """Direct unit test of `seed_stability`, independent of the (stochastic,
    hard-to-force-a-tie-in) full store fixture. Two of 16 strengths are made
    EXACTLY equal, which makes their relative order within any shared
    boundary category a Monte Carlo coin flip -- searched empirically to
    reliably disagree across these 8 fixed seeds at this sim count (fully
    deterministic once seeds/n_sims are pinned, so not flaky). Catches a
    diagnostic that always reports 0 unstable teams, e.g. one that ignores
    the `seeds` argument and reuses a single simulation for every entry.
    """
    rules = load_rules("config/ti2026_rules.yaml")
    strengths = {f"T{i:02d}": (i - 7.5) * 0.3 for i in range(16)}
    strengths["T08"] = strengths["T07"]  # exact tie

    seeds = list(range(1, 9))
    cards_by_seed, unstable = seed_stability(strengths, rules, seeds, n_sims=1000)

    assert set(cards_by_seed) == set(seeds)
    for seed, card in cards_by_seed.items():
        assert set(card) == set(strengths), f"seed {seed} did not assign every team"
    assert unstable == ["T07", "T08"]


@pytest.mark.slow
def test_seed_stability_section_is_well_formed_in_the_full_report(tmp_path):
    """Wiring/format smoke test for the full pipeline: the section must
    always name every seed checked, and if any team is reported unstable,
    its row must show at least two genuinely DIFFERENT category values
    across the printed seed columns (a diagnostic that claims instability
    without ever showing a difference would be worse than no diagnostic).
    The actual seed-sensitivity MECHANISM is proven separately and
    deterministically by `test_seed_stability_detects_a_genuine_tie_across_seeds`
    above -- this fixture's own near-ties are not forced to land exactly on
    a category boundary, so requiring instability here would be fragile.
    """
    store = tmp_path / "d2.sqlite"
    card_store(store)
    teams_path = write_team_config(tmp_path / "teams.yaml")
    out = tmp_path / "reports"

    rc = card_main([
        "--teams", str(teams_path), "--store", str(store), "--out", str(out),
        "--min-train", "150", "--card-sims", "1500", "--card-seed", "1",
        "--stability-seeds", "1,2,3,4",
    ])
    assert rc == 0

    report = (out / "card_provenance.md").read_text()
    assert "## Seed-stability diagnostic" in report
    assert "seeds (1, 2, 3, 4)" in report

    stable_all = "**All teams are seed-stable across the seeds checked.**" in report
    unstable_match = re.search(r"\*\*(\d+) of (\d+) team\(s\) are NOT seed-stable", report)
    assert stable_all or unstable_match is not None

    if unstable_match:
        n_unstable = int(unstable_match.group(1))
        n_total = int(unstable_match.group(2))
        assert n_total == N_CONFIGURED
        assert 0 < n_unstable < N_CONFIGURED
        table_start = report.find("| team | seed 1")
        assert table_start != -1
        for line in report[table_start:].splitlines()[2:2 + n_unstable]:
            cols = [c.strip() for c in line.strip("|").split("|")][1:]
            assert len(set(cols)) > 1, line


@pytest.mark.slow
def test_observed_recent_form_is_reused_not_reimplemented(tmp_path, monkeypatch):
    """Spies on `public_ratings.observed_recent_form` (as imported into
    `cli_card`) to confirm it is actually called -- not reimplemented -- and
    checks the report carries the mandated caveat paragraph and reconciling
    counts, mirroring the wiring smoke test `test_cli_rung3.py` already runs
    for the same function.
    """
    store = tmp_path / "d2.sqlite"
    card_store(store)
    teams_path = write_team_config(tmp_path / "teams.yaml")
    out = tmp_path / "reports"

    from ti26 import cli_card as cli_card_module

    calls = []
    original = cli_card_module.observed_recent_form

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(cli_card_module, "observed_recent_form", spy)

    rc = card_main([
        "--teams", str(teams_path), "--store", str(store), "--out", str(out),
        "--min-train", "150", "--card-sims", "2000", "--card-seed", "1",
        "--stability-seeds", "1,2,3",
    ])
    assert rc == 0
    assert len(calls) == 1

    report = (out / "card_provenance.md").read_text()
    assert "## Observed recent form" in report
    assert "Reused directly from `public_ratings.observed_recent_form`" in report
    assert "opposition strength is not controlled" in report.lower()

    m = re.search(
        r"\*\*(\d+) consistent, (\d+) form ABOVE implied, (\d+) form BELOW implied\*\*"
        r"(, (\d+) no data)?",
        report,
    )
    assert m is not None
    consistent, above, below = int(m.group(1)), int(m.group(2)), int(m.group(3))
    no_data = int(m.group(5)) if m.group(5) else 0
    assert consistent + above + below + no_data == N_CONFIGURED


def test_team_count_mismatch_fails_loudly(tmp_path):
    teams_path = write_team_config(tmp_path / "teams.yaml", n_teams=9)
    with pytest.raises(SystemExit, match="9 teams"):
        card_main(["--teams", str(teams_path), "--out", str(tmp_path / "reports")])


def test_empty_store_fails_loudly(tmp_path):
    store = tmp_path / "empty.sqlite"
    open_store(store)
    teams_path = write_team_config(tmp_path / "teams.yaml")
    with pytest.raises(SystemExit, match="empty"):
        card_main([
            "--teams", str(teams_path), "--store", str(store),
            "--out", str(tmp_path / "reports"),
        ])
