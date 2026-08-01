# D1: Swiss Rules Engine and Card Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Given any 16-team strength vector, produce a legal TI 2026 prediction card — exercising the exact Swiss pairing, tiebreak, elimination, and constrained-assignment rules — with zero dependency on external match data.

**Architecture:** Pure-Python domain core with no I/O. `config/ti2026_rules.yaml` is the single source of truth for every rule that could differ from our reading of Valve's text; everything logically forced by the format (record capacities, category capacities, the random baseline) is *derived* from it rather than duplicated. Ranking, pairing, round progression, elimination choice, and assignment are separate modules with narrow interfaces. `run_swiss` returns a full round-by-round log so invariants can inspect actual rankings, pairings, and repeat optimality rather than trusting final state. Team strengths are an *input*, so the whole layer is testable before ingestion exists.

**Tech Stack:** Python 3.12, `uv`, `pytest`, `numpy`, `scipy` (Hungarian assignment), `PyYAML`, `ruff`.

## Global Constraints

- **No duplicated rule constants.** Record capacities, category capacities, and the random baseline are computed by `derive_*` functions from the format parameters in `config/ti2026_rules.yaml`. Writing `[1, 2, 5, 5, 2, 1]` as a literal anywhere in `src/` is a plan violation — it may appear only in tests, as an independent expected value.
- Every random operation takes an explicit `random.Random` instance. No module-level RNG, no `random.*` free functions.
- Same seed + same inputs → identical outputs.
- Tiebreak order (provenance `official`): matches won ↓, matches lost ↑, opponents' total matches won ↓, game-win % ↓, opponents' average game-win % ↓, average game duration ↑, coin toss.
- **Hard constraints never degrade silently.** A round constraint that cannot be satisfied raises `NoLegalPairingError`. A five-criterion tie with no duration resolver raises `DurationUnavailableError`. Neither falls through to a weaker rule.
- Repeat opponents are avoided **when a legal non-repeat perfect matching exists**. When one does not, the engine takes the minimum achievable repeat count. Whether a forced repeat is reachable in a real 16-team five-round Swiss is **unproven and not asserted either way** — the engine and its tests handle both cases.
- Average duration is evaluated **lazily** — sampled only for teams inside a tie block that survived the first five criteria, memoised per team, and extended as maps accumulate.
- Every rules-engine branch carries a provenance tag: `official`, `logically_forced`, `inferred`, or `arbitrary`.
- No network calls in any module under `src/ti26/`.
- Monte Carlo symmetry tests carry `@pytest.mark.slow`. Per-task loops run `-m "not slow"`; Task 8 and final verification run the whole suite.

---

## File Structure

| File | Responsibility |
|---|---|
| `config/ti2026_rules.yaml` | Format parameters, tiebreak order, round constraints, provenance. No capacities — those are derived |
| `src/ti26/rules.py` | Load config; derive record and category capacities; expose frozen `Rules` |
| `src/ti26/types.py` | `Category`, `TeamState`, `SeriesResult`, `RoundLog`, `SwissRun`, `EliminationMatch`, `EliminationRun` |
| `src/ti26/tiebreak.py` | Official ranking, `DurationResolver`, `DurationUnavailableError` |
| `src/ti26/pairing.py` | Matching enumeration, `PairingChoice`, `NoLegalPairingError` |
| `src/ti26/series.py` | Bradley-Terry map model and Bo3 simulation |
| `src/ti26/swiss.py` | Round progression R1–R5 returning `SwissRun` |
| `src/ti26/elimination.py` | Sequential opponent choice returning `EliminationRun` |
| `src/ti26/montecarlo.py` | Simulation driver → `P[team][category]` |
| `src/ti26/optimize.py` | Hungarian constrained assignment → card |
| `src/ti26/cli.py` | Entry point writing CSV + JSON |

---

## Task 1: Rules config, derived capacities, domain types

**Files:**
- Create: `pyproject.toml`, `config/ti2026_rules.yaml`, `src/ti26/__init__.py`, `src/ti26/types.py`, `src/ti26/rules.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Category` (str enum: `W4_0, W4_1, ELIM_WIN, ELIM_LOSS, L1_4, L0_4`); `TeamState` (fields `team_id: str, initial_group: str, series_wins: int, series_losses: int, map_wins: int, map_losses: int, opponents: list[str]`; properties `active: bool`, `record: tuple[int,int]`, `maps_played: int`); `SeriesResult(round_no: int, team_a: str, team_b: str, wins_a: int, wins_b: int, was_repeat: bool)`; `derive_record_capacities(n_teams, advance_at, eliminate_at, total_rounds) -> dict[tuple[int,int], int]`; `category_for_terminal_record(record, advance_at, eliminate_at) -> Category | None`; `derive_category_capacities(record_capacities, advance_at, eliminate_at) -> dict[Category,int]`; `load_rules(path) -> Rules` exposing `.n_teams, .total_rounds, .advance_at_wins, .eliminate_at_losses, .tiebreak_order, .within_group_rounds, .cross_group_rounds, .max_distance_elimination_rounds, .provenance, .record_capacities, .category_capacities, .random_baseline`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rules.py
import pytest
import yaml

from ti26.rules import (
    category_for_terminal_record,
    derive_category_capacities,
    derive_record_capacities,
    load_rules,
)
from ti26.types import Category, TeamState

RULES_PATH = "config/ti2026_rules.yaml"


def test_record_capacities_are_derived_not_configured():
    caps = derive_record_capacities(n_teams=16, advance_at=4, eliminate_at=4, total_rounds=5)
    assert caps == {(4, 0): 1, (4, 1): 2, (3, 2): 5, (2, 3): 5, (1, 4): 2, (0, 4): 1}


def test_record_capacities_generalise_to_a_smaller_bracket():
    # 8 teams, 3 wins advance / 3 losses out, 5 rounds.
    caps = derive_record_capacities(n_teams=8, advance_at=3, eliminate_at=3, total_rounds=5)
    assert sum(caps.values()) == 8
    assert caps[(3, 0)] == 1
    assert caps[(0, 3)] == 1


def test_odd_record_group_is_rejected():
    with pytest.raises(ValueError, match="odd"):
        derive_record_capacities(n_teams=6, advance_at=4, eliminate_at=4, total_rounds=5)


def test_category_for_terminal_record():
    assert category_for_terminal_record((4, 0), 4, 4) is Category.W4_0
    assert category_for_terminal_record((4, 1), 4, 4) is Category.W4_1
    assert category_for_terminal_record((0, 4), 4, 4) is Category.L0_4
    assert category_for_terminal_record((1, 4), 4, 4) is Category.L1_4
    # 3-2 and 2-3 are undecided until the elimination round.
    assert category_for_terminal_record((3, 2), 4, 4) is None
    assert category_for_terminal_record((2, 3), 4, 4) is None


def test_category_capacities_are_derived():
    records = derive_record_capacities(16, 4, 4, 5)
    caps = derive_category_capacities(records, advance_at=4, eliminate_at=4)
    assert caps == {
        Category.W4_0: 1,
        Category.W4_1: 2,
        Category.ELIM_WIN: 5,
        Category.ELIM_LOSS: 5,
        Category.L1_4: 2,
        Category.L0_4: 1,
    }
    assert sum(caps.values()) == 16


def test_advancing_teams_equal_eight():
    rules = load_rules(RULES_PATH)
    caps = rules.category_capacities
    advancing = caps[Category.W4_0] + caps[Category.W4_1] + caps[Category.ELIM_WIN]
    assert advancing == 8


def test_random_baseline_is_derived():
    rules = load_rules(RULES_PATH)
    expected = sum(k**2 for k in rules.category_capacities.values()) / rules.n_teams
    assert rules.random_baseline == pytest.approx(expected)
    assert rules.random_baseline == pytest.approx(3.75)


def test_config_declares_no_capacity_values():
    """Capacities must be derived, never configured — no divergent sources.

    The provenance block may *name* capacities; it must mark them derived.
    """
    raw = yaml.safe_load(open(RULES_PATH))
    assert "capacities" not in raw
    assert "category_capacities" not in raw
    assert raw["provenance"]["record_capacities"] == "logically_forced"
    assert raw["provenance"]["category_capacities"] == "logically_forced"


def test_tiebreak_order_is_the_official_seven():
    rules = load_rules(RULES_PATH)
    assert rules.tiebreak_order == [
        "series_wins",
        "series_losses",
        "opponent_series_wins",
        "game_win_pct",
        "opponent_game_win_pct",
        "avg_duration",
        "coin_toss",
    ]


def test_round_constraints():
    rules = load_rules(RULES_PATH)
    assert rules.within_group_rounds == [2, 3]
    assert rules.cross_group_rounds == [4]
    assert rules.max_distance_elimination_rounds == [5]


def test_every_rule_carries_a_provenance_tag():
    rules = load_rules(RULES_PATH)
    allowed = {"official", "logically_forced", "inferred", "arbitrary"}
    assert rules.provenance
    assert set(rules.provenance.values()) <= allowed


def test_team_state_properties():
    t = TeamState(team_id="alpha", initial_group="A")
    assert t.record == (0, 0)
    assert t.maps_played == 0
    t.series_wins, t.map_wins, t.map_losses = 4, 8, 3
    assert t.record == (4, 0)
    assert t.maps_played == 11


def test_is_active_uses_configured_thresholds():
    rules = load_rules(RULES_PATH)
    assert rules.is_active(TeamState(team_id="a", initial_group="A")) is True
    assert rules.is_active(TeamState(team_id="b", initial_group="A", series_wins=4)) is False
    assert rules.is_active(TeamState(team_id="c", initial_group="B", series_losses=4)) is False
    assert rules.is_active(TeamState(team_id="d", initial_group="B", series_wins=3, series_losses=2)) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26'`

- [ ] **Step 3: Write minimal implementation**

```toml
# pyproject.toml
[project]
name = "ti26"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["numpy>=2.0", "scipy>=1.14", "PyYAML>=6.0"]

[dependency-groups]
dev = ["pytest>=8.0", "ruff>=0.6"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ti26"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
markers = ["slow: Monte Carlo convergence tests; run at final verification"]

[tool.ruff]
line-length = 100
```

