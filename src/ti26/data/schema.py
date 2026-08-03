"""Normalize raw explorer rows into a validated, hashable map record."""

from collections.abc import Sequence
from dataclasses import dataclass

RADIANT_SLOTS = frozenset(range(5))
DIRE_SLOTS = frozenset(range(128, 133))

# OpenDota series_type: 0=Bo1, 1=Bo3, 2=Bo5. Value 3 occurs in real data
# (171/3011 in the sampled month) and is undocumented; it and NULL fall back
# to 1. best_of is reporting-only — rating updates are per-map regardless.
_BEST_OF = {0: 1, 1: 3, 2: 5}


class RosterSlotError(ValueError):
    """A match's player slots do not form a legal 5v5 roster."""


@dataclass(frozen=True)
class MapRow:
    match_id: int
    start_time: int
    duration: int
    radiant_win: bool
    league_id: int | None
    tier: str | None
    radiant_team_id: int | None
    dire_team_id: int | None
    series_id: int | None
    series_type: int | None
    patch: str | None
    radiant_accounts: tuple[int, ...]
    dire_accounts: tuple[int, ...]
    radiant_heroes: tuple[int, ...]
    dire_heroes: tuple[int, ...]
    has_null_team: bool
    has_bad_roster: bool

    @property
    def best_of(self) -> int:
        return _BEST_OF.get(self.series_type, 1)


def _split(slots: Sequence, accounts: Sequence, heroes: Sequence, match_id) -> tuple:
    if not (len(slots) == len(accounts) == len(heroes)):
        raise RosterSlotError(f"match {match_id}: ragged slot/account/hero arrays")
    if len(slots) != 10:
        raise RosterSlotError(f"match {match_id}: expected 10 players, got {len(slots)}")
    slot_ints = [int(s) for s in slots]
    if len(set(slot_ints)) != 10:
        raise RosterSlotError(f"match {match_id}: duplicate player slots {slot_ints}")
    radiant, dire = ([], []), ([], [])
    for slot, account, hero in zip(slot_ints, accounts, heroes):
        target = radiant if slot in RADIANT_SLOTS else dire if slot in DIRE_SLOTS else None
        if target is None:
            raise RosterSlotError(f"match {match_id}: slot {slot} is neither radiant nor dire")
        target[0].append(int(account) if account is not None else -1)
        target[1].append(int(hero) if hero is not None else -1)
    if len(radiant[0]) != 5 or len(dire[0]) != 5:
        raise RosterSlotError(
            f"match {match_id}: {len(radiant[0])}v{len(dire[0])} is not a legal 5v5"
        )
    return tuple(radiant[0]), tuple(dire[0]), tuple(radiant[1]), tuple(dire[1])


def _opt_int(value: int | str | None) -> int | None:
    return None if value is None else int(value)


def normalize_row(raw: dict) -> MapRow:
    r_acc, d_acc, r_hero, d_hero = _split(
        raw["slots"], raw["accounts"], raw["heroes"], raw["match_id"]
    )
    return MapRow(
        match_id=int(raw["match_id"]),
        start_time=int(raw["start_time"]),
        duration=int(raw["duration"]),
        radiant_win=bool(raw["radiant_win"]),
        league_id=_opt_int(raw.get("leagueid")),
        tier=raw.get("tier"),
        radiant_team_id=_opt_int(raw.get("radiant_team_id")),
        dire_team_id=_opt_int(raw.get("dire_team_id")),
        series_id=_opt_int(raw.get("series_id")),
        series_type=_opt_int(raw.get("series_type")),
        patch=raw.get("patch"),
        radiant_accounts=r_acc,
        dire_accounts=d_acc,
        radiant_heroes=r_hero,
        dire_heroes=d_hero,
        has_null_team=raw.get("radiant_team_id") is None or raw.get("dire_team_id") is None,
        has_bad_roster=-1 in r_acc or -1 in d_acc,
    )


def normalize_all(raw: list[dict]) -> tuple[list[MapRow], dict[str, int]]:
    rows: list[MapRow] = []
    tally: dict[str, int] = {}
    for item in raw:
        try:
            rows.append(normalize_row(item))
        except RosterSlotError:
            tally["roster_slot_error"] = tally.get("roster_slot_error", 0) + 1
        except (KeyError, TypeError, ValueError):
            tally["malformed_row"] = tally.get("malformed_row", 0) + 1
    return rows, tally
