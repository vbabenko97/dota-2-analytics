from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Category(str, Enum):
    W4_0 = "4-0"
    W4_1 = "4-1"
    ELIM_WIN = "elim_win"
    ELIM_LOSS = "elim_loss"
    L1_4 = "1-4"
    L0_4 = "0-4"


@dataclass
class TeamState:
    team_id: str
    initial_group: str
    series_wins: int = 0
    series_losses: int = 0
    map_wins: int = 0
    map_losses: int = 0
    opponents: list[str] = field(default_factory=list)

    @property
    def record(self) -> tuple[int, int]:
        return (self.series_wins, self.series_losses)

    @property
    def maps_played(self) -> int:
        return self.map_wins + self.map_losses


@dataclass(frozen=True)
class SeriesResult:
    round_no: int
    team_a: str
    team_b: str
    wins_a: int
    wins_b: int
    was_repeat: bool


@dataclass(frozen=True)
class RoundLog:
    round_no: int
    ranking: list[str]
    pairings: list[tuple[str, str]]
    repeat_count: int
    min_possible_repeats: int
    results: list[SeriesResult]


@dataclass(frozen=True)
class SwissRun:
    states: dict[str, TeamState]
    groups: dict[str, str]
    rounds: list[RoundLog]


@dataclass(frozen=True)
class EliminationMatch:
    """One elimination-round series, named by record rather than by agency.

    `higher` is the 3-2 team, `lower` the 2-3 team it was paired against by
    maximum ranking distance. These used to be `chooser`/`opponent`, from a
    model in which the 3-2 team picked; the published rules give it no choice.
    """

    higher: str
    lower: str
    wins_higher: int
    wins_lower: int


@dataclass(frozen=True)
class EliminationRun:
    categories: dict[str, Category]
    matches: list[EliminationMatch]