```yaml
# config/ti2026_rules.yaml
# Single source of truth for rules that could differ from our reading of
# Valve's published text. Anything logically forced by these parameters
# (record counts, category counts, the random baseline) is DERIVED in
# rules.py and deliberately absent here.

format:
  n_teams: 16
  total_rounds: 5
  advance_at_wins: 4
  eliminate_at_losses: 4

tiebreak_order:
  - series_wins
  - series_losses
  - opponent_series_wins
  - game_win_pct
  - opponent_game_win_pct
  - avg_duration
  - coin_toss

rounds:
  within_group: [2, 3]
  cross_group: [4]
  max_distance_when_loser_eliminated: [5]

duration_model:
  log_mean: 7.65      # exp(7.65) ~ 2100s ~ 35 min
  log_sigma: 0.25

provenance:
  n_teams: official
  total_rounds: official
  advance_at_wins: official
  eliminate_at_losses: official
  tiebreak_order: official
  within_group_rounds: official
  cross_group_rounds: official
  max_distance_when_loser_eliminated: official
  record_capacities: logically_forced
  category_capacities: logically_forced
  # Round 4's 0-3 group also eliminates its loser, but the published rule
  # names Round 5 only. Applying max-distance at R4 would be an inference
  # and is deliberately NOT enabled.
  max_distance_at_round_4: inferred
  # No published rule orders teams still exactly tied after duration.
  coin_toss_resolution: arbitrary
  # Repeat avoidance is "where possible" per the official text.
  repeat_avoidance_is_soft: official
  # Duration distribution is our own placeholder, not a Valve statement.
  duration_model: arbitrary
```

```python
# src/ti26/types.py
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
    chooser: str
    opponent: str
    available_when_choosing: list[str]
    wins_chooser: int
    wins_opponent: int


@dataclass(frozen=True)
class EliminationRun:
    categories: dict[str, Category]
    matches: list[EliminationMatch]
```

> `TeamState` has no `active` property: whether a team is still playing depends
> on the configured `advance_at_wins` / `eliminate_at_losses`, so it lives as
> `Rules.is_active(team)` rather than as a property with hard-coded constants.

```python
# src/ti26/rules.py
from collections import Counter, defaultdict
from dataclasses import dataclass

import yaml

from ti26.types import Category, TeamState


def derive_record_capacities(
    n_teams: int, advance_at: int, eliminate_at: int, total_rounds: int
) -> dict[tuple[int, int], int]:
    """Compute the terminal (wins, losses) distribution from format parameters.

    Teams reaching advance_at wins or eliminate_at losses stop playing. Every
    remaining record group splits evenly each round, so the distribution is
    forced by the format rather than by who wins.
    """
    counts: dict[tuple[int, int], int] = {(0, 0): n_teams}
    for _ in range(total_rounds):
        nxt: dict[tuple[int, int], int] = defaultdict(int)
        for (wins, losses), n in counts.items():
            if wins >= advance_at or losses >= eliminate_at:
                nxt[(wins, losses)] += n
                continue
            if n % 2 != 0:
                raise ValueError(
                    f"record group {(wins, losses)} has an odd size {n}; cannot pair"
                )
            nxt[(wins + 1, losses)] += n // 2
            nxt[(wins, losses + 1)] += n // 2
        counts = dict(nxt)
    return dict(counts)


def category_for_terminal_record(
    record: tuple[int, int], advance_at: int, eliminate_at: int
) -> Category | None:
    """Map a final Swiss record to a card category, or None if undecided."""
    wins, losses = record
    if wins >= advance_at:
        return Category.W4_0 if losses == 0 else Category.W4_1
    if losses >= eliminate_at:
        return Category.L0_4 if wins == 0 else Category.L1_4
    return None


def derive_category_capacities(
    record_capacities: dict[tuple[int, int], int], advance_at: int, eliminate_at: int
) -> dict[Category, int]:
    caps: Counter[Category] = Counter()
    undecided = 0
    for record, n in record_capacities.items():
        category = category_for_terminal_record(record, advance_at, eliminate_at)
        if category is None:
            undecided += n
        else:
            caps[category] += n
    if undecided % 2 != 0:
        raise ValueError(f"{undecided} undecided teams cannot form elimination pairs")
    caps[Category.ELIM_WIN] = undecided // 2
    caps[Category.ELIM_LOSS] = undecided // 2
    return dict(caps)


@dataclass(frozen=True)
class Rules:
    n_teams: int
    total_rounds: int
    advance_at_wins: int
    eliminate_at_losses: int
    tiebreak_order: list[str]
    within_group_rounds: list[int]
    cross_group_rounds: list[int]
    max_distance_elimination_rounds: list[int]
    duration_log_mean: float
    duration_log_sigma: float
    provenance: dict[str, str]
    record_capacities: dict[tuple[int, int], int]
    category_capacities: dict[Category, int]

    @property
    def random_baseline(self) -> float:
        return sum(k**2 for k in self.category_capacities.values()) / self.n_teams

    def is_active(self, team: TeamState) -> bool:
        return (
            team.series_wins < self.advance_at_wins
            and team.series_losses < self.eliminate_at_losses
        )


def load_rules(path: str) -> Rules:
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    fmt, rounds, duration = raw["format"], raw["rounds"], raw["duration_model"]
    records = derive_record_capacities(
        n_teams=fmt["n_teams"],
        advance_at=fmt["advance_at_wins"],
        eliminate_at=fmt["eliminate_at_losses"],
        total_rounds=fmt["total_rounds"],
    )
    return Rules(
        n_teams=fmt["n_teams"],
        total_rounds=fmt["total_rounds"],
        advance_at_wins=fmt["advance_at_wins"],
        eliminate_at_losses=fmt["eliminate_at_losses"],
        tiebreak_order=list(raw["tiebreak_order"]),
        within_group_rounds=list(rounds["within_group"]),
        cross_group_rounds=list(rounds["cross_group"]),
        max_distance_elimination_rounds=list(rounds["max_distance_when_loser_eliminated"]),
        duration_log_mean=float(duration["log_mean"]),
        duration_log_sigma=float(duration["log_sigma"]),
        provenance=dict(raw["provenance"]),
        record_capacities=records,
        category_capacities=derive_category_capacities(
            records, fmt["advance_at_wins"], fmt["eliminate_at_losses"]
        ),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_rules.py -v -m "not slow" && uv run ruff check src tests`
Expected: 13 passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml config/ti2026_rules.yaml src/ti26/__init__.py src/ti26/types.py src/ti26/rules.py tests/test_rules.py
git commit -m "feat: rules config with derived capacities and provenance tags"
```

---

## Task 2: Ranking with mandatory duration resolution

**Files:**
- Create: `src/ti26/tiebreak.py`
- Test: `tests/test_tiebreak.py`

**Interfaces:**
- Consumes: `TeamState` (Task 1).
- Produces: `DurationUnavailableError(RuntimeError)`; `DurationResolver(rng, log_mean, log_sigma)` with `.average_for(team_id, maps_played) -> float`, `.bind(states) -> Callable[[str], float]`, `.consultations: int`; `game_win_pct(team) -> float`; `rank_teams(states, rng, duration_fn=None) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tiebreak.py
import random

import pytest

from ti26.tiebreak import (
    DurationResolver,
    DurationUnavailableError,
    game_win_pct,
    rank_teams,
)
from ti26.types import TeamState


def make(team_id, sw, sl, mw, ml, opponents=(), group="A"):
    return TeamState(
        team_id=team_id,
        initial_group=group,
        series_wins=sw,
        series_losses=sl,
        map_wins=mw,
        map_losses=ml,
        opponents=list(opponents),
    )


def test_game_win_pct_handles_zero_maps():
    assert game_win_pct(make("a", 0, 0, 0, 0)) == 0.0
    assert game_win_pct(make("b", 1, 0, 2, 1)) == 2 / 3


def test_series_wins_dominate():
    states = [make("low", 1, 2, 3, 5), make("high", 3, 0, 6, 1)]
    assert rank_teams(states, random.Random(0)) == ["high", "low"]


def test_series_losses_break_equal_wins():
    states = [make("more", 2, 2, 4, 4), make("fewer", 2, 1, 4, 3)]
    assert rank_teams(states, random.Random(0)) == ["fewer", "more"]


def test_opponent_series_wins_break_identical_records():
    strong = make("strong", 3, 0, 6, 0)
    weak = make("weak", 0, 3, 0, 6)
    a = make("a", 1, 1, 2, 2, opponents=["strong"])
    b = make("b", 1, 1, 2, 2, opponents=["weak"])
    ranked = rank_teams([a, b, strong, weak], random.Random(0))
    assert ranked.index("a") < ranked.index("b")


def test_game_win_pct_breaks_equal_opponent_wins():
    shared = make("shared", 1, 1, 2, 2)
    a = make("a", 1, 1, 2, 1, opponents=["shared"])
    b = make("b", 1, 1, 2, 3, opponents=["shared"])
    ranked = rank_teams([a, b, shared], random.Random(0))
    assert ranked.index("a") < ranked.index("b")


def test_opponent_game_win_pct_is_the_fifth_criterion():
    # a and b identical through four criteria; their opponents differ on gwp.
    opp_good = make("opp_good", 1, 1, 3, 1)   # gwp 0.75
    opp_bad = make("opp_bad", 1, 1, 1, 3)     # gwp 0.25
    a = make("a", 1, 1, 2, 2, opponents=["opp_good"])
    b = make("b", 1, 1, 2, 2, opponents=["opp_bad"])
    ranked = rank_teams([a, b, opp_good, opp_bad], random.Random(0))
    assert ranked.index("a") < ranked.index("b")


def test_duration_is_not_consulted_when_five_criteria_separate():
    resolver = DurationResolver(random.Random(0), log_mean=7.65, log_sigma=0.25)
    states = [make("a", 1, 1, 3, 1), make("b", 1, 1, 1, 3)]
    rank_teams(states, random.Random(0), duration_fn=resolver.bind({s.team_id: s for s in states}))
    assert resolver.consultations == 0


def test_shorter_average_duration_wins_a_surviving_tie():
    tie_a, tie_b = make("a", 1, 1, 2, 2), make("b", 1, 1, 2, 2)
    consulted = []

    def duration_fn(team_id):
        consulted.append(team_id)
        return {"a": 1800.0, "b": 2400.0}[team_id]

    ranked = rank_teams([tie_a, tie_b], random.Random(0), duration_fn=duration_fn)
    assert sorted(consulted) == ["a", "b"]
    assert ranked == ["a", "b"]


def test_missing_duration_resolver_raises_rather_than_skipping_to_coin_toss():
    tie_a, tie_b = make("a", 1, 1, 2, 2), make("b", 1, 1, 2, 2)
    with pytest.raises(DurationUnavailableError, match="tied"):
        rank_teams([tie_a, tie_b], random.Random(0))


