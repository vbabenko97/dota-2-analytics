from pathlib import Path

import pytest
import yaml

from ti26.cli_playoff_bracket import DEFAULT_SEEDS, main


def test_default_seeds_are_eight_configured_teams():
    """Kills a typo in a hardcoded seed name.

    The seeds are written by hand from the client bracket. A misspelling would
    otherwise surface only at run time, after the whole Glicko fit, as a missing
    strength -- and only if someone ran it.
    """
    teams = yaml.safe_load(Path("config/ti2026_teams.yaml").read_text())["teams"]
    configured = {entry["name"] for entry in teams}
    assert len(DEFAULT_SEEDS) == 8
    assert len(set(DEFAULT_SEEDS)) == 8
    assert set(DEFAULT_SEEDS) <= configured


def test_seed_list_must_be_eight_distinct_names():
    """Kills accepting a short or duplicated seed list.

    A duplicate would put one team in two quarterfinals and still produce a
    plausible-looking slate.
    """
    with pytest.raises(SystemExit, match="eight distinct"):
        main(["--store", "unused.sqlite", "--seeds", "A,B,C,D,E,F,G"])
    with pytest.raises(SystemExit, match="eight distinct"):
        main(["--store", "unused.sqlite", "--seeds", "A,B,C,D,E,F,G,A"])
