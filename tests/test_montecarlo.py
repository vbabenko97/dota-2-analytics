import pytest

from ti26.elimination import ChoicePolicy
from ti26.montecarlo import (
    card_score_distribution,
    category_marginals,
    monte_carlo_stderr,
)
from ti26.rules import load_rules
from ti26.types import Category

RULES = load_rules("config/ti2026_rules.yaml")
CAPS = RULES.category_capacities
TEAMS = [f"t{i:02d}" for i in range(16)]


def test_each_team_row_sums_to_one():
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=200, seed=0)
    for row in marginals.values():
        assert sum(row.values()) == pytest.approx(1.0)


def test_each_category_column_sums_to_its_capacity():
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=200, seed=0)
    for category, capacity in CAPS.items():
        assert sum(r[category] for r in marginals.values()) == pytest.approx(capacity)


def test_stderr_formula():
    assert monte_carlo_stderr(0.5, 10_000) == pytest.approx(0.005)
    assert monte_carlo_stderr(0.0, 100) == 0.0


def test_stronger_team_is_likelier_to_go_four_zero():
    strengths = dict.fromkeys(TEAMS, 0.0)
    strengths["t00"] = 1.5
    marginals = category_marginals(strengths, RULES, n_sims=2000, seed=2)
    assert marginals["t00"][Category.W4_0] > marginals["t01"][Category.W4_0]
    assert marginals["t00"][Category.L0_4] < marginals["t01"][Category.L0_4]


def test_same_seed_reproduces_identical_marginals():
    a = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=100, seed=9)
    b = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=100, seed=9)
    assert a == b


def test_different_seeds_produce_different_marginals():
    a = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=100, seed=9)
    b = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=100, seed=10)
    assert a != b


def test_policy_choice_is_plumbed_through():
    """A rational chooser always picks its weakest available opponent; a
    random chooser does not. With the same seed and differentiated
    strengths, that mechanical difference must show up as a difference in
    the resulting marginals -- a row-sums-to-one check alone cannot tell
    the two policies apart."""
    strengths = {t: (i - 7.5) * 0.3 for i, t in enumerate(TEAMS)}
    rational = category_marginals(
        strengths, RULES, n_sims=300, seed=3, elimination_policy=ChoicePolicy.RATIONAL
    )
    randomised = category_marginals(
        strengths, RULES, n_sims=300, seed=3, elimination_policy=ChoicePolicy.RANDOM
    )
    assert rational != randomised


def test_the_default_policy_is_the_configured_one():
    """Kills mutation: hardcode a policy in `category_marginals`.

    The choice policy is an assumption the config records and the card payload
    reports. If the simulation ignores the config and uses its own default, the
    card would advertise one assumption and be built on another.
    """
    strengths = {t: (i - 7.5) * 0.3 for i, t in enumerate(TEAMS)}
    default = category_marginals(strengths, RULES, n_sims=200, seed=4)
    explicit = category_marginals(
        strengths, RULES, n_sims=200, seed=4, elimination_policy=RULES.elimination_choice_policy
    )
    assert default == explicit

    other = "random" if RULES.elimination_choice_policy != "random" else "rational"
    assert default != category_marginals(
        strengths, RULES, n_sims=200, seed=4, elimination_policy=other
    )


@pytest.mark.slow
def test_equal_strength_teams_approach_capacity_over_sixteen():
    n = 4000
    marginals = category_marginals(dict.fromkeys(TEAMS, 0.0), RULES, n_sims=n, seed=1)
    for team, row in marginals.items():
        for category, capacity in CAPS.items():
            expected = capacity / 16
            tolerance = 4 * monte_carlo_stderr(expected, n)
            assert row[category] == pytest.approx(expected, abs=tolerance), (
                f"{team}/{category}"
            )


def test_display_names_cannot_move_the_marginals():
    """A pure relabel must not change a single probability.

    This is the 2026-08-04 defect. `run_swiss` sorts its team ids before every
    RNG draw it makes, so renaming "1win" to "Iron Wing" -- which changed no
    strength at all -- moved that team from first to seventh in alphabetical
    order, shifted which team consumed which draw, and flipped the card's 0-4
    slot. The two candidate assignments were 4.2e-4 expected points apart
    against 6.5e-4 of Monte Carlo error, so the reshuffle alone decided it.

    The renamed key below sorts BEFORE every other name, reproducing that
    first-versus-seventh move rather than a harmless adjacent one.
    """
    strengths = {f"team{i:02d}": 0.6 - 0.08 * i for i in range(16)}
    renamed_key = "team07"
    base = category_marginals(strengths, RULES, n_sims=300, seed=3)

    renamed = {("0aaa" if k == renamed_key else k): v for k, v in strengths.items()}
    after = category_marginals(renamed, RULES, n_sims=300, seed=3)

    assert set(after) == (set(strengths) - {renamed_key}) | {"0aaa"}
    for team in strengths:
        got = after["0aaa" if team == renamed_key else team]
        assert got == base[team], f"relabel moved {team}"


def _tied_field() -> tuple[dict[str, float], dict[str, str]]:
    """16 teams, two of them at EXACTLY equal strength, with stable ids.

    The ids are assigned so that id order and name order DISAGREE for the tied
    pair: team00 holds the later id. A tie broken by name and a tie broken by id
    therefore pick different teams, which is what makes the tests below able to
    tell them apart.

    The tie sits at ranks 0 and 1 deliberately. Those ranks take the 4-0 and 4-1
    slots, so swapping the pair changes a category. An earlier version of this
    fixture tied ranks 3 and 4, which are BOTH elim_win -- the swap was real but
    invisible, and the score-distribution test below passed under the very
    mutation it claimed to kill.
    """
    strengths = {f"team{i:02d}": 0.6 - 0.08 * i for i in range(16)}
    strengths["team00"] = strengths["team01"]
    ids = {name: f"id{i:02d}" for i, name in enumerate(sorted(strengths))}
    ids["team00"], ids["team01"] = ids["team01"], ids["team00"]
    return strengths, ids