def test_exact_duration_ties_fall_to_a_seeded_coin_toss():
    tie_a, tie_b = make("a", 1, 1, 2, 2), make("b", 1, 1, 2, 2)
    fn = lambda _team_id: 2000.0  # noqa: E731 - identical durations by design
    first = rank_teams([tie_a, tie_b], random.Random(7), duration_fn=fn)
    second = rank_teams([tie_a, tie_b], random.Random(7), duration_fn=fn)
    assert first == second
    assert sorted(first) == ["a", "b"]


def test_resolver_memoises_and_extends_as_maps_accumulate():
    resolver = DurationResolver(random.Random(3), log_mean=7.65, log_sigma=0.25)
    first = resolver.average_for("a", maps_played=2)
    again = resolver.average_for("a", maps_played=2)
    assert first == again, "same map count must return the memoised average"
    extended = resolver.average_for("a", maps_played=5)
    assert extended != first, "more maps must extend the sample, not reuse it"


def test_resolver_raises_when_no_maps_have_been_played():
    resolver = DurationResolver(random.Random(0), log_mean=7.65, log_sigma=0.25)
    with pytest.raises(DurationUnavailableError, match="no maps"):
        resolver.average_for("a", maps_played=0)


def test_ranking_is_a_permutation_of_input():
    states = [make(f"t{i}", i % 3, 2 - i % 3, i, 5 - i % 5) for i in range(8)]
    resolver = DurationResolver(random.Random(1), log_mean=7.65, log_sigma=0.25)
    ranked = rank_teams(
        states, random.Random(3), duration_fn=resolver.bind({s.team_id: s for s in states})
    )
    assert sorted(ranked) == sorted(s.team_id for s in states)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tiebreak.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.tiebreak'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ti26/tiebreak.py
import random
from collections.abc import Callable

from ti26.types import TeamState


class DurationUnavailableError(RuntimeError):
    """Raised when criterion 6 is required but no duration source exists."""


class DurationResolver:
    """Lazily samples per-map durations, memoised and extended per team.

    Durations are drawn only when a tie survives the first five criteria, so
    the common path never pays for them. Samples persist across rounds and are
    extended as maps accumulate, keeping a team's average monotone in its own
    history rather than resampled each time it is consulted.
    """

    def __init__(self, rng: random.Random, log_mean: float, log_sigma: float) -> None:
        self._rng = rng
        self._log_mean = log_mean
        self._log_sigma = log_sigma
        self._samples: dict[str, list[float]] = {}
        self.consultations = 0

    def average_for(self, team_id: str, maps_played: int) -> float:
        self.consultations += 1
        if maps_played <= 0:
            raise DurationUnavailableError(
                f"team {team_id!r} has no maps; cannot compute average duration"
            )
        samples = self._samples.setdefault(team_id, [])
        while len(samples) < maps_played:
            samples.append(self._rng.lognormvariate(self._log_mean, self._log_sigma))
        return sum(samples) / len(samples)

    def bind(self, states: dict[str, TeamState]) -> Callable[[str], float]:
        def resolve(team_id: str) -> float:
            return self.average_for(team_id, states[team_id].maps_played)

        return resolve


def game_win_pct(team: TeamState) -> float:
    total = team.map_wins + team.map_losses
    return team.map_wins / total if total else 0.0


def _primary_key(team: TeamState, by_id: dict[str, TeamState]) -> tuple:
    known = [by_id[o] for o in team.opponents if o in by_id]
    opp_series_wins = sum(o.series_wins for o in known)
    opp_gwp = sum(game_win_pct(o) for o in known) / len(known) if known else 0.0
    return (
        -team.series_wins,
        team.series_losses,
        -opp_series_wins,
        -game_win_pct(team),
        -opp_gwp,
    )


def rank_teams(
    states: list[TeamState],
    rng: random.Random,
    duration_fn: Callable[[str], float] | None = None,
) -> list[str]:
    """Order team ids best to worst by the official tiebreak sequence.

    Criteria 1-5 are computed eagerly. Average duration is consulted only
    inside blocks still tied after those five. A surviving tie with no
    duration source is an error, not a licence to skip to the coin toss.
    """
    by_id = {s.team_id: s for s in states}
    keys = {s.team_id: _primary_key(s, by_id) for s in states}
    ordered = sorted(states, key=lambda s: keys[s.team_id])

    out: list[TeamState] = []
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and keys[ordered[j + 1].team_id] == keys[ordered[i].team_id]:
            j += 1
        block = ordered[i : j + 1]
        if len(block) > 1:
            if duration_fn is None:
                tied = [s.team_id for s in block]
                raise DurationUnavailableError(
                    f"teams {tied} tied through five criteria; duration resolver required"
                )
            durations = {s.team_id: duration_fn(s.team_id) for s in block}
            block = sorted(block, key=lambda s: (durations[s.team_id], rng.random()))
        out.extend(block)
        i = j + 1
    return [s.team_id for s in out]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tiebreak.py -v -m "not slow" && uv run ruff check src tests`
Expected: 13 passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add src/ti26/tiebreak.py tests/test_tiebreak.py
git commit -m "feat: official ranking with mandatory lazy duration resolution"
```

---

## Task 3: Pairing engine with hard constraint enforcement

**Files:**
- Create: `src/ti26/pairing.py`
- Test: `tests/test_pairing.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `NoLegalPairingError(ValueError)`; `PairingChoice(matching, repeat_count, min_possible_repeats, candidates_considered)`; `perfect_matchings(items) -> Iterator[list[tuple[str,str]]]`; `choose_pairing(team_ids, rank_index, prior_opponents, rng, *, group_of=None, cross_group=False, maximize_distance=False) -> PairingChoice`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pairing.py
import random

import pytest

from ti26.pairing import NoLegalPairingError, choose_pairing, perfect_matchings


def pairs_of(choice):
    return {frozenset(p) for p in choice.matching}


def test_perfect_matchings_count_for_four_items():
    assert len(list(perfect_matchings(["a", "b", "c", "d"]))) == 3


def test_perfect_matchings_count_for_eight_items():
    assert len(list(perfect_matchings(list("abcdefgh")))) == 105


def test_every_matching_covers_every_item_exactly_once():
    items = list("abcdef")
    for matching in perfect_matchings(items):
        flat = [x for pair in matching for x in pair]
        assert sorted(flat) == sorted(items)


def test_no_team_is_paired_with_itself():
    for matching in perfect_matchings(list("abcd")):
        assert all(a != b for a, b in matching)


def test_repeat_opponents_avoided_when_a_clean_matching_exists():
    teams = ["a", "b", "c", "d"]
    rank_index = {t: i for i, t in enumerate(teams)}
    prior = {"a": {"b"}, "b": {"a"}, "c": set(), "d": set()}
    choice = choose_pairing(teams, rank_index, prior, random.Random(0))
    assert choice.repeat_count == 0
    assert choice.min_possible_repeats == 0
    assert frozenset({"a", "b"}) not in pairs_of(choice)


def test_round_five_forced_repeat_takes_the_minimum_not_zero():
    """A realistic Round 5 record group where no repeat-free matching exists.

    Four teams share a 1-3 record. Team 'a' has already faced all three
    others, so every one of the three perfect matchings pairs 'a' with a
    previous opponent. The minimum achievable repeat count is 1, and the
    engine must take it rather than fail or silently allow more.
    """
    teams = ["a", "b", "c", "d"]
    rank_index = {t: i for i, t in enumerate(teams)}
    prior = {
        "a": {"b", "c", "d"},
        "b": {"a"},
        "c": {"a"},
        "d": {"a"},
    }
    choice = choose_pairing(teams, rank_index, prior, random.Random(0))
    assert choice.min_possible_repeats == 1
    assert choice.repeat_count == 1
    assert len(choice.matching) == 2
    flat = sorted(x for pair in choice.matching for x in pair)
    assert flat == teams


def test_complete_prior_history_yields_two_forced_repeats():
    teams = ["a", "b", "c", "d"]
    rank_index = {t: i for i, t in enumerate(teams)}
    prior = {t: set(teams) - {t} for t in teams}
    choice = choose_pairing(teams, rank_index, prior, random.Random(0))
    assert choice.min_possible_repeats == 2
    assert choice.repeat_count == 2


def test_minimum_ranking_distance_is_preferred():
    teams = ["r0", "r1", "r2", "r3"]
    rank_index = {"r0": 0, "r1": 1, "r2": 2, "r3": 3}
    prior = {t: set() for t in teams}
    choice = choose_pairing(teams, rank_index, prior, random.Random(0))
    assert pairs_of(choice) == {frozenset({"r0", "r1"}), frozenset({"r2", "r3"})}


def test_maximize_distance_flips_the_preference():
    teams = ["r0", "r1", "r2", "r3"]
    rank_index = {"r0": 0, "r1": 1, "r2": 2, "r3": 3}
    prior = {t: set() for t in teams}
    choice = choose_pairing(
        teams, rank_index, prior, random.Random(0), maximize_distance=True
    )
    assert pairs_of(choice) == {frozenset({"r0", "r3"}), frozenset({"r1", "r2"})}


def test_repeat_minimisation_outranks_ranking_distance():
    teams = ["r0", "r1", "r2", "r3"]
    rank_index = {"r0": 0, "r1": 1, "r2": 2, "r3": 3}
    # The minimum-distance matching {r0r1, r2r3} is all repeats.
    prior = {"r0": {"r1"}, "r1": {"r0"}, "r2": {"r3"}, "r3": {"r2"}}
    choice = choose_pairing(teams, rank_index, prior, random.Random(0))
    assert choice.repeat_count == 0
    assert frozenset({"r0", "r1"}) not in pairs_of(choice)


def test_cross_group_constraint_pairs_only_across_groups():
    teams = ["a1", "a2", "b1", "b2"]
    group_of = {"a1": "A", "a2": "A", "b1": "B", "b2": "B"}
    rank_index = {t: i for i, t in enumerate(teams)}
    prior = {t: set() for t in teams}
    choice = choose_pairing(
        teams, rank_index, prior, random.Random(0), group_of=group_of, cross_group=True
    )
    assert all(group_of[a] != group_of[b] for a, b in choice.matching)


def test_impossible_cross_group_raises_rather_than_falling_back():
    """A hard round constraint must never degrade silently."""
    teams = ["a1", "a2", "a3", "a4"]
    group_of = dict.fromkeys(teams, "A")
    rank_index = {t: i for i, t in enumerate(teams)}
    prior = {t: set() for t in teams}
    with pytest.raises(NoLegalPairingError, match="cross-group"):
        choose_pairing(
            teams, rank_index, prior, random.Random(0), group_of=group_of, cross_group=True
        )


def test_odd_number_of_teams_raises():
    with pytest.raises(NoLegalPairingError, match="odd"):
        choose_pairing(["a", "b", "c"], {"a": 0, "b": 1, "c": 2}, {}, random.Random(0))


def test_selection_is_deterministic_under_a_fixed_seed():
    teams = list("abcdefgh")
    rank_index = {t: i for i, t in enumerate(teams)}
    prior = {t: set() for t in teams}
    first = choose_pairing(teams, rank_index, prior, random.Random(11))
    second = choose_pairing(teams, rank_index, prior, random.Random(11))
    assert first.matching == second.matching
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pairing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.pairing'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ti26/pairing.py
import random
from collections.abc import Iterator
from dataclasses import dataclass


class NoLegalPairingError(ValueError):
    """Raised when no matching satisfies the round's hard constraints."""


@dataclass(frozen=True)
class PairingChoice:
    matching: list[tuple[str, str]]
    repeat_count: int
    min_possible_repeats: int
    candidates_considered: int


def perfect_matchings(items: list[str]) -> Iterator[list[tuple[str, str]]]:
    """Enumerate every way to partition items into unordered pairs.

    Record groups hold at most 8 teams, giving 105 matchings — small enough
    that brute force is both exhaustive and auditable.
    """
    if not items:
        yield []
        return
    first, rest = items[0], items[1:]
    for i, partner in enumerate(rest):
        remainder = rest[:i] + rest[i + 1 :]
        for tail in perfect_matchings(remainder):
            yield [(first, partner)] + tail


def choose_pairing(
    team_ids: list[str],
    rank_index: dict[str, int],
    prior_opponents: dict[str, set[str]],
    rng: random.Random,
    *,
    group_of: dict[str, str] | None = None,
    cross_group: bool = False,
    maximize_distance: bool = False,
) -> PairingChoice:
    """Select a legal pairing by lexicographic preference.

    Order: hard group constraint -> fewest repeat opponents -> ranking
    distance (minimised, or maximised for Round 5 matches whose loser is
    eliminated) -> uniform random among exact ties.

    Hard constraints raise rather than degrade. Repeat avoidance is soft per
    the official text, so the engine minimises repeats instead of forbidding
    them — whether a forced repeat is reachable in the real bracket is
    unproven, and the engine does not assume either way.
    """
    if len(team_ids) % 2 != 0:
        raise NoLegalPairingError(f"cannot pair an odd number of teams: {len(team_ids)}")

    candidates = list(perfect_matchings(list(team_ids)))
    considered = len(candidates)

    if cross_group:
        if group_of is None:
            raise NoLegalPairingError("cross-group pairing requested without group map")
        candidates = [m for m in candidates if all(group_of[a] != group_of[b] for a, b in m)]
        if not candidates:
            raise NoLegalPairingError(
                f"no cross-group matching exists for {sorted(team_ids)}"
            )

    def repeats(matching: list[tuple[str, str]]) -> int:
        return sum(1 for a, b in matching if b in prior_opponents.get(a, set()))

    fewest = min(repeats(m) for m in candidates)
    candidates = [m for m in candidates if repeats(m) == fewest]

    def distance(matching: list[tuple[str, str]]) -> int:
        return sum(abs(rank_index[a] - rank_index[b]) for a, b in matching)

    sign = -1 if maximize_distance else 1
    best = min(sign * distance(m) for m in candidates)
    candidates = [m for m in candidates if sign * distance(m) == best]

    chosen = rng.choice(candidates)
    return PairingChoice(
        matching=chosen,
        repeat_count=repeats(chosen),
        min_possible_repeats=fewest,
        candidates_considered=considered,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pairing.py -v -m "not slow" && uv run ruff check src tests`
