"""Score the shipped card against what TI 2026 actually did.

DIAGNOSTIC -- it gates nothing and can alter no card. The card it scores was
frozen and submitted before the event; nothing here can reach back to it.

Every number this prints is computed here from the store and the frozen truth
file. The Swiss/elimination boundary is not configured: it is derived from the
published format facts bound in the TI 2026 evidence record, and the runner
re-derives every record and category rather than trusting `--outcome`.
"""

import argparse
import collections
import json
import sqlite3
from pathlib import Path

import yaml

from ti26.cli_external_cards import exact_null_distribution

# Valve's published format, as bound by the evidence record. Named here so the
# derivation reads as what it is -- a consequence of the captured facts.
ADVANCE_AT_WINS = 4
ELIMINATE_AT_LOSSES = 4
TOTAL_ROUNDS = 5


class OutcomeError(RuntimeError):
    """The store and the frozen truth file disagree, or the store is unusable."""


def load_team_names(teams_path: Path, extra: dict[int, str]) -> dict[int, str]:
    """Map every team_id seen at the event onto its configured TI-facing name.

    `extra` carries duplicate registrations that share a configured roster --
    including `10150413`, which Iron Wing used for its elimination series and
    which appears in no config. Resolving these by hand here is a diagnostic
    convenience; the rating pipeline never needs it, because it keys on roster.
    """
    configured = {t["team_id"]: t["name"] for t in yaml.safe_load(teams_path.read_text())["teams"]}
    return {**configured, **extra}


def read_series(store: Path, league_id: int) -> list[tuple[int, int, int, int]]:
    """Return `(start, team_a, team_b, a_map_wins, total_maps)` per series, chronological."""
    conn = sqlite3.connect(store)
    rows = conn.execute(
        "select series_id, start_time, radiant_team_id, dire_team_id, radiant_win "
        "from maps where league_id = ? order by start_time",
        (league_id,),
    ).fetchall()
    if not rows:
        raise OutcomeError(f"store holds no maps for league {league_id}")
    grouped: dict[int, list] = collections.defaultdict(list)
    for series_id, start, radiant, dire, radiant_win in rows:
        if not series_id:
            raise OutcomeError("event contains a map with no series_id; cannot group series")
        grouped[series_id].append((start, radiant, dire, radiant_win))
    series = []
    for maps in grouped.values():
        start = min(m[0] for m in maps)
        a, b = maps[0][1], maps[0][2]
        a_wins = sum(1 for _, radiant, _, radiant_win in maps if (radiant == a) == bool(radiant_win))
        series.append((start, a, b, a_wins, len(maps)))
    return sorted(series), len(rows)


def derive(series: list, names: dict[int, str]) -> dict[str, object]:
    """Split the event into Swiss and elimination purely from the published facts.

    A team is terminal once it has `ADVANCE_AT_WINS` wins, `ELIMINATE_AT_LOSSES`
    losses, or has played `TOTAL_ROUNDS` series. A series is Swiss while neither
    side is already terminal. No timestamp is consulted, so the boundary cannot
    be tuned by moving a cutoff.
    """
    records: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])

    def terminal(team: str) -> bool:
        wins, losses = records[team]
        return (
            wins >= ADVANCE_AT_WINS
            or losses >= ELIMINATE_AT_LOSSES
            or wins + losses >= TOTAL_ROUNDS
        )

    swiss, elimination = 0, []
    for _, a, b, a_wins, total in series:
        if a not in names or b not in names:
            missing = a if a not in names else b
            raise OutcomeError(f"team_id {missing} at this event maps to no configured name")
        left, right = names[a], names[b]
        winner, loser = (left, right) if a_wins > total - a_wins else (right, left)
        if terminal(left) or terminal(right):
            elimination.append({"winner": winner, "loser": loser})
            continue
        records[winner][0] += 1
        records[loser][1] += 1
        swiss += 1

    categories = {}
    for team, (wins, losses) in records.items():
        if wins >= ADVANCE_AT_WINS:
            categories[team] = "4-0" if losses == 0 else "4-1"
        elif losses >= ELIMINATE_AT_LOSSES:
            categories[team] = "0-4" if wins == 0 else "1-4"
    for match in elimination:
        categories[match["winner"]] = "elim_win"
        categories[match["loser"]] = "elim_loss"
    return {
        "swiss_series": swiss,
        "elimination_series": len(elimination),
        "swiss_records": {t: list(r) for t, r in records.items()},
        "elimination_round": elimination,
        "categories": categories,
    }


