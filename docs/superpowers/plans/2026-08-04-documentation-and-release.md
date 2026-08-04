# Documentation, Historical Regeneration, and Near-Lock Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make current prose and reports traceable to manifest-bound producers, preserve historical auditability without unproduced claims, and prepare a strictly controlled near-lock TI 2026 regeneration.

**Architecture:** Treat configuration, source comments, and authored runbooks as versioned inputs; treat empirical reports as generated outputs in a per-run `reports/runs/` directory whose manifest hashes every result and report. Replace current-tree historical narratives with short, nonnumeric correction/supersession notices that link to the canonical generated bundle and correction register. The release process is a command checklist with hard stop conditions for ambiguous account sets or display names; on 2026-08-04 it is prepared and scheduled, not claimed as executed.

**Tech Stack:** Python `>=3.12`, `pytest`, `ruff`, stdlib `ast`, `pathlib`, `re`, `json`, `hashlib`, YAML configuration, SQLite build store, and `src/ti26/data/opendota.py::explorer_query` as the sole network seam. Run Python commands with `.venv/bin/python`; do not use `uv run`.

---

## Global constraints

- D2, D3, and D3b registrations and verdict rules remain frozen. D4 remains diagnostic-only; no documentation task may turn it into a selection gate.
- The six Swiss categories and capacities remain unchanged. No prose or release task may alter assignments to improve the D4 result.
- Empirical claims are current only when their report links to a committed run manifest and the manifest verifies report/result hashes. Authored dates, thresholds, capacities, seeds, paths, CLI syntax, and synthetic fixture values are versioned inputs, not measured claims.
- Never delete a tracked audit document in this plan. Replace its working-tree contents with an explicit supersession notice; Git preserves the historic narrative.
- Never rewrite historical Git commits. Record unbound or refuted historic commit-message claims in a correction register, with a successor producer or an explicit withdrawal.
- Every new or changed test must start with a docstring that names one concrete implementation mutation it kills. After the green focused run, apply that exact mutation locally, run the focused test and observe the intended failure, restore the implementation, then run the focused test green again. Record the two commands and observed status in the commit body or its adjacent generated verification note; never commit the mutation.
- Generated reports distinguish `optimizer marginal objective` from `evaluation-simulation mean score`. Do not use the ambiguous label `model expected`.

## File structure

| File | Responsibility |
|---|---|
| `src/ti26/numeric_provenance.py` | Parse numeric-provenance markers, check generated-report manifest references, and reject legacy unsupported claim markers in current authoritative prose. |
| `tests/test_numeric_provenance.py` | Offline regression tests for marker parsing, manifest linkage, output tampering, and banned unbound claim phrases. |
| `docs/README.md` | Defines the current-document taxonomy and the manifest marker grammar. |
| `docs/audits/2026-08-01-d1-build-ledger.md` | Nonnumeric supersession notice for the D1 ledger. |
| `docs/audits/2026-08-01-d1-differential-audit.md` | Nonnumeric supersession notice for the D1 differential audit. |
| `docs/audits/2026-08-02-d2-build-ledger.md` | Nonnumeric supersession notice for D2 empirical results. |
| `docs/audits/2026-08-02-rung3-build-report.md` | Nonnumeric supersession notice for public-rating diagnostics. |
| `docs/audits/2026-08-02-rung3-review.md` | Nonnumeric supersession notice for the rung-3 review. |
| `docs/audits/2026-08-02-rung3-source-research.md` | Nonnumeric source/provenance notice containing no derived result. |
| `docs/audits/2026-08-03-calibrated-card-report.md` | Nonnumeric supersession notice for the prior card report. |
| `docs/audits/2026-08-03-d3-calibration-report.md` | Nonnumeric supersession notice for frozen gate results. |
| `docs/audits/2026-08-04-d4-card-backtest.md` | Nonnumeric D4 diagnostic supersession notice pointing to the generated D4 bundle. |
| `docs/audits/2026-08-04-identity-and-determinism-audit.md` | Nonnumeric correction notice for historical display-name dependence. |
| `docs/audits/2026-08-04-correction-register.md` | One record per unsupported/refuted historical claim family, its status, and its canonical replacement or withdrawal. |
| `config/ti2025_backtest.yaml` | Machine-readable TI 2025 input only; comments name input provenance, not outcomes. |
| `config/ti2026_teams.yaml` | Machine-readable team identity/display-name input only; comments contain no stale roster/result assertions. |
| `src/ti26/public_ratings.py` | Descriptive public-rating diagnostics without causal attribution to noise or systematic mechanisms. |
| `src/ti26/cli_rung3.py` | Public-rating report wording limited to measured diagnostic fields and explicitly labeled hypotheses. |
| `src/ti26/cli_d3.py` | Multiple-candidate prose states the design choice without an uncomputed false-pass multiplier. |
| `src/ti26/cli_d2.py`, `src/ti26/duration.py` | Duration prose describes fields actually measured by the duration producer, without unproduced population shares. |
| `src/ti26/cli_card.py`, `src/ti26/cli_d4.py` | Generated-card and D4 terminology links every result to bundle data; approximation prose does not infer tracking from a `g(phi)` range. |
| `docs/ti26/near-lock-runbook.md` | Exact pre-lock command sequence, account-set/name stop criteria, verification, and release-report template. |
| `docs/ti26/owner-display-names.yaml` | Owner-supplied submission names as an explicit, versioned input for the release check. |
| `reports/runs/20260802T165535Z-historical/` and later release directories | Committed, generated historical and near-lock run bundles; created only after producer code and pinned inputs are committed. |

## Provenance marker grammar

Use one first-line marker in every authoritative Markdown document:

