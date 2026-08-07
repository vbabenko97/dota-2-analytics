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
    total_matchings: int


def perfect_matchings(items: list[str]) -> Iterator[list[tuple[str, str]]]:
    """Enumerate every way to partition items into unordered pairs.

    Record groups hold at most 8 teams, giving 105 matchings — small enough
    that brute force is both exhaustive and auditable.
    """
    if len(items) % 2 != 0:
        raise NoLegalPairingError(
            f"cannot enumerate matchings for an odd number of items: {len(items)}"
        )
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
    preference: str | None = None,
) -> PairingChoice:
    """Select a legal pairing by lexicographic preference.

    Order: hard group constraint -> fewest repeat opponents -> ranking
    distance (minimised, or maximised for Round 5 matches whose loser is
    eliminated) -> uniform random among exact ties.

    Hard constraints raise rather than degrade. Repeat avoidance is soft per
    the official text, so the engine minimises repeats instead of forbidding
    them — whether a forced repeat is reachable in the real bracket is
    unproven, and the engine does not assume either way.

    `preference` overrides ONLY the distance step, for the schedule-sensitivity
    diagnostic. `None` is the shipping rule and every other value exists to
    measure what that rule is worth, because `cli_pairing_check` established
    that it does not reproduce TI 2025's real pairings:

      "random"  ignore distance entirely — the no-information floor
      "min"     always minimise, even where the rules say maximise
      "max"     always maximise
      "fold"    conventional Swiss: seed the bucket, pair top half vs bottom

    The group and repeat filters apply under every setting, because those ARE
    corroborated by TI 2025. Leave it unset and this function behaves exactly
    as it did before the parameter existed, consuming the RNG identically.
    """
    if len(team_ids) % 2 != 0:
        raise NoLegalPairingError(f"cannot pair an odd number of teams: {len(team_ids)}")

    candidates = list(perfect_matchings(list(team_ids)))
    total = len(candidates)

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

    if preference == "fold":
        seeded = sorted(team_ids, key=lambda t: rank_index[t])
        half = len(seeded) // 2
        target = {frozenset((seeded[i], seeded[i + half])) for i in range(half)}
        folded = [m for m in candidates if {frozenset(p) for p in m} == target]
        candidates = folded or candidates
    elif preference != "random":
        sign = -1 if maximize_distance else 1
        if preference == "min":
            sign = 1
        elif preference == "max":
            sign = -1
        best = min(sign * distance(m) for m in candidates)
        candidates = [m for m in candidates if sign * distance(m) == best]

    chosen = rng.choice(candidates)
    return PairingChoice(
        matching=chosen,
        repeat_count=repeats(chosen),
        min_possible_repeats=fewest,
        total_matchings=total,
    )
