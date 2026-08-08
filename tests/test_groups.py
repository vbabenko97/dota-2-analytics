"""The organiser's group draw: loading, validation, and what it must not change."""

import pytest
import yaml

from ti26.groups import GroupDrawError, load_group_draw
from ti26.montecarlo import category_marginals
from ti26.rules import load_rules

RULES = load_rules("config/ti2026_rules.yaml")
TEAMS = [f"t{i:02d}" for i in range(16)]


def _write(tmp_path, payload):
    path = tmp_path / "groups.yaml"
    path.write_text(yaml.safe_dump(payload))
    return path


def _even_draw():
    return {"groups": {"A": TEAMS[:8], "B": TEAMS[8:]}}


def test_a_legal_draw_loads(tmp_path):
    groups, round_one = load_group_draw(_write(tmp_path, _even_draw()), TEAMS)
    assert set(groups) == set(TEAMS)
    assert sorted(set(groups.values())) == ["A", "B"]
    assert round_one is None


def test_unequal_groups_are_refused(tmp_path):
    """Kills mutation: accept any partition and let the simulation run.

    A 9/7 split does not crash anything. It silently produces a confident
    forecast of a bracket that does not exist, because rounds 2 and 3 pair
    inside the group and an odd group cannot pair internally at all.
    """
    draw = {"groups": {"A": TEAMS[:9], "B": TEAMS[9:]}}
    with pytest.raises(GroupDrawError, match="equal-sized"):
        load_group_draw(_write(tmp_path, draw), TEAMS)


def test_a_draw_that_is_not_the_configured_field_is_refused(tmp_path):
    """Kills mutation: intersect with the configured field instead of matching.

    Silently dropping an unknown name would leave a 15-team group stage whose
    capacities no longer sum to the field, and the card would be a forecast of
    a different event.
    """
    draw = {"groups": {"A": TEAMS[:7] + ["ghost"], "B": TEAMS[8:]}}
    with pytest.raises(GroupDrawError, match="unknown"):
        load_group_draw(_write(tmp_path, draw), TEAMS)

    missing = {"groups": {"A": TEAMS[:7], "B": TEAMS[8:]}}
    with pytest.raises(GroupDrawError, match="missing"):
        load_group_draw(_write(tmp_path, missing), TEAMS)


def test_a_team_in_two_groups_is_refused(tmp_path):
    draw = {"groups": {"A": TEAMS[:8], "B": [TEAMS[0]] + TEAMS[9:]}}
    with pytest.raises(GroupDrawError, match="more than one group"):
        load_group_draw(_write(tmp_path, draw), TEAMS)


def test_more_than_two_groups_is_refused(tmp_path):
    draw = {"groups": {"A": TEAMS[:6], "B": TEAMS[6:12], "C": TEAMS[12:]}}
    with pytest.raises(GroupDrawError, match="exactly 2 groups"):
        load_group_draw(_write(tmp_path, draw), TEAMS)


def test_round_one_must_pair_inside_the_group(tmp_path):
    """Kills mutation: accept any round-one pairing.

    The published rules pair round one INSIDE the initial group. A cross-group
    round one would contradict the group constraint the rest of the engine
    enforces, and the disagreement would surface as unexplained pairings later.
    """
    draw = _even_draw()
    draw["round_one"] = [[TEAMS[0], TEAMS[8]]] + [
        [TEAMS[i], TEAMS[i + 1]] for i in range(1, 7, 2)
    ]
    with pytest.raises(GroupDrawError, match="across groups"):
        load_group_draw(_write(tmp_path, draw), TEAMS)


def test_round_one_must_cover_every_team(tmp_path):
    draw = _even_draw()
    draw["round_one"] = [[TEAMS[0], TEAMS[1]]]
    with pytest.raises(GroupDrawError, match="every team"):
        load_group_draw(_write(tmp_path, draw), TEAMS)


def test_a_full_round_one_loads(tmp_path):
    draw = _even_draw()
    draw["round_one"] = [[TEAMS[i], TEAMS[i + 1]] for i in range(0, 16, 2)]
    groups, round_one = load_group_draw(_write(tmp_path, draw), TEAMS)
    assert round_one is not None
    assert len(round_one) == 8
    assert all(groups[a] == groups[b] for a, b in round_one)


def test_no_draw_is_byte_identical_to_not_passing_one():
    """Kills mutation: change the default path while plumbing the draw through.

    The groups are not announced yet, so every card shipped before they are
    runs the `groups=None` path. If threading the argument moved that path by
    even one RNG draw, it would silently move the shipping card, and the
    regenerated bundle would stop reproducing.
    """
    strengths = {t: (i - 7.5) * 0.15 for i, t in enumerate(TEAMS)}
    without = category_marginals(strengths, RULES, n_sims=200, seed=5)
    explicit_none = category_marginals(
        strengths, RULES, n_sims=200, seed=5, groups=None, round_one=None
    )
    assert without == explicit_none


def test_a_supplied_draw_actually_changes_the_marginals():
    """Kills mutation: accept `groups` and never pass it to `run_swiss`.

    An argument that is validated, recorded in the payload and then dropped is
    the worst outcome here: the report would claim the card is conditioned on
    the real bracket while the simulation kept inventing its own.
    """
    strengths = {t: (i - 7.5) * 0.15 for i, t in enumerate(TEAMS)}
    # Stack the strong half into one group so the split cannot be immaterial.
    stacked = {t: ("A" if i % 2 == 0 else "B") for i, t in enumerate(TEAMS)}
    split = {t: ("A" if i < 8 else "B") for i, t in enumerate(TEAMS)}
    a = category_marginals(strengths, RULES, n_sims=400, seed=5, groups=stacked)
    b = category_marginals(strengths, RULES, n_sims=400, seed=5, groups=split)
    assert a != b
