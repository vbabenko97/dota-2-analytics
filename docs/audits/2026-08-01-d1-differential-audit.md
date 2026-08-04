# Superseded: D1 differential audit

This document no longer publishes results in the current tree. It recorded an
independent reference implementation written from the rules spec and compared
against `src/ti26`, along with the discrepancy counts that comparison produced.

The method was sound and the exercise was worth doing. The counts are not
regenerable: the reference implementation lived in a scratch directory outside the
repository and was never committed, so nothing here reproduces them. They are
withdrawn rather than restated.

What survives is in the test suite, which encodes the rules invariants the audit
checked.

See [the correction register](2026-08-04-correction-register.md). The prior
narrative remains in Git history.
