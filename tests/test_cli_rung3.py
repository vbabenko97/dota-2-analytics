import csv
import json
import math
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ti26.cli_rung3 import main as rung3_main
from ti26.data.schema import MapRow
from ti26.data.store import insert_rows, open_store

TEAM_ID_BASE = 1000
N_TEAMS = 16


def row(match_id, start_time, radiant, dire, radiant_win, r_team, d_team, series_id, duration=2000):
    return MapRow(
        match_id=match_id, start_time=start_time, duration=duration, radiant_win=radiant_win,
        league_id=1, tier="professional", radiant_team_id=r_team, dire_team_id=d_team,
        series_id=series_id, series_type=1, patch="7.41",
        radiant_accounts=tuple(radiant), dire_accounts=tuple(dire),
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=False, has_bad_roster=False,
    )


def small_store(path, n_teams=N_TEAMS):
    """Every configured team_id fields at least one series as radiant and one
    as dire -- enough for `resolve_rosters`/`latest_rosters` to find every
    team's current roster and for a single Elo pass to rate every roster,
    without needing the fold/backtest machinery cli_rung3 does not use.
    """
    rosters = [[t * 5 + p for p in range(5)] for t in range(n_teams)]
    rows, match_id = [], 0
    for i in range(n_teams):
        a, b = i, (i + 1) % n_teams
        for g in range(3):
            rows.append(
                row(match_id, match_id * 600, rosters[a], rosters[b], (a + g) % 2 == 0,
                    TEAM_ID_BASE + a, TEAM_ID_BASE + b, series_id=i)
            )
            match_id += 1
    conn = open_store(path)
    insert_rows(conn, rows)
    return conn


def write_team_config(path, n_teams=N_TEAMS):
    lines = ["teams:"]
    for t in range(n_teams):
        lines.append(f"  - {{name: Team{t:02d}, team_id: {TEAM_ID_BASE + t}}}")
    path.write_text("\n".join(lines) + "\n")
    return path


def fake_transport(rows):
    payload = json.dumps({"err": None, "rows": rows}).encode()

    def transport(url):
        return payload

    return transport


def rating_row(team_id, rating, wins=1000, losses=800, stale_days=1.0, now_ts=None):
    now_ts = now_ts if now_ts is not None else int(time.time())
    last_match_time = now_ts - int(stale_days * 86400)
    return {
        "team_id": str(team_id),  # bigint -> JSON string, like the real explorer
        "rating": float(rating),
        "wins": wins,
        "losses": losses,
        "last_match_time": str(last_match_time),
    }


def full_rating_rows(n_teams=N_TEAMS, now_ts=None):
    return [
        rating_row(TEAM_ID_BASE + i, rating=1300.0 + i * 15.0, now_ts=now_ts)
        for i in range(n_teams)
    ]