```markdown
<!-- numeric-provenance: authored-input -->
<!-- numeric-provenance: generated manifest=manifest.json -->
<!-- numeric-provenance: superseded correction=docs/audits/2026-08-04-correction-register.md -->
```

`authored-input` documents may state versioned inputs and procedure only. `generated` documents may state computed values only if their referenced manifest verifies. `superseded` documents may state document identity, the withdrawal/correction status, and canonical paths, but no empirical totals, directions, comparisons, or causal explanations. The generated report itself must contain the same manifest path and run ID emitted from its result JSON; hand-written Markdown cannot satisfy the generated marker.

### Task 1: Add a narrow numeric-provenance validator

**Files:**
- Create: `src/ti26/numeric_provenance.py`
- Create: `tests/test_numeric_provenance.py`
- Modify: `docs/README.md`

- [ ] **Step 1: Write failing manifest-link and supersession tests**

```python
# tests/test_numeric_provenance.py
from pathlib import Path

import pytest

from ti26.numeric_provenance import ProvenanceError, validate_document


def write_manifest(path: Path, report: Path) -> None:
    path.write_text(
        '{"run_id":"r1","outputs":[{"path":"report.md",'
        '"sha256":"' + __import__("hashlib").sha256(report.read_bytes()).hexdigest() + '"}]}'
    )


def test_generated_document_requires_matching_manifest_output(tmp_path: Path) -> None:
    """Kills mutation: accepting a generated marker when its manifest omits the report."""
    report = tmp_path / "report.md"
    report.write_text(
        "<!-- numeric-provenance: generated manifest=manifest.json -->\\n"
        "Run r1 computed score 4.0.\\n"
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"run_id":"r1","outputs":[]}')

    with pytest.raises(ProvenanceError, match="does not list"):
        validate_document(report)


def test_superseded_document_rejects_empirical_result_language(tmp_path: Path) -> None:
    """Kills mutation: allowing a superseded audit to retain an unbound score claim."""
    report = tmp_path / "audit.md"
    report.write_text(
        "<!-- numeric-provenance: superseded correction=corrections.md -->\\n"
        "The score was 1/16.\\n"
    )

    with pytest.raises(ProvenanceError, match="empirical"):
        validate_document(report)
```

- [ ] **Step 2: Run the two tests and observe red**

Run: `.venv/bin/python -m pytest tests/test_numeric_provenance.py -q`

Expected: FAIL during collection because `ti26.numeric_provenance` does not exist.

- [ ] **Step 3: Implement only marker parsing and manifest/report hash checks**

```python
# src/ti26/numeric_provenance.py
"""Validate the explicit provenance boundary of authoritative prose."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


class ProvenanceError(ValueError):
    """A document does not meet its declared numeric-provenance contract."""


_MARKER = re.compile(
    r"^<!-- numeric-provenance: "
    r"(?P<kind>authored-input|generated manifest=(?P<manifest>[^ >]+)|"
    r"superseded correction=(?P<correction>[^ >]+)) -->$"
)
_EMPIRICAL = re.compile(
    r"\\b(?:score|mean|median|correlation|slope|interval|pass|fail|"
    r"higher|lower|random|[0-9]+(?:\\.[0-9]+)?(?:/[0-9]+)?)\\b",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_document(path: Path) -> None:
    lines = path.read_text().splitlines()
    if not lines:
        raise ProvenanceError(f"{path} is empty")
    marker = _MARKER.fullmatch(lines[0])
    if marker is None:
        raise ProvenanceError(f"{path} lacks a numeric-provenance marker")
    kind = marker.group("kind")
    if kind.startswith("generated"):
        manifest_path = path.parent / marker.group("manifest")
        payload = json.loads(manifest_path.read_text())
        relative = path.relative_to(manifest_path.parent).as_posix()
        outputs = {entry["path"]: entry["sha256"] for entry in payload["outputs"]}
        if relative not in outputs:
            raise ProvenanceError(f"manifest does not list {relative}")
        if outputs[relative] != _sha256(path):
            raise ProvenanceError(f"manifest hash differs for {relative}")
    if kind.startswith("superseded") and _EMPIRICAL.search("\\n".join(lines[1:])):
        raise ProvenanceError(f"superseded document contains empirical result language: {path}")
```

- [ ] **Step 4: Run focused tests green**

Run: `.venv/bin/python -m pytest tests/test_numeric_provenance.py -q`

Expected: PASS.

- [ ] **Step 5: Perform and verify both declared mutations**

Run: temporarily remove the `relative not in outputs` branch; then run `.venv/bin/python -m pytest tests/test_numeric_provenance.py::test_generated_document_requires_matching_manifest_output -q`.

Expected: FAIL because no `ProvenanceError` is raised. Restore the branch.

Run: temporarily remove the `kind.startswith("superseded")` branch; then run `.venv/bin/python -m pytest tests/test_numeric_provenance.py::test_superseded_document_rejects_empirical_result_language -q`.

Expected: FAIL because no `ProvenanceError` is raised. Restore the branch and rerun both focused tests PASS.

- [ ] **Step 6: Document the marker contract and commit**

Add this exact section to `docs/README.md`:

```markdown
## Numeric provenance

Authoritative prose begins with a `numeric-provenance` marker. Generated reports must be listed,
with their SHA-256, in the referenced run manifest. Superseded audits contain no empirical results;
their correction register and generated run bundle are the current evidence.
```

Run: `.venv/bin/python -m ruff check src/ti26/numeric_provenance.py tests/test_numeric_provenance.py && .venv/bin/python -m pytest tests/test_numeric_provenance.py -q`

Expected: Ruff clean and PASS.

```bash
git add src/ti26/numeric_provenance.py tests/test_numeric_provenance.py docs/README.md
git commit -m "test: bind authoritative prose to manifest outputs" \
  -m "Verified numeric-provenance tests, including observed failures after omitting output membership and superseded-content checks, then Ruff."
```

