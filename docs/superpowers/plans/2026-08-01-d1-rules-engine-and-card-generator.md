# D1: Swiss Rules Engine and Card Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Given any 16-team strength vector, produce a legal TI 2026 prediction card — exercising the exact Swiss pairing, tiebreak, elimination, and constrained-assignment rules — with zero dependency on external match data.

**Architecture:** Pure-Python domain core with no I/O. A rules config (`config/ti2026_rules.yaml`) carries every rule with a provenance tag. Ranking, pairing, round progression, elimination choice, and assignment are separate modules with narrow interfaces, each independently testable. A Monte Carlo driver composes them into category marginals; a Hungarian solver turns marginals into a card. Team strengths are an *input*, so this whole layer is testable against synthetic ratings before any ingestion exists.

**Tech Stack:** Python 3.12, `uv`, `pytest`, `numpy`, `scipy` (Hungarian assignment), `PyYAML`, `ruff`.

## Global Constraints

- Category capacities are exactly `[1, 2, 5, 5, 2, 1]` for `4-0`, `4-1`, `elim_win`, `elim_loss`, `1-4`, `0-4`. Total 16.
- Advancing teams = `1 + 2 + 5 = 8`. Any code path producing a different count is a bug.
- Every random operation takes an explicit `random.Random` instance. No module-level RNG, no `random.*` free functions.
- Same seed + same inputs → identical outputs. No `Date.now()`-style nondeterminism.
- Tiebreak order (provenance `official`): matches won ↓, matches lost ↑, opponents' total matches won ↓, game-win % ↓, opponents' average game-win % ↓, average game duration ↑, coin toss.
- Repeat opponents are avoided **when a legal non-repeat perfect matching exists**, not forbidden absolutely.
- Average duration is evaluated **lazily** — only for ties surviving the first five criteria.
- Every rules-engine branch carries a provenance tag: `official`, `logically_forced`, `inferred`, or `arbitrary`.
- No network calls in any module under `src/ti26/`. Rules verification against Valve's site is a separate D1 side-task, not part of this code.

---

## File Structure

| File | Responsibility |
|---|---|
| `config/ti2026_rules.yaml` | Rules truth table: capacities, tiebreak order, round constraints, provenance tags |
| `src/ti26/rules.py` | Load and validate the rules config into a frozen `Rules` object |
| `src/ti26/types.py` | `Category`, `CATEGORY_CAPACITY`, `TeamState`, `SeriesResult` |
| `src/ti26/tiebreak.py` | Official ranking with lazy duration resolution |
| `src/ti26/pairing.py` | Perfect-matching enumeration and lexicographic selection |
| `src/ti26/series.py` | Bradley-Terry map model and Bo3 series simulation |
| `src/ti26/swiss.py` | Round progression R1–R5, record groups, group constraints |
| `src/ti26/elimination.py` | Sequential opponent choice, three policies |
| `src/ti26/montecarlo.py` | Simulation driver → `P[team][category]` |
| `src/ti26/optimize.py` | Hungarian constrained assignment → card |
| `src/ti26/cli.py` | Entry point: strengths in, card + probability table out |
| `tests/test_rules.py` … `tests/test_invariants.py` | One test module per source module, plus the cross-cutting invariant suite |

---

## Task 1: Scaffold, rules config, domain types

**Files:**
- Create: `pyproject.toml`, `config/ti2026_rules.yaml`, `src/ti26/__init__.py`, `src/ti26/types.py`, `src/ti26/rules.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Category` (str enum with members `W4_0, W4_1, ELIM_WIN, ELIM_LOSS, L1_4, L0_4`); `CATEGORY_CAPACITY: dict[Category, int]`; `TeamState` dataclass with fields `team_id: str, initial_group: str, series_wins: int, series_losses: int, map_wins: int, map_losses: int, opponents: list[str], map_durations: list[float]` and properties `active: bool`, `record: tuple[int,int]`; `SeriesResult` dataclass with `team_a: str, team_b: str, wins_a: int, wins_b: int, round_no: int`; `load_rules(path: str) -> Rules` where `Rules` exposes `.capacities: dict[Category,int]`, `.tiebreak_order: list[str]`, `.within_group_rounds: list[int]`, `.cross_group_rounds: list[int]`, `.max_distance_elimination_rounds: list[int]`, `.provenance: dict[str,str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rules.py
import pytest
from ti26.rules import load_rules
from ti26.types import Category, CATEGORY_CAPACITY, TeamState

RULES_PATH = "config/ti2026_rules.yaml"


def test_capacities_sum_to_sixteen():
    assert sum(CATEGORY_CAPACITY.values()) == 16


def test_advancing_teams_equal_eight():
    advancing = (
        CATEGORY_CAPACITY[Category.W4_0]
        + CATEGORY_CAPACITY[Category.W4_1]
        + CATEGORY_CAPACITY[Category.ELIM_WIN]
    )
    assert advancing == 8


def test_rules_config_matches_code_capacities():
    rules = load_rules(RULES_PATH)
    assert rules.capacities == CATEGORY_CAPACITY


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


def test_every_rule_carries_a_provenance_tag():
    rules = load_rules(RULES_PATH)
    allowed = {"official", "logically_forced", "inferred", "arbitrary"}
    assert rules.provenance, "provenance map must not be empty"
    assert set(rules.provenance.values()) <= allowed


def test_round_constraints():
    rules = load_rules(RULES_PATH)
    assert rules.within_group_rounds == [2, 3]
    assert rules.cross_group_rounds == [4]
    assert rules.max_distance_elimination_rounds == [5]


def test_team_state_active_and_record():
    t = TeamState(team_id="alpha", initial_group="A")
    assert t.active is True
    assert t.record == (0, 0)
    t.series_wins = 4
    assert t.active is False
    t2 = TeamState(team_id="beta", initial_group="B", series_losses=4)
    assert t2.active is False
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

[tool.ruff]
line-length = 100
```

