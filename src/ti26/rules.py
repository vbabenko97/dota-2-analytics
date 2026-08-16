from collections import Counter, defaultdict
from dataclasses import dataclass

import yaml

from ti26.tiebreak import TIEBREAK_ORDER
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
    """Every Category member is present, 0 for any format that produces none."""
    caps: Counter[Category] = Counter({c: 0 for c in Category})
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
    # How a 3-2 team picks its elimination opponent. TI 2026 fixes the order of
    # choosing and says nothing about the basis, so this is an assumption about
    # team behaviour rather than a rule -- see `elimination.ChoicePolicy`.
    elimination_choice_policy: str
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
    configured_order = list(raw["tiebreak_order"])
    if configured_order != TIEBREAK_ORDER:
        raise ValueError(
            f"config tiebreak_order {configured_order} does not match the order "
            f"tiebreak.py actually implements: {TIEBREAK_ORDER}"
        )
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
        tiebreak_order=configured_order,
        within_group_rounds=list(rounds["within_group"]),
        cross_group_rounds=list(rounds["cross_group"]),
        max_distance_elimination_rounds=list(rounds["max_distance_when_loser_eliminated"]),
        elimination_choice_policy=str(raw["elimination_round"]["choice_policy"]),
        duration_log_mean=float(duration["log_mean"]),
        duration_log_sigma=float(duration["log_sigma"]),
        provenance=dict(raw["provenance"]),
        record_capacities=records,
        category_capacities=derive_category_capacities(
            records, fmt["advance_at_wins"], fmt["eliminate_at_losses"]
        ),
    )


def shipping_rules_facts(path: str) -> dict[str, object]:
    """Project the shipping rules configuration into the normalized facts vocabulary.

    Reads `path` with `yaml.safe_load` only; never calls `load_rules`, never
    mutates the YAML, and exposes no model-facing behavior. The derived
    `elimination_selection_order` names the existing sequential 3-2 chooser
    invariant already exercised by
    `tests/test_elimination.py::test_choosers_act_in_ranking_order`; this
    function adds no second policy switch and does not edit elimination
    behavior.
    """
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    rounds = raw["rounds"]
    return {
        "tiebreak_order": list(raw["tiebreak_order"]),
        "rounds": {
            "within_group": list(rounds["within_group"]),
            "cross_group": list(rounds["cross_group"]),
            "max_distance_when_loser_eliminated": list(
                rounds["max_distance_when_loser_eliminated"]
            ),
        },
        "elimination_selection_order": "best_3_2_sequential_choice",
    }


def shipping_rules_format_facts(path: str) -> dict[str, object]:
    """Project the shipping format configuration into the published-format facts vocabulary.

    Reads `path` with `yaml.safe_load` only; never calls `load_rules`, never
    mutates the YAML, and exposes no model-facing behavior.

    Only `n_teams`, `advance_at_wins` and `eliminate_at_losses` are configured
    values. The other five are DERIVED here from the same
    `derive_record_capacities`/`derive_category_capacities` the card already
    runs on, rather than restated as a second configured vocabulary that could
    drift from the first. `series_type` is not configured at all -- it names
    the existing `ti26.series.series_win_prob` default of `best_of=3`.

    `total_rounds` is deliberately absent: no retrieved published source
    states the round count as a number, so it has no place in a vocabulary
    that reconciles against captured spans. It remains a configured value
    feeding the capacities below.
    """
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    fmt = raw["format"]
    records = derive_record_capacities(
        n_teams=fmt["n_teams"],
        advance_at=fmt["advance_at_wins"],
        eliminate_at=fmt["eliminate_at_losses"],
        total_rounds=fmt["total_rounds"],
    )
    caps = derive_category_capacities(records, fmt["advance_at_wins"], fmt["eliminate_at_losses"])
    direct_advance_count = caps[Category.W4_0] + caps[Category.W4_1]
    elimination_round_pool = caps[Category.ELIM_WIN] + caps[Category.ELIM_LOSS]
    return {
        "n_teams": fmt["n_teams"],
        "advance_at_wins": fmt["advance_at_wins"],
        "eliminate_at_losses": fmt["eliminate_at_losses"],
        "series_type": "bo3",
        "direct_advance_count": direct_advance_count,
        "elimination_round_pool": elimination_round_pool,
        "elimination_matches": caps[Category.ELIM_WIN],
        "main_event_slots": direct_advance_count + caps[Category.ELIM_WIN],
    }