### Task 2: Make the validator cover the authoritative current tree

**Files:**
- Modify: `src/ti26/numeric_provenance.py`
- Modify: `tests/test_numeric_provenance.py`
- Modify: `docs/README.md`

- [ ] **Step 1: Add a failing repository-scan test**

```python
# append to tests/test_numeric_provenance.py
from ti26.numeric_provenance import validate_authoritative_tree


def test_authoritative_documents_have_declared_numeric_provenance() -> None:
    """Kills mutation: skipping `docs/audits` while scanning authoritative documentation."""
    validate_authoritative_tree(Path.cwd())
```

- [ ] **Step 2: Run it and observe red**

Run: `.venv/bin/python -m pytest tests/test_numeric_provenance.py::test_authoritative_documents_have_declared_numeric_provenance -q`

Expected: FAIL naming an existing audit file without a first-line marker.

- [ ] **Step 3: Implement the exact authoritative set**

```python
# append to src/ti26/numeric_provenance.py
AUTHORITATIVE_MARKDOWN_DIRS = (Path("docs/audits"), Path("docs/ti26"))


def validate_authoritative_tree(root: Path) -> None:
    for relative_dir in AUTHORITATIVE_MARKDOWN_DIRS:
        directory = root / relative_dir
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.md")):
            validate_document(path)
```

Do not scan `docs/superpowers/`: plans and specifications are authored design records, not published empirical reports. Add that exception and its rationale verbatim to `docs/README.md`.

- [ ] **Step 4: Mark only documents that already meet the contract**

Add `<!-- numeric-provenance: authored-input -->` to any current runbook containing only procedures and versioned inputs. Do not add `generated` markers until Tasks 4–6 create manifests, and do not add `superseded` markers until Task 3 removes empirical language.

- [ ] **Step 5: Verify mutation and commit**

Run: temporarily change `AUTHORITATIVE_MARKDOWN_DIRS` to `(Path("docs/ti26"),)`; then run `.venv/bin/python -m pytest tests/test_numeric_provenance.py::test_authoritative_documents_have_declared_numeric_provenance -q`.

Expected: PASS only if an audit lacks a marker, demonstrating this mutation is a false green. Therefore add a fixture audit directory to the test before accepting this test:

```python
def test_repository_scan_includes_audits(tmp_path: Path) -> None:
    """Kills mutation: removing `docs/audits` from the authoritative scan roots."""
    audit = tmp_path / "docs/audits/audit.md"
    audit.parent.mkdir(parents=True)
    audit.write_text("unmarked\\n")
    with pytest.raises(ProvenanceError, match="lacks"):
        validate_authoritative_tree(tmp_path)
```

Run the fixture test with the mutation and observe FAIL; restore the audit root. Then run:

`.venv/bin/python -m pytest tests/test_numeric_provenance.py -q`

Expected: PASS after Task 3 completes, not before.

```bash
git add src/ti26/numeric_provenance.py tests/test_numeric_provenance.py docs/README.md
git commit -m "test: scan current authoritative prose for provenance markers" \
  -m "Verified focused scan tests and observed failure after removing the audit scan root."
```

### Task 3: Replace historical result narratives with correction-backed notices

**Files:**
- Create: `docs/audits/2026-08-04-correction-register.md`
- Modify: every audit file listed in the File structure table
- Modify: `docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md`

- [ ] **Step 1: Write a failing correction-register test**

```python
# append to tests/test_numeric_provenance.py
def test_every_superseded_audit_links_the_single_correction_register() -> None:
    """Kills mutation: leaving a superseded audit without a correction-register reference."""
    root = Path.cwd()
    register = root / "docs/audits/2026-08-04-correction-register.md"
    for audit in sorted((root / "docs/audits").glob("*.md")):
        if audit == register:
            continue
        first_line = audit.read_text().splitlines()[0]
        assert "superseded correction=docs/audits/2026-08-04-correction-register.md" in first_line
```

- [ ] **Step 2: Run it and observe red**

Run: `.venv/bin/python -m pytest tests/test_numeric_provenance.py::test_every_superseded_audit_links_the_single_correction_register -q`

Expected: FAIL on the first legacy audit.

- [ ] **Step 3: Write the correction register and notices**

Use this exact nonnumeric correction-register structure; identifiers are prose labels, not results:

```markdown
<!-- numeric-provenance: authored-input -->
# TI 2026 correction register

| claim family | status | current evidence |
|---|---|---|
| D1 duration influence and generated-card claims | withdrawn from current prose | generated historical run bundle |
| D2 forecast-value and floor claims | superseded | frozen-gate result artifact |
| D3 and D3b gate summaries | superseded | frozen-gate result artifact |
| rung-3 public-rating direction and drift explanations | narrowed | generated rung-3 diagnostic bundle |
| D4 sweep, random-control, ladder, and rank claims | superseded | generated D4 diagnostic bundle |
| display-name independence | corrected | stable-ID regression tests and generated card bundle |
| historic Git commit-message measurements | immutable historical record; not current evidence | this correction register |
```

Each listed audit begins exactly as follows, replacing its previous current-tree body:

```markdown
<!-- numeric-provenance: superseded correction=docs/audits/2026-08-04-correction-register.md -->
# Superseded audit

This document no longer publishes empirical results in the current tree. Its filename identifies
the audit it supersedes. See the correction register and the manifest-bound generated bundle
named there. The prior narrative remains available in Git history.
```

For `2026-08-04-identity-and-determinism-audit.md`, add one additional nonnumeric sentence: “The prior display-name-independence assertion was false for exact ties; the current contract is stable configured identifiers, verified by regression tests.” Do not include old result totals or percentages.

