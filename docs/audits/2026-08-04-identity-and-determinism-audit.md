# Corrected: identity and determinism audit

This document no longer publishes results in the current tree, and one of its
central claims was false.

**The card was not independent of display names.** It was independent of them
wherever strengths differed, which is why the rename tests of the time passed. At
an exact tie the display name was still the ordering key -- in `canonical_labels`
for the simulation streams, and in `solve_card` for byte-identical marginal rows.
The prior claim that tied teams are interchangeable and that the choice cannot
matter was reasoning, not measurement: equal strength does not mean equal
simulation stream, so swapping two tied teams' labels swaps their results. An
external auditor executed exactly that and watched marginal rows and an assigned
slot move.

The current contract is that ordering falls back to the configured team id, and
display names never reach an ordering decision. It is covered by exact-tie
regression tests in `tests/test_montecarlo.py` and `tests/test_optimize.py`, each
observed failing when the name-based fallback is restored.

The shipping card did not change as a result. Running the production command
before and after the fix produced identical assignments for all 16 teams, because
float Glicko strengths do not tie exactly.

The before/after counts the prior document quoted for this defect have no retained
input/output pair and are not reproducible. They are withdrawn, not restated.

The owner-facing identity mapping this audit established is preserved as a
versioned input in `docs/ti26/owner-display-names.yaml`, and the account-set
procedure it used is now the recorded pre-lock check in
`docs/ti26/near-lock-runbook.md`.

See [the correction register](2026-08-04-correction-register.md). The prior
narrative remains in Git history.
