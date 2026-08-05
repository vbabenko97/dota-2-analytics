"""Derive a Swiss stage's OBSERVED outcome from the store, for D4's card backtest.

This module reconstructs what actually happened at a historical event so a card
can be scored against it. It deliberately re-derives everything the frozen
`config/ti2025_backtest.yaml` also states, because the runner asserts the two
agree: a transcription error in the config and a reconstruction error here are
different failures, and only cross-checking catches both.

The derivation rule is fixed by spec section II ("D4") and was written down
before any of this code existed.
"""

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from ti26.data.schema import MapRow
from ti26.types import Category


class OutcomeError(ValueError):
    """The store does not support the outcome the frozen truth claims."""


@dataclass(frozen=True)
class SwissOutcome:
    """One team's observed Swiss result. `advanced` is playoff participation."""

    team_id: int
    wins: int
    losses: int
    advanced: bool
    category: Category

    @property
    def record(self) -> str:
        return f"{self.wins}-{self.losses}"


@dataclass(frozen=True)
class BacktestTruth:
    """The frozen expectation from config, plus the event's own bounds."""

    league_id: int
    swiss_end: int
    training_cutoff: int
    expected_swiss_maps: int
    expected_swiss_series: int
    expected_playoff_teams: int
    categories: dict[int, Category]
    records: dict[int, str]
    advanced: dict[int, bool]
    names: dict[int, str]


def load_backtest_truth(path: str | Path) -> BacktestTruth:
    data = yaml.safe_load(Path(path).read_text()) or {}
    event = data["event"]
    teams = data["teams"]
    return BacktestTruth(
        league_id=int(event["league_id"]),
        swiss_end=int(event["swiss_end"]),
        training_cutoff=int(event["training_cutoff"]),
        expected_swiss_maps=int(event["expected_swiss_maps"]),
        expected_swiss_series=int(event["expected_swiss_series"]),
        expected_playoff_teams=int(event["expected_playoff_teams"]),
        categories={int(t["team_id"]): Category(t["category"]) for t in teams},
        records={int(t["team_id"]): str(t["record"]) for t in teams},
        advanced={int(t["team_id"]): bool(t["advanced"]) for t in teams},
        names={int(t["team_id"]): str(t["name"]) for t in teams},
    )


def _category_for(wins: int, losses: int, advanced: bool) -> Category:
    """Map a Bo3 series record to a card category.

    The first six branches are TI 2026's own format (5 rounds, 4 wins advance /
    4 losses eliminate), where every team resolves to 4 wins or 4 losses.

    The last branch exists because TI 2025 capped its Swiss at 6 rounds, leaving
    four teams at 3-3 -- a record TI 2026 cannot produce and the card cannot
    express. Those are split by observed playoff participation, which preserves
    the card's semantics (elim_win = advanced despite losses, elim_loss =
    eliminated despite wins) instead of inventing a record for them.

    Anything else raises rather than being bucketed by a fallback, because a
    silent default here would quietly redefine the target being scored against.
    """
    if wins == 4 and losses == 0:
        return Category.W4_0
    if wins == 4 and losses == 1:
        return Category.W4_1
    if wins == 4:
        return Category.ELIM_WIN
    if losses == 4 and wins == 0:
        return Category.L0_4
    if losses == 4 and wins == 1:
        return Category.L1_4
    if losses == 4:
        return Category.ELIM_LOSS
    if wins < 4 and losses < 4:
        return Category.ELIM_WIN if advanced else Category.ELIM_LOSS
    raise OutcomeError(f"no card category for record {wins}-{losses}")