For `2026-08-04-d4-card-backtest.md`, add: “D4 is a diagnostic and cannot promote or demote the card.” Do not include its observed score, comparison values, or a causal interpretation.

Rewrite the result-bearing prose in `docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md` to retain only frozen registration text and point readers to the generated frozen-gate artifact. Preserve the original preregistration rules; remove all post-registration result values and post-hoc conclusions.

- [ ] **Step 4: Run provenance and content checks green**

Run: `.venv/bin/python -m pytest tests/test_numeric_provenance.py -q`

Expected: PASS except for generated reports that do not yet exist; authoritative audit notices all pass their superseded contract.

- [ ] **Step 5: Verify the declared mutation and commit**

Run: temporarily replace one audit’s marker with `<!-- numeric-provenance: authored-input -->`; then run `.venv/bin/python -m pytest tests/test_numeric_provenance.py::test_every_superseded_audit_links_the_single_correction_register -q`.

Expected: FAIL naming that audit. Restore the superseded marker and rerun PASS.

```bash
git add docs/audits docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md tests/test_numeric_provenance.py
git commit -m "docs: supersede unbound historical forecast claims" \
  -m "Verified all current audits link the correction register and observed the link test fail after replacing one superseded marker."
```

### Task 4: Narrow source comments and generated-report prose to computed facts

**Files:**
- Modify: `src/ti26/public_ratings.py:67,231,302,418,472-505`
- Modify: `src/ti26/cli_rung3.py:190,275,339,383-390`
- Modify: `src/ti26/cli_d3.py:1-18,69-72,182-187`
- Modify: `src/ti26/cli_d2.py:188,463,556-559`
- Modify: `src/ti26/duration.py:1-3,145-166`
- Modify: `src/ti26/cli_card.py:1-52,150-158,376-381,455-465`
- Modify: `src/ti26/cli_d4.py:140-167`
- Modify: `tests/test_public_ratings.py`, `tests/test_cli_rung3.py`, `tests/test_cli_d2.py`, `tests/test_cli_d3.py`, `tests/test_cli_card.py`, `tests/test_cli_d4.py`

- [ ] **Step 1: Add failing wording/field-origin tests**

```python
# append to tests/test_cli_card.py
def test_card_report_labels_the_two_expected_score_quantities_separately(tmp_path, monkeypatch) -> None:
    """Kills mutation: rendering both independent quantities as ambiguous `model expected`."""
    # Use the existing controlled-card fixture and invoke cli_card.main with its output directory.
    # The produced report must contain these exact labels, populated from result fields.
    report = (tmp_path / "out" / "card_provenance.md").read_text()
    assert "optimizer marginal objective" in report
    assert "evaluation-simulation mean score" in report
    assert "Model-implied expected score" not in report


# append to tests/test_public_ratings.py
def test_deviation_summary_does_not_assign_a_noise_or_systematic_cause() -> None:
    """Kills mutation: reintroducing a causal `sampling noise` explanation from sign counts."""
    text = deviation_summary([1.0, -1.0], resolvable=2, unresolved=0)
    assert "sampling noise" not in text
    assert "systematic" not in text
    assert "does not determine cause" in text
```

Use the repository’s existing fixture helpers rather than a network request. For every changed test, put the mutation statement in its docstring before its setup.

- [ ] **Step 2: Run focused wording tests and observe red**

Run: `.venv/bin/python -m pytest tests/test_cli_card.py::test_card_report_labels_the_two_expected_score_quantities_separately tests/test_public_ratings.py::test_deviation_summary_does_not_assign_a_noise_or_systematic_cause -q`

Expected: FAIL because current report language is ambiguous and current deviation prose assigns causes.

- [ ] **Step 3: Replace every uncomputed claim with exact bounded language**

Apply these replacements, keeping every existing computed field and producer intact:

```python
# src/ti26/public_ratings.py: deviation_summary branches
return "Mixed signed deviations; this diagnostic does not determine cause."
return "One-directional deviations; this diagnostic does not determine cause."

# src/ti26/cli_d3.py, report prose
"Glicko is reported as a diagnostic only. The frozen registration specifies Elo as the sole gated candidate."

# src/ti26/cli_d2.py and src/ti26/duration.py
"Duration sensitivity is reported from the configured sweep; this report does not infer its share of every ranking."

# src/ti26/cli_rung3.py
"Thin-history status is a diagnostic flag; this report does not establish an Elo bias mechanism."
"The historic drift example is not forward guidance; consult the generated diagnostic table for this run."

# src/ti26/cli_card.py
"The displayed RD and g(phi) ranges are diagnostics. They do not measure the error made by transferring per-map calibration to scalar strengths."
```

In `cli_d4.py`, rename payload/report fields exactly:

```python
"optimizer_marginal_objective": model_expected,
"evaluation_simulation_mean_score": sim_mean,
```

Update their report templates to use exactly `optimizer marginal objective` and `evaluation-simulation mean score`. Never retain aliases in generated output, because aliases preserve the ambiguity.

Remove all old numeric claims from module docstrings and comments unless they are a configuration input referenced by path. Replace “sampling noise”, “systematic”, “roughly doubles”, “roughly 30%”, “underrates thin-history rosters”, and forward-looking historic-drift claims with the bounded text above. Do not replace them with a different causal story.

- [ ] **Step 4: Run affected tests green**

Run: `.venv/bin/python -m pytest tests/test_public_ratings.py tests/test_cli_rung3.py tests/test_cli_d2.py tests/test_cli_d3.py tests/test_cli_card.py tests/test_cli_d4.py -q`

Expected: PASS.

- [ ] **Step 5: Verify mutations for each changed test**

