"""The bracket-validation producer, pinned where I actually got it wrong."""

import random

import pytest

from ti26.cli_pairing_check import _allowed_matchings, _is_fold, infer_groups, split_rounds
from ti26.pairing import choose_pairing


def _series(start, teams):
    return {"start": start, "teams": set(teams), "map_wins": {}, "durations": []}


def test_allowed_matchings_always_contains_what_choose_pairing_samples():
    """Kills mutation: filter on distance before repeats in `_allowed_matchings`.

    This module re-derives the engine's candidate set instead of calling it,
    because `choose_pairing` returns one random sample. That is only sound if
    the two apply the same filters in the same ORDER -- repeats first, then
    distance. Swap them and the sampled pairing escapes the set, which would
    silently turn every 'the real bracket disagrees with the engine' finding
    into an artifact of this file.
    """
    members = ["a", "b", "c", "d"]
    rank_index = {"a": 0, "b": 1, "c": 2, "d": 3}
    # Make the repeat filter and the distance filter disagree: the closest
    # pairing by rank is exactly the one that repeats.
    prior = {"a": {"b"}, "b": {"a"}, "c": {"d"}, "d": {"c"}}
    groups = dict.fromkeys(members, "A")

    allowed = _allowed_matchings(
        members, rank_index, prior, groups, cross_group=False, maximize_distance=False
    )
    as_sets = [{frozenset(p) for p in m} for m in allowed]
    for seed in range(40):
        sampled = choose_pairing(members, rank_index, prior, random.Random(seed))
        assert {frozenset(p) for p in sampled.matching} in as_sets


def test_groups_need_every_within_group_round_to_come_out_right():
    """Kills mutation: infer groups from rounds 2-3 only, dropping round 1.

    After round 1 a group's winners and losers never meet again inside it, so
    connectivity over rounds 2-3 alone yields components of HALF the true
    group size -- four groups of four instead of two of eight. That silently
    weakens the round-4 cross-group check into a much easier test, which is
    exactly the error this producer made on its first run.
    """
    # One group of eight, paired the way a Swiss group really is: round 1 by
    # seeding, then winners with winners and losers with losers. That is what
    # makes rounds 2-3 close into two four-cycles instead of spanning the group.
    rounds = [
        [_series(1, p) for p in (("t1", "t2"), ("t3", "t4"), ("t5", "t6"), ("t7", "t8"))],
        [_series(2, p) for p in (("t1", "t3"), ("t5", "t7"), ("t2", "t4"), ("t6", "t8"))],
        [_series(3, p) for p in (("t1", "t5"), ("t3", "t7"), ("t2", "t6"), ("t4", "t8"))],
    ]
    full = infer_groups(rounds, within_rounds=3)
    assert len(set(full.values())) == 1, "round 1 binds the group into one component"
    assert len(full) == 8

    partial = infer_groups(rounds[1:], within_rounds=2)
    assert len(set(partial.values())) == 2, "without round 1 the group splits in half"
    assert partial["t1"] != partial["t2"], "winners and losers never meet in rounds 2-3"


def test_rounds_are_cut_on_a_repeated_team_not_a_fixed_size():
    """Kills mutation: split rounds into fixed-size chunks.

    Swiss rounds shrink as teams finish -- TI 2025 ran 8, 8, 8, 8, 7 then 5 --
    so any fixed chunk size mis-assigns every round after the first shrink and
    corrupts the standings fed to the ranking.
    """
    series = [
        _series(1, ("a", "b")), _series(2, ("c", "d")),
        _series(3, ("a", "c")), _series(4, ("b", "d")),
        _series(5, ("a", "d")),
    ]
    rounds = split_rounds(series)
    assert [len(r) for r in rounds] == [2, 2, 1]


def test_fold_pairing_is_the_top_half_against_the_bottom_half():
    """Kills mutation: implement the fold as adjacent seeds (1v2, 3v4).

    The fold is the competing hypothesis for what the real bracket does, so
    getting it wrong would make the comparison meaningless. With four seeds it
    is 1v3 and 2v4, never 1v2 and 3v4.
    """
    members = ["w", "x", "y", "z"]
    rank_index = {"w": 0, "x": 1, "y": 2, "z": 3}
    assert _is_fold(members, rank_index, [("w", "y"), ("x", "z")])
    assert not _is_fold(members, rank_index, [("w", "x"), ("y", "z")])
    assert not _is_fold(members, rank_index, [("w", "z"), ("x", "y")])


def test_split_rounds_rejects_nothing_and_returns_empty_for_no_series():
    assert split_rounds([]) == []


@pytest.mark.parametrize("size", [3, 5])
def test_fold_needs_an_even_bucket(size):
    members = [str(i) for i in range(size)]
    rank_index = {t: i for i, t in enumerate(members)}
    assert not _is_fold(members, rank_index, [])
