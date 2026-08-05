import json

import pytest

from ti26.cli import main
from ti26.rules import load_rules
from ti26.types import Category

RULES = load_rules("config/ti2026_rules.yaml")


def _strengths_file(tmp_path, n):
    path = tmp_path / "s.csv"
    rows = ["team,team_id,strength"] + [f"x{i:02d},{9000 + i},0.0" for i in range(n)]
    path.write_text("\n".join(rows) + "\n")
    return path


def test_cli_writes_a_legal_card(tmp_path):
    out = tmp_path / "reports"
    assert main(["--n-sims", "300", "--seed", "4", "--out", str(out)]) == 0

    card = json.loads((out / "recommended_card.json").read_text())
    assert len(card["assignments"]) == 16
    counts = {c: 0 for c in Category}
    for category in card["assignments"].values():
        counts[Category(category)] += 1
    assert counts == RULES.category_capacities
    assert card["seed"] == 4
    assert card["n_sims"] == 300
    assert card["random_baseline"] == RULES.random_baseline
    assert "optimizer_marginal_objective" in card
    assert "model_implied_expected_score" not in card, (
        "the ambiguous label named two different quantities and must not return"
    )

    lines = (out / "category_probabilities.csv").read_text().splitlines()
    assert lines[0].startswith("team,")
    assert len(lines) == 17


def test_cli_is_reproducible(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    main(["--n-sims", "200", "--seed", "77", "--out", str(a)])
    main(["--n-sims", "200", "--seed", "77", "--out", str(b)])
    assert (a / "recommended_card.json").read_text() == (
        b / "recommended_card.json"
    ).read_text()


def test_cli_accepts_a_strengths_file(tmp_path):
    strengths = tmp_path / "s.csv"
    rows = ["team,team_id,strength"] + [
        f"x{i:02d},{9000 + i},{(i - 7.5) * 0.2:.4f}" for i in range(16)
    ]
    strengths.write_text("\n".join(rows) + "\n")
    out = tmp_path / "reports"
    assert main(["--strengths", str(strengths), "--n-sims", "200", "--out", str(out)]) == 0
    card = json.loads((out / "recommended_card.json").read_text())
    assert sorted(card["assignments"]) == [f"x{i:02d}" for i in range(16)]
    assert card["team_ids"] == {f"x{i:02d}": str(9000 + i) for i in range(16)}


def test_cli_rejects_a_strengths_file_without_team_ids(tmp_path):
    """Kills mutation: fall back to the display name when team_id is absent.

    A silent fallback is the whole defect this column exists to prevent: the
    card would go back to being decided by names at exact ties, and every
    downstream report would still describe it as name-independent. Refusing the
    file is the only outcome that cannot be mistaken for success.
    """
    strengths = tmp_path / "s.csv"
    rows = ["team,strength"] + [f"x{i:02d},{(i - 7.5) * 0.2:.4f}" for i in range(16)]
    strengths.write_text("\n".join(rows) + "\n")
    out = tmp_path / "reports"

    with pytest.raises(ValueError, match="team_id"):
        main(["--strengths", str(strengths), "--n-sims", "200", "--out", str(out)])
    assert not (out / "recommended_card.json").exists()


def test_cli_rejects_a_blank_team_id(tmp_path):
    """Kills mutation: accept an empty team_id cell as a valid identifier.

    An empty string is falsy but present, so a columns-exist check alone lets
    it through and the ordering key silently becomes the same value for every
    team that omitted one.
    """
    strengths = tmp_path / "s.csv"
    rows = ["team,team_id,strength"] + [
        f"x{i:02d},{'' if i == 3 else 9000 + i},{(i - 7.5) * 0.2:.4f}" for i in range(16)
    ]
    strengths.write_text("\n".join(rows) + "\n")
    out = tmp_path / "reports"

    with pytest.raises(ValueError, match="blank team_id"):
        main(["--strengths", str(strengths), "--n-sims", "200", "--out", str(out)])


def test_cli_rejects_a_short_strengths_file(tmp_path):
    strengths = _strengths_file(tmp_path, 10)
    out = tmp_path / "reports"
    with pytest.raises(ValueError) as exc_info:
        main(["--strengths", str(strengths), "--n-sims", "200", "--out", str(out)])
    assert "10" in str(exc_info.value)
    assert "16" in str(exc_info.value)


def test_cli_rejects_a_long_strengths_file(tmp_path):
    strengths = _strengths_file(tmp_path, 17)
    out = tmp_path / "reports"
    with pytest.raises(ValueError) as exc_info:
        main(["--strengths", str(strengths), "--n-sims", "200", "--out", str(out)])
    assert "17" in str(exc_info.value)
    assert "16" in str(exc_info.value)


def test_cli_rejects_an_even_but_wrong_count_before_simulating(tmp_path, monkeypatch):
    """12 is even, so it would slip past a parity-only check.

    Guards against validation being added only after `category_marginals`
    runs: patches it to blow up if called at all, proving the team-count
    check happens before any simulation work, not just that it eventually
    raises the right exception.
    """

    def _boom(*args, **kwargs):
        raise AssertionError("category_marginals must not run before the team-count check")

    monkeypatch.setattr("ti26.cli.category_marginals", _boom)

    strengths = _strengths_file(tmp_path, 12)
    out = tmp_path / "reports"
    with pytest.raises(ValueError) as exc_info:
        main(["--strengths", str(strengths), "--n-sims", "500000", "--out", str(out)])
    assert "12" in str(exc_info.value)
    assert "16" in str(exc_info.value)