Run: temporarily restore `"sampling noise"` in the mixed-sign branch, then run `.venv/bin/python -m pytest tests/test_public_ratings.py::test_deviation_summary_does_not_assign_a_noise_or_systematic_cause -q`.

Expected: FAIL. Restore bounded wording.

Run: temporarily render `"Model-implied expected score"` instead of `"optimizer marginal objective"`, then run `.venv/bin/python -m pytest tests/test_cli_card.py::test_card_report_labels_the_two_expected_score_quantities_separately -q`.

Expected: FAIL. Restore distinct labels.

For every additional test modified in this task, perform the mutation named in that test’s docstring and save the focused failure output path in the task verification note before commit.

- [ ] **Step 6: Confirm no targeted claim remains and commit**

Run: `.venv/bin/python -m ruff check src/ti26/public_ratings.py src/ti26/cli_rung3.py src/ti26/cli_d2.py src/ti26/duration.py src/ti26/cli_d3.py src/ti26/cli_card.py src/ti26/cli_d4.py tests/test_public_ratings.py tests/test_cli_rung3.py tests/test_cli_d2.py tests/test_cli_d3.py tests/test_cli_card.py tests/test_cli_d4.py`

Run: `rg -n 'sampling noise|systematic.*bias|roughly doubles|roughly 30%|underrates thin-history|17\.74|Model-implied expected score' src/ti26`

Expected: no source-prose matches; numeric configuration inputs can remain only in YAML.

```bash
git add src/ti26/public_ratings.py src/ti26/cli_rung3.py src/ti26/cli_d2.py src/ti26/duration.py src/ti26/cli_d3.py src/ti26/cli_card.py src/ti26/cli_d4.py tests
git commit -m "docs: narrow forecast prose to measured diagnostics" \
  -m "Verified affected CLI and rating tests; observed each changed test fail under its documented mutation; Ruff clean."
```

### Task 5: Remove outcome narratives from configuration comments and bind inputs

**Files:**
- Modify: `config/ti2025_backtest.yaml`
- Modify: `config/ti2026_teams.yaml`
- Create: `docs/ti26/owner-display-names.yaml`
- Modify: `tests/test_rules.py`, `tests/test_teams.py`

- [ ] **Step 1: Add failing input-only configuration tests**

```python
# append to tests/test_teams.py
from pathlib import Path
import yaml


def test_owner_display_name_file_contains_exact_submission_names() -> None:
    """Kills mutation: changing a TI-facing submission name while retaining the model team ID."""
    names = yaml.safe_load(Path("docs/ti26/owner-display-names.yaml").read_text())
    assert names["teams"] == [
        "Aurora", "BoomBoys", "Iron Wing", "Falcons", "Liquid", "Yandex", "Xtreme", "Spirit",
        "Team Vision", "Nigma", "Huligani", "Resilience", "Vici Gaming", "OG", "GamerLegion", "LGD Gaming",
    ]
```

- [ ] **Step 2: Run and observe red**

Run: `.venv/bin/python -m pytest tests/test_teams.py::test_owner_display_name_file_contains_exact_submission_names -q`

Expected: FAIL because the owner display-name input file is absent.

- [ ] **Step 3: Add input-only files/comments**

Create exactly:

```yaml
# docs/ti26/owner-display-names.yaml
teams:
  - Aurora
  - BoomBoys
  - Iron Wing
  - Falcons
  - Liquid
  - Yandex
  - Xtreme
  - Spirit
  - Team Vision
  - Nigma
  - Huligani
  - Resilience
  - Vici Gaming
  - OG
  - GamerLegion
  - LGD Gaming
```

Replace comments in `config/ti2025_backtest.yaml` and `config/ti2026_teams.yaml` with comments that describe only field semantics, source identifier, and alias/rebrand identity. Remove historical results, counts, causal interpretation, and current-roster assertions. Keep every parsed YAML value unchanged unless a separate, verified input correction is required; a comment cleanup must not alter D4 truth, gate registration, capacities, team IDs, or aliases.

- [ ] **Step 4: Run tests green**

Run: `.venv/bin/python -m pytest tests/test_rules.py tests/test_teams.py -q`

Expected: PASS.

- [ ] **Step 5: Verify mutation and commit**

Run: temporarily change `BoomBoys` to `BetBoom` in `docs/ti26/owner-display-names.yaml`, then run `.venv/bin/python -m pytest tests/test_teams.py::test_owner_display_name_file_contains_exact_submission_names -q`.

Expected: FAIL. Restore `BoomBoys`, rerun PASS, then run `.venv/bin/python -m ruff check tests/test_rules.py tests/test_teams.py`.

```bash
git add config/ti2025_backtest.yaml config/ti2026_teams.yaml docs/ti26/owner-display-names.yaml tests/test_rules.py tests/test_teams.py
git commit -m "docs: separate forecast inputs from historical outcomes" \
  -m "Verified YAML parsing and exact owner display names; observed the submission-name test fail after a deliberate rename."
```

### Task 6: Generate and commit the pinned historical evidence bundles

**Files:**
- Create: `reports/runs/20260802T165535Z-historical/manifest.json`
- Create: `reports/runs/20260802T165535Z-historical/frozen_gate_results.json`
- Create: `reports/runs/20260802T165535Z-historical/d4_diagnostics.json`
- Create: `reports/runs/20260802T165535Z-historical/card_result.json`
- Create: generated Markdown and CSV files beneath `reports/runs/20260802T165535Z-historical/`
- Modify: `docs/audits/2026-08-04-correction-register.md`
- Modify: `tests/test_numeric_provenance.py`

**Prerequisite:** Complete the provenance, frozen-gate, D4, stable-ID, and generated-report producer plans first. The producer commit and raw snapshot commit must exist before this task starts. Do not fabricate a historical bundle from copied report text.