@pytest.mark.slow
def test_writes_16_strength_rows_and_a_card_from_our_team_names(tmp_path):
    """End-to-end happy path. Catches: a runner that writes the wrong row
    count, or that invokes D1's `cli.main` without `--strengths` -- D1 falls
    back to a synthetic t00..t15 ladder in that case (the exact bug the D2
    build's own end-to-end test guards against), which would make the card
    name synthetic teams instead of ours.
    """
    small_store(tmp_path / "d2.sqlite")
    teams = write_team_config(tmp_path / "teams.yaml")
    out = tmp_path / "reports"

    rc = rung3_main(
        [
            "--teams", str(teams), "--store", str(tmp_path / "d2.sqlite"),
            "--out", str(out), "--card-sims", "3000", "--sweep-sims", "2000",
        ],
        transport=fake_transport(full_rating_rows()),
    )
    assert rc == 0

    with (out / "strengths_public.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 16
    assert {r["team"] for r in rows} == {f"Team{t:02d}" for t in range(16)}
    assert len({r["strength"] for r in rows}) > 1, "a flat vector means nothing was converted"

    card = json.loads((out / "recommended_card.json").read_text())
    assert set(card["assignments"]) == {f"Team{t:02d}" for t in range(16)}, (
        "the card must name OUR teams, not D1's synthetic t00..t15 fallback ladder"
    )

    provenance = (out / "rung3_provenance.md").read_text()
    assert "inferred" in provenance
    assert "datdota" in provenance
    assert "unreachable" in provenance
    assert "403" in provenance
    assert "Elo-ordering" in provenance

    sweep = json.loads((out / "rung3_scale_sensitivity.json").read_text())
    assert sweep[0]["is_baseline"] is True
    assert len(sweep) == 3


def test_missing_team_rating_stops_without_writing_a_card(tmp_path):
    """Spec requirement: a team with no team_rating row must halt the run
    rather than default to a fabricated strength. Catches a runner that
    substitutes 0.0 (or any default) for a missing team instead of refusing.
    """
    small_store(tmp_path / "d2.sqlite")
    teams = write_team_config(tmp_path / "teams.yaml")
    out = tmp_path / "reports"

    incomplete_rows = full_rating_rows()[:-1]  # drop Team15's rating row

    with pytest.raises(SystemExit, match="team_rating row"):
        rung3_main(
            [
                "--teams", str(teams), "--store", str(tmp_path / "d2.sqlite"),
                "--out", str(out), "--card-sims", "3000", "--sweep-sims", "2000",
            ],
            transport=fake_transport(incomplete_rows),
        )
    assert not (out / "strengths_public.csv").exists()


def test_null_rating_field_stops_without_writing_a_card(tmp_path):
    """FIX C (2026-08-02 rung-3 review, Finding 3): a team_rating row that IS
    present but carries a null field (as opposed to Finding 3's sibling
    case, the row being absent entirely -- see
    `test_missing_team_rating_stops_without_writing_a_card` above) must stop
    the run the same way: `SystemExit`, no card, no fabricated strength, and
    -- unlike before this fix -- a message naming the team and the null
    field rather than an unhandled `TypeError` stack trace.
    """
    small_store(tmp_path / "d2.sqlite")
    teams = write_team_config(tmp_path / "teams.yaml")
    out = tmp_path / "reports"

    rows = full_rating_rows()
    null_team_id = TEAM_ID_BASE + 5
    for r in rows:
        if int(r["team_id"]) == null_team_id:
            r["rating"] = None

    with pytest.raises(SystemExit, match="Team05.*null 'rating'"):
        rung3_main(
            [
                "--teams", str(teams), "--store", str(tmp_path / "d2.sqlite"),
                "--out", str(out), "--card-sims", "3000", "--sweep-sims", "2000",
            ],
            transport=fake_transport(rows),
        )
    assert not (out / "strengths_public.csv").exists()


@pytest.mark.slow
def test_thin_and_stale_teams_are_flagged_in_the_provenance_report(tmp_path):
    """Catches a runner that computes the thin/stale flags but never
    surfaces them in the report -- the 'instrument built, never consumed'
    pattern this codebase's own D2 ledger flags repeatedly. One team is
    given a deliberately thin (100 games) AND stale (40 days) rating; all
    others are thick and fresh.
    """
    small_store(tmp_path / "d2.sqlite")
    teams = write_team_config(tmp_path / "teams.yaml")
    out = tmp_path / "reports"

    rows = full_rating_rows()
    thin_stale_team_id = TEAM_ID_BASE + 3
    for r in rows:
        if int(r["team_id"]) == thin_stale_team_id:
            r["wins"], r["losses"] = 50, 50
            r["last_match_time"] = str(int(time.time()) - 40 * 86400)

    rc = rung3_main(
        [
            "--teams", str(teams), "--store", str(tmp_path / "d2.sqlite"),
            "--out", str(out), "--card-sims", "3000", "--sweep-sims", "2000",
        ],
        transport=fake_transport(rows),
    )
    assert rc == 0

    provenance = (out / "rung3_provenance.md").read_text()
    assert "1 thin team(s):** Team03" in provenance
    assert "1 stale team(s):** Team03" in provenance


@pytest.mark.slow
def test_elo_anchor_reports_a_real_rank_correlation_and_top4_overlap(tmp_path):
    """Spec V rung 6: our Elo is disqualified as a strength SOURCE but its
    ORDERING must still be checked against rung 3's ordering. Catches a
    runner that never computes the anchor, or that reports a placeholder
    (e.g. nan or a hardcoded 0) instead of a real correlation from the
    locally-fitted Elo model.

    Both assertions pin the ACTUAL value for this deterministic fixture, not
    a range: `0 <= overlap <= 4` is satisfied by a hardcoded `0` (this was
    the rung-3 review's Finding 2 -- confirmed by mutation: hardcoding
    `top4_overlap = 0` in `cli_rung3.py` still passed the old range
    assertion). `small_store`'s round-robin Elo fit and `full_rating_rows`'
    monotonic-in-index public ratings are both fully deterministic, so the
    correlation and overlap are fixed for this fixture: public rating orders
    the field purely by index (Team12..Team15 top-4), while the round-robin
    Elo fit does not fully agree with that ordering (rank correlation 0.40;
    top-4 by Elo is Team08/Team10/Team12/Team14, overlapping the public
    top-4 in exactly Team12 and Team14).
    """
    small_store(tmp_path / "d2.sqlite")
    teams = write_team_config(tmp_path / "teams.yaml")
    out = tmp_path / "reports"

    rc = rung3_main(
        [
            "--teams", str(teams), "--store", str(tmp_path / "d2.sqlite"),
            "--out", str(out), "--card-sims", "3000", "--sweep-sims", "2000",
        ],
        transport=fake_transport(full_rating_rows()),
    )
    assert rc == 0

    provenance = (out / "rung3_provenance.md").read_text()
    m = re.search(r"rank correlation.*?\*\*(-?[\d.]+)\*\*", provenance)
    assert m is not None, "the report must state a numeric rank correlation"
    assert not math.isnan(float(m.group(1)))
    assert float(m.group(1)) == pytest.approx(0.4000, abs=1e-4), (
        "this fixture's Elo fit and public ratings are both deterministic -- "
        "the rank correlation must be the actual computed 0.4000, not any "
        "other placeholder value"
    )

    m2 = re.search(r"Top-4 overlap: \*\*(\d) of 4\*\*", provenance)
    assert m2 is not None
    assert int(m2.group(1)) == 2, (
        "must be the actual overlap between Team12-Team15 (public top-4) and "
        "Team08/Team10/Team12/Team14 (Elo top-4) -- exactly 2 -- not a "
        "hardcoded value that merely happens to satisfy 0 <= x <= 4"
    )


@pytest.mark.slow
def test_boundary_proximity_and_fetch_timestamp_appear_in_the_report(tmp_path):
    """FIX D (2026-08-02 rung-3 review, Finding 4): the report must state
    plainly when the ratings snapshot was fetched, and must surface a
    boundary-proximity table so a reader knows the card is a moving target.
    `full_rating_rows`' rating is a constant +15.0-per-index step, so EVERY
    adjacent pair in the (rating-order-preserving) strength ordering has an
    identical, exactly-computable 15.00-rating-point gap -- below the
    17.74-point threshold, so all 15 adjacent pairs (16 teams) must be
    flagged.
    """
    small_store(tmp_path / "d2.sqlite")
    teams = write_team_config(tmp_path / "teams.yaml")
    out = tmp_path / "reports"

    before = datetime.now(UTC)
    rc = rung3_main(
        [
            "--teams", str(teams), "--store", str(tmp_path / "d2.sqlite"),
            "--out", str(out), "--card-sims", "3000", "--sweep-sims", "2000",
        ],
        transport=fake_transport(full_rating_rows()),
    )
    after = datetime.now(UTC)
    assert rc == 0

    provenance = (out / "rung3_provenance.md").read_text()

    m = re.search(r"Ratings snapshot valid as of: (\S+) \(UTC\)", provenance)
    assert m is not None, "the report must state the fetch timestamp plainly"
    fetched_at = datetime.fromisoformat(m.group(1))
    assert before <= fetched_at <= after, (
        "the stated timestamp must be a real capture from during this run, "
        "not a placeholder or a stale wall-clock read from outside it"
    )

    section_idx = provenance.find("## Boundary-proximity diagnostic")
    assert section_idx != -1
    section = provenance[section_idx:]
    gap_lines = [
        line for line in section.splitlines()
        if line.startswith("| Team")
    ]
    assert len(gap_lines) == N_TEAMS - 1, "16 teams -> 15 adjacent pairs"
    for line in gap_lines:
        cols = [c.strip() for c in line.strip("|").split("|")]
        assert cols[2] == "0.0863", f"constant +15-per-index rating step: {line}"
        assert cols[3] == "15.00", f"constant +15-per-index rating step: {line}"
        assert cols[4] == "YES", "15.00 < 17.74-point threshold must be flagged"
    assert f"**{N_TEAMS - 1} of {N_TEAMS - 1} adjacent pair(s) flagged.**" in provenance


def test_anchor_k_comes_from_the_gate_config_not_a_hardcoded_default(tmp_path):
    """The Elo anchor is only a valid comparison against D2's backtest if it
    uses the SAME k that backtest used, and that value lives in the gate
    config. Catches a runner that hardcodes a numeric default: this config
    says 37.5, so a hardcoded 20.0 would be reported instead and the anchor
    would silently be against a model we never evaluated.

    Asserts the k is READ, not that it equals the repo's current 20.0 --
    otherwise the test would pass against exactly the hardcoded default it
    exists to forbid.
    """
    small_store(tmp_path / "d2.sqlite")
    teams = write_team_config(tmp_path / "teams.yaml")
    gate = tmp_path / "gate.yaml"
    gate.write_text(
        (Path("config/d2_gate.yaml").read_text()).replace("elo_k: 20.0", "elo_k: 37.5")
    )
    assert "37.5" in gate.read_text(), "fixture must actually differ from the default"
    out = tmp_path / "reports"

    rc = rung3_main(
        [
            "--teams", str(teams), "--store", str(tmp_path / "d2.sqlite"),
            "--gate-config", str(gate), "--out", str(out),
            "--card-sims", "3000", "--sweep-sims", "2000",
        ],
        transport=fake_transport(full_rating_rows()),
    )
    assert rc == 0

    provenance = (out / "rung3_provenance.md").read_text()
    assert "elo_k=37.5" in provenance, "the anchor must use the k from the gate config"
    assert "elo_k=20.0" not in provenance


@pytest.mark.slow
def test_observed_recent_form_section_appears_with_caveats_and_reconciling_counts(tmp_path, capsys):
    """Wiring smoke test: catches a report writer that computes the observed-
    recent-form diagnostic but never renders it (the "instrument built,
    never consumed" pattern this codebase's own reports repeatedly flag), or
    that drops either mandated caveat paragraph, or whose printed one-line
    stdout summary doesn't reconcile with the table it just wrote.
    """
    small_store(tmp_path / "d2.sqlite")
    teams = write_team_config(tmp_path / "teams.yaml")
    out = tmp_path / "reports"

    rc = rung3_main(
        [
            "--teams", str(teams), "--store", str(tmp_path / "d2.sqlite"),
            "--out", str(out), "--card-sims", "3000", "--sweep-sims", "2000",
        ],
        transport=fake_transport(full_rating_rows()),
    )
    assert rc == 0

    provenance = (out / "rung3_provenance.md").read_text()
    assert "## Observed recent form" in provenance
    assert "Opposition strength is not controlled" in provenance
    # This fixture's implied/observed rates coincide for every team (see
    # test_elo_anchor_reports_a_real_rank_correlation_and_top4_overlap's
    # docstring for why the fixture is fully deterministic), so the real,
    # computed distribution is 16 consistent / 0 above / 0 below -- the
    # rendered paragraph must say so, not a stale literal from a past run
    # (rung-3 review Finding 1 / FIX A).
    assert "No deviations this run:** all 16 team(s)" in provenance
    assert "| team | strength | implied | observed | n | 95% Wilson CI | verdict |" in provenance

    captured = capsys.readouterr()
    m = re.search(
        r"observed form (\d+) consistent, (\d+) above implied, (\d+) below implied", captured.out
    )
    assert m is not None, "must print the one-line observed-form stdout summary"
    consistent, above, below = (int(x) for x in m.groups())
    assert consistent + above + below == N_TEAMS, (
        "every team in this fixture plays maps, so the printed verdict counts "
        "must add up to all 16 configured teams with none left as 'no data'"
    )


def test_team_count_mismatch_fails_loudly(tmp_path):
    """Catches a runner that silently proceeds (or crashes obscurely) when
    the teams file does not have as many entries as the rules require,
    instead of failing with a clear message naming the counts -- the same
    check cli_d2 already makes for the same reason."""
    teams = write_team_config(tmp_path / "teams.yaml", n_teams=9)
    with pytest.raises(SystemExit, match="9 teams"):
        rung3_main(
            ["--teams", str(teams), "--out", str(tmp_path / "reports")],
            transport=fake_transport([]),
        )
