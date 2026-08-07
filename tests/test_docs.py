"""The documentation contract, pinned.

Prose drifts silently. These tests fail when it drifts in the specific
directions this project has already drifted once: an audit republishing an
unbound result, a submission name changing without the team id behind it, or the
pre-lock check quietly becoming a name comparison.
"""

from pathlib import Path

import yaml

AUDITS = Path("docs/audits")
REGISTER = AUDITS / "2026-08-04-correction-register.md"
RUNBOOK = Path("docs/ti26/near-lock-runbook.md")
OWNER_NAMES = Path("docs/ti26/owner-display-names.yaml")


def test_every_audit_points_at_the_correction_register():
    """Kills mutation: leave a superseded audit with no route to the register.

    An audit that no longer carries its numbers but does not say where they went
    reads as an empty file rather than as a correction.
    """
    orphans = [
        audit.name
        for audit in sorted(AUDITS.glob("*.md"))
        if audit != REGISTER and REGISTER.name not in audit.read_text()
    ]
    assert not orphans, f"audits with no link to the correction register: {orphans}"


def test_the_owner_submission_names_are_the_sixteen_the_owner_gave():
    """Kills mutation: change a TI-facing submission name while keeping its team id.

    Names are cosmetic to the model but they are what goes on the compendium
    form, so a silent edit here is a submission error nothing else would catch.
    """
    entries = yaml.safe_load(OWNER_NAMES.read_text())["teams"]
    assert [entry["submission_name"] for entry in entries] == [
        "Aurora", "BoomBoys", "Iron Wing", "Falcons", "Liquid", "Yandex",
        "Xtreme", "Spirit", "Team Vision", "Nigma", "Huligani", "Resilience",
        "Vici Gaming", "OG", "GamerLegion", "LGD Gaming",
    ]


def test_every_owner_submission_name_maps_to_a_configured_team():
    """Kills mutation: list a submission name whose model_name is not configured.

    The submission list and the model's team config have to describe the same 16
    organisations, or the pre-lock name check compares against nothing.
    """
    entries = yaml.safe_load(OWNER_NAMES.read_text())["teams"]
    configured = {
        team["name"] for team in yaml.safe_load(Path("config/ti2026_teams.yaml").read_text())["teams"]
    }
    unmatched = [entry["model_name"] for entry in entries if entry["model_name"] not in configured]
    assert not unmatched, f"submission names with no configured team: {unmatched}"
    assert len(entries) == len(configured) == 16


def test_the_runbook_confirms_the_field_against_a_source_outside_the_repository():
    """Kills mutation: rewrite the field check as something the store can answer.

    Which sixteen organisations are invited is not in the store, which holds
    match rows and no invitations. Every other pre-lock check verifies internal
    consistency against the configured sixteen, so a field that is wrong by one
    team passes all of them. The step therefore has to send the reader outside
    `explorer_query` and stop on failure, not resolve it locally.
    """
    text = RUNBOOK.read_text()
    assert "Confirm the sixteen-team field" in text
    assert "outside `explorer_query`" in text
    assert "The store holds match rows, not invitations." in text
    assert "if the official field is not exactly the" in text


def test_the_runbook_stops_on_identity_ambiguity_and_checks_account_sets():
    """Kills mutation: let the pre-lock roster review proceed on names alone.

    Comparing organisation names is not evidence: the local store holds no team
    names at all. The roster-review step itself has to instruct an account-set
    comparison and rule names out -- asserting that the phrase "account set"
    appears somewhere in the document is not enough, because it also appears in
    the stop conditions and would survive the review step being rewritten to
    compare names.
    """
    text = RUNBOOK.read_text()
    assert "compare the CONFIGURED and RESOLVED account sets" in text
    assert "Do not compare organisation names." in text
    assert text.count("STOP — owner decision required") >= 3
    assert "explorer_query" in text
    assert "It is never caused by D4" in text