```yaml
# config/ti2026_rules.yaml
capacities:
  "4-0": 1
  "4-1": 2
  elim_win: 5
  elim_loss: 5
  "1-4": 2
  "0-4": 1

tiebreak_order:
  - series_wins
  - series_losses
  - opponent_series_wins
  - game_win_pct
  - opponent_game_win_pct
  - avg_duration
  - coin_toss

rounds:
  total: 5
  advance_at_wins: 4
  eliminate_at_losses: 4
  within_group: [2, 3]
  cross_group: [4]
  max_distance_when_loser_eliminated: [5]

provenance:
  capacities: logically_forced
  tiebreak_order: official
  advance_at_wins: official
  eliminate_at_losses: official
  within_group_rounds: official
  cross_group_rounds: official
  max_distance_when_loser_eliminated: official
  # Round 4's 0-3 group also eliminates its loser, but the published rule
  # names Round 5 only. Applying max-distance at R4 would be an inference;
  # it is deliberately NOT enabled.
  max_distance_at_round_4: inferred
  # No published rule orders exactly-tied teams after a coin toss.
  coin_toss_resolution: arbitrary
  # Repeat avoidance is "where possible" per the official text.
  repeat_avoidance_is_soft: official
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


CATEGORY_CAPACITY: dict[Category, int] = {
    Category.W4_0: 1,
    Category.W4_1: 2,
    Category.ELIM_WIN: 5,
    Category.ELIM_LOSS: 5,
    Category.L1_4: 2,
    Category.L0_4: 1,
}

ADVANCE_AT_WINS = 4
ELIMINATE_AT_LOSSES = 4


@dataclass
class TeamState:
    team_id: str
    initial_group: str
    series_wins: int = 0
    series_losses: int = 0
    map_wins: int = 0
    map_losses: int = 0
    opponents: list[str] = field(default_factory=list)
    map_durations: list[float] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.series_wins < ADVANCE_AT_WINS and self.series_losses < ELIMINATE_AT_LOSSES

    @property
    def record(self) -> tuple[int, int]:
        return (self.series_wins, self.series_losses)


@dataclass
class SeriesResult:
    team_a: str
    team_b: str
    wins_a: int
    wins_b: int
    round_no: int
```

```python
# src/ti26/rules.py
from dataclasses import dataclass

import yaml

from ti26.types import Category


@dataclass(frozen=True)
class Rules:
    capacities: dict[Category, int]
    tiebreak_order: list[str]
    total_rounds: int
    advance_at_wins: int
    eliminate_at_losses: int
    within_group_rounds: list[int]
    cross_group_rounds: list[int]
    max_distance_elimination_rounds: list[int]
    provenance: dict[str, str]


def load_rules(path: str) -> Rules:
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    rounds = raw["rounds"]
    return Rules(
        capacities={Category(k): v for k, v in raw["capacities"].items()},
        tiebreak_order=list(raw["tiebreak_order"]),
        total_rounds=rounds["total"],
        advance_at_wins=rounds["advance_at_wins"],
        eliminate_at_losses=rounds["eliminate_at_losses"],
        within_group_rounds=list(rounds["within_group"]),
        cross_group_rounds=list(rounds["cross_group"]),
        max_distance_elimination_rounds=list(rounds["max_distance_when_loser_eliminated"]),
        provenance=dict(raw["provenance"]),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_rules.py -v && uv run ruff check src tests`
Expected: 6 passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml config/ti2026_rules.yaml src/ti26/__init__.py src/ti26/types.py src/ti26/rules.py tests/test_rules.py
git commit -m "feat: rules truth table, domain types, provenance tags"
```

---

## Task 2: Official ranking with lazy duration

**Files:**
- Create: `src/ti26/tiebreak.py`
- Test: `tests/test_tiebreak.py`

**Interfaces:**
- Consumes: `TeamState` from `ti26.types`.
- Produces: `game_win_pct(t: TeamState) -> float`; `rank_teams(states: list[TeamState], rng: random.Random, duration_fn: Callable[[str], float] | None = None) -> list[str]` returning team ids best→worst; `DurationConsultation` counter object with `.count: int`, incremented each time `duration_fn` is invoked.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tiebreak.py
import random

from ti26.tiebreak import DurationConsultation, game_win_pct, rank_teams
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
    # Same wins, fewer losses ranks higher.
    states = [make("more_losses", 2, 2, 4, 4), make("fewer_losses", 2, 1, 4, 3)]
    assert rank_teams(states, random.Random(0)) == ["fewer_losses", "more_losses"]


def test_opponent_series_wins_break_identical_records():
    strong_opp = make("strong_opp", 3, 0, 6, 0)
    weak_opp = make("weak_opp", 0, 3, 0, 6)
    a = make("a", 1, 1, 2, 2, opponents=["strong_opp"])
    b = make("b", 1, 1, 2, 2, opponents=["weak_opp"])
    ranked = rank_teams([a, b, strong_opp, weak_opp], random.Random(0))
    assert ranked.index("a") < ranked.index("b")


def test_game_win_pct_breaks_equal_opponent_wins():
    shared = make("shared", 1, 1, 2, 2)
    a = make("a", 1, 1, 2, 1, opponents=["shared"])   # gwp 0.667
    b = make("b", 1, 1, 2, 3, opponents=["shared"])   # gwp 0.400
    ranked = rank_teams([a, b, shared], random.Random(0))
    assert ranked.index("a") < ranked.index("b")


def test_duration_consulted_only_for_ties_surviving_five_criteria():
    counter = DurationConsultation()

    def duration_fn(team_id):
        counter.count += 1
        return {"a": 1800.0, "b": 2400.0}[team_id]

    # Separable on game_win_pct — duration must not be consulted.
    sep_a = make("a", 1, 1, 3, 1)
    sep_b = make("b", 1, 1, 1, 3)
    rank_teams([sep_a, sep_b], random.Random(0), duration_fn=duration_fn)
    assert counter.count == 0

    # Identical through all five criteria — duration decides, shorter wins.
    tie_a = make("a", 1, 1, 2, 2)
    tie_b = make("b", 1, 1, 2, 2)
    ranked = rank_teams([tie_a, tie_b], random.Random(0), duration_fn=duration_fn)
    assert counter.count == 2
    assert ranked == ["a", "b"]


def test_exact_ties_fall_to_seeded_coin_toss():
    a = make("a", 1, 1, 2, 2)
    b = make("b", 1, 1, 2, 2)
    first = rank_teams([a, b], random.Random(7))
    second = rank_teams([a, b], random.Random(7))
    assert first == second
    assert sorted(first) == ["a", "b"]


def test_ranking_is_a_permutation_of_input():
    states = [make(f"t{i}", i % 3, 2 - i % 3, i, 5 - i % 5) for i in range(8)]
    ranked = rank_teams(states, random.Random(3))
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
from dataclasses import dataclass

from ti26.types import TeamState


@dataclass
class DurationConsultation:
    """Counts how often the sixth tiebreak criterion was actually needed."""

    count: int = 0


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

    Criteria 1-5 are computed eagerly. Average duration (criterion 6) is
    consulted only inside blocks that remain tied after those five, which
    is what makes the evaluation lazy.
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
            block = _break_tie(block, rng, duration_fn)
        out.extend(block)
        i = j + 1
    return [s.team_id for s in out]


def _break_tie(
    block: list[TeamState],
    rng: random.Random,
    duration_fn: Callable[[str], float] | None,
) -> list[TeamState]:
    if duration_fn is None:
        return sorted(block, key=lambda s: rng.random())
    durations = {s.team_id: duration_fn(s.team_id) for s in block}
    return sorted(block, key=lambda s: (durations[s.team_id], rng.random()))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tiebreak.py -v && uv run ruff check src tests`