Expected: 14 passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add src/ti26/pairing.py tests/test_pairing.py
git commit -m "feat: pairing with repeat minimisation and hard constraint enforcement"
```

---

## Task 4: Bradley-Terry map model and Bo3 series

**Files:**
- Create: `src/ti26/series.py`
- Test: `tests/test_series.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `map_win_prob(s_a, s_b) -> float`; `series_win_prob(p_map, best_of=3) -> float`; `simulate_series(s_a, s_b, rng, best_of=3) -> tuple[int,int]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_series.py
import random

import pytest

from ti26.series import map_win_prob, series_win_prob, simulate_series


def test_equal_strength_is_a_coin_flip():
    assert map_win_prob(0.0, 0.0) == pytest.approx(0.5)


def test_map_prob_is_monotone_in_strength_gap():
    assert map_win_prob(1.0, 0.0) > map_win_prob(0.5, 0.0) > map_win_prob(0.0, 0.0)


def test_quarter_logit_matches_closed_form():
    # Referenced in the spec's manual-adjustment table.
    assert map_win_prob(0.25, 0.0) == pytest.approx(0.5621765, abs=1e-6)


def test_series_win_prob_closed_form():
    assert series_win_prob(0.5) == pytest.approx(0.5)
    assert series_win_prob(0.5621765) == pytest.approx(0.5928, abs=1e-4)
    assert series_win_prob(0.525) == pytest.approx(0.5375, abs=1e-4)


def test_simulate_series_always_reaches_two_wins():
    rng = random.Random(0)
    for _ in range(500):
        wa, wb = simulate_series(0.3, -0.2, rng)
        assert max(wa, wb) == 2
        assert min(wa, wb) in (0, 1)
        assert wa + wb in (2, 3)


def test_simulated_frequency_matches_closed_form():
    rng = random.Random(42)
    trials = 20_000
    wins = sum(1 for _ in range(trials) if simulate_series(0.4, 0.0, rng)[0] == 2)
    expected = series_win_prob(map_win_prob(0.4, 0.0))
    assert wins / trials == pytest.approx(expected, abs=0.015)


def test_shared_rng_stream_is_reproducible_and_actually_varies():
    """A fresh Random per call would make this pass vacuously — use one stream."""
    rng_a = random.Random(5)
    first = [simulate_series(0.1, 0.0, rng_a) for _ in range(20)]
    rng_b = random.Random(5)
    second = [simulate_series(0.1, 0.0, rng_b) for _ in range(20)]
    assert first == second
    assert len(set(first)) > 1, "sequence must vary; identical results prove nothing"


def test_different_seeds_produce_different_sequences():
    rng_a, rng_b = random.Random(5), random.Random(99)
    seq_a = [simulate_series(0.0, 0.0, rng_a) for _ in range(30)]
    seq_b = [simulate_series(0.0, 0.0, rng_b) for _ in range(30)]
    assert seq_a != seq_b


def test_unsupported_best_of_raises():
    with pytest.raises(ValueError, match="best-of-3"):
        series_win_prob(0.5, best_of=5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_series.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.series'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ti26/series.py
import math
import random


def map_win_prob(s_a: float, s_b: float) -> float:
    """Bradley-Terry on the logit scale: P(A wins one map against B)."""
    return 1.0 / (1.0 + math.exp(-(s_a - s_b)))


def series_win_prob(p_map: float, best_of: int = 3) -> float:
    """Closed-form series win probability assuming independent maps."""
    if best_of != 3:
        raise ValueError("only best-of-3 has a closed form here")
    return p_map**2 * (3.0 - 2.0 * p_map)


def simulate_series(
    s_a: float, s_b: float, rng: random.Random, best_of: int = 3
) -> tuple[int, int]:
    """Simulate maps until one side reaches the required win count.

    Maps are conditionally independent given strengths: the spec defaults the
    series shock to zero until historical residual dependence supports one.
    """
    need = best_of // 2 + 1
    p = map_win_prob(s_a, s_b)
    wins_a = wins_b = 0
    while wins_a < need and wins_b < need:
        if rng.random() < p:
            wins_a += 1
        else:
            wins_b += 1
    return wins_a, wins_b
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_series.py -v -m "not slow" && uv run ruff check src tests`
Expected: 9 passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add src/ti26/series.py tests/test_series.py
git commit -m "feat: Bradley-Terry map model and Bo3 series simulation"
```

---

## Task 5: Swiss progression returning a full round log

**Files:**
- Create: `src/ti26/swiss.py`
- Test: `tests/test_swiss.py`

**Interfaces:**
- Consumes: `TeamState, SeriesResult, RoundLog, SwissRun` (Task 1); `rank_teams, DurationResolver` (Task 2); `choose_pairing` (Task 3); `simulate_series` (Task 4); `Rules` (Task 1).
- Produces: `random_initial_groups(team_ids, rng) -> dict[str,str]`; `random_round_one_schedule(groups, rng) -> list[tuple[str,str]]`; `run_swiss(strengths, rules, rng, groups=None, round_one=None) -> SwissRun`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_swiss.py
import random
from collections import Counter

from ti26.pairing import perfect_matchings
from ti26.rules import load_rules
from ti26.swiss import random_initial_groups, random_round_one_schedule, run_swiss

RULES = load_rules("config/ti2026_rules.yaml")
TEAMS = [f"t{i:02d}" for i in range(16)]


def flat(value=0.0):
    return dict.fromkeys(TEAMS, value)


def test_initial_groups_split_eight_and_eight():
    groups = random_initial_groups(TEAMS, random.Random(0))
    assert Counter(groups.values()) == {"A": 8, "B": 8}


def test_round_one_schedule_pairs_within_groups():
    rng = random.Random(1)
    groups = random_initial_groups(TEAMS, rng)
    schedule = random_round_one_schedule(groups, rng)
    assert len(schedule) == 8
    assert all(groups[a] == groups[b] for a, b in schedule)
    flat_ids = [x for pair in schedule for x in pair]
    assert sorted(flat_ids) == sorted(TEAMS)


def test_final_record_distribution_matches_derived_capacities():
    for seed in range(20):
        run = run_swiss(flat(), RULES, random.Random(seed))
        records = Counter(s.record for s in run.states.values())
        assert dict(records) == RULES.record_capacities


def test_round_log_has_one_entry_per_played_round():
    run = run_swiss(flat(), RULES, random.Random(3))
    assert [r.round_no for r in run.rounds] == [1, 2, 3, 4, 5]


def test_round_log_pairings_match_recorded_results():
    run = run_swiss(flat(), RULES, random.Random(4))
    for round_log in run.rounds:
        assert len(round_log.pairings) == len(round_log.results)
        logged = {frozenset(p) for p in round_log.pairings}
        played = {frozenset((r.team_a, r.team_b)) for r in round_log.results}
        assert logged == played
        for result in round_log.results:
            assert max(result.wins_a, result.wins_b) == 2


def test_every_round_achieves_the_minimum_possible_repeat_count():
    """Repeats are minimised, not assumed to be zero."""
    for seed in range(30):
        run = run_swiss(flat(), RULES, random.Random(seed))
        for round_log in run.rounds:
            assert round_log.repeat_count == round_log.min_possible_repeats


def test_repeat_flags_agree_with_prior_opponents():
    run = run_swiss(flat(), RULES, random.Random(5))
    seen: dict[str, set[str]] = {t: set() for t in TEAMS}
    for round_log in run.rounds:
        for result in round_log.results:
            assert result.was_repeat == (result.team_b in seen[result.team_a])
            seen[result.team_a].add(result.team_b)
            seen[result.team_b].add(result.team_a)


def test_rankings_are_logged_and_cover_every_team():
    run = run_swiss(flat(), RULES, random.Random(6))
    for round_log in run.rounds[1:]:  # round 1 uses the organiser schedule
        assert sorted(round_log.ranking) == sorted(TEAMS)


def records_before_round(run, round_no):
    """Replay the log to recover each team's (wins, losses) entering a round."""
    tally = {t: [0, 0] for t in run.states}
    for round_log in run.rounds:
        if round_log.round_no >= round_no:
            break
        for result in round_log.results:
            winner, loser = (
                (result.team_a, result.team_b)
                if result.wins_a > result.wins_b
                else (result.team_b, result.team_a)
            )
            tally[winner][0] += 1
            tally[loser][1] += 1
    return {t: tuple(v) for t, v in tally.items()}


def test_round_two_pairs_within_record_and_initial_group():
    rng = random.Random(8)
    groups = random_initial_groups(TEAMS, rng)
    schedule = random_round_one_schedule(groups, rng)
    run = run_swiss(flat(), RULES, rng, groups=groups, round_one=schedule)
    before = records_before_round(run, 2)
    for a, b in run.rounds[1].pairings:
        assert before[a] == before[b], "round 2 pairs equal records"
        assert groups[a] == groups[b], "round 2 stays within the initial group"


def test_no_team_ever_plays_itself():
    run = run_swiss(flat(), RULES, random.Random(3))
    for state in run.states.values():
        assert state.team_id not in state.opponents


def test_rounds_two_and_three_stay_within_initial_groups():
    rng = random.Random(4)
    groups = random_initial_groups(TEAMS, rng)
    schedule = random_round_one_schedule(groups, rng)
    run = run_swiss(flat(), RULES, rng, groups=groups, round_one=schedule)
    for state in run.states.values():
        for opponent in state.opponents[:3]:
            assert groups[opponent] == groups[state.team_id]


def test_round_four_is_cross_group():
    rng = random.Random(5)
    groups = random_initial_groups(TEAMS, rng)
    schedule = random_round_one_schedule(groups, rng)
    run = run_swiss(flat(), RULES, rng, groups=groups, round_one=schedule)
    for state in run.states.values():
        if len(state.opponents) >= 4:
            assert groups[state.opponents[3]] != groups[state.team_id]


def spread(matching, rank_index):
    return sum(abs(rank_index[a] - rank_index[b]) for a, b in matching)


def test_round_five_maximises_distance_when_the_loser_is_eliminated():
    """The 1-3 group's Round 5 loser goes to 1-4 and is out, so pair furthest."""
    run = run_swiss(flat(), RULES, random.Random(12))
    round_five = run.rounds[4]
    before = records_before_round(run, 5)
    rank_index = {t: i for i, t in enumerate(round_five.ranking)}

    group = sorted(t for t, rec in before.items() if rec == (1, 3))
    assert len(group) == 4
    chosen = [p for p in round_five.pairings if set(p) <= set(group)]
    assert len(chosen) == 2

    best = max(spread(m, rank_index) for m in perfect_matchings(group))
    assert spread(chosen, rank_index) == best


def test_round_five_minimises_distance_when_the_loser_survives():
    """The 3-1 group's Round 5 loser drops to 3-2 and plays on, so pair closest."""
    run = run_swiss(flat(), RULES, random.Random(12))
    round_five = run.rounds[4]
    before = records_before_round(run, 5)
    rank_index = {t: i for i, t in enumerate(round_five.ranking)}

    group = sorted(t for t, rec in before.items() if rec == (3, 1))
    assert len(group) == 4
    chosen = [p for p in round_five.pairings if set(p) <= set(group)]
    assert len(chosen) == 2

    smallest = min(spread(m, rank_index) for m in perfect_matchings(group))
    assert spread(chosen, rank_index) == smallest


def test_stronger_teams_finish_higher_on_average():
    strengths = {t: (i - 7.5) * 0.4 for i, t in enumerate(TEAMS)}
    totals = Counter()
    for seed in range(200):
        run = run_swiss(strengths, RULES, random.Random(seed))
        for tid, state in run.states.items():
            totals[tid] += state.series_wins
    assert totals["t15"] > totals["t00"]


def test_run_is_seed_reproducible():
    a = run_swiss(flat(), RULES, random.Random(9))
    b = run_swiss(flat(), RULES, random.Random(9))
    assert {k: v.record for k, v in a.states.items()} == {
        k: v.record for k, v in b.states.items()
    }
    assert [r.pairings for r in a.rounds] == [r.pairings for r in b.rounds]


def test_map_counts_are_consistent_with_series_counts():
    run = run_swiss(flat(), RULES, random.Random(2))
    for state in run.states.values():
        played = state.series_wins + state.series_losses
        assert played == len(state.opponents)
        assert 2 * played <= state.maps_played <= 3 * played
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_swiss.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.swiss'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ti26/swiss.py
import random
from collections import defaultdict

from ti26.pairing import choose_pairing
from ti26.rules import Rules
from ti26.series import simulate_series
from ti26.tiebreak import DurationResolver, rank_teams
from ti26.types import RoundLog, SeriesResult, SwissRun, TeamState


def random_initial_groups(team_ids: list[str], rng: random.Random) -> dict[str, str]:
    shuffled = list(team_ids)
    rng.shuffle(shuffled)
    half = len(shuffled) // 2
    return {t: ("A" if i < half else "B") for i, t in enumerate(shuffled)}


def random_round_one_schedule(
    groups: dict[str, str], rng: random.Random
) -> list[tuple[str, str]]:
    schedule: list[tuple[str, str]] = []
    for label in sorted(set(groups.values())):
        members = sorted(t for t, g in groups.items() if g == label)
        rng.shuffle(members)
        schedule.extend((members[i], members[i + 1]) for i in range(0, len(members), 2))
    return schedule


def _play(
    states: dict[str, TeamState],
    pair: tuple[str, str],
    strengths: dict[str, float],
    rng: random.Random,
    round_no: int,
) -> SeriesResult:
    a, b = pair
    sa, sb = states[a], states[b]
    was_repeat = b in sa.opponents
    wins_a, wins_b = simulate_series(strengths[a], strengths[b], rng)
    sa.map_wins += wins_a
    sa.map_losses += wins_b
    sb.map_wins += wins_b
    sb.map_losses += wins_a
    if wins_a > wins_b:
        sa.series_wins += 1
        sb.series_losses += 1
    else:
        sb.series_wins += 1
        sa.series_losses += 1
    sa.opponents.append(b)
    sb.opponents.append(a)
    return SeriesResult(
        round_no=round_no,
        team_a=a,
        team_b=b,
        wins_a=wins_a,
        wins_b=wins_b,
        was_repeat=was_repeat,
    )


def run_swiss(
    strengths: dict[str, float],
    rules: Rules,
    rng: random.Random,
    groups: dict[str, str] | None = None,
    round_one: list[tuple[str, str]] | None = None,
) -> SwissRun:
    """Run all Swiss rounds, returning final states plus a full round log."""
    team_ids = sorted(strengths)
    if groups is None:
        groups = random_initial_groups(team_ids, rng)
    if round_one is None:
        round_one = random_round_one_schedule(groups, rng)

    states = {t: TeamState(team_id=t, initial_group=groups[t]) for t in team_ids}
    resolver = DurationResolver(rng, rules.duration_log_mean, rules.duration_log_sigma)
    logs: list[RoundLog] = []

    results = [_play(states, pair, strengths, rng, 1) for pair in round_one]
    logs.append(
        RoundLog(
            round_no=1,
            ranking=list(team_ids),
            pairings=list(round_one),
            repeat_count=0,
            min_possible_repeats=0,
            results=results,
        )
    )

    for round_no in range(2, rules.total_rounds + 1):
        active = [s for s in states.values() if rules.is_active(s)]
        if not active:
            break
        ranking = rank_teams(
            list(states.values()), rng, duration_fn=resolver.bind(states)
        )
        rank_index = {tid: i for i, tid in enumerate(ranking)}
        prior = {s.team_id: set(s.opponents) for s in states.values()}

        buckets: dict[tuple, list[str]] = defaultdict(list)
        for state in active:
            key = (
                (state.record, state.initial_group)
                if round_no in rules.within_group_rounds
                else (state.record,)
            )
            buckets[key].append(state.team_id)

        pairings: list[tuple[str, str]] = []
        results = []
        repeat_count = min_possible = 0
        for key in sorted(buckets, key=str):
            record = key[0]
            loser_out = record[1] + 1 >= rules.eliminate_at_losses
            choice = choose_pairing(
                sorted(buckets[key]),
                rank_index,
                prior,
                rng,
                group_of=groups,
                cross_group=round_no in rules.cross_group_rounds,
                maximize_distance=(
                    loser_out and round_no in rules.max_distance_elimination_rounds
                ),
            )
            repeat_count += choice.repeat_count
            min_possible += choice.min_possible_repeats
            pairings.extend(choice.matching)
            results.extend(
                _play(states, pair, strengths, rng, round_no) for pair in choice.matching
            )

        logs.append(
            RoundLog(
                round_no=round_no,
                ranking=ranking,
                pairings=pairings,
                repeat_count=repeat_count,
                min_possible_repeats=min_possible,
                results=results,
            )
        )

    return SwissRun(states=states, groups=groups, rounds=logs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_swiss.py -v -m "not slow" && uv run ruff check src tests`