def series_results(
    rows: Sequence[MapRow], league_id: int, swiss_end: int
) -> tuple[dict[int, tuple[int, int]], int, int]:
    """Per-team (wins, losses) in Bo3 SERIES, plus the map and series counts.

    The two counts are returned rather than recomputed by the caller so the
    reconciliation checks in `derive_outcome` measure the same traversal that
    produced the records.

    Series are grouped by `series_id`. A null or zero `series_id` is refused
    rather than treated as its own one-map series: that fallback would silently
    inflate both the series count and every affected team's record.
    """
    tally: dict[int, Counter[int]] = defaultdict(Counter)
    members: dict[int, set[int]] = defaultdict(set)
    n_maps = 0
    for row in rows:
        if row.league_id != league_id or row.start_time >= swiss_end:
            continue
        n_maps += 1
        if not row.series_id:
            raise OutcomeError(
                f"map {row.match_id} in league {league_id} has no series_id; "
                "cannot group it into a series"
            )
        winner = row.radiant_team_id if row.radiant_win else row.dire_team_id
        tally[row.series_id][winner] += 1
        members[row.series_id].update((row.radiant_team_id, row.dire_team_id))

    wins: Counter[int] = Counter()
    losses: Counter[int] = Counter()
    for series_id, sides in members.items():
        if len(sides) != 2:
            raise OutcomeError(f"series {series_id} has {len(sides)} sides, expected 2")
        a, b = sorted(sides)
        won_a, won_b = tally[series_id][a], tally[series_id][b]
        if won_a == won_b:
            raise OutcomeError(f"series {series_id} is tied {won_a}-{won_b}")
        winner, loser = (a, b) if won_a > won_b else (b, a)
        wins[winner] += 1
        losses[loser] += 1

    if sum(wins.values()) != sum(losses.values()):
        raise OutcomeError(
            f"{sum(wins.values())} wins against {sum(losses.values())} losses; "
            "every series has exactly one winner and one loser"
        )
    return {t: (wins[t], losses[t]) for t in set(wins) | set(losses)}, n_maps, len(members)


def playoff_teams(rows: Sequence[MapRow], league_id: int, swiss_end: int) -> set[int]:
    """Teams appearing in the same league at or after `swiss_end` -- i.e. advanced."""
    out: set[int] = set()
    for row in rows:
        if row.league_id == league_id and row.start_time >= swiss_end:
            out.update((row.radiant_team_id, row.dire_team_id))
    out.discard(None)
    return out


def derive_outcome(
    rows: Sequence[MapRow], truth: BacktestTruth
) -> dict[int, SwissOutcome]:
    """Reconstruct the Swiss outcome and check it against the frozen expectation.

    Raises rather than returning a mismatch: the point of the frozen file is that
    a disagreement means one of the two is wrong, and continuing would score
    against a target nobody registered.
    """
    records, n_maps, n_series = series_results(rows, truth.league_id, truth.swiss_end)
    advanced = playoff_teams(rows, truth.league_id, truth.swiss_end)

    if n_maps != truth.expected_swiss_maps:
        raise OutcomeError(f"{n_maps} Swiss maps, frozen file says {truth.expected_swiss_maps}")
    if n_series != truth.expected_swiss_series:
        raise OutcomeError(
            f"{n_series} Swiss series, frozen file says {truth.expected_swiss_series}"
        )
    if len(advanced) != truth.expected_playoff_teams:
        raise OutcomeError(
            f"{len(advanced)} playoff teams, frozen file says {truth.expected_playoff_teams}"
        )
    if set(records) != set(truth.categories):
        missing = set(truth.categories) - set(records)
        extra = set(records) - set(truth.categories)
        raise OutcomeError(f"Swiss field mismatch: missing {sorted(missing)}, extra {sorted(extra)}")

    out: dict[int, SwissOutcome] = {}
    for team_id, (wins, losses) in records.items():
        did_advance = team_id in advanced
        outcome = SwissOutcome(
            team_id=team_id,
            wins=wins,
            losses=losses,
            advanced=did_advance,
            category=_category_for(wins, losses, did_advance),
        )
        if outcome.record != truth.records[team_id]:
            raise OutcomeError(
                f"team {team_id}: derived {outcome.record}, frozen {truth.records[team_id]}"
            )
        if did_advance != truth.advanced[team_id]:
            raise OutcomeError(
                f"team {team_id}: derived advanced={did_advance}, "
                f"frozen {truth.advanced[team_id]}"
            )
        if outcome.category != truth.categories[team_id]:
            raise OutcomeError(
                f"team {team_id}: derived {outcome.category.value}, "
                f"frozen {truth.categories[team_id].value}"
            )
        out[team_id] = outcome
    return out


def score_card(
    card: dict[str, Category], outcome: dict[int, SwissOutcome], names: dict[int, str]
) -> tuple[int, list[tuple[str, Category, Category, bool]]]:
    """Count exact category matches, and return the per-slot table.

    Every configured team must appear in the card: a team silently absent would
    lower the score without being visible as a miss.
    """
    table: list[tuple[str, Category, Category, bool]] = []
    score = 0
    for team_id, obs in outcome.items():
        name = names[team_id]
        if name not in card:
            raise OutcomeError(f"{name} is in the observed field but not on the card")
        predicted = card[name]
        hit = predicted == obs.category
        score += hit
        table.append((name, predicted, obs.category, hit))
    # Misses first: which slots were wrong is the informative part, and burying
    # them under a dozen hits is how a reader stops reading before reaching them.
    table.sort(key=lambda r: (r[3], r[0]))
    return score, table