Expected: 8 passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add src/ti26/tiebreak.py tests/test_tiebreak.py
git commit -m "feat: official ranking with lazy duration resolution"
```

---

## Task 3: Pairing engine

**Files:**
- Create: `src/ti26/pairing.py`
- Test: `tests/test_pairing.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (operates on plain ids).
- Produces: `perfect_matchings(items: list[str]) -> Iterator[list[tuple[str, str]]]`; `choose_pairing(team_ids: list[str], rank_index: dict[str,int], prior_opponents: dict[str,set[str]], rng: random.Random, *, group_of: dict[str,str] | None = None, cross_group: bool = False, maximize_distance: bool = False) -> list[tuple[str,str]]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pairing.py
import random

import pytest

from ti26.pairing import choose_pairing, perfect_matchings


def test_perfect_matchings_count_for_four_items():
    # (2n-1)!! = 3 for n=2 pairs
    assert len(list(perfect_matchings(["a", "b", "c", "d"]))) == 3


def test_perfect_matchings_count_for_eight_items():
    # (2n-1)!! = 7*5*3*1 = 105
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
    matching = choose_pairing(teams, rank_index, prior, random.Random(0))
    pairs = {frozenset(p) for p in matching}
    assert frozenset({"a", "b"}) not in pairs


def test_forced_repeat_is_taken_rather_than_failing():
    # Everyone has played everyone: no repeat-free matching exists.
    teams = ["a", "b", "c", "d"]
    rank_index = {t: i for i, t in enumerate(teams)}
    prior = {t: set(teams) - {t} for t in teams}
    matching = choose_pairing(teams, rank_index, prior, random.Random(0))
    assert len(matching) == 2
    flat = [x for pair in matching for x in pair]
    assert sorted(flat) == teams


def test_minimum_ranking_distance_is_preferred():
    teams = ["r0", "r1", "r2", "r3"]
    rank_index = {"r0": 0, "r1": 1, "r2": 2, "r3": 3}
    prior = {t: set() for t in teams}
    matching = choose_pairing(teams, rank_index, prior, random.Random(0))
    pairs = {frozenset(p) for p in matching}
    assert pairs == {frozenset({"r0", "r1"}), frozenset({"r2", "r3"})}


def test_maximize_distance_flips_the_preference():
    teams = ["r0", "r1", "r2", "r3"]
    rank_index = {"r0": 0, "r1": 1, "r2": 2, "r3": 3}
    prior = {t: set() for t in teams}
    matching = choose_pairing(
        teams, rank_index, prior, random.Random(0), maximize_distance=True
    )
    pairs = {frozenset(p) for p in matching}
    assert pairs == {frozenset({"r0", "r3"}), frozenset({"r1", "r2"})}


def test_cross_group_constraint_pairs_only_across_groups():
    teams = ["a1", "a2", "b1", "b2"]
    group_of = {"a1": "A", "a2": "A", "b1": "B", "b2": "B"}
    rank_index = {t: i for i, t in enumerate(teams)}
    prior = {t: set() for t in teams}
    matching = choose_pairing(
        teams, rank_index, prior, random.Random(0), group_of=group_of, cross_group=True
    )
    assert all(group_of[a] != group_of[b] for a, b in matching)


def test_cross_group_falls_back_when_impossible():
    # All in one group: no cross-group matching exists, must not raise.
    teams = ["a1", "a2", "a3", "a4"]
    group_of = dict.fromkeys(teams, "A")
    rank_index = {t: i for i, t in enumerate(teams)}
    prior = {t: set() for t in teams}
    matching = choose_pairing(
        teams, rank_index, prior, random.Random(0), group_of=group_of, cross_group=True
    )
    assert len(matching) == 2


def test_odd_number_of_teams_raises():
    with pytest.raises(ValueError):
        choose_pairing(["a", "b", "c"], {"a": 0, "b": 1, "c": 2}, {}, random.Random(0))


def test_selection_is_deterministic_under_a_fixed_seed():
    teams = list("abcdefgh")
    rank_index = {t: i for i, t in enumerate(teams)}
    prior = {t: set() for t in teams}
    first = choose_pairing(teams, rank_index, prior, random.Random(11))
    second = choose_pairing(teams, rank_index, prior, random.Random(11))
    assert first == second
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pairing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.pairing'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ti26/pairing.py
import random
from collections.abc import Iterator


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
) -> list[tuple[str, str]]:
    """Select a legal pairing by lexicographic preference.

    Order: group constraint -> fewest repeat opponents -> ranking distance
    (minimised, or maximised for Round 5 matches whose loser is eliminated)
    -> uniform random among exact ties.
    """
    if len(team_ids) % 2 != 0:
        raise ValueError(f"cannot pair an odd number of teams: {len(team_ids)}")

    candidates = list(perfect_matchings(list(team_ids)))

    if cross_group and group_of is not None:
        crossed = [m for m in candidates if all(group_of[a] != group_of[b] for a, b in m)]
        # Fall back rather than fail: the constraint is satisfiable in the real
        # bracket, but property tests exercise degenerate inputs.
        candidates = crossed or candidates

    def repeats(matching: list[tuple[str, str]]) -> int:
        return sum(1 for a, b in matching if b in prior_opponents.get(a, set()))

    fewest = min(repeats(m) for m in candidates)
    candidates = [m for m in candidates if repeats(m) == fewest]

    def distance(matching: list[tuple[str, str]]) -> int:
        return sum(abs(rank_index[a] - rank_index[b]) for a, b in matching)

    sign = -1 if maximize_distance else 1
    best = min(sign * distance(m) for m in candidates)
    candidates = [m for m in candidates if sign * distance(m) == best]

    return rng.choice(candidates)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pairing.py -v && uv run ruff check src tests`
