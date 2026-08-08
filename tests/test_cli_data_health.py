"""The data-health producer: what it must measure, and how it can lie quietly.

Every assertion here guards a number that reaches the weaknesses documentation.
A wrong number in a gate report fails loudly; a wrong number here reads as a
reassuring paragraph about coverage the corpus does not have.
"""

from ti26.cli_data_health import corpus_facts, field_facts, headline, render_markdown
from ti26.data.schema import MapRow

DAY = 86400


def row(
    match_id,
    start_time,
    *,
    tier="professional",
    patch="7.41",
    league_id=1,
    radiant_accounts=(1, 2, 3, 4, 5),
    dire_accounts=(6, 7, 8, 9, 10),
    radiant_win=True,
    null_team=False,
):
    return MapRow(
        match_id=match_id, start_time=start_time, duration=2000, radiant_win=radiant_win,
        league_id=league_id, tier=tier, radiant_team_id=10, dire_team_id=20,
        series_id=match_id, series_type=1, patch=patch,
        radiant_accounts=radiant_accounts, dire_accounts=dire_accounts,
        radiant_heroes=(1, 2, 3, 4, 5), dire_heroes=(6, 7, 8, 9, 10),
        has_null_team=null_team, has_bad_roster=False,
    )


def _teams_config(tmp_path, entries):
    path = tmp_path / "teams.yaml"
    body = "teams:\n" + "".join(
        f"  - name: {name}\n    team_id: {team_id}\n" for name, team_id in entries
    )
    path.write_text(body)
    return str(path)


def _aliases(tmp_path):
    path = tmp_path / "aliases.yaml"
    path.write_text("aliases: []\n")
    return str(path)


def test_target_tier_events_counts_distinct_leagues_not_maps():
    """Kills mutation: report the target tier's MAP count as its event count.

    This is the single most misleading substitution available in this report.
    "144 premium maps" invites the reading that the corpus samples several top
    events thinly, when in fact it holds one event completely. A model with one
    premium event in its history cannot be said to have seen the population it
    is asked about, and the map count alone never says so.
    """
    rows = [row(i, i * DAY, tier="premium", league_id=777) for i in range(40)]
    rows += [row(100 + i, (100 + i) * DAY, tier="professional", league_id=5) for i in range(10)]

    corpus = corpus_facts(rows)
    assert corpus["target_tier_leagues"] == [
        {"league_id": 777, "maps": 40, "first_start_time": 0, "last_start_time": 39 * DAY}
    ]

    head = headline(corpus, {"teams": []}, thin_roster_maps=50)
    assert head["target_tier_events"] == 1, "40 maps from one league is one event, not 40"


def test_recency_is_measured_from_the_stores_last_map_not_the_wall_clock():
    """Kills mutation: window the recency table against `time.time()`.

    Two failures at once. The report stops being reproducible -- the same store
    yields different numbers tomorrow, so no manifest can bind it -- and a
    store that is merely old reports zero recent activity, which reads as
    "the scene stopped playing" rather than "this snapshot is stale".
    """
    # Every row sits far in the past relative to any plausible wall clock.
    base = 1_000_000
    rows = [row(i, base + i * DAY) for i in range(10)]
    corpus = corpus_facts(rows)

    window_30 = next(w for w in corpus["recency"] if w["window_days"] == 30)
    assert window_30["maps"] == 10, "all ten maps fall inside 30 days of the store's own last map"
    assert window_30["share"] == 1.0