Expected: 17 passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add src/ti26/swiss.py tests/test_swiss.py
git commit -m "feat: Swiss progression with round-by-round pairing and ranking log"
```

---

## Task 6: Elimination round with an inspectable choice log

**Files:**
- Create: `src/ti26/elimination.py`
- Test: `tests/test_elimination.py`

**Interfaces:**
- Consumes: `SwissRun, EliminationMatch, EliminationRun, Category` (Task 1); `rank_teams, DurationResolver` (Task 2); `map_win_prob, series_win_prob, simulate_series` (Task 4); `category_for_terminal_record`, `Rules` (Task 1).
- Produces: `ChoicePolicy` str enum (`RATIONAL, NOISY, RANDOM`); `run_elimination(run: SwissRun, strengths, rules, rng, policy=ChoicePolicy.RATIONAL, softmax_temp=1.0) -> EliminationRun`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_elimination.py
import random
from collections import Counter

import pytest

from ti26.elimination import ChoicePolicy, run_elimination
from ti26.rules import load_rules
from ti26.swiss import run_swiss
from ti26.types import Category

RULES = load_rules("config/ti2026_rules.yaml")
TEAMS = [f"t{i:02d}" for i in range(16)]


def flat(value=0.0):
    return dict.fromkeys(TEAMS, value)


@pytest.mark.parametrize("policy", list(ChoicePolicy))
def test_every_team_gets_exactly_one_category(policy):
    run = run_swiss(flat(), RULES, random.Random(0))
    result = run_elimination(run, flat(), RULES, random.Random(0), policy=policy)
    assert set(result.categories) == set(TEAMS)


@pytest.mark.parametrize("policy", list(ChoicePolicy))
def test_category_counts_match_derived_capacities(policy):
    for seed in range(10):
        run = run_swiss(flat(), RULES, random.Random(seed))
        result = run_elimination(run, flat(), RULES, random.Random(seed), policy=policy)
        assert Counter(result.categories.values()) == RULES.category_capacities


def test_swiss_records_map_to_the_right_categories():
    run = run_swiss(flat(), RULES, random.Random(1))
    result = run_elimination(run, flat(), RULES, random.Random(1))
    for tid, state in run.states.items():
        if state.record == (4, 0):
            assert result.categories[tid] == Category.W4_0
        elif state.record == (4, 1):
            assert result.categories[tid] == Category.W4_1
        elif state.record == (1, 4):
            assert result.categories[tid] == Category.L1_4
        elif state.record == (0, 4):
            assert result.categories[tid] == Category.L0_4
        else:
            assert result.categories[tid] in (Category.ELIM_WIN, Category.ELIM_LOSS)


def test_five_matches_pair_three_two_against_two_three():
    run = run_swiss(flat(), RULES, random.Random(7))
    result = run_elimination(run, flat(), RULES, random.Random(7))
    assert len(result.matches) == 5
    for match in result.matches:
        assert run.states[match.chooser].record == (3, 2)
        assert run.states[match.opponent].record == (2, 3)


def test_rational_policy_selects_the_weakest_available_opponent():
    """Assert the SELECTION, not a stochastic match outcome."""
    strengths = flat()
    run = run_swiss(strengths, RULES, random.Random(2))
    two_three = [t for t, s in run.states.items() if s.record == (2, 3)]
    weakest = sorted(two_three)[0]
    strengths[weakest] = -6.0

    result = run_elimination(
        run, strengths, RULES, random.Random(2), policy=ChoicePolicy.RATIONAL
    )
    first = result.matches[0]
    assert weakest in first.available_when_choosing
    assert first.opponent == weakest


def test_rational_choices_are_never_worse_than_the_alternatives():
    from ti26.series import map_win_prob, series_win_prob

    strengths = {t: (i - 7.5) * 0.35 for i, t in enumerate(TEAMS)}
    run = run_swiss(strengths, RULES, random.Random(11))
    result = run_elimination(
        run, strengths, RULES, random.Random(11), policy=ChoicePolicy.RATIONAL
    )
    for match in result.matches:
        chosen = series_win_prob(
            map_win_prob(strengths[match.chooser], strengths[match.opponent])
        )
        for alternative in match.available_when_choosing:
            other = series_win_prob(
                map_win_prob(strengths[match.chooser], strengths[alternative])
            )
            assert chosen >= other - 1e-12


def test_choosers_act_in_ranking_order():
    run = run_swiss(flat(), RULES, random.Random(3))
    result = run_elimination(run, flat(), RULES, random.Random(3))
    sizes = [len(m.available_when_choosing) for m in result.matches]
    assert sizes == [5, 4, 3, 2, 1]


def test_random_policy_still_selects_from_available_only():
    run = run_swiss(flat(), RULES, random.Random(4))
    result = run_elimination(
        run, flat(), RULES, random.Random(4), policy=ChoicePolicy.RANDOM
    )
    taken: set[str] = set()
    for match in result.matches:
        assert match.opponent in match.available_when_choosing
        assert match.opponent not in taken
        taken.add(match.opponent)


def test_policies_are_seed_reproducible():
    run = run_swiss(flat(), RULES, random.Random(6))
    a = run_elimination(run, flat(), RULES, random.Random(6))
    b = run_elimination(run, flat(), RULES, random.Random(6))
    assert a.categories == b.categories
    assert [m.opponent for m in a.matches] == [m.opponent for m in b.matches]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_elimination.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.elimination'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ti26/elimination.py
import math
import random
from enum import Enum

from ti26.rules import Rules, category_for_terminal_record
from ti26.series import map_win_prob, series_win_prob, simulate_series
from ti26.tiebreak import DurationResolver, rank_teams
from ti26.types import Category, EliminationMatch, EliminationRun, SwissRun


class ChoicePolicy(str, Enum):
    RATIONAL = "rational"
    NOISY = "noisy"
    RANDOM = "random"


def _select_opponent(
    chooser: str,
    available: list[str],
    strengths: dict[str, float],
    rng: random.Random,
    policy: ChoicePolicy,
    softmax_temp: float,
) -> str:
    if policy is ChoicePolicy.RANDOM:
        return rng.choice(available)

    win_probs = [
        series_win_prob(map_win_prob(strengths[chooser], strengths[opp]))
        for opp in available
    ]
    if policy is ChoicePolicy.RATIONAL:
        return available[win_probs.index(max(win_probs))]

    weights = [math.exp(p / softmax_temp) for p in win_probs]
    return rng.choices(available, weights=weights, k=1)[0]


def run_elimination(
    run: SwissRun,
    strengths: dict[str, float],
    rules: Rules,
    rng: random.Random,
    policy: ChoicePolicy = ChoicePolicy.RATIONAL,
    softmax_temp: float = 1.0,
) -> EliminationRun:
    """Resolve the elimination matches and assign every team a category."""
    categories: dict[str, Category] = {}
    undecided: list[str] = []
    for tid, state in run.states.items():
        fixed = category_for_terminal_record(
            state.record, rules.advance_at_wins, rules.eliminate_at_losses
        )
        if fixed is None:
            undecided.append(tid)
        else:
            categories[tid] = fixed

    resolver = DurationResolver(rng, rules.duration_log_mean, rules.duration_log_sigma)
    ranking = rank_teams(
        list(run.states.values()), rng, duration_fn=resolver.bind(run.states)
    )
    order = {tid: i for i, tid in enumerate(ranking)}

    top_record = max(run.states[t].record for t in undecided)
    choosers = sorted(
        (t for t in undecided if run.states[t].record == top_record),
        key=lambda t: order[t],
    )
    available = sorted(
        (t for t in undecided if run.states[t].record != top_record),
        key=lambda t: order[t],
    )

    matches: list[EliminationMatch] = []
    for chooser in choosers:
        snapshot = list(available)
        opponent = _select_opponent(
            chooser, available, strengths, rng, policy, softmax_temp
        )
        available.remove(opponent)
        wins_c, wins_o = simulate_series(strengths[chooser], strengths[opponent], rng)
        if wins_c > wins_o:
            categories[chooser] = Category.ELIM_WIN
            categories[opponent] = Category.ELIM_LOSS
        else:
            categories[chooser] = Category.ELIM_LOSS
            categories[opponent] = Category.ELIM_WIN
        matches.append(
            EliminationMatch(
                chooser=chooser,
                opponent=opponent,
                available_when_choosing=snapshot,
                wins_chooser=wins_c,
                wins_opponent=wins_o,
            )
        )

    return EliminationRun(categories=categories, matches=matches)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_elimination.py -v -m "not slow" && uv run ruff check src tests`