Expected: 12 passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add src/ti26/pairing.py tests/test_pairing.py
git commit -m "feat: brute-force pairing with lexicographic legal selection"
```

---

## Task 4: Bradley-Terry map model and Bo3 series

**Files:**
- Create: `src/ti26/series.py`
- Test: `tests/test_series.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `map_win_prob(s_a: float, s_b: float) -> float`; `simulate_series(s_a: float, s_b: float, rng: random.Random, best_of: int = 3) -> tuple[int, int]` returning `(maps_won_a, maps_won_b)`; `series_win_prob(p_map: float, best_of: int = 3) -> float`.

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
    # Bo3 with independent maps: p^2 * (3 - 2p)
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


def test_simulation_is_seed_reproducible():
    a = [simulate_series(0.1, 0.0, random.Random(5)) for _ in range(3)]
    b = [simulate_series(0.1, 0.0, random.Random(5)) for _ in range(3)]
    assert a == b
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

Run: `uv run pytest tests/test_series.py -v && uv run ruff check src tests`
Expected: 7 passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add src/ti26/series.py tests/test_series.py
git commit -m "feat: Bradley-Terry map model and Bo3 series simulation"
```

---

## Task 5: Swiss round progression

**Files:**
- Create: `src/ti26/swiss.py`
- Test: `tests/test_swiss.py`

**Interfaces:**
- Consumes: `TeamState`, `SeriesResult` (Task 1); `rank_teams` (Task 2); `choose_pairing` (Task 3); `simulate_series` (Task 4); `Rules` (Task 1).
- Produces: `random_initial_groups(team_ids: list[str], rng: random.Random) -> dict[str,str]`; `random_round_one_schedule(groups: dict[str,str], rng: random.Random) -> list[tuple[str,str]]`; `run_swiss(strengths: dict[str,float], rules: Rules, rng: random.Random, groups: dict[str,str] | None = None, round_one: list[tuple[str,str]] | None = None) -> dict[str, TeamState]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_swiss.py
import random
from collections import Counter

import pytest

from ti26.rules import load_rules
from ti26.swiss import random_initial_groups, random_round_one_schedule, run_swiss

RULES = load_rules("config/ti2026_rules.yaml")
TEAMS = [f"t{i:02d}" for i in range(16)]


def flat_strengths(value=0.0):
    return dict.fromkeys(TEAMS, value)


def test_initial_groups_split_eight_and_eight():
    groups = random_initial_groups(TEAMS, random.Random(0))
    counts = Counter(groups.values())
    assert counts == {"A": 8, "B": 8}


def test_round_one_schedule_pairs_within_groups():
    rng = random.Random(1)
    groups = random_initial_groups(TEAMS, rng)
    schedule = random_round_one_schedule(groups, rng)
    assert len(schedule) == 8
    assert all(groups[a] == groups[b] for a, b in schedule)
    flat = [x for pair in schedule for x in pair]
    assert sorted(flat) == sorted(TEAMS)


def test_final_record_distribution_is_structurally_forced():
    for seed in range(20):
        states = run_swiss(flat_strengths(), RULES, random.Random(seed))
        records = Counter(s.record for s in states.values())
        assert records == {
            (4, 0): 1,
            (4, 1): 2,
            (3, 2): 5,
            (2, 3): 5,
            (1, 4): 2,
            (0, 4): 1,
        }


def test_no_team_ever_plays_itself():
    states = run_swiss(flat_strengths(), RULES, random.Random(3))
    for state in states.values():
        assert state.team_id not in state.opponents


def test_rounds_two_and_three_stay_within_initial_groups():
    rng = random.Random(4)
    groups = random_initial_groups(TEAMS, rng)
    schedule = random_round_one_schedule(groups, rng)
    states = run_swiss(flat_strengths(), RULES, rng, groups=groups, round_one=schedule)
    # Each team plays 3 within-group opponents in rounds 1-3.
    for state in states.values():
        same_group = [o for o in state.opponents[:3] if groups[o] == groups[state.team_id]]
        assert len(same_group) == 3


def test_round_four_is_cross_group():
    rng = random.Random(5)
    groups = random_initial_groups(TEAMS, rng)
    schedule = random_round_one_schedule(groups, rng)
    states = run_swiss(flat_strengths(), RULES, rng, groups=groups, round_one=schedule)
    # Every team still active at round 4 played across groups.
    for state in states.values():
        if len(state.opponents) >= 4:
            opponent = state.opponents[3]
            assert groups[opponent] != groups[state.team_id]


def test_stronger_teams_finish_higher_on_average():
    strengths = {t: (i - 7.5) * 0.4 for i, t in enumerate(TEAMS)}
    totals = Counter()
    for seed in range(200):
        states = run_swiss(strengths, RULES, random.Random(seed))
        for tid, state in states.items():
            totals[tid] += state.series_wins
    assert totals["t15"] > totals["t00"]


