# Superseded: D2 build ledger

This document no longer publishes results in the current tree. Its gate metrics,
model comparisons and duration diagnostics had no committed producer and no
manifest binding them to the store they were measured on.

D2's registered computation is unchanged. It now serialises the result object it
already computed into `d2/d2_gate.json` inside the generated run bundle under
`reports/runs/`, and its human report into `d2/d2_gate.md`, both hash-bound by
that bundle's manifest.

The ledger's central finding is not softened by being regenerated: the
forecast-value gate failed, and no rating model beat the constant floor. Those
verdicts are in the artifact, with the numbers behind them.

One claim was withdrawn rather than regenerated: that the duration parameter is
consulted on a given share of every ranking. The sensitivity sweep measures how
far a category probability moves when the parameter varies. It does not measure a
share of a ranking, and nothing else did either.

See [the correction register](2026-08-04-correction-register.md). The prior
narrative remains in Git history.
