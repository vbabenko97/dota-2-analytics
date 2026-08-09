"""The organiser's own group draw, when it exists.

TI 2026's groups were still unannounced as of 2026-08-09. Until they are, every
simulation invents its own split, which averages over a fact that will be known
before the compendium locks. Rounds 2 and 3 pair inside the initial group and
round 4 pairs across it, so the split is not cosmetic.

Round one is a SEPARATE publication, not a consequence of the groups: the 2026
rules make it organiser-set. So `round_one` is optional here, and the groups can
arrive without it. The near-lock runbook checks for both.

This loads the draw when a file is supplied and validates it hard. A group
assignment that is wrong -- unequal halves, a missing team, a name that does not
match the configured field -- would not crash the simulation. It would produce a
confident forecast of a bracket that does not exist, which is the failure the
validation below exists to make impossible.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml


class GroupDrawError(ValueError):
    """The supplied draw is not a legal group stage for this field."""


def load_group_draw(
    path: str | Path, team_names: Sequence[str]
) -> tuple[dict[str, str], list[tuple[str, str]] | None]:
    """Read a group draw and check it against the configured field.

    Returns `(groups, round_one)`. `round_one` is None when the file omits it,
    which is the normal case: the groups are typically announced before the
    opening matchups.
    """
    raw = yaml.safe_load(Path(path).read_text()) or {}
    groups_raw = raw.get("groups")
    if not isinstance(groups_raw, Mapping) or not groups_raw:
        raise GroupDrawError(f"{path} has no `groups:` mapping of label -> team list")

    groups: dict[str, str] = {}
    for label, members in groups_raw.items():
        if not isinstance(members, Sequence) or isinstance(members, str):
            raise GroupDrawError(f"group {label!r} is not a list of team names")
        for team in members:
            if team in groups:
                raise GroupDrawError(f"{team!r} appears in more than one group")
            groups[team] = str(label)

    configured = set(team_names)
    if set(groups) != configured:
        missing = sorted(configured - set(groups))
        unknown = sorted(set(groups) - configured)
        raise GroupDrawError(
            f"{path} does not describe the configured field: "
            f"missing {missing}, unknown {unknown}"
        )

    sizes = {label: sum(1 for g in groups.values() if g == label) for label in set(groups.values())}
    if len(sizes) != 2:
        raise GroupDrawError(f"expected exactly 2 groups, got {len(sizes)}: {sizes}")
    if len(set(sizes.values())) != 1:
        raise GroupDrawError(f"groups are not equal-sized: {sizes}")
    if any(size % 2 for size in sizes.values()):
        raise GroupDrawError(f"a group with an odd size cannot pair internally: {sizes}")

    round_one_raw = raw.get("round_one")
    if not round_one_raw:
        return groups, None

    round_one: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pair in round_one_raw:
        if len(pair) != 2:
            raise GroupDrawError(f"round-one entry {pair!r} is not a pair")
        a, b = (str(x) for x in pair)
        for team in (a, b):
            if team not in groups:
                raise GroupDrawError(f"round-one names {team!r}, which is not in the draw")
            if team in seen:
                raise GroupDrawError(f"{team!r} plays twice in round one")
            seen.add(team)
        if groups[a] != groups[b]:
            raise GroupDrawError(
                f"round-one pairs {a!r} and {b!r} across groups; the published "
                "rules pair round one INSIDE the initial group"
            )
        round_one.append((a, b))

    if seen != set(groups):
        raise GroupDrawError(
            f"round one covers {len(seen)} of {len(groups)} teams; every team "
            "plays in round one"
        )
    return groups, round_one
