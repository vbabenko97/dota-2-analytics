"""Spec V floors 1 and 3: constant and exponentially weighted recent form."""

import math

from ti26.data.schema import MapRow
from ti26.ratings import skip_reason
from ti26.roster import roster_version_id


class ConstantModel:
    """Floor 1: every map 50/50. Log loss = ln 2 = 0.693."""

    def __init__(self, p: float = 0.5) -> None:
        self._p = p

    def predict(self, row: MapRow) -> float:
        return self._p

    def update(self, row: MapRow) -> None:
        pass


def _logit(rate: float) -> float:
    # Clipped so a roster with a perfect (or winless) record does not yield
    # an infinite logit.
    eps = 1e-6
    clipped = min(max(rate, eps), 1 - eps)
    return math.log(clipped / (1 - clipped))


class EwmaModel:
    """Floor 3: exponentially weighted map win rate, no opponent adjustment."""

    def __init__(self, half_life_maps: float = 30.0) -> None:
        self._decay = 0.5 ** (1.0 / half_life_maps)
        self._wins: dict[str, float] = {}
        self._total: dict[str, float] = {}
        self.skipped: dict[str, int] = {}

    def _rate(self, rvid: str) -> float:
        # Laplace smoothing: a roster with one win and a roster with two
        # hundred straight wins both have a raw wins/total of 1.0, which
        # would clip to the same predicted probability and make this floor
        # unable to tell a single data point from a long streak. `total`
        # defaulting to 0 falls out of the same formula as (0+1)/(0+2)=0.5.
        wins = self._wins.get(rvid, 0.0)
        total = self._total.get(rvid, 0.0)
        return (wins + 1.0) / (total + 2.0)

    def predict(self, row: MapRow) -> float:
        a = self._rate(roster_version_id(row.radiant_accounts))
        b = self._rate(roster_version_id(row.dire_accounts))
        # Two independent win rates compared on the logit scale.
        return 1.0 / (1.0 + math.exp(-(_logit(a) - _logit(b))))

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