def assert_matches_frozen(derived: dict[str, object], frozen: dict[str, object]) -> None:
    """Raise on the first disagreement between the store and the frozen truth.

    Compared field by field rather than as one blob so the message names what
    diverged. A mismatch means either the transcription is wrong or the store
    changed under us; both are reasons to stop, never to update the file.
    """
    event = frozen["event"]
    for key in ("swiss_series", "elimination_series"):
        if derived[key] != event[key]:
            raise OutcomeError(f"{key}: store says {derived[key]}, frozen file says {event[key]}")
    for team, record in sorted(frozen["swiss_records"].items()):
        if derived["swiss_records"].get(team) != list(record):
            raise OutcomeError(
                f"swiss record {team}: store says "
                f"{derived['swiss_records'].get(team)}, frozen file says {list(record)}"
            )
    if derived["elimination_round"] != [dict(m) for m in frozen["elimination_round"]]:
        raise OutcomeError("elimination round results disagree with the frozen file")
    if derived["categories"] != dict(frozen["categories"]):
        raise OutcomeError("derived categories disagree with the frozen file")


def score(card: dict[str, str], categories: dict[str, str]) -> list[str]:
    if set(card) != set(categories):
        raise OutcomeError("card names do not match the event field")
    return sorted(team for team, pick in card.items() if pick == categories[team])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score the shipped card against TI 2026")
    parser.add_argument("--store", required=True)
    # The outcome and the external cards live under `data/`, not `config/`.
    # They are observed event data, exactly as the group draw is, and the
    # release bundle reads neither -- so hashing them into every run manifest
    # would bind a release to files no release producer opens.
    parser.add_argument("--outcome", default="data/ti2026_outcome.yaml")
    parser.add_argument("--teams", default="config/ti2026_teams.yaml")
    parser.add_argument("--card", default="reports/card_ti2026_rules/recommended_card.json")
    parser.add_argument("--external", default="data/ti2026_external_cards.yaml")
    args = parser.parse_args(argv)

    frozen = yaml.safe_load(Path(args.outcome).read_text())
    names = load_team_names(
        Path(args.teams), {int(k): v for k, v in (frozen.get("duplicate_team_ids") or {}).items()}
    )
    series, maps = read_series(Path(args.store), frozen["event"]["league_id"])
    if maps != frozen["event"]["maps"]:
        raise OutcomeError(f"store holds {maps} maps, frozen file says {frozen['event']['maps']}")
    derived = derive(series, names)
    assert_matches_frozen(derived, frozen)

    categories = derived["categories"]
    capacities = sorted(collections.Counter(categories.values()).values())
    null = exact_null_distribution(capacities)
    tail = [sum(null[k:]) for k in range(len(null))]
    mean = sum(k * p for k, p in enumerate(null))

    print("# TI 2026 outcome")
    print()
    print("**DIAGNOSTIC -- gates nothing, alters no card. The card it scores was already submitted.**")
    print()
    print(f"Store: `{args.store}`, league {frozen['event']['league_id']}, {maps} maps.")
    print(
        f"Derived from the published format facts alone: {derived['swiss_series']} Swiss series, "
        f"{derived['elimination_series']} elimination series. Every record and category "
        f"re-derived and asserted equal to `{args.outcome}`."
    )
    print()
    print(f"Card category capacities: {capacities}. Random-card mean: **{float(mean):.4f}**.")
    print()

    cards = [("shipped", json.loads(Path(args.card).read_text())["assignments"])]
    external_path = Path(args.external)
    if external_path.exists():
        for entry in yaml.safe_load(external_path.read_text())["cards"]:
            cards.append((entry["id"], entry["assignments"]))

    print("## Scores")
    print()
    print("| card | score | P(random card scores at least this) |")
    print("|---|---|---|")
    for label, card in cards:
        hits = score(card, categories)
        print(f"| {label} | **{len(hits)}/{len(categories)}** | {float(tail[len(hits)]):.4f} |")
    print()

    for label, card in cards:
        hits = set(score(card, categories))
        print(f"## {label}")
        print()
        print("| team | predicted | actual | |")
        print("|---|---|---|---|")
        for team in sorted(card):
            mark = "HIT" if team in hits else ""
            print(f"| {team} | {card[team]} | {categories[team]} | {mark} |")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
