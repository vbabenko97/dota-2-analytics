"""Eight-team double-elimination bracket: topology, slot distributions, exact optimum.

Registered in `docs/superpowers/specs/2026-08-16-ti2026-playoff-bracket-prediction.md`
before this module existed. Nothing here reads a rating; it takes a pairwise
series-win probability function and returns structure.

The lower-bracket feed edge is NOT established for TI 2026, so both variants are
implemented and neither is the default. Callers pass the one they mean, and the
producer is required to report both until the locked client bracket settles it.
"""

from collections.abc import Callable, Iterable, Iterator, Sequence
from itertools import product

# Slot order is fixed and is the order picks are reported in. Grand Final last.
SLOTS: tuple[str, ...] = (
    "UB QF1",
    "UB QF2",
    "UB QF3",
    "UB QF4",
    "UB SF1",
    "UB SF2",
    "UB Final",
    "LB R1M1",
    "LB R1M2",
    "LB QF1",
    "LB QF2",
    "LB SF",
    "LB Final",
    "Grand Final",
)

# Only the Grand Final changes length. Registered, not inferred at run time.
BEST_OF: dict[str, int] = {slot: 3 for slot in SLOTS}
BEST_OF["Grand Final"] = 5


def resolve(
    seeds: Sequence[object], decide: Callable[[object, object, str], object], cross_feed: bool
) -> dict[str, object]:
    """Play the bracket, asking `decide(a, b, slot)` for each winner.

    `seeds` is the eight teams in Upper Bracket quarterfinal order: QF1 is
    seeds[0] vs seeds[1], QF2 is seeds[2] vs seeds[3], and so on.

    `cross_feed` routes an Upper Bracket semifinal loser against the Lower
    Bracket Round 1 winner from the OPPOSITE half. The alternative sends it
    against its own half. This single edge changes the winner distribution of
    every lower-bracket slot from the quarterfinals onward, which is why it is a
    parameter and not a constant.
    """
    if len(seeds) != 8 or len(set(map(id, seeds))) != 8:
        raise ValueError("bracket needs exactly eight distinct seeds")
    winners: dict[str, object] = {}

    def play(a: object, b: object, slot: str) -> tuple[object, object]:
        won = decide(a, b, slot)
        if won is not a and won is not b:
            raise ValueError(f"{slot}: decide returned a team that is not playing")
        winners[slot] = won
        return won, (b if won is a else a)

    qf = [play(seeds[2 * i], seeds[2 * i + 1], f"UB QF{i + 1}") for i in range(4)]
    sf1 = play(qf[0][0], qf[1][0], "UB SF1")
    sf2 = play(qf[2][0], qf[3][0], "UB SF2")
    ubf = play(sf1[0], sf2[0], "UB Final")

    r1 = play(qf[0][1], qf[1][1], "LB R1M1")
    r2 = play(qf[2][1], qf[3][1], "LB R1M2")
    if cross_feed:
        qf1 = play(r1[0], sf2[1], "LB QF1")
        qf2 = play(r2[0], sf1[1], "LB QF2")
    else:
        qf1 = play(r1[0], sf1[1], "LB QF1")
        qf2 = play(r2[0], sf2[1], "LB QF2")

    lbsf = play(qf1[0], qf2[0], "LB SF")
    lbf = play(lbsf[0], ubf[1], "LB Final")
    play(ubf[0], lbf[0], "Grand Final")
    return winners


def all_brackets(seeds: Sequence[object], cross_feed: bool) -> list[dict[str, object]]:
    """Every coherent bracket: exactly 2**14, one per assignment of the 14 binary choices.

    Enumerated rather than searched. The space is small enough that the optimum
    is exact, so no greedy per-slot rule is needed -- and a greedy rule is not
    even guaranteed coherent, since it can name a team the same bracket never
    advanced.
    """
    out = []
    for bits in product((0, 1), repeat=len(SLOTS)):
        choices = iter(bits)
        # `choices` is bound as a default so the closure cannot outlive its
        # iteration; `resolve` consumes it immediately, but binding says so.
        out.append(
            resolve(seeds, lambda a, b, _slot, it=choices: a if next(it) == 0 else b, cross_feed)
        )
    return out


def weighted_brackets(
    seeds: Sequence[object],
    series_win_prob: Callable[[object, object, int], float],
    cross_feed: bool,
) -> Iterator[tuple[dict[str, object], float]]:
    """Every coherent bracket paired with its probability.

    The 2**14 leaves carry structure and probability on the same walk, so any
    quantity accumulated from this is exact: no Monte Carlo error, no seed, no
    generator whose stream stability has to be pinned.

    Yielded rather than returned as a list. Callers accumulate as they go, and
    holding 16384 dicts at once buys nothing.
    """
    for bits in product((0, 1), repeat=len(SLOTS)):
        choices = iter(bits)
        weight = 1.0

        def decide(a: object, b: object, slot: str, it=choices) -> object:
            nonlocal weight
            p = series_win_prob(a, b, BEST_OF[slot])
            if next(it) == 0:
                weight *= p
                return a
            weight *= 1.0 - p
            return b

        winners = resolve(seeds, decide, cross_feed)
        yield winners, weight


def slot_distributions(
    seeds: Sequence[object],
    series_win_prob: Callable[[object, object, int], float],
    cross_feed: bool,
) -> dict[str, dict[object, float]]:
    """P(team wins slot) for every slot, by exact enumeration over outcome space.

    Exact rather than simulated: the same 2**14 leaves carry both the bracket
    structure and its probability, so there is no Monte Carlo error to reason
    about and no seed to be unstable under.
    """
    dist: dict[str, dict[object, float]] = {slot: {} for slot in SLOTS}
    for winners, weight in weighted_brackets(seeds, series_win_prob, cross_feed):
        for slot, team in winners.items():
            dist[slot][team] = dist[slot].get(team, 0.0) + weight
    return dist


def best_bracket(
    seeds: Sequence[object],
    series_win_prob: Callable[[object, object, int], float],
    cross_feed: bool,
) -> tuple[dict[str, object], float]:
    """The coherent bracket maximising expected hits, and that expectation.

    Ties are broken by the enumeration order of `all_brackets`, which is
    deterministic, so repeated runs return the same slate.
    """
    dist = slot_distributions(seeds, series_win_prob, cross_feed)
    best, best_score = None, -1.0
    for candidate in all_brackets(seeds, cross_feed):
        score = sum(dist[slot].get(team, 0.0) for slot, team in candidate.items())
        if score > best_score:
            best, best_score = candidate, score
    return best, best_score


def coherent_coin_null(seeds: Sequence[object], cross_feed: bool) -> float:
    """Expected hits for a random player who must pre-commit a coherent bracket.

    Not the same control as a coin shown each slot's actual two participants:
    that one scores 7/14, because it is told who got there. This one is not.
    """
    dist = slot_distributions(seeds, lambda a, b, best_of: 0.5, cross_feed)
    return sum(sum(p * p for p in dist[slot].values()) for slot in SLOTS)


def disagreements(left: dict[str, object], right: dict[str, object]) -> list[str]:
    """Slots where two slates name different winners, in registered slot order."""
    return [slot for slot in SLOTS if left[slot] is not right[slot]]


def format_slate(slate: dict[str, object], name: Callable[[object], str] = str) -> Iterable[str]:
    return (f"{slot}: {name(slate[slot])}" for slot in SLOTS)