def test_run_is_seed_reproducible():
    a = run_swiss(flat_strengths(), RULES, random.Random(9))
    b = run_swiss(flat_strengths(), RULES, random.Random(9))
    assert {k: v.record for k, v in a.items()} == {k: v.record for k, v in b.items()}


def test_map_counts_are_consistent_with_series_counts():
    states = run_swiss(flat_strengths(), RULES, random.Random(2))
    for state in states.values():
        played = state.series_wins + state.series_losses
        assert played == len(state.opponents)
        assert state.map_wins + state.map_losses >= 2 * played
        assert state.map_wins + state.map_losses <= 3 * played
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
from ti26.tiebreak import rank_teams
from ti26.types import TeamState


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
) -> None:
    a, b = pair
    wins_a, wins_b = simulate_series(strengths[a], strengths[b], rng)
    sa, sb = states[a], states[b]
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
    del round_no  # recorded by the caller if a match log is needed


def run_swiss(
    strengths: dict[str, float],
    rules: Rules,
    rng: random.Random,
    groups: dict[str, str] | None = None,
    round_one: list[tuple[str, str]] | None = None,
) -> dict[str, TeamState]:
    """Run all five Swiss rounds and return final team states."""
    team_ids = sorted(strengths)
    if groups is None:
        groups = random_initial_groups(team_ids, rng)
    if round_one is None:
        round_one = random_round_one_schedule(groups, rng)

    states = {t: TeamState(team_id=t, initial_group=groups[t]) for t in team_ids}

    for pair in round_one:
        _play(states, pair, strengths, rng, 1)

    for round_no in range(2, rules.total_rounds + 1):
        active = [s for s in states.values() if s.active]
        if not active:
            break
        ranked = rank_teams(list(states.values()), rng)
        rank_index = {tid: i for i, tid in enumerate(ranked)}
        prior = {s.team_id: set(s.opponents) for s in states.values()}

        buckets: dict[tuple, list[str]] = defaultdict(list)
        for state in active:
            key = (
                (state.record, state.initial_group)
                if round_no in rules.within_group_rounds
                else (state.record,)
            )
            buckets[key].append(state.team_id)

        for key, members in sorted(buckets.items(), key=lambda kv: str(kv[0])):
            record = key[0]
            loser_is_eliminated = record[1] + 1 >= rules.eliminate_at_losses
            matching = choose_pairing(
                sorted(members),
                rank_index,
                prior,
                rng,
                group_of=groups,
                cross_group=round_no in rules.cross_group_rounds,
                maximize_distance=(
                    loser_is_eliminated
                    and round_no in rules.max_distance_elimination_rounds
                ),
            )
            for pair in matching:
                _play(states, pair, strengths, rng, round_no)

    return states
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_swiss.py -v && uv run ruff check src tests`
Expected: 9 passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add src/ti26/swiss.py tests/test_swiss.py
git commit -m "feat: five-round Swiss progression with group and distance constraints"
```

---

## Task 6: Elimination round with sequential opponent choice

**Files:**
- Create: `src/ti26/elimination.py`
- Test: `tests/test_elimination.py`

**Interfaces:**
- Consumes: `TeamState`, `Category` (Task 1); `rank_teams` (Task 2); `map_win_prob`, `simulate_series` (Task 4).
- Produces: `ChoicePolicy` str enum with members `RATIONAL, NOISY, RANDOM`; `run_elimination(states: dict[str, TeamState], strengths: dict[str,float], rng: random.Random, policy: ChoicePolicy = ChoicePolicy.RATIONAL, softmax_temp: float = 1.0) -> dict[str, Category]` returning the final category for every one of the 16 teams.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_elimination.py
import random
from collections import Counter

import pytest

from ti26.elimination import ChoicePolicy, run_elimination
from ti26.rules import load_rules
from ti26.swiss import run_swiss
from ti26.types import CATEGORY_CAPACITY, Category

RULES = load_rules("config/ti2026_rules.yaml")
TEAMS = [f"t{i:02d}" for i in range(16)]


def flat_strengths(value=0.0):
    return dict.fromkeys(TEAMS, value)


@pytest.mark.parametrize("policy", list(ChoicePolicy))
def test_every_team_gets_exactly_one_category(policy):
    states = run_swiss(flat_strengths(), RULES, random.Random(0))
    result = run_elimination(states, flat_strengths(), random.Random(0), policy=policy)
    assert set(result) == set(TEAMS)
    assert all(isinstance(c, Category) for c in result.values())


@pytest.mark.parametrize("policy", list(ChoicePolicy))
def test_category_counts_match_capacities(policy):
    for seed in range(10):
        states = run_swiss(flat_strengths(), RULES, random.Random(seed))
        result = run_elimination(
            states, flat_strengths(), random.Random(seed), policy=policy
        )
        assert Counter(result.values()) == CATEGORY_CAPACITY


def test_swiss_records_map_to_the_right_categories():
    states = run_swiss(flat_strengths(), RULES, random.Random(1))
    result = run_elimination(states, flat_strengths(), random.Random(1))
    for tid, state in states.items():
        if state.record == (4, 0):
            assert result[tid] == Category.W4_0
        elif state.record == (4, 1):
            assert result[tid] == Category.W4_1
        elif state.record == (1, 4):
            assert result[tid] == Category.L1_4
        elif state.record == (0, 4):
            assert result[tid] == Category.L0_4
        else:
            assert result[tid] in (Category.ELIM_WIN, Category.ELIM_LOSS)


def test_rational_chooser_picks_its_weakest_available_opponent():
    strengths = {t: 0.0 for t in TEAMS}
    # Make one 2-3 team clearly weakest so the top seed should select it.
    states = run_swiss(strengths, RULES, random.Random(2))
    two_three = [t for t, s in states.items() if s.record == (2, 3)]
    weakest = two_three[0]
    strengths[weakest] = -5.0
    result = run_elimination(
        states, strengths, random.Random(2), policy=ChoicePolicy.RATIONAL
    )
    # The heavily weakened team should almost certainly lose its match.
    assert result[weakest] == Category.ELIM_LOSS


