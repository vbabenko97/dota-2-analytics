"""Map-level Elo keyed by roster, the comparator for the D2 gate (spec V)."""

import math

from ti26.data.schema import MapRow
from ti26.ratings import skip_reason
from ti26.roster import roster_version_id


class EloModel:
    def __init__(self, k: float = 20.0, initial: float = 1500.0, scale: float = 400.0) -> None:
        self._k = k
        self._initial = initial
        self._scale = scale
        self._ratings: dict[str, float] = {}
        self.skipped: dict[str, int] = {}

    def rating(self, rvid: str) -> float:
        return self._ratings.get(rvid, self._initial)

    def predict(self, row: MapRow) -> float:
        ra = self.rating(roster_version_id(row.radiant_accounts))
        rb = self.rating(roster_version_id(row.dire_accounts))
        return 1.0 / (1.0 + 10.0 ** ((rb - ra) / self._scale))

    def update(self, row: MapRow) -> None:
        reason = skip_reason(row)
        if reason is not None:
            self.skipped[reason] = self.skipped.get(reason, 0) + 1
            return
        a = roster_version_id(row.radiant_accounts)
        b = roster_version_id(row.dire_accounts)
        expected = self.predict(row)
        outcome = 1.0 if row.radiant_win else 0.0
        delta = self._k * (outcome - expected)
        self._ratings[a] = self.rating(a) + delta
        self._ratings[b] = self.rating(b) - delta

    def strengths(self) -> dict[str, float]:
        """Logit-scale, zero-centred strengths for `ti26.montecarlo`.

        Converted from this instance's own `scale`, not a fixed 400: a
        `scale`-point gap is 10:1 odds by construction, so the conversion
        factor is ln(10)/scale. Hardcoding 400 here would silently
        desynchronize from `predict()` for any non-default scale.
        """
        if not self._ratings:
            return {}
        mean = sum(self._ratings.values()) / len(self._ratings)
        logit_per_point = math.log(10) / self._scale
        return {k: (v - mean) * logit_per_point for k, v in self._ratings.items()}