Expected: 13 passed (2 tests parametrised over 3 policies), ruff clean

- [ ] **Step 5: Commit**

```bash
git add src/ti26/elimination.py tests/test_elimination.py
git commit -m "feat: elimination round with inspectable sequential opponent choice"
```

---

## Task 7: Monte Carlo driver and Hungarian card optimizer

**Files:**
- Create: `src/ti26/montecarlo.py`, `src/ti26/optimize.py`
- Test: `tests/test_montecarlo.py`, `tests/test_optimize.py`

**Interfaces:**
- Consumes: `run_swiss` (Task 5); `run_elimination, ChoicePolicy` (Task 6); `Rules, Category` (Task 1).
- Produces: `monte_carlo_stderr(p, n) -> float`; `category_marginals(strengths, rules, n_sims, seed, policy=ChoicePolicy.RATIONAL) -> dict[str, dict[Category, float]]`; `solve_card(marginals, capacities, weights=None) -> tuple[dict[str, Category], float]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_optimize.py
import pytest

from ti26.optimize import solve_card
from ti26.rules import load_rules
from ti26.types import Category

RULES = load_rules("config/ti2026_rules.yaml")
CAPS = RULES.category_capacities
TEAMS = [f"t{i:02d}" for i in range(16)]


def uniform_marginals():
    return {t: {c: CAPS[c] / 16 for c in Category} for t in TEAMS}


def test_card_respects_capacities():
    card, _ = solve_card(uniform_marginals(), CAPS)
    counts = {c: sum(1 for v in card.values() if v == c) for c in Category}
    assert counts == CAPS


def test_every_team_assigned_exactly_once():
    card, _ = solve_card(uniform_marginals(), CAPS)
    assert sorted(card) == sorted(TEAMS)


def test_uniform_marginals_score_the_random_baseline():
    _, score = solve_card(uniform_marginals(), CAPS)
    assert score == pytest.approx(RULES.random_baseline)
    assert score == pytest.approx(3.75)


def test_confident_marginals_beat_the_baseline():
    marginals = uniform_marginals()
    marginals["t00"] = {c: 0.0 for c in Category}
    marginals["t00"][Category.W4_0] = 1.0
    _, score = solve_card(marginals, CAPS)
    assert score > RULES.random_baseline


def test_greedy_argmax_would_violate_capacity_but_solver_does_not():
    marginals = {}
    for t in TEAMS:
        row = {c: 0.01 for c in Category}
        row[Category.W4_0] = 0.95
        marginals[t] = row
    card, _ = solve_card(marginals, CAPS)
    assert sum(1 for v in card.values() if v == Category.W4_0) == 1


def test_category_weights_shift_the_assignment():
    marginals = uniform_marginals()
    marginals["t00"][Category.L0_4] = 0.30
    marginals["t00"][Category.ELIM_WIN] = 0.31
    heavy = {c: 1.0 for c in Category}
    heavy[Category.L0_4] = 10.0
    card, _ = solve_card(marginals, CAPS, weights=heavy)
    assert card["t00"] == Category.L0_4


def test_team_count_mismatch_raises():
    marginals = {t: {c: CAPS[c] / 16 for c in Category} for t in TEAMS[:15]}
    with pytest.raises(ValueError, match="slots"):
        solve_card(marginals, CAPS)
```