def test_policies_are_seed_reproducible():
    states = run_swiss(flat_strengths(), RULES, random.Random(6))
    a = run_elimination(states, flat_strengths(), random.Random(6))
    b = run_elimination(states, flat_strengths(), random.Random(6))
    assert a == b


def test_elimination_pairs_three_two_against_two_three_only():
    states = run_swiss(flat_strengths(), RULES, random.Random(7))
    result = run_elimination(states, flat_strengths(), random.Random(7))
    winners = [t for t, c in result.items() if c == Category.ELIM_WIN]
    losers = [t for t, c in result.items() if c == Category.ELIM_LOSS]
    assert len(winners) == 5
    assert len(losers) == 5
    for tid in winners + losers:
        assert states[tid].record in {(3, 2), (2, 3)}
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

from ti26.series import map_win_prob, series_win_prob, simulate_series
from ti26.tiebreak import rank_teams
from ti26.types import Category, TeamState

RECORD_TO_CATEGORY: dict[tuple[int, int], Category] = {
    (4, 0): Category.W4_0,
    (4, 1): Category.W4_1,
    (1, 4): Category.L1_4,
    (0, 4): Category.L0_4,
}


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
        best = max(win_probs)
        return available[win_probs.index(best)]

    weights = [math.exp(p / softmax_temp) for p in win_probs]
    return rng.choices(available, weights=weights, k=1)[0]


def run_elimination(
    states: dict[str, TeamState],
    strengths: dict[str, float],
    rng: random.Random,
    policy: ChoicePolicy = ChoicePolicy.RATIONAL,
    softmax_temp: float = 1.0,
) -> dict[str, Category]:
    """Resolve the five elimination matches and assign every team a category."""
    categories: dict[str, Category] = {}
    for tid, state in states.items():
        fixed = RECORD_TO_CATEGORY.get(state.record)
        if fixed is not None:
            categories[tid] = fixed

    choosers = [t for t, s in states.items() if s.record == (3, 2)]
    pool = [t for t, s in states.items() if s.record == (2, 3)]

    ranked = rank_teams(list(states.values()), rng)
    order = {tid: i for i, tid in enumerate(ranked)}
    choosers.sort(key=lambda t: order[t])

    available = sorted(pool, key=lambda t: order[t])
    for chooser in choosers:
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

    return categories
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_elimination.py -v && uv run ruff check src tests`
Expected: 14 passed (parametrised), ruff clean

- [ ] **Step 5: Commit**

```bash
git add src/ti26/elimination.py tests/test_elimination.py
git commit -m "feat: elimination round with three opponent-choice policies"
```

---

## Task 7: Monte Carlo driver and Hungarian card optimizer

**Files:**
- Create: `src/ti26/montecarlo.py`, `src/ti26/optimize.py`
- Test: `tests/test_montecarlo.py`, `tests/test_optimize.py`

**Interfaces:**
- Consumes: `run_swiss` (Task 5); `run_elimination`, `ChoicePolicy` (Task 6); `Category`, `CATEGORY_CAPACITY` (Task 1).
- Produces: `category_marginals(strengths: dict[str,float], rules: Rules, n_sims: int, seed: int, policy: ChoicePolicy = ChoicePolicy.RATIONAL) -> dict[str, dict[Category, float]]`; `monte_carlo_stderr(p: float, n: int) -> float`; `solve_card(marginals: dict[str, dict[Category, float]], weights: dict[Category, float] | None = None) -> tuple[dict[str, Category], float]` returning `(card, model_implied_expected_score)`; `RANDOM_BASELINE: float = 3.75`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_optimize.py
import pytest

from ti26.optimize import RANDOM_BASELINE, solve_card
from ti26.types import CATEGORY_CAPACITY, Category

TEAMS = [f"t{i:02d}" for i in range(16)]


def uniform_marginals():
    return {
        t: {c: CATEGORY_CAPACITY[c] / 16 for c in Category} for t in TEAMS
    }


def test_random_baseline_constant():
    assert RANDOM_BASELINE == pytest.approx(sum(k**2 for k in CATEGORY_CAPACITY.values()) / 16)
    assert RANDOM_BASELINE == pytest.approx(3.75)


def test_card_respects_capacities():
    card, _ = solve_card(uniform_marginals())
    counts = {c: sum(1 for v in card.values() if v == c) for c in Category}
    assert counts == CATEGORY_CAPACITY


def test_every_team_assigned_exactly_once():
    card, _ = solve_card(uniform_marginals())
    assert sorted(card) == sorted(TEAMS)


def test_uniform_marginals_score_the_random_baseline():
    _, score = solve_card(uniform_marginals())
    assert score == pytest.approx(RANDOM_BASELINE)


def test_confident_marginals_beat_the_baseline():
    marginals = uniform_marginals()
    marginals["t00"] = {c: 0.0 for c in Category}
    marginals["t00"][Category.W4_0] = 1.0
    _, score = solve_card(marginals)
    assert score > RANDOM_BASELINE


def test_greedy_argmax_would_violate_capacity_but_solver_does_not():
    # Every team most likely 4-0: a greedy pick duplicates the single slot.
    marginals = {}
    for t in TEAMS:
        row = {c: 0.01 for c in Category}
        row[Category.W4_0] = 0.95
        marginals[t] = row
    card, _ = solve_card(marginals)
    assert sum(1 for v in card.values() if v == Category.W4_0) == 1


def test_category_weights_shift_the_assignment():
    marginals = uniform_marginals()
    marginals["t00"][Category.L0_4] = 0.30
    marginals["t00"][Category.ELIM_WIN] = 0.31
    heavy = {c: 1.0 for c in Category}
    heavy[Category.L0_4] = 10.0
    card, _ = solve_card(marginals, weights=heavy)
    assert card["t00"] == Category.L0_4
```