- [ ] **Step 1: Add a failing bundle-verification test**

```python
# append to tests/test_numeric_provenance.py
from ti26.provenance import verify_run_manifest


def test_committed_historical_bundle_verifies_and_is_referenced_by_corrections() -> None:
    """Kills mutation: changing a generated historical report without updating its manifest hash."""
    bundle = Path("reports/runs/20260802T165535Z-historical")
    verify_run_manifest(bundle / "manifest.json")
    register = Path("docs/audits/2026-08-04-correction-register.md").read_text()
    assert bundle.as_posix() in register
```

- [ ] **Step 2: Run it and observe red**

Run: `.venv/bin/python -m pytest tests/test_numeric_provenance.py::test_committed_historical_bundle_verifies_and_is_referenced_by_corrections -q`

Expected: FAIL because no committed historical bundle exists.

- [ ] **Step 3: Rebuild the pinned store and run frozen producers**

Use the pinned snapshot ID already committed by the provenance plan and a source revision that names the producer commit. Substitute only the explicit source commit SHA; do not use `HEAD` after creating generated output.

```bash
.venv/bin/python -m ti26.cli_ingest \
  --raw data/raw \
  --snapshot 20260802T165535Z \
  --store data/processed/20260802T165535Z.sqlite
.venv/bin/python -m ti26.cli_d2 \
  --store data/processed/20260802T165535Z.sqlite \
  --gate-config config/d2_gate.yaml \
  --rules config/ti2026_rules.yaml \
  --aliases config/team_aliases.yaml \
  --teams config/ti2026_teams.yaml \
  --out reports/runs/20260802T165535Z-historical/d2
.venv/bin/python -m ti26.cli_d3 \
  --store data/processed/20260802T165535Z.sqlite \
  --gate-config config/d2_gate.yaml \
  --aliases config/team_aliases.yaml \
  --out reports/runs/20260802T165535Z-historical/d3
.venv/bin/python -m ti26.cli_d3b \
  --store data/processed/20260802T165535Z.sqlite \
  --gate-config config/d2_gate.yaml \
  --aliases config/team_aliases.yaml \
  --out reports/runs/20260802T165535Z-historical/d3b
.venv/bin/python -m ti26.cli_d4 \
  --store data/processed/20260802T165535Z.sqlite \
  --rules config/ti2026_rules.yaml \
  --truth config/ti2025_backtest.yaml \
  --aliases config/team_aliases.yaml \
  --out reports/runs/20260802T165535Z-historical/d4
.venv/bin/python -m ti26.cli_card \
  --store data/processed/20260802T165535Z.sqlite \
  --rules config/ti2026_rules.yaml \
  --teams config/ti2026_teams.yaml \
  --aliases config/team_aliases.yaml \
  --frozen-gates reports/runs/20260802T165535Z-historical/frozen_gate_results.json \
  --out reports/runs/20260802T165535Z-historical/card
```

The exact new `--manifest`, `--source-revision`, and `--frozen-gates` arguments must be supplied as defined by the provenance/gate plans; this command block is the execution order, not authorization to invent fallback literals. Combine D2/D3/D3b machine results with the registered artifact builder, then emit a single run manifest after every result/report exists.

- [ ] **Step 4: Compare rather than reconcile results**

Run: `.venv/bin/python -m ti26.provenance verify reports/runs/20260802T165535Z-historical/manifest.json`

Expected: PASS and a complete list of hashed outputs.

If a frozen result differs from the previously asserted narrative, record the mismatch in the correction register and generated report. Do not alter a threshold, seed, configuration, model, D4 status, or card assignment to match the narrative. If the stable-ID/tie correction changes an assignment, stop and obtain owner direction before publishing the historical card bundle.

- [ ] **Step 5: Make corrections point to the concrete bundle and test green**

Replace generic “generated historical run bundle” cells in the correction register with `reports/runs/20260802T165535Z-historical/manifest.json`. Add the generated marker to every generated Markdown report and leave audit notices superseded.

Run: `.venv/bin/python -m pytest tests/test_numeric_provenance.py -q`

Expected: PASS.

- [ ] **Step 6: Verify the declared mutation and commit the output-only bundle**

Run: temporarily append one newline to `reports/runs/20260802T165535Z-historical/d4/d4_card_backtest.md`, then run `.venv/bin/python -m pytest tests/test_numeric_provenance.py::test_committed_historical_bundle_verifies_and_is_referenced_by_corrections -q`.

Expected: FAIL on the manifest hash. Restore the exact generated file, rerun the test PASS, then run `.venv/bin/python -m ruff check .`.

```bash
git add reports/runs/20260802T165535Z-historical docs/audits/2026-08-04-correction-register.md tests/test_numeric_provenance.py
git commit -m "reports: publish manifest-bound historical forecast evidence" \
  -m "Verified the pinned snapshot rebuild, all frozen producers, manifest hashes, and observed tamper detection on the D4 report."
```

### Task 7: Add the near-lock runbook and schedule the release wake-up

**Files:**
- Create: `docs/ti26/near-lock-runbook.md`
- Modify: `docs/README.md`
- Test: `tests/test_numeric_provenance.py`

- [ ] **Step 1: Add a failing runbook-content test**

```python
# append to tests/test_numeric_provenance.py
def test_near_lock_runbook_has_ambiguity_stop_and_account_set_review() -> None:
    """Kills mutation: allowing a name-only roster review to proceed through an ambiguous account set."""
    text = Path("docs/ti26/near-lock-runbook.md").read_text()
    assert "account set" in text
    assert "STOP — owner decision required" in text
    assert "explorer_query" in text
```

- [ ] **Step 2: Run and observe red**

Run: `.venv/bin/python -m pytest tests/test_numeric_provenance.py::test_near_lock_runbook_has_ambiguity_stop_and_account_set_review -q`

