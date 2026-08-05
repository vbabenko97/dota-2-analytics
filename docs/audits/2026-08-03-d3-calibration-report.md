# Superseded: D3 and D3b calibration gate report

This document no longer publishes results in the current tree. Its gate metrics
had no committed producer and no manifest binding them to the store they were
measured on.

Both gates' registered computations are unchanged. They now serialise the result
objects they already computed into `d3/d3_gate.json` and `d3b/d3b_gate.json`
inside the generated run bundle under `reports/runs/`, combined into
`frozen_gate_results.json` and hash-bound by that bundle's manifest. The card
report reads that artifact instead of restating the numbers.

D3b remains what it was registered as: a one-condition test, weaker than a fresh
three-condition pass, because margin and slope were already measured and already
passing when it ran and only the bootstrap interval was open. That framing is
recorded in the artifact's `open_for_test` flags, so it travels with the numbers
instead of depending on prose.

See [the correction register](2026-08-04-correction-register.md). The prior
narrative remains in Git history.