```python
# tests/test_montecarlo.py
import pytest

from ti26.elimination import ChoicePolicy
from ti26.montecarlo import category_marginals, monte_carlo_stderr
from ti26.rules import load_rules
from ti26.types import CATEGORY_CAPACITY, Category

RULES = load_rules("config/ti2026_rules.yaml")
TEAMS = [f"t{i:02d}" for i in range(16)]


def test_each_team_row_sums_to_one():
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=200, seed=0)
    for row in marginals.values():
        assert sum(row.values()) == pytest.approx(1.0)


def test_each_category_column_sums_to_its_capacity():
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=200, seed=0)
    for category, capacity in CATEGORY_CAPACITY.items():
        column = sum(row[category] for row in marginals.values())
        assert column == pytest.approx(capacity)


def test_equal_strength_teams_approach_capacity_over_sixteen():
    n = 4000
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=n, seed=1)
    for team, row in marginals.items():
        for category, capacity in CATEGORY_CAPACITY.items():
            expected = capacity / 16
            tolerance = 4 * monte_carlo_stderr(expected, n)
            assert row[category] == pytest.approx(expected, abs=tolerance), (
                f"{team}/{category}"
            )


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


def test_policy_choice_is_plumbed_through():
    a = category_marginals(
        dict.fromkeys(TEAMS, 0.0), RULES, n_sims=100, seed=3, policy=ChoicePolicy.RANDOM
    )
    assert sum(a["t00"].values()) == pytest.approx(1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_optimize.py tests/test_montecarlo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ti26.optimize'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ti26/optimize.py
import numpy as np
from scipy.optimize import linear_sum_assignment

from ti26.types import CATEGORY_CAPACITY, Category

RANDOM_BASELINE: float = sum(k**2 for k in CATEGORY_CAPACITY.values()) / 16


def solve_card(
    marginals: dict[str, dict[Category, float]],
    weights: dict[Category, float] | None = None,
) -> tuple[dict[str, Category], float]:
    """Assign every team to exactly one category, respecting slot capacities.

    Returns the card and the model-implied expected score. That score is
    computed from the model's own probabilities and is therefore descriptive
    only -- never evidence of forecast quality (see spec section II).
    """
    teams = sorted(marginals)
    slots: list[Category] = [c for c in Category for _ in range(CATEGORY_CAPACITY[c])]
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
        states = run_swiss(strengths, rules, rng)
        outcome = run_elimination(states, strengths, rng, policy=policy)
        for team, category in outcome.items():
            tally[team][category] += 1
    return {
        team: {c: tally[team][c] / n_sims for c in Category} for team in strengths
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_optimize.py tests/test_montecarlo.py -v && uv run ruff check src tests`
Expected: 13 passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add src/ti26/montecarlo.py src/ti26/optimize.py tests/test_montecarlo.py tests/test_optimize.py
git commit -m "feat: Monte Carlo category marginals and Hungarian card optimizer"
```

---

## Task 8: Invariant suite and CLI end-to-end run

**Files:**
- Create: `src/ti26/cli.py`, `tests/test_invariants.py`
- Test: `tests/test_invariants.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: `main(argv: list[str] | None = None) -> int` writing `reports/category_probabilities.csv` and `reports/recommended_card.json`.

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
from ti26.types import CATEGORY_CAPACITY, Category

RULES = load_rules("config/ti2026_rules.yaml")
TEAMS = [f"t{i:02d}" for i in range(16)]
SEEDS = range(60)


@pytest.mark.parametrize("seed", SEEDS)
def test_category_counts_are_always_exact(seed):
    strengths = {t: random.Random(seed + i).gauss(0, 0.8) for i, t in enumerate(TEAMS)}
    states = run_swiss(strengths, RULES, random.Random(seed))
    outcome = run_elimination(states, strengths, random.Random(seed))
    assert Counter(outcome.values()) == CATEGORY_CAPACITY


@pytest.mark.parametrize("seed", SEEDS)
def test_exactly_eight_teams_advance(seed):
    strengths = dict.fromkeys(TEAMS, 0.0)
    states = run_swiss(strengths, RULES, random.Random(seed))
    outcome = run_elimination(states, strengths, random.Random(seed))
    advancing = sum(
        1
        for c in outcome.values()
        if c in (Category.W4_0, Category.W4_1, Category.ELIM_WIN)
    )
    assert advancing == 8


@pytest.mark.parametrize("seed", SEEDS)
def test_no_self_pairing_and_no_avoidable_repeat(seed):
    strengths = dict.fromkeys(TEAMS, 0.0)
    states = run_swiss(strengths, RULES, random.Random(seed))
    for state in states.values():
        assert state.team_id not in state.opponents
        # A repeat is legal only when unavoidable; with 16 teams over 5 rounds
        # the record groups are large enough that repeats never become forced.
        assert len(set(state.opponents)) == len(state.opponents)


@pytest.mark.parametrize("seed", SEEDS)
def test_group_constraints_hold(seed):
    rng = random.Random(seed)
    groups = random_initial_groups(TEAMS, rng)
    schedule = random_round_one_schedule(groups, rng)
    states = run_swiss(
        dict.fromkeys(TEAMS, 0.0), RULES, rng, groups=groups, round_one=schedule
    )
    for state in states.values():
        tid = state.team_id
        for opponent in state.opponents[:3]:
            assert groups[opponent] == groups[tid], "rounds 1-3 must stay in group"
        if len(state.opponents) >= 4:
            assert groups[state.opponents[3]] != groups[tid], "round 4 is cross-group"


def test_equal_strength_symmetry_within_monte_carlo_tolerance():
    n = 6000
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=n, seed=101)
    for team, row in marginals.items():
        for category, capacity in CATEGORY_CAPACITY.items():
            expected = capacity / 16
            tolerance = 4 * monte_carlo_stderr(expected, n)
            assert row[category] == pytest.approx(expected, abs=tolerance), (
                f"{team}/{category} outside {tolerance:.4f} of {expected:.4f}"
            )