def test_roster_volume_is_keyed_on_the_roster_not_the_organisation(tmp_path):
    """Kills mutation: count a team's maps by `team_id` instead of roster hash.

    An organisation that swapped a player carries its old results under the
    same `team_id`. Counting that way credits the current five with maps they
    never played, which is exactly the inflation the roster-continuity design
    exists to prevent -- and it inflates precisely the thin-evidence teams the
    report is meant to expose.
    """
    old_roster = (1, 2, 3, 4, 5)
    new_roster = (1, 2, 3, 4, 99)  # one player swapped, same organisation
    opponent = (6, 7, 8, 9, 10)

    rows = [
        row(i, i * DAY, radiant_accounts=old_roster, dire_accounts=opponent) for i in range(30)
    ]
    rows += [
        row(100 + i, (100 + i) * DAY, radiant_accounts=new_roster, dire_accounts=opponent)
        for i in range(4)
    ]

    teams = _teams_config(tmp_path, [("Swapped", 10), ("Opponent", 20)])
    field = field_facts(rows, teams, _aliases(tmp_path), tau=0.5)
    swapped = next(t for t in field["teams"] if t["team"] == "Swapped")

    assert swapped["roster_maps"] == 4, (
        "the current five played 4 maps; the organisation played 34"
    )


def test_a_thin_roster_and_a_deep_one_are_reported_with_their_own_uncertainty(tmp_path):
    """Kills mutation: drop RD from the per-team table.

    RD is the only column that distinguishes a strength backed by 300 maps from
    one backed by 30, and `strengths()` discards it before the simulation ever
    runs. If this report drops it too, nothing in the project states the
    difference anywhere a reader will see it.
    """
    thin = (1, 2, 3, 4, 5)
    deep = (11, 12, 13, 14, 15)
    filler = (21, 22, 23, 24, 25)

    rows = [row(i, i * DAY, radiant_accounts=deep, dire_accounts=filler) for i in range(200)]
    rows += [
        row(500 + i, (500 + i) * DAY, radiant_accounts=thin, dire_accounts=filler)
        for i in range(3)
    ]

    teams = _teams_config(tmp_path, [("Thin", 10), ("Filler", 20)])
    field = field_facts(rows, teams, _aliases(tmp_path), tau=0.5)
    by_name = {t["team"]: t for t in field["teams"]}

    assert by_name["Thin"]["rd"] is not None
    assert by_name["Thin"]["roster_maps"] == 3
    assert by_name["Thin"]["rd"] > by_name["Filler"]["rd"], (
        "three maps must carry more rating deviation than two hundred"
    )


def test_the_headline_ratio_survives_a_field_with_a_zero_map_team():
    """Kills mutation: divide by the minimum roster volume unguarded.

    A roster with no maps is a real state during a pre-lock run -- a qualifier
    team the snapshot predates. The report is the thing that should say so, so
    it must not be the thing that crashes on it.
    """
    field = {
        "teams": [
            {"team": "Zero", "roster_maps": 0, "rd": 90.0, "target_tier_maps": 0},
            {"team": "Deep", "roster_maps": 300, "rd": 40.0, "target_tier_maps": 5},
        ]
    }
    corpus = corpus_facts([row(1, DAY)])
    head = headline(corpus, field, thin_roster_maps=50)

    assert head["roster_maps_ratio"] is None
    assert head["roster_maps_min"] == 0
    assert head["teams_below_thin_threshold"] == 1


def test_the_markdown_states_the_event_count_next_to_the_tier_share():
    """Kills mutation: render the tier share without the event count beside it.

    The share and the event count only mean something together. `0.4%` alone
    reads as an ordinary class imbalance, which is a solvable problem; `0.4%
    from one event` is a coverage gap, which is not solvable by reweighting.
    """
    rows = [row(i, i * DAY, tier="premium", league_id=777) for i in range(5)]
    rows += [row(50 + i, (50 + i) * DAY, tier="excluded", league_id=1) for i in range(95)]
    corpus = corpus_facts(rows)
    payload = {
        "status": "DIAGNOSTIC",
        "store": "x.sqlite",
        "corpus": corpus,
        "field": {"teams": []},
        "headline": headline(corpus, {"teams": []}, thin_roster_maps=50),
    }
    text = render_markdown(payload)

    assert "5.0%" in text
    assert "1 distinct event(s)" in text
    assert "777" in text