```python
# tests/test_montecarlo.py
import pytest

from ti26.elimination import ChoicePolicy
from ti26.montecarlo import category_marginals, monte_carlo_stderr
from ti26.rules import load_rules
from ti26.types import Category

RULES = load_rules("config/ti2026_rules.yaml")
CAPS = RULES.category_capacities
TEAMS = [f"t{i:02d}" for i in range(16)]


def test_each_team_row_sums_to_one():
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=200, seed=0)
    for row in marginals.values():
        assert sum(row.values()) == pytest.approx(1.0)


def test_each_category_column_sums_to_its_capacity():
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=200, seed=0)
    for category, capacity in CAPS.items():
        assert sum(r[category] for r in marginals.values()) == pytest.approx(capacity)


def test_stderr_formula():
    assert monte_carlo_stderr(0.5, 10_000) == pytest.approx(0.005)
    assert monte_carlo_stderr(0.0, 100) == 0.0


def test_stronger_team_is_likelier_to_go_four_zero():
    strengths = dict.fromkeys(TEAMS, 0.0)
    strengths["t00"] = 1.5
    marginals = category_marginals(strengths, RULES, n_sims=2000, seed=2)
    assert marginals["t00"][Category.W4_0] > marginals["t01"][Category.W4_0]
    assert marginals["t00"][Category.L0_4] < marginals["t01"][Category.L0_4]


def test_same_seed_reproduces_identical_marginals():
    a = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=100, seed=9)
    b = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=100, seed=9)
    assert a == b


def test_different_seeds_produce_different_marginals():
    a = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=100, seed=9)
    b = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=100, seed=10)
    assert a != b


def test_policy_choice_is_plumbed_through():
    marginals = category_marginals(
        dict.fromkeys(TEAMS, 0.0), RULES, n_sims=100, seed=3, policy=ChoicePolicy.RANDOM
    )
    assert sum(marginals["t00"].values()) == pytest.approx(1.0)


@pytest.mark.slow
def test_equal_strength_teams_approach_capacity_over_sixteen():
    n = 4000
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=n, seed=1)
    for team, row in marginals.items():
        for category, capacity in CAPS.items():
            expected = capacity / 16
            tolerance = 4 * monte_carlo_stderr(expected, n)
            assert row[category] == pytest.approx(expected, abs=tolerance), (
                f"{team}/{category}"
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_optimize.py tests/test_montecarlo.py -v -m "not slow"`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.optimize'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ti26/optimize.py
import numpy as np
from scipy.optimize import linear_sum_assignment

from ti26.types import Category


def solve_card(
    marginals: dict[str, dict[Category, float]],
    capacities: dict[Category, int],
    weights: dict[Category, float] | None = None,
) -> tuple[dict[str, Category], float]:
    """Assign every team to exactly one category, respecting slot capacities.

    Returns the card and the model-implied expected score. That score is
    computed from the model's own probabilities and is therefore descriptive
    only -- never evidence of forecast quality (see spec section II).
    """
    teams = sorted(marginals)
    slots: list[Category] = [c for c in Category for _ in range(capacities[c])]
    if len(slots) != len(teams):
        raise ValueError(f"{len(teams)} teams cannot fill {len(slots)} slots")

    weight = weights or dict.fromkeys(Category, 1.0)
    payoff = np.array(
        [[marginals[t][c] * weight[c] for c in slots] for t in teams], dtype=float
    )
    rows, cols = linear_sum_assignment(-payoff)
    card = {teams[r]: slots[c] for r, c in zip(rows, cols, strict=True)}
    return card, float(payoff[rows, cols].sum())
```

```python
# src/ti26/montecarlo.py
import math
import random
from collections import Counter

from ti26.elimination import ChoicePolicy, run_elimination
from ti26.rules import Rules
from ti26.swiss import run_swiss
from ti26.types import Category


def monte_carlo_stderr(p: float, n: int) -> float:
    return math.sqrt(max(p * (1.0 - p), 0.0) / n)


def category_marginals(
    strengths: dict[str, float],
    rules: Rules,
    n_sims: int,
    seed: int,
    policy: ChoicePolicy = ChoicePolicy.RATIONAL,
) -> dict[str, dict[Category, float]]:
    """Run n_sims tournaments and return P[team][category]."""
    tally: dict[str, Counter] = {t: Counter() for t in strengths}
    for i in range(n_sims):
        rng = random.Random(seed * 1_000_003 + i)
        run = run_swiss(strengths, rules, rng)
        outcome = run_elimination(run, strengths, rules, rng, policy=policy)
        for team, category in outcome.categories.items():
            tally[team][category] += 1
    return {t: {c: tally[t][c] / n_sims for c in Category} for t in strengths}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_optimize.py tests/test_montecarlo.py -v -m "not slow" && uv run ruff check src tests`
Expected: 14 passed, 1 deselected (slow), ruff clean

- [ ] **Step 5: Commit**

```bash
git add src/ti26/montecarlo.py src/ti26/optimize.py tests/test_montecarlo.py tests/test_optimize.py
git commit -m "feat: Monte Carlo category marginals and Hungarian card optimizer"
```

---

## Task 8: Invariant suite, equivariance, and CLI

**Files:**
- Create: `src/ti26/cli.py`, `tests/test_invariants.py`, `tests/test_cli.py`
- Test: all of the above, plus the full suite including `slow`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: `main(argv=None) -> int` writing `reports/category_probabilities.csv` and `reports/recommended_card.json`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_invariants.py
"""The spec section IX invariant suite. These must hold in 100% of runs."""

import random
from collections import Counter

import pytest

from ti26.elimination import ChoicePolicy, run_elimination
from ti26.montecarlo import category_marginals, monte_carlo_stderr
from ti26.rules import load_rules
from ti26.swiss import random_initial_groups, random_round_one_schedule, run_swiss
from ti26.types import Category

RULES = load_rules("config/ti2026_rules.yaml")
CAPS = RULES.category_capacities
TEAMS = [f"t{i:02d}" for i in range(16)]
SEEDS = range(60)


def varied_strengths(seed):
    rng = random.Random(seed)
    return {t: rng.gauss(0, 0.8) for t in TEAMS}


@pytest.mark.parametrize("seed", SEEDS)
def test_category_counts_are_always_exact(seed):
    strengths = varied_strengths(seed)
    run = run_swiss(strengths, RULES, random.Random(seed))
    outcome = run_elimination(run, strengths, RULES, random.Random(seed))
    assert Counter(outcome.categories.values()) == CAPS


@pytest.mark.parametrize("seed", SEEDS)
def test_exactly_eight_teams_advance(seed):
    strengths = varied_strengths(seed)
    run = run_swiss(strengths, RULES, random.Random(seed))
    outcome = run_elimination(run, strengths, RULES, random.Random(seed))
    advancing = sum(
        1
        for c in outcome.categories.values()
        if c in (Category.W4_0, Category.W4_1, Category.ELIM_WIN)
    )
    assert advancing == 8


@pytest.mark.parametrize("seed", SEEDS)
def test_no_self_pairing(seed):
    run = run_swiss(varied_strengths(seed), RULES, random.Random(seed))
    for state in run.states.values():
        assert state.team_id not in state.opponents


@pytest.mark.parametrize("seed", SEEDS)
def test_repeats_are_minimised_not_assumed_absent(seed):
    """The engine must achieve the minimum repeat count every round.

    Whether that minimum is ever above zero in a real 16-team five-round
    Swiss is unproven; this asserts optimality, not absence.
    """
    run = run_swiss(varied_strengths(seed), RULES, random.Random(seed))
    for round_log in run.rounds:
        assert round_log.repeat_count == round_log.min_possible_repeats


@pytest.mark.parametrize("seed", SEEDS)
def test_group_constraints_hold(seed):
    rng = random.Random(seed)
    groups = random_initial_groups(TEAMS, rng)
    schedule = random_round_one_schedule(groups, rng)
    run = run_swiss(varied_strengths(seed), RULES, rng, groups=groups, round_one=schedule)
    for state in run.states.values():
        for opponent in state.opponents[:3]:
            assert groups[opponent] == groups[state.team_id], "rounds 1-3 stay in group"
        if len(state.opponents) >= 4:
            assert groups[state.opponents[3]] != groups[state.team_id], "R4 cross-group"


@pytest.mark.parametrize("policy", list(ChoicePolicy))
def test_invariants_hold_under_every_choice_policy(policy):
    strengths = {t: (i - 7.5) * 0.3 for i, t in enumerate(TEAMS)}
    for seed in range(10):
        run = run_swiss(strengths, RULES, random.Random(seed))
        outcome = run_elimination(
            run, strengths, RULES, random.Random(seed), policy=policy
        )
        assert Counter(outcome.categories.values()) == CAPS


def test_probability_rows_and_columns_are_consistent():
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=500, seed=8)
    for row in marginals.values():
        assert sum(row.values()) == pytest.approx(1.0)
    for category, capacity in CAPS.items():
        assert sum(r[category] for r in marginals.values()) == pytest.approx(capacity)


def test_renaming_teams_maps_every_row_through_the_bijection():
    """Row-wise equivariance under an explicit order-preserving bijection.

    Team identity must not influence outcomes beyond ordering, so relabelling
    must reproduce each team's full probability row exactly -- not merely
    preserve column sums, which hold by construction and prove nothing.
    """
    n = 800
    bijection = {f"t{i:02d}": f"z{i:02d}" for i in range(16)}
    base = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=n, seed=5)
    renamed = category_marginals(
        {bijection[t]: 0.0 for t in TEAMS}, RULES, n_sims=n, seed=5
    )
    for team, row in base.items():
        target = renamed[bijection[team]]
        for category in Category:
            assert target[category] == row[category], f"{team}->{bijection[team]}"


@pytest.mark.slow
def test_permuting_strengths_permutes_the_marginals():
    """Outcomes must track strength, not team name."""
    n = 6000
    ladder = [(i - 7.5) * 0.5 for i in range(16)]
    straight = category_marginals(
        {t: ladder[i] for i, t in enumerate(TEAMS)}, RULES, n_sims=n, seed=21
    )
    reversed_map = {t: ladder[15 - i] for i, t in enumerate(TEAMS)}
    flipped = category_marginals(reversed_map, RULES, n_sims=n, seed=21)
    tolerance = 5 * monte_carlo_stderr(0.25, n)
    for i, team in enumerate(TEAMS):
        mirror = TEAMS[15 - i]
        for category in Category:
            assert flipped[mirror][category] == pytest.approx(
                straight[team][category], abs=tolerance
            ), f"{team} vs {mirror} / {category}"


@pytest.mark.slow
def test_equal_strength_symmetry_within_monte_carlo_tolerance():
    n = 6000
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=n, seed=101)
    for team, row in marginals.items():
        for category, capacity in CAPS.items():
            expected = capacity / 16
            tolerance = 4 * monte_carlo_stderr(expected, n)
            assert row[category] == pytest.approx(expected, abs=tolerance), (
                f"{team}/{category} outside {tolerance:.4f} of {expected:.4f}"
            )
```