Expected: FAIL because the near-lock runbook is absent.

- [ ] **Step 3: Write the runbook with an explicit time boundary**

Begin `docs/ti26/near-lock-runbook.md` with:

```markdown
<!-- numeric-provenance: authored-input -->
# TI 2026 near-lock regeneration runbook

This runbook was prepared on 2026-08-04. It does not claim that the near-lock regeneration has
occurred. Execute it close to the 2026-08-13 compendium deadline, after the historical bundle
and full verification are green.
```

Then include this exact ordered checklist:

```markdown
1. Create a new immutable snapshot only through `src/ti26/data/opendota.py::explorer_query` by
   running `.venv/bin/python -m ti26.cli_ingest --months 18 --raw data/raw --store data/processed/release.sqlite`.
2. Commit the new raw snapshot manifest and chunks before generating a release bundle. Rebuild the
   SQLite store from that snapshot and verify the logical store digest.
3. Run `.venv/bin/python -m ti26.teams check-roster-staleness --store data/processed/release.sqlite --teams config/ti2026_teams.yaml --aliases config/team_aliases.yaml`.
   For every hit, compare configured and resolved account sets, including account IDs, rather than
   organization/display names. Record duplicate `team_id` observations separately; do not merge a
   duplicate merely because its name matches.
4. STOP — owner decision required if an account set cannot be reconciled to one configured team,
   if a duplicate `team_id` has competing account sets, or if the source supplies insufficient
   account data. Do not select the most plausible identity.
5. Compare the release display names, in order, with `docs/ti26/owner-display-names.yaml`:
   Aurora; BoomBoys; Iron Wing; Falcons; Liquid; Yandex; Xtreme; Spirit; Team Vision; Nigma;
   Huligani; Resilience; Vici Gaming; OG; GamerLegion; LGD Gaming.
6. STOP — owner decision required if the owner list and configured identity mapping disagree. A
   display-name change is cosmetic only after the corresponding stable team ID/account set passes.
7. Run frozen gate producers exactly as registered, generate D4 diagnostics without using them to
   select a card, generate the card, write the release manifest, and verify every output hash.
8. Diff the keyed assignments and headline result fields against the prior manifest. Attribute a
   changed assignment only to fresh snapshot input or a separately documented corrected computation.
   Never attribute it to D4 performance. STOP — owner decision required if a tie-rule correction
   changes an assignment.
9. Run `.venv/bin/python -m pytest -q`, `.venv/bin/python -m ruff check .`, and manifest verify.
   Commit the bundle and generated closing report only after all three succeed.
```

Record the generated immutable snapshot ID printed by `cli_ingest` in the release manifest; never hand-write a date. Include a release-report renderer with headings “Snapshot and manifest”, “Account-set review”, “Display-name review”, “Assignment diff and cause”, “Verification”, “Unverified”, and “Claim boundary”.

- [ ] **Step 4: Schedule a persistent wake-up without faking execution**

In the Codex desktop application, use its automation facility (not a shell cron job) to create a one-time wake-up for **2026-08-12 09:00 Europe/Vienna** with this message:

```text
Execute docs/ti26/near-lock-runbook.md for the TI 2026 compendium lock. Today’s run must use a fresh explorer_query snapshot, account-set review, exact owner display-name list, manifest verification, full pytest, and Ruff. Stop for any identity/name/tie-assignment ambiguity.
```

Record only the automation identifier and scheduled time in the task’s operator note; do not put it in a generated forecast report and do not state the run completed. If the automation facility is unavailable, report the unverified scheduling failure and request an owner-created reminder; do not substitute a background shell process.

- [ ] **Step 5: Run, mutate, restore, and commit**

Run: `.venv/bin/python -m pytest tests/test_numeric_provenance.py::test_near_lock_runbook_has_ambiguity_stop_and_account_set_review -q`

Expected: PASS.

Run: temporarily replace `account set` with `team name` in the runbook, then rerun the focused test.

Expected: FAIL. Restore exact account-set wording, rerun PASS, then run `.venv/bin/python -m ruff check tests/test_numeric_provenance.py`.

```bash
git add docs/ti26/near-lock-runbook.md docs/README.md tests/test_numeric_provenance.py
git commit -m "docs: prepare accountable TI 2026 near-lock release" \
  -m "Verified the runbook test and observed it fail after replacing account-set review with name-only review; scheduling is recorded separately and is not a completed release."
```

### Task 8: Independent reviews and final historical-tree verification

**Files:**
- Modify only files identified by review findings; do not edit generated bundles manually.
- Create: `reports/runs/20260802T165535Z-historical/verification.json` only if the manifest producer already supports it.

- [ ] **Step 1: Request a fresh specification review**

Give a fresh reviewer only the implementation requirements, current diff, generated manifest paths, and these acceptance checks:

```text
Return PASS, FAIL, or UNKNOWN for: frozen gates unchanged; D4 diagnostic-only; all former D4 sweep/random/ladder/rank claims have producers or are absent; card report reads versioned gate artifact; source comments make no unsupported causal/quantitative claim; every authoritative document has a valid marker; all generated reports verify; historical audits retain no empirical result; owner names input is exact; runbook stops on ambiguous account sets/names/tie assignment.
```

The reviewer must cite file paths and evidence, and must not approve based solely on a passing test command.

- [ ] **Step 2: Correct concrete review findings test-first**

For each finding, add a focused regression test with a docstring naming the exact mutation. Run it red, implement the narrow correction, run it green, apply the named mutation and observe failure, restore, then rerun green. Commit each logically independent correction separately.

- [ ] **Step 3: Request a fresh code-quality review**

