# Reproduce the retrospective

Run commands from the repository root in a full-history checkout. Setup may download dependencies; analysis uses committed inputs offline.

```bash
uv sync --locked --python 3.13
```

Use `.venv/bin/python` directly. The lock selects dependencies; it does not pin the interpreter build, operating system, or numerical libraries outside Python wheels. Platform-dependent numeric differences must be investigated rather than normalized away.

## Artifact index

The machine-readable manifests are authoritative for exact source revisions, hashes, invocation arguments, and randomness. This index links those fields instead of duplicating them.

| Artifact | Source and inputs | Command / randomness | Output and comparison |
|---|---|---|---|
| [Historical bundles](../reports/runs/) | Each `manifest.json`: `source_revision`, `inputs`, snapshot/store fields | `invocation.producers` and seed/simulation fields | Paths/hashes in `outputs`; historical integrity verification below |
| [Oracle baseline](../reports/runs/frozen-output-oracle-baseline/61c63f4aa32c573cdbc7e4abe48e08308801f1ff3cb8e5629a4ae446d5d22b6b/manifest.json) | Recorded source revision, snapshot, configs, logical store | Frozen predictive arguments in manifest; oracle reuses them | Frozen gate decisions and roster-keyed assignments, with candidate integrity checks |
| [Corrected group forecast](../reports/card_ti2026_rules/card_provenance.md) | Frozen [card](../reports/card_ti2026_rules/recommended_card.json), strengths/marginals beside it; source/input attestation in group replay manifest | Original card metadata contains simulation settings; retained forecast is an input to retrospective evaluation | Frozen card and marginals, not a newly promoted forecast |
| [Group postmortem manifest](../reports/postmortems/group-replay.manifest.json) | `producer_source_revision`, source file hashes, frozen forecast, rules, truth, lock | `invocation` records evaluation seed; simulation count comes from frozen card | [Report](../reports/card_postmortem.md); exact byte equality |
| [Playoff postmortem manifest](../reports/postmortems/playoff-replay.manifest.json) | Recorded source, snapshot, configs, [cards](../data/ti2026_playoff_cards.yaml), truth, external texts, lock, logical store digest | `invocation`; exact bracket enumeration, no sampling seed | [Report](../reports/playoff_postmortem.md); equality after one printed store-path replacement |

Postmortem manifests are **retrospective replay attestations**, not evidence of the original generating revision. Producer source hashes are checked against the recorded Git commit and current files; new replay tooling has separate hashes. Historical forecast manifests remain unchanged and do not gain lock provenance retroactively.

## Bounded historical integrity check

```bash
.venv/bin/python -m ti26.cli_provenance verify-run \
  --bundle reports/runs/frozen-output-oracle-baseline/61c63f4aa32c573cdbc7e4abe48e08308801f1ff3cb8e5629a4ae446d5d22b6b \
  --repo-root . --at-source-revision
```

Repeat with each historical bundle directory containing a manifest. List them with `git ls-files -- 'reports/runs/**/manifest.json'`; the workflow enumerates the same set. Success is exit status 0; the command prints the verified manifest as JSON. This checks declared Git input blobs and current output hashes, not actual past execution or undeclared runtime dependencies. Use live-tree verification only for a bundle intended to describe the current checkout.

## Input reconstruction

Choose a store path that does not exist; ingestion is not an overwrite-safety wrapper.

```bash
.venv/bin/python -m ti26.cli_ingest \
  --raw data/raw --snapshot 20260816T115509Z \
  --store /private/tmp/ti26-input-reconstruction.sqlite
.venv/bin/python -m ti26.cli_provenance store-digest \
  --store /private/tmp/ti26-input-reconstruction.sqlite
```

Ingest validates raw chunks against the snapshot manifest. Compare the complete logical digest with `expected_store` in the playoff replay manifest, not SQLite file bytes. The automated replay below performs this comparison before evaluating anything.

## Group and playoff replay

Choose a new absent path. The wrapper refuses existing stores and symlinks.

```bash
.venv/bin/python -m ti26.cli_replay_postmortems \
  --snapshot 20260816T115509Z \
  --store /private/tmp/ti26-postmortem-replay.sqlite
```

The wrapper verifies manifest-bound inputs, reconstructs the store, checks its logical digest, and renders both reports. Group output must match exactly. Playoff output may differ only in the single printed database path, replaced with the recorded historical path before comparison. Any other difference fails. The rebuilt store is retained; frozen reports are never overwritten. The command prints nothing until it finishes; expect several minutes. It fails before rendering if any replay-bound file (producer source, replay tooling or input listed in the manifests) differs from its recorded bytes.

The JSON receipt reports comparison results and the store digest. A successful report comparison does not establish predictive skill. Both diagnostics share a tournament; group results inform playoff strengths.

## Optional full forecast replay

This expensive check needs a clean committed checkout and a new external replay directory. No runtime bound is promised.

```bash
git rev-parse HEAD | xargs .venv/bin/python -m ti26.frozen_output_oracle \
  --replay-root /private/tmp/ti26-frozen-output-oracle-replay \
  --repo-root . --source-revision
```

The oracle uses the baseline snapshot and predictive arguments, verifies the temporary candidate, and compares frozen outputs. It removes its isolated replay root on success and preserves it on failure. It does not publish a registered bundle or registry entry. Release producers rebuild ignored processed stores.

Historical gate failure is expected evidence; do not change thresholds or retry with different parameters. Diagnostics do not become shipping gates.

## Verification and limits

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

The full suite includes slow tests. CI installs the lock before isolating each verification command from networking. Local tests also deny Python socket connections and transmissions. [Release checks](release-checklist.md) distinguish local evidence, hosted CI, optional expensive replay, and publication authorization.
