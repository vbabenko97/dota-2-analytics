"""Shared types for rating models.

All models expose the same two-method surface so the backtest harness in
`ti26.backtest` can drive any of them without special-casing.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from ti26.data.schema import MapRow


@dataclass(frozen=True)
class Prediction:
    """One out-of-sample forecast, carrying enough provenance to be re-grouped.

    `series_id` is what the clustered bootstrap resamples on and `fold_id`
    is what fold-integrity assertions check, so neither is optional.
    """

    fold_id: int
    match_id: int
    start_time: int
    league_id: int | None
    series_id: int | None
    p_radiant: float
    rated: bool
    reason: str | None = None


class RatingModel(Protocol):
    def predict(self, row: MapRow) -> float: ...
    def update(self, row: MapRow) -> None: ...


@dataclass(frozen=True)
class GateConfig:
    min_margin_nats: float
    bootstrap_draws: int
    bootstrap_ci: float
    seed: int
    elo_k: float
    glicko_tau: float
    ewma_half_life_maps: float


def load_gate_config(path: str | Path) -> GateConfig:
    data = yaml.safe_load(Path(path).read_text())
    gate, hyper = data["gate"], data["hyperparameters"]
    return GateConfig(
        min_margin_nats=float(gate["min_margin_nats"]),
        bootstrap_draws=int(gate["bootstrap_draws"]),
        bootstrap_ci=float(gate["bootstrap_ci"]),
        seed=int(gate["seed"]),
        elo_k=float(hyper["elo_k"]),
        glicko_tau=float(hyper["glicko_tau"]),
        ewma_half_life_maps=float(hyper["ewma_half_life_maps"]),
    )


def skip_reason(row: MapRow) -> str | None:
    """Why this row cannot drive a rating update, or None if it can."""
    if row.has_null_team:
        return "null_team"
    if row.has_bad_roster:
        return "bad_roster"
    return None