```python
# tests/test_cli.py
import json

from ti26.cli import main
from ti26.rules import load_rules
from ti26.types import Category

RULES = load_rules("config/ti2026_rules.yaml")


def test_cli_writes_a_legal_card(tmp_path):
    out = tmp_path / "reports"
    assert main(["--n-sims", "300", "--seed", "4", "--out", str(out)]) == 0

    card = json.loads((out / "recommended_card.json").read_text())
    assert len(card["assignments"]) == 16
    counts = {c: 0 for c in Category}
    for category in card["assignments"].values():
        counts[Category(category)] += 1
    assert counts == RULES.category_capacities
    assert card["seed"] == 4
    assert card["n_sims"] == 300
    assert card["random_baseline"] == RULES.random_baseline
    assert "model_implied_expected_score" in card

    lines = (out / "category_probabilities.csv").read_text().splitlines()
    assert lines[0].startswith("team,")
    assert len(lines) == 17


def test_cli_is_reproducible(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    main(["--n-sims", "200", "--seed", "77", "--out", str(a)])
    main(["--n-sims", "200", "--seed", "77", "--out", str(b)])
    assert (a / "recommended_card.json").read_text() == (
        b / "recommended_card.json"
    ).read_text()


def test_cli_accepts_a_strengths_file(tmp_path):
    strengths = tmp_path / "s.csv"
    rows = ["team,strength"] + [f"x{i:02d},{(i - 7.5) * 0.2:.4f}" for i in range(16)]
    strengths.write_text("\n".join(rows) + "\n")
    out = tmp_path / "reports"
    assert main(["--strengths", str(strengths), "--n-sims", "200", "--out", str(out)]) == 0
    card = json.loads((out / "recommended_card.json").read_text())
    assert sorted(card["assignments"]) == [f"x{i:02d}" for i in range(16)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v -m "not slow"`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.cli'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ti26/cli.py
import argparse
import csv
import json
from pathlib import Path

from ti26.elimination import ChoicePolicy
from ti26.montecarlo import category_marginals
from ti26.optimize import solve_card
from ti26.rules import load_rules
from ti26.types import Category


def _load_strengths(path: str | None, n_teams: int) -> dict[str, float]:
    if path is None:
        # Synthetic ladder: D1 has no ingestion, so strengths are an input.
        return {f"t{i:02d}": (i - (n_teams - 1) / 2) * 0.15 for i in range(n_teams)}
    with open(path) as fh:
        return {row["team"]: float(row["strength"]) for row in csv.DictReader(fh)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TI 2026 Swiss card generator")
    parser.add_argument("--strengths", default=None, help="CSV with team,strength")
    parser.add_argument("--rules", default="config/ti2026_rules.yaml")
    parser.add_argument("--n-sims", type=int, default=250_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--policy", default=ChoicePolicy.RATIONAL.value)
    parser.add_argument("--out", default="reports")
    args = parser.parse_args(argv)

    rules = load_rules(args.rules)
    strengths = _load_strengths(args.strengths, rules.n_teams)
    marginals = category_marginals(
        strengths,
        rules,
        n_sims=args.n_sims,
        seed=args.seed,
        policy=ChoicePolicy(args.policy),
    )
    card, score = solve_card(marginals, rules.category_capacities)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with (out / "category_probabilities.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["team", *(c.value for c in Category)])
        for team in sorted(marginals):
            writer.writerow([team, *(f"{marginals[team][c]:.6f}" for c in Category)])

    payload = {
        "assignments": {t: c.value for t, c in sorted(card.items())},
        "model_implied_expected_score": round(score, 4),
        "random_baseline": rules.random_baseline,
        "n_sims": args.n_sims,
        "seed": args.seed,
        "policy": args.policy,
        "note": (
            "model_implied_expected_score is computed from the model's own "
            "probabilities and is descriptive only, never evidence of skill"
        ),
    }
    (out / "recommended_card.json").write_text(json.dumps(payload, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the full suite including slow tests, then an end-to-end run**

Run: `uv run pytest -v` (no marker filter — slow tests included)
Expected: entire suite passes

Run: `uv run ruff check src tests`
Expected: clean

Run: `uv run python -m ti26.cli --n-sims 50000 --seed 1 --out reports`
Expected: exit 0; `reports/recommended_card.json` holds 16 assignments whose category counts equal `rules.category_capacities`; `model_implied_expected_score` above 3.75 for the synthetic ladder.

Run: `grep -rn "1, 2, 5, 5, 2, 1\|\[1,2,5,5,2,1\]" src/`
Expected: no matches — capacities are derived, never literal in source.

- [ ] **Step 5: Commit**

```bash
git add src/ti26/cli.py tests/test_invariants.py tests/test_cli.py
git commit -m "feat: invariant suite, row-wise equivariance, and card generator CLI"
```

---

## Self-Review

**Spec coverage.** Rules truth table and provenance → Task 1; official tiebreak with lazy-but-mandatory duration → Task 2; pairing with soft repeat minimisation and hard constraint enforcement → Task 3; map simulation under conditional independence (§VI) → Task 4; round constraints and max-distance-when-loser-eliminated → Task 5; sequential opponent choice, three policies → Task 6; Hungarian assignment with weights and the descriptive-only objective → Task 7; the §IX invariant list → Task 8.

**Revision notes (what changed and why).**
1. *Forced repeats.* The previous plan asserted repeats can never be forced in a 16-team five-round Swiss. That was unverified and is now removed everywhere. Task 3 adds a concrete four-team Round 5 group where one team has faced all three others, making every matching contain a repeat, with `min_possible_repeats == 1`. Task 5 and Task 8 assert `repeat_count == min_possible_repeats` — optimality, not absence.
2. *No silent fallback.* `choose_pairing` raises `NoLegalPairingError` when cross-group is unsatisfiable, replacing the `or candidates` degradation.
3. *Duration is wired in.* `DurationResolver` is constructed per tournament in `run_swiss` and `run_elimination` and bound into every `rank_teams` call. A surviving five-criterion tie with no resolver raises `DurationUnavailableError` instead of skipping to the coin toss.
4. *`SeriesResult` is used.* `run_swiss` returns `SwissRun(states, groups, rounds)` where each `RoundLog` carries the ranking used, the pairings chosen, repeat counts, and per-series results.
5. *Equivariance replaces the vacuous test.* Column sums held by construction. Replaced with exact row-wise mapping through an explicit bijection, plus a slow test that permuting the strength vector permutes the marginals.
6. *One source of truth.* Capacities, category capacities, and the random baseline are derived by `derive_record_capacities` / `derive_category_capacities` from format parameters. The config contains no capacity keys — Task 1 asserts that, and Task 8 greps `src/` for the literal.
7. *RNG and selection tests fixed.* `test_shared_rng_stream_is_reproducible_and_actually_varies` uses one stream and asserts the sequence varies. Rational choice is verified via `EliminationMatch.opponent` and `available_when_choosing`, not a stochastic match result.
8. *Slow tests marked.* Marker registered in `pyproject.toml`; per-task commands use `-m "not slow"`; Task 8 runs the whole suite.

**Type consistency.** `Rules` is threaded through `run_swiss`, `run_elimination`, `category_marginals`, `solve_card`, and `cli`. `rank_teams(states, rng, duration_fn=None)` is identical in Tasks 2, 5, 6. `choose_pairing` returns `PairingChoice` in Tasks 3 and 5; callers use `.matching`, `.repeat_count`, `.min_possible_repeats`. `run_elimination` takes a `SwissRun` and returns `EliminationRun` in Tasks 6, 7. `solve_card(marginals, capacities, weights=None)` matches between Task 7 and Task 8.

**Deliberate scope exclusions**, tracked for the D2 plan: ingestion, roster canonicalization, ratings fitting, market shrinkage, backtesting, the `as_of` leakage assertion, TI 2025 replay, schedule-sensitivity, meta scouting.

**Round 5 distance is now tested exactly, not approximately.** `records_before_round` replays the log to recover pre-round records, so Task 5 can isolate the 1-3 group (loser eliminated → maximise) and the 3-1 group (loser survives → minimise) and compare the chosen matching's spread against every alternative from `perfect_matchings`. Both are exact optimality assertions.

**One honest uncertainty, stated not hidden.** The spec calls duration ties "rare". Task 5's early rounds likely contradict that: after Round 1, several 1-0 teams share identical records, 2-0 map scores, and zero-win opponents, tying through all five criteria. `DurationResolver.consultations` measures the real rate — if it is high, the spec's §XII framing needs correcting, and that is a finding to report rather than a bug to fix.