Give a second fresh reviewer the changed files and test/mutation evidence. Require severity-ranked findings with file/line citations for: manifest validation bypasses, generated/manual report confusion, unsafe YAML/JSON handling, source-prose overclaims, tests that merely parse their own report, and test mutations not actually killed.

- [ ] **Step 4: Address quality findings and run final verification**

Run these commands on the exact final historical tree, after the most recent code/doc edit:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m ti26.provenance verify reports/runs/20260802T165535Z-historical/manifest.json
.venv/bin/python -m pytest tests/test_numeric_provenance.py -q
```

Expected: every command exits zero. If any command fails, report the failure, retain the failing output, and do not claim the historical tree or card is verified.

- [ ] **Step 5: Commit only verification-derived material**

Commit every review correction in the task that introduced its test. If the manifest producer emits `reports/runs/20260802T165535Z-historical/verification.json`, stage that exact file with the final correction and use this commit message:

```bash
git commit -m "test: verify reproducible historical forecast tree" \
  -m "Verified full pytest, Ruff, historical-manifest verification, provenance tests, and two independent reviews after the final change."
```

Do not create `verification.json` by hand. If the producer cannot emit it, omit that file and state verification in the commit message only.

### Task 9: Execute the near-lock release only when the scheduled date arrives

**Files:**
- Create: a new generated directory beneath `reports/runs/` named by the manifest run identifier
- Create: `docs/audits/2026-08-13-ti2026-lock-report.md`
- Modify: `docs/audits/2026-08-04-correction-register.md`

**Time gate:** Today is **2026-08-04**. This task is intentionally not executable today and cannot be marked complete until a run close to the 2026-08-13 deadline has occurred. The wake-up in Task 7 is the only authorized persistence mechanism.

- [ ] **Step 1: On wake-up, record the actual date and start the runbook**

Run: `date -u +%Y-%m-%dT%H:%M:%SZ`

Expected: a timestamp close enough to the deadline to satisfy the owner’s release timing. If it is not near lock, stop and keep the task pending; do not regenerate merely to claim completion.

- [ ] **Step 2: Execute all runbook commands and hard stops**

Follow `docs/ti26/near-lock-runbook.md` verbatim. Network access occurs only through `explorer_query` invoked by `cli_ingest`. Tests remain offline. For each staleness hit, save the configured and resolved sorted account IDs in the generated release result; names alone are insufficient evidence. If an ambiguity is encountered, stop and ask the owner with the conflicting account sets and source rows.

- [ ] **Step 3: Generate the closing report from release result JSON**

`docs/audits/2026-08-13-ti2026-lock-report.md` begins with the generated marker pointing to the near-lock manifest. Its producer renders, rather than hand-types, the following required material from the release result JSON:

```markdown
# TI 2026 lock report

## Final assignments

| stable team ID | owner display name | category |
|---|---|---|
One row per `card_result.json["assignments"]` item, in stable-team-ID order.

## Manifest identifiers

The manifest run ID, producer source revision, snapshot ID, raw digest, logical-store digest, and all configuration digests.

## Diff from prior card

The stable-team-ID keyed category diff, both distinctly named expected-score quantities where present, and the machine-recorded cause.

## Verification

The pytest, Ruff, and manifest-verification statuses from verification data.

## Unverified

Every unavailable evidence item from `release_result.json["unverified"]`, or `None` only when that list is empty.

## Claim boundary

A fixed generated statement: this is a deterministic manifest-bound pipeline output; broad forecast-value gates did not establish predictive value; D3b is a weak one-condition result; D4 does not select the card.
```

The report’s cause field may contain only `fresh_snapshot_input`, a `corrected_computation:` value with the registered issue identifier, or `no_assignment_change`. It must reject an unrecognized cause and must reject `d4_result`.

- [ ] **Step 4: Verify, review, and commit the near-lock bundle**

Run the three final commands from Task 8 against the near-lock manifest. Have a fresh reviewer check that every displayed assignment maps to the generated JSON by stable team ID and that any change has one permitted cause. Resolve review findings test-first; do not manually patch generated reports.

Commit only when all verification is green:

```bash
git add data/raw/ reports/runs/ docs/audits/2026-08-13-ti2026-lock-report.md docs/audits/2026-08-04-correction-register.md
git commit -m "reports: regenerate TI 2026 card near compendium lock" \
  -m "Verified fresh explorer_query snapshot, account-set and owner-name review, manifest hashes, full pytest, Ruff, and generated assignment diff."
```

No push, PR, merge, force-push, history rewrite, branch deletion, or file deletion is authorized by this plan. Ask the owner before any of those actions.

## Self-review

- [x] Every listed source overclaim is covered by Task 4: public-rating causal language, thin-history mechanism, historical drift forward guidance, D3 false-pass multiplier, D2/duration ranking share, and `g(phi)` approximation inference.
- [x] Task 3 removes current-tree unproduced D4 sweep, random-control, naive-ladder, rank-correlation, and identity claims while Task 6 restores them only through generated producers and manifests.
- [x] Task 5 preserves configuration values and records the owner’s exact display-name list as versioned input.
- [x] Tasks 1–2 make document/result/manifest linkage testable; Task 6 tests output tampering.
- [x] Every test snippet includes a named mutation, and each task includes an explicit mutate/fail/restore step. The repository-scan test includes a fixture so its own scan-root mutation is actually killed.
- [x] Task 8 requires independent specification and quality review plus final `pytest`, Ruff, and manifest verification after the final edit.
- [x] Task 9 states plainly that 2026-08-04 is too early to claim near-lock regeneration and uses a scheduled wake-up instead of inventing a release.
- [x] Interface names are consistent: `validate_document`, `validate_authoritative_tree`, `verify_run_manifest`, generated `manifest.json`, and the two expected-score labels are used consistently throughout.
