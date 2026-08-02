"""Spec V floors 1 and 3: constant and exponentially weighted recent form."""

import math

from ti26.data.schema import MapRow
from ti26.ratings import skip_reason
from ti26.roster import roster_version_id


class ConstantModel:
    """Floor 1: every map 50/50. Log loss = ln 2 = 0.693."""

    def __init__(self, p: float = 0.5) -> None:
        self._p = p
        self.skipped: dict[str, int] = {}

    def predict(self, row: MapRow) -> float:
        return self._p

    def update(self, row: MapRow) -> None:
        return None


class EwmaModel:
    """Floor 3: exponentially weighted map win rate, no opponent adjustment."""

    def __init__(self, half_life_maps: float = 30.0) -> None:
        self._decay = 0.5 ** (1.0 / half_life_maps)
        self._wins: dict[str, float] = {}
        self._total: dict[str, float] = {}
        self.skipped: dict[str, int] = {}

    def _rate(self, rvid: str) -> float:
        total = self._total.get(rvid, 0.0)
        return self._wins.get(rvid, 0.0) / total if total > 0 else 0.5

    def predict(self, row: MapRow) -> float:
        a = self._rate(roster_version_id(row.radiant_accounts))
        b = self._rate(roster_version_id(row.dire_accounts))
        # Two independent win rates compared on the logit scale, clipped so a
        # roster with a perfect record does not yield an infinite logit.
        eps = 1e-6
        la = math.log(min(max(a, eps), 1 - eps) / (1 - min(max(a, eps), 1 - eps)))
        lb = math.log(min(max(b, eps), 1 - eps) / (1 - min(max(b, eps), 1 - eps)))
        return 1.0 / (1.0 + math.exp(-(la - lb)))

    def update(self, row: MapRow) -> None:
        reason = skip_reason(row)
        if reason is not None:
            self.skipped[reason] = self.skipped.get(reason, 0) + 1
            return
        for accounts, won in (
            (row.radiant_accounts, row.radiant_win),
            (row.dire_accounts, not row.radiant_win),
        ):
            rvid = roster_version_id(accounts)
            self._wins[rvid] = self._wins.get(rvid, 0.0) * self._decay + (1.0 if won else 0.0)
            self._total[rvid] = self._total.get(rvid, 0.0) * self._decay + 1.0
