import json
import re
from pathlib import Path

import pytest

from ti26.cli_card_postmortem import CATEGORIES, EVAL_SEED, PostmortemError, main, read_marginals

CARD = Path("reports/card_ti2026_rules/recommended_card.json")


def test_eval_seed_differs_from_the_shipped_card_seed():
    """Kills reusing the card's own seed for evaluation.

    `card_score_distribution`'s docstring is explicit: the card was chosen to
    maximise expected score over those specific draws, so scoring it against
    them again rewards it for noise it was fitted to. The inflated number
    would look entirely plausible -- a slightly higher `E_model[S]` -- which is
    why this is a hard refusal rather than a comment.
    """
    card_seed = json.loads(CARD.read_text())["seed"]
    assert EVAL_SEED != card_seed
    with pytest.raises(PostmortemError, match="equals the card's own seed"):
        main(["--eval-seed", str(card_seed)])


def test_eval_seed_matches_the_one_the_spec_registered():
    """Kills silently re-picking the evaluation seed.

    The spec's whole argument for 90001 is provenance: `cli_d4` chose it long
    before TI 2026 was played, so it cannot have been tuned to this result. A
    seed invented later would be indistinguishable in the output and worthless
    as evidence.

    This binds the constant to the REGISTRATION DOCUMENT rather than to a
    literal, so changing the seed silently is impossible: it forces an edit to
    the tracked spec, where it is reviewable. (`reports/d4_card_backtest.json`,
    where the seed originates, is not tracked, so it cannot be the anchor.)
    """
    spec = Path(
        "docs/superpowers/specs/2026-08-16-group-card-postmortem.md"
    ).read_text()
    registered = re.search(r"eval_seed\s*=\s*(\d+)", spec)
    assert registered is not None, "the spec no longer registers an eval seed"
    assert EVAL_SEED == int(registered.group(1))


def test_marginals_are_read_as_full_distributions():
    """Kills dropping or reordering a category column.

    A missing column would leave every row summing to less than 1, which
    `proper_scores` rejects -- but only if the reader actually asked for all
    six. A reader that silently took whatever columns it found would score a
    five-category forecast as though it were complete.
    """
    marginals = read_marginals(Path("reports/card_ti2026_rules/category_probabilities.csv"))
    assert len(marginals) == 16
    for team, row in marginals.items():
        assert set(row) == set(CATEGORIES), team
        assert sum(row.values()) == pytest.approx(1.0, abs=1e-6), team
