# TI 2026 reproducible forecast design

## Purpose

Make the published TI 2026 prediction card reproducible from repository-owned inputs,
without changing any frozen gate, the Swiss category structure, or D4's diagnostic status.
Then use the same path for the near-lock regeneration.

The existing numerical card and gate statements are migration inputs, not verified facts.
They become publishable only after a committed producer reproduces them from a manifest-bound
snapshot. A value that cannot be reproduced is removed from current documentation.

## Non-negotiable behavior

- Keep the six card categories and their configured capacities unchanged.
- Keep D2, D3, and D3b registrations and verdict rules unchanged.
- Keep D4 diagnostic-only. Its output cannot promote or demote a card.
- Do not select a shipping card because it improves the TI 2025 diagnostic.
- Use only `explorer_query` for network ingestion. Tests remain offline.
- Stop for owner input if a roster account set or TI-facing name is ambiguous, or if a change
  to the tie rule changes the published assignments.

## Reproducibility boundary

The reproducibility claim covers the resulting tracked tree and all new commits. Existing Git
history remains immutable; a correction note will identify historical claims that were
unsupported or later refuted.

Authored identifiers, dates, seeds, capacities, thresholds, and synthetic test fixtures are
versioned inputs. Empirical results and quantities derived from them require a producer and a
run manifest.

## Repository-owned inputs

The compressed OpenDota snapshot used by the published run will be committed under its existing
snapshot identifier. Its snapshot manifest will record the query definition, source endpoint,
retrieval window, row count, and a SHA-256 digest for every chunk. Snapshot reload will validate
the manifest before loading any row.

The processed SQLite store is a build product. Run manifests bind both the raw snapshot digest
and a logical store digest computed from schema plus deterministically ordered rows. A raw
snapshot must rebuild to the recorded logical digest; byte-identical SQLite files are not the
portability contract.

Configuration files are inputs. Every invoked configuration file and the dependency lock file
will be hashed into the run manifest.

## Run bundles

Each published execution creates a tracked bundle containing:

- a canonical JSON manifest;
- machine-readable result files;
- human-readable reports generated from those result files;
- any diagnostic tables needed to reproduce prose claims.

The manifest records:

- schema version and run kind;
- deterministic run identifier;
- source revision containing the producer;
- exact command, arguments, seeds, and simulation counts;
- input paths and SHA-256 digests;
- raw-snapshot and logical-store digests;
- configuration and dependency-lock digests;
- relevant runtime versions;
- every generated output path and SHA-256 digest.

The run identifier is derived from the canonical invocation and input metadata before outputs
are written. Reports reference the manifest path and run identifier. The manifest then hashes
the reports, avoiding a manifest/report hash cycle.

A published run uses two commits: first the code, configuration, and pinned input; then the
generated run bundle. The bundle's `source_revision` points to the first commit.

Manifest verification fails closed on a missing file, changed digest, unexpected snapshot
chunk, malformed manifest, or result/report disagreement.

## Frozen gate results

D2, D3, and D3b are rerun once against the pinned historical snapshot with their registered
configuration and seeds. Their machine-readable results form a versioned frozen-gate artifact.
The production-card report reads that artifact instead of embedding copied metrics.

The rerun is a provenance migration, not a new registration or a search for a better outcome.
Any mismatch with the historical record is reported and investigated. The registered verdict
logic is not changed to reconcile it.

## D4 diagnostic producer

The D4 command will emit all published diagnostics from the same pinned backtest input:

- the registered card backtest and per-slot table;
- the configured simulation-count and seed sweep;
- the seeded random-card control;
- the naive strength-ladder comparator;
- rank-correlation and displacement statistics;
- the full-store production calibration comparator recomputed from data.

No diagnostic value is copied into source or prose. D4's report states explicitly that it is a
diagnostic and cannot alter gate verdicts or card selection.

## Solver determinism and tie tolerance

Production simulations and optimization use stable configured team identifiers as identity
keys. Display names are presentation only. Renaming a team or reordering input rows must leave
the keyed simulation streams, marginals, and assignments unchanged, including exact strength
and exact marginal ties. Generic callers without configured identifiers use explicit stable
keys supplied by the caller; input order is not silently converted into identity.

The existing numeric tie tolerance remains unchanged unless evidence shows that doing so changes
the published assignments. Documentation will call it a worst-case single-marginal magnitude
heuristic. It is not labeled as the standard error of an assignment difference or of the total
objective, because the current simulation does not estimate either correlated quantity.

## Test evidence

New behavior is developed test-first. Every added or changed test has a docstring naming a
specific implementation mutation it rejects. For each such test, the mutation is applied
temporarily, the focused test is observed failing for the intended reason, and the mutation is
restored before commit.

Required coverage includes:

- snapshot digest validation and manifest verification;
- report/result/manifest binding and tamper detection;
- display-name rename, row reorder, exact-strength tie, and exact-marginal tie invariance;
- D4 end-to-end execution against a temporary store with pre-cutoff, exact-cutoff, and
  post-cutoff rows, proving the strict cutoff reaches calibration and roster resolution;
- D3b report fields and exit status derived from controlled gate values;
- public-rating sensitivity with a known non-zero delta and both resolvability outcomes;
- generated D4 diagnostics and frozen-gate artifact consumption.

Verification for each commit is its focused tests, affected tests, and Ruff. Release verification
is the unfiltered full test suite and Ruff on the final tree.

## Documentation migration

Current reports contain only values loaded from or computed into their run bundle. Source
docstrings and comments describe algorithms and authored choices, not observations from an old
run. Unsupported causal language is either replaced by a measured diagnostic or narrowed to an
explicit hypothesis or historical observation.

Long historical build ledgers remain available in Git history but their current-tree versions
become concise supersession notices pointing to canonical run bundles and correction records.
This preserves auditability without presenting self-attested historical totals as current
evidence.

The two distinct card quantities receive distinct names:

- `optimizer marginal objective` for the sum optimized from estimated category marginals;
- `evaluation-simulation mean score` for the independent simulation estimate of exact matches.

## Near-lock release flow

The near-lock task runs the following fixed sequence:

1. ingest a fresh snapshot through `explorer_query`;
2. rebuild and validate the logical store;
3. run roster-staleness detection and review every hit by account set;
4. compare display names with the owner's authoritative submission list;
5. regenerate frozen-model inputs, the card, diagnostics, and run manifest;
6. compare assignments and headline card fields with the prior pinned run;
7. run the full verification suite and Ruff;
8. commit the final bundle and closing report.

The release report explains any assignment change only through fresh data or a corrected
computation. If account-set or name evidence is ambiguous, the release pauses for owner input.

## Honest claim boundary

The final card may be described as a deterministic, manifest-bound output of the selected
calibrated-Glicko pipeline on the pinned snapshot. The documentation must also state that the
forecast-value gates did not establish broad predictive value, the calibrated-Glicko gate is a
weak one-condition result, and the held-out TI 2025 card diagnostic underperformed its random
assignment reference. No stronger accuracy claim follows from reproducibility.