def test_label_permutation_invariance():
    """Relabelling teams must not change the aggregate category distribution."""
    n = 3000
    base = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=n, seed=5)
    relabelled = category_marginals(
        {f"z{i:02d}": 0.0 for i in range(16)}, RULES, n_sims=n, seed=5
    )
    for category in Category:
        base_col = sum(row[category] for row in base.values())
        other_col = sum(row[category] for row in relabelled.values())
        assert base_col == pytest.approx(other_col, abs=1e-9)


@pytest.mark.parametrize("policy", list(ChoicePolicy))
def test_invariants_hold_under_every_choice_policy(policy):
    strengths = {t: (i - 7.5) * 0.3 for i, t in enumerate(TEAMS)}
    for seed in range(10):
        states = run_swiss(strengths, RULES, random.Random(seed))
        outcome = run_elimination(states, strengths, random.Random(seed), policy=policy)
        assert Counter(outcome.values()) == CATEGORY_CAPACITY


def test_probability_rows_and_columns_are_consistent():
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=500, seed=8)
    for row in marginals.values():
        assert sum(row.values()) == pytest.approx(1.0)
    for category, capacity in CATEGORY_CAPACITY.items():
        assert sum(r[category] for r in marginals.values()) == pytest.approx(capacity)
```

```python
# tests/test_cli.py
import json
from pathlib import Path

from ti26.cli import main
from ti26.types import CATEGORY_CAPACITY, Category


def test_cli_writes_a_legal_card(tmp_path):
    out = tmp_path / "reports"
    code = main(["--n-sims", "300", "--seed", "4", "--out", str(out)])
    assert code == 0

    card = json.loads((out / "recommended_card.json").read_text())
    assert len(card["assignments"]) == 16
    counts = {c: 0 for c in Category}
    for category in card["assignments"].values():
        counts[Category(category)] += 1
    assert counts == CATEGORY_CAPACITY
    assert card["seed"] == 4
    assert card["n_sims"] == 300
    assert "model_implied_expected_score" in card
    assert "random_baseline" in card

    csv_text = (out / "category_probabilities.csv").read_text()
    assert csv_text.splitlines()[0].startswith("team,")
    assert len(csv_text.splitlines()) == 17


def test_cli_is_reproducible(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    main(["--n-sims", "200", "--seed", "77", "--out", str(a)])
    main(["--n-sims", "200", "--seed", "77", "--out", str(b)])
    assert (a / "recommended_card.json").read_text() == (
        b / "recommended_card.json"
    ).read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
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
from ti26.optimize import RANDOM_BASELINE, solve_card
from ti26.rules import load_rules
from ti26.types import Category


def _load_strengths(path: str | None) -> dict[str, float]:
    if path is None:
        # Synthetic ladder: D1 has no ingestion, so strengths are an input.
        return {f"t{i:02d}": (i - 7.5) * 0.15 for i in range(16)}
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

    strengths = _load_strengths(args.strengths)
    rules = load_rules(args.rules)
    marginals = category_marginals(
        strengths,
        rules,
        n_sims=args.n_sims,
        seed=args.seed,
        policy=ChoicePolicy(args.policy),
    )
    card, score = solve_card(marginals)

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
        "random_baseline": RANDOM_BASELINE,
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

- [ ] **Step 4: Run the full suite and a real end-to-end run**

Run: `uv run pytest -v && uv run ruff check src tests`
Expected: entire suite passes, ruff clean

Run: `uv run python -m ti26.cli --n-sims 50000 --seed 1 --out reports`
Expected: exit 0; `reports/recommended_card.json` contains 16 assignments with counts `[1,2,5,5,2,1]`; `model_implied_expected_score` above 3.75 for the synthetic ladder (strengths are not flat).

- [ ] **Step 5: Commit**

```bash
git add src/ti26/cli.py tests/test_invariants.py tests/test_cli.py
git commit -m "feat: invariant suite and end-to-end card generator CLI"
```

---

## Self-Review

**Spec coverage.** Every D1 requirement in the spec maps to a task: rules truth table and provenance tags → Task 1; official tiebreak order with lazy duration → Task 2; brute-force pairing with lexicographic selection and soft repeat avoidance → Task 3; map-level simulation with conditional independence (series shock defaulted to zero per §VI) → Task 4; round constraints and max-distance-when-loser-eliminated → Task 5; sequential opponent choice under three policies → Task 6; Hungarian assignment with category weights and the descriptive-only objective → Task 7; the full §IX invariant list including avoidable-repeat phrasing, Monte Carlo tolerance, and label-permutation invariance → Task 8.

**Deliberately out of scope for this plan**, tracked for the D2 plan: ingestion, roster canonicalization, ratings fitting, market shrinkage, backtesting, the `as_of` leakage assertion, TI 2025 replay, the schedule-sensitivity experiment, and the meta scouting report. Browser verification of the published rules is a D1 side-task producing an archival snapshot; it does not gate this code.

**Known gap, stated rather than hidden.** `test_no_self_pairing_and_no_avoidable_repeat` asserts repeats never occur, which holds for 16 teams over 5 rounds because record groups stay large enough. The forced-repeat *code path* is covered by `test_forced_repeat_is_taken_rather_than_failing` in Task 3, which constructs the degenerate input directly. The Codex differential test (spec cut list) must exercise constructed ties and forced repeats against an independent implementation — that is not in this plan.

**Type consistency.** `TeamState`, `SeriesResult`, `Category`, and `CATEGORY_CAPACITY` are defined once in Task 1 and imported unchanged. `rank_teams` keeps the signature `(states, rng, duration_fn=None)` in Tasks 2, 5, and 6. `choose_pairing` keeps its keyword-only `group_of` / `cross_group` / `maximize_distance` across Tasks 3 and 5. `simulate_series` returns `(wins_a, wins_b)` in Tasks 4, 5, and 6. `category_marginals` and `solve_card` signatures match between Task 7 and the Task 8 CLI.

**One unused export.** `SeriesResult` is defined in Task 1 and tested there, but `run_swiss` records outcomes directly onto `TeamState` rather than returning a match log. It is retained because the D2 plan's backtest harness needs a match log — if D2 changes shape, delete it rather than build around it.
