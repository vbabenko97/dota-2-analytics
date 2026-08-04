# Stable Team Identity and Tie Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Implement one task at a time with test-first RED, named mutation failure, GREEN, review, and commit.

**Goal:** Make exact-strength and exact-marginal ties deterministic by stable team ID, while keeping display names cosmetic and describing the existing `tie_tolerance` magnitude honestly.

**Architecture:** Team-facing mappings remain keyed by display name for report compatibility, but every simulation and solver ordering receives an aligned, unique stable-ID mapping. Production CLIs derive those IDs from the versioned team configuration and generic CSV input must carry a `team_id` column. Synthetic/internal callers may omit the mapping only when their keys already are stable identifiers. `tie_tolerance` keeps its existing numeric value and becomes a documented worst-case single-marginal Monte Carlo magnitude heuristic; it is not called a covariance-aware standard error for assignment-total differences.

**Verification:** Exact-tie tests survive display-name renames and input-row reorder; tests fail under explicit name-fallback and zero-tolerance mutations; production card assignments match the pre-change pinned invocation; affected tests and Ruff pass. If the pinned assignments change, stop before committing and ask the owner as required.

---

### Task 1: Give Monte Carlo ordering an explicit stable identity

**Files:**
- Modify: `src/ti26/montecarlo.py`
- Modify: `tests/test_montecarlo.py`

- [ ] Add an exact-strength-tie test that runs the same stable IDs under two display-name mappings and reversed insertion order. Assert identical stable-ID marginals after translating display names back to IDs. Its docstring must name this mutation: “sort tied strengths by display name instead of stable team ID.”
- [ ] Run the focused test and observe RED because the current name fallback changes RNG ordering.
- [ ] Add `team_ids: Mapping[str, str] | None = None` to `canonical_labels`, `simulate_marginals`, and `simulate_card_score`. Validate exact key alignment and unique, non-empty IDs. If omitted, treat mapping keys as stable caller identities. Sort strength ties by stable ID, never display name.
- [ ] Run the test GREEN. Temporarily restore the name fallback and observe the named test fail; restore stable-ID ordering.
- [ ] Run `tests/test_montecarlo.py` and Ruff. Commit as `fix: order simulations by stable team identity`, with the focused mutation failure and verification commands in the body.

### Task 2: Give solver tie-breaking the same identity

**Files:**
- Modify: `src/ti26/optimize.py`
- Modify: `tests/test_optimize.py`

- [ ] Add a fixture whose marginal rows are exactly equal for at least two teams. Rename those display names and reverse row insertion while retaining stable IDs; assert the ID-to-category assignment is identical. Its docstring must name this mutation: “use display name as the final `solve_card` row-order key.”
- [ ] Observe RED with current solver ordering.
- [ ] Add the aligned optional `team_ids` argument to `solve_card`, reuse the same validation semantics, and use stable ID as the final order key. Keep all capacities and objective logic unchanged.
- [ ] Observe GREEN, then restore name ordering temporarily and confirm the focused test fails.
- [ ] Run `tests/test_optimize.py` and Ruff. Commit as `fix: break solver ties by stable team identity` with mutation evidence.

### Task 3: Wire stable IDs through every card-producing path

**Files:**
- Modify: `src/ti26/cli.py`
- Modify: `src/ti26/cli_card.py`
- Modify: `src/ti26/cli_d2.py`
- Modify: `src/ti26/cli_d4.py`
- Modify: `src/ti26/cli_rung3.py`
- Modify other direct simulation/solver call sites found by `rg -n 'simulate_marginals|simulate_card_score|solve_card|canonical_labels' src tests`
- Modify affected CLI tests

- [ ] Change generic strengths CSV input to require `team,team_id,strength`; reject missing, blank, duplicate, or misaligned IDs. Add a CLI test whose docstring names the mutation “silently substitute display names when `team_id` is absent,” and observe RED before implementation.
- [ ] Production paths construct `{display_name: configured_team_id}` from the versioned team config and pass it to simulation and solver calls. Test one production-style rename fixture; its docstring names the mutation “drop `team_ids` at the CLI-to-simulator boundary.”
- [ ] Keep displayed assignments keyed by the owner-facing names; include the stable ID alongside the display name in machine-readable outputs where one already exists.
- [ ] Run affected CLI tests and Ruff. Perform each named temporary mutation and record the focused failing node ID before restoring.

Before committing, run the pinned historical card command once on the pre-change commit (or preserve its machine output before editing) and once on the candidate tree with identical snapshot/config/seed/simulation inputs. Compare category assignments by configured team ID. If any assignment differs, stop and ask the owner; do not commit. If identical, commit as `fix: carry stable team ids through card generation`, citing the comparison and tests.

### Task 4: Relabel the tolerance without changing its numeric behavior

**Files:**
- Modify: `src/ti26/cli.py`
- Modify: `src/ti26/optimize.py`
- Modify relevant tests and generated-report wording

- [ ] Add a test that controls `n_sims`, captures the tolerance passed to `solve_card`, and asserts it remains `monte_carlo_stderr(0.5, n_sims)`. Its docstring names the mutation “pass zero instead of the configured magnitude heuristic.” Observe it fail under that temporary mutation.
- [ ] Rename local variables/report fields to `tie_magnitude_heuristic` where externally visible compatibility permits. Document it as the worst-case standard error of one Bernoulli marginal at the configured simulation count. State explicitly that it is not the standard error of a difference between correlated 16-team assignment totals and does not estimate that covariance.
- [ ] Do not derive a new covariance-aware value in this change. This preserves the published assignment unless another corrected computation independently changes it.
- [ ] Run affected tests and Ruff, prove the zero mutation fails, and commit as `docs: define card tie magnitude heuristic`.

### Task 5: Remove the name-independence overclaim

**Files:**
- Modify all tracked docs/comments located by `rg -n -i 'display name|name.independent|rename|tie.tolerance|standard error' src tests docs config`
- Modify numeric/provenance checks owned by the documentation plan if needed

- [ ] Replace unconditional “independent of names” prose with the computed contract: display names do not affect ordering when a unique stable ID mapping is supplied; invalid/missing production IDs fail closed.
- [ ] Ensure no prose describes the magnitude heuristic as an assignment-total SE.
- [ ] Add or extend a narrow source-text regression test. Its docstring names the mutation “restore the assignment-total standard-error claim,” then observe the test fail under that temporary text mutation.
- [ ] Run the regression test, affected tests, Ruff, and `git diff --check`; commit with mutation evidence.

## Self-review

- Frozen gates, D4 diagnostic status, six categories, and capacities are unchanged.
- Stable IDs affect only previously unspecified exact ties; display names remain report labels.
- The required stop condition protects published assignments before the identity wiring commit.
- Every new or changed test receives a mutation-specific docstring and is observed failing under that mutation.
- Commands use `.venv/bin/python`; tests remain offline.
