"""Statistical identity follows the roster, not the organization (spec III)."""

import hashlib
from collections.abc import Iterable
from pathlib import Path

import yaml

from ti26.data.schema import MapRow


def roster_version_id(accounts: Iterable[int]) -> str:
    joined = ",".join(str(a) for a in sorted(accounts))
    return hashlib.sha1(joined.encode()).hexdigest()[:16]


def continuity(previous: Iterable[int], current: Iterable[int]) -> float:
    return len(set(previous) & set(current)) / 5.0


def load_aliases(path: str | Path) -> dict[int, int]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return {int(entry["from"]): int(entry["to"]) for entry in data.get("aliases", [])}


def canonical_team_id(team_id: int | None, aliases: dict[int, int]) -> int | None:
    if team_id is None:
        return None
    return aliases.get(int(team_id), int(team_id))


class RosterIndex:
    """Tracks which roster each canonical team most recently fielded.

    Stores the account set per roster, not just the id, so continuity can be
    computed from actual player overlap rather than assumed.
    """

    def __init__(self, aliases: dict[int, int] | None = None) -> None:
        self._aliases = aliases or {}
        self._latest_by_team: dict[int, str] = {}
        self._predecessor: dict[str, str | None] = {}
        self._accounts: dict[str, tuple[int, ...]] = {}
        self._maps: dict[str, int] = {}

    def observe(self, row: MapRow, count: bool = True) -> tuple[str, str]:
        """Register both rosters. `count=False` registers without tallying maps.

        Prediction needs a roster's predecessor resolved before the roster has
        played anything, so `predict` registers with `count=False`. Only team
        ids and player ids are read — never the outcome — so registering a
        future row cannot leak.
        """
        out = []
        for team_id, accounts in (
            (row.radiant_team_id, row.radiant_accounts),
            (row.dire_team_id, row.dire_accounts),
        ):
            rvid = roster_version_id(accounts)
            self._accounts.setdefault(rvid, tuple(sorted(accounts)))
            if count:
                self._maps[rvid] = self._maps.get(rvid, 0) + 1
            canonical = canonical_team_id(team_id, self._aliases)
            if canonical is not None:
                previous = self._latest_by_team.get(canonical)
                if rvid not in self._predecessor:
                    self._predecessor[rvid] = previous
                self._latest_by_team[canonical] = rvid
            else:
                self._predecessor.setdefault(rvid, None)
            out.append(rvid)
        return out[0], out[1]

    def predecessor(self, rvid: str) -> str | None:
        return self._predecessor.get(rvid)

    def accounts(self, rvid: str) -> tuple[int, ...]:
        return self._accounts.get(rvid, ())

    def continuity_with_predecessor(self, rvid: str) -> float:
        """Measured shared-player fraction, or 0.0 when there is no history.

        This replaces a fixed inheritance weight. A fixed weight is right for
        a single substitution and badly wrong for a three-player change, and
        nothing in the id alone distinguishes the two cases.
        """
        previous = self.predecessor(rvid)
        if previous is None:
            return 0.0
        return continuity(self._accounts.get(previous, ()), self._accounts.get(rvid, ()))

    def history(self, rvid: str) -> int:
        return self._maps.get(rvid, 0)
