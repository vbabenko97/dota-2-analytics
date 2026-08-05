# Superseded: D4, the TI 2025 card backtest

**D4 is a diagnostic. It cannot promote or demote the card, and never could** --
that was registered in `9ceb28e`, before `observed.py` or `cli_d4.py` existed and
before any score was computed. Nothing here changes that.

This document no longer publishes results in the current tree. Four of the values
it carried -- the simulation-count sweep, the random-card control, the naive
strength-ladder comparator, and the rank-correlation and displacement statistics
-- had no producer anywhere in the repository. They were computed in throwaway
inline commands. An external audit independently recomputed them and got the same
numbers, which is exactly the problem: true and unbound to code means the next run
cannot check them.

All four now have committed, seeded producers in `src/ti26/cli_d4.py`, and every
D4 value is emitted into `d4/d4_card_backtest.json` inside the generated run
bundle under `reports/runs/`, hash-bound by that bundle's manifest. The Markdown
and CSV in the bundle are rendered from that JSON, so no report line restates a
number the payload does not carry.

See [the correction register](2026-08-04-correction-register.md) for what happened
to each claim family, and the bundle's own `d4/d4_card_backtest.md` for the
current results. The prior narrative remains in Git history.
