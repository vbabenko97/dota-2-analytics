# TI 2026 near-lock regeneration runbook

Written 2026-08-04. **This document does not claim the near-lock regeneration has
happened.** Run it close to the 2026-08-13 compendium deadline, not before:
rosters and public ratings keep moving until then, and regenerating early means
regenerating twice.

Everything below is a command plus a stop condition. The stop conditions are the
point of the document. If one fires, stop and ask the owner; do not pick the most
plausible reading.

---

## 1. Fetch a fresh snapshot

```
.venv/bin/python -m ti26.cli_ingest --months 18 --raw data/raw --store data/processed/release.sqlite
```

This is the only command here that touches the network, through
`src/ti26/data/opendota.py::explorer_query`. It prints a new snapshot id of the
form `YYYYMMDDTHHMMSSZ`. Record what it printed; never hand-write one.

Commit the new `data/raw/<snapshot-id>/` directory -- chunks and manifest --
before generating anything from it. A run bundle whose input is not committed
cannot be reproduced by anyone else, which is the whole point of the exercise.

## 2. Rebuild and verify the store

```
.venv/bin/python -m ti26.cli_provenance store-digest --store data/processed/release.sqlite
```

`cli_ingest` validates every chunk's SHA-256 against the manifest before loading a
single row, so a corrupted or edited chunk fails here rather than silently
changing a forecast.

## 3. Roster staleness, confirmed by account set

```
.venv/bin/python -m ti26.cli_d2 --store data/processed/release.sqlite --skip-card --out /tmp/staleness
```

`cli_d2` runs `teams.check_roster_staleness` and prints a warning naming every
configured team whose accounts now appear under a different `team_id`. Five such
migrations were already present on the pinned snapshot, four of which appeared in
a single burst on 2026-07-31, so expect more rather than fewer.

For each hit, compare the CONFIGURED and RESOLVED account sets — the five account
ids a roster actually fielded. Do not compare organisation names. The local store
holds no team names at all, so a name-based check is not evidence of anything.

**STOP — owner decision required** if any of these is true:

- an account set cannot be reconciled to exactly one configured team;
- a duplicate `team_id` has competing account sets rather than an identical one;
- the source supplies too few accounts to decide;
- a roster changed players, rather than the organisation changing `team_id`. That
  is a real roster change, not a duplicate, and merging it would erase history the
  model should see.

## 4. Display names against the owner's list

Compare the resolved display names with `docs/ti26/owner-display-names.yaml`.
Names are cosmetic to the model: ordering is keyed on `team_id` throughout, and
the exact-tie regression tests cover the case where that used to fail. They are
what the owner submits, so they still have to be right.

**STOP — owner decision required** if the owner's list and the configured identity
mapping disagree about which organisation a `team_id` is. A display name is safe to
change only after the underlying account set has passed step 3.

## 5. Regenerate everything into one bundle

```
.venv/bin/python -m ti26.cli_release \
  --snapshot <snapshot-id-from-step-1> \
  --source-revision $(git rev-parse HEAD)
```

This rebuilds the store from the committed chunks, runs D2, D3, D3b, the card and
D4, builds the frozen-gate artifact, re-renders the card report against it, and
writes `reports/runs/<run-id>/manifest.json` hashing every output.

Run it AFTER committing the code and the snapshot, so `--source-revision` names a
commit that actually contains the producers. The bundle is then a second commit.

A gate that fails exits non-zero. That is expected evidence and the driver records
it. Do not rerun a gate with different arguments to change its verdict.

## 6. Verify the bundle

```
.venv/bin/python -m ti26.cli_provenance verify-run --bundle reports/runs/<run-id>
```

Fails closed on a changed input, a changed output, or a report whose first line
names a different run.

## 7. Diff the card against the prior bundle

Compare `card/recommended_card.json` with the previous bundle's, keyed on
`team_ids`, not on display name.

A changed assignment has exactly two permitted causes: fresh snapshot input, or a
separately documented corrected computation. **It is never caused by D4.** D4 is a
diagnostic; it does not select, promote or demote a card, and a change attributed
to it would be the one thing this project has consistently refused to do.

**STOP — owner decision required** if a tie-rule or tolerance change moves an
assignment.

## 8. Full verification, then commit

```
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

Run pytest with NO marker filter. A slow-marked test failure was once excluded by
a `-m` filter and went unnoticed for a whole fix round.

Commit the bundle and the closing report only after all three of pytest, ruff and
`verify-run` succeed.

## 9. What the closing report must say

Render the final assignments from `card/recommended_card.json`, keyed by team id,
alongside the manifest's run id, source revision, snapshot id and store digest.
State the diff from the prior card and its cause. List anything that could not be
verified.

Then state the claim boundary, which does not improve just because the pipeline
became reproducible: the forecast-value gates did not establish predictive value,
D3b is a weak one-condition result, and the one held-out card-level test scored
below its random baseline.