def test_exactly_tied_strengths_are_ordered_by_stable_id_not_display_name():
    """Kills mutation: break exact-strength ties with the display name.

    The rename test above passes today only because distinct float strengths
    never reach the tie-break. Two teams at exactly equal strength do reach it,
    and then the NAME decides which of them takes which simulation stream --
    so renaming one moves probability mass with no strength change at all.
    Keying the tie-break on the configured team id removes the name from the
    computation entirely.
    """
    strengths, ids = _tied_field()
    base = category_marginals(strengths, RULES, n_sims=300, seed=3, team_ids=ids)

    renamed = {("0aaa" if k == "team01" else k): v for k, v in strengths.items()}
    renamed_ids = {("0aaa" if k == "team01" else k): v for k, v in ids.items()}
    after = category_marginals(renamed, RULES, n_sims=300, seed=3, team_ids=renamed_ids)

    by_id_before = {ids[team]: row for team, row in base.items()}
    by_id_after = {renamed_ids[team]: row for team, row in after.items()}
    assert by_id_after == by_id_before


def test_card_score_distribution_is_unmoved_by_renaming_an_exactly_tied_team():
    """Kills mutation: break exact-strength ties with the display name.

    Same defect as the marginals, reached through the scoring path instead:
    canonical_labels is what both share, so a name-keyed tie-break moves the
    score distribution of a card nobody edited.
    """
    strengths, ids = _tied_field()
    slots = [c for c in Category for _ in range(CAPS[c])]
    order = sorted(strengths, key=lambda t: (-strengths[t], ids[t]))
    card = dict(zip(order, slots, strict=True))
    base = card_score_distribution(card, strengths, RULES, n_sims=300, seed=4, team_ids=ids)

    rename = lambda k: "0aaa" if k == "team01" else k
    renamed_s = {rename(k): v for k, v in strengths.items()}
    renamed_c = {rename(k): v for k, v in card.items()}
    renamed_ids = {rename(k): v for k, v in ids.items()}
    after = card_score_distribution(
        renamed_c, renamed_s, RULES, n_sims=300, seed=4, team_ids=renamed_ids
    )
    assert after == base


def test_team_ids_must_cover_exactly_the_strength_keys():
    """Kills mutation: ignore a team_ids mapping that does not match the strengths.

    A silently-ignored id mapping is worse than none: the caller believes the
    card is name-independent while the name fallback is still deciding ties.
    """
    strengths, ids = _tied_field()
    with pytest.raises(ValueError, match="team_ids"):
        category_marginals(
            strengths, RULES, n_sims=10, seed=0, team_ids={k: v for k, v in list(ids.items())[:15]}
        )


def test_team_ids_must_be_unique():
    """Kills mutation: accept duplicate stable ids, which cannot order a tie."""
    strengths, ids = _tied_field()
    collided = dict(ids)
    collided["team03"] = collided["team04"]
    with pytest.raises(ValueError, match="team_ids"):
        category_marginals(strengths, RULES, n_sims=10, seed=0, team_ids=collided)


def test_card_score_distribution_is_a_proper_distribution_over_possible_scores():
    strengths = {t: (i - 7.5) * 0.2 for i, t in enumerate(TEAMS)}
    slots = [c for c in Category for _ in range(CAPS[c])]
    card = dict(zip(TEAMS, slots, strict=True))
    n = 400
    dist = card_score_distribution(card, strengths, RULES, n_sims=n, seed=5)
    assert sum(dist.values()) == n, "every simulation must yield exactly one score"
    assert all(0 <= s <= 16 for s in dist)


def test_card_score_distribution_rewards_a_card_aligned_with_the_strengths():
    """A card ordered WITH the strengths must outscore one ordered against them.

    Without this the function could ignore the card argument entirely --
    returning the same distribution for every assignment -- and still satisfy
    the shape check above.
    """
    strengths = {t: (i - 7.5) * 0.4 for i, t in enumerate(TEAMS)}
    slots = [c for c in Category for _ in range(CAPS[c])]
    strongest_first = sorted(TEAMS, key=lambda t: -strengths[t])
    aligned = dict(zip(strongest_first, slots, strict=True))
    inverted = dict(zip(list(reversed(strongest_first)), slots, strict=True))

    def mean(card):
        d = card_score_distribution(card, strengths, RULES, n_sims=600, seed=11)
        return sum(s * n for s, n in d.items()) / sum(d.values())

    assert mean(aligned) > mean(inverted) + 1.0


def test_card_score_distribution_ignores_display_names():
    """Same defect class as the marginals: a pure relabel must not move scores."""
    strengths = {f"team{i:02d}": 0.6 - 0.08 * i for i in range(16)}
    slots = [c for c in Category for _ in range(CAPS[c])]
    order = sorted(strengths, key=lambda t: -strengths[t])
    card = dict(zip(order, slots, strict=True))
    base = card_score_distribution(card, strengths, RULES, n_sims=300, seed=4)

    ren_s = {("0aaa" if k == "team07" else k): v for k, v in strengths.items()}
    ren_c = {("0aaa" if k == "team07" else k): v for k, v in card.items()}
    after = card_score_distribution(ren_c, ren_s, RULES, n_sims=300, seed=4)
    assert after == base
