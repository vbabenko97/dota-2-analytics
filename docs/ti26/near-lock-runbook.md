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

## 3. Confirm the sixteen-team field

Nothing in this repository can do this, and until 2026-08-07 nothing in this
runbook asked for it.

`config/ti2026_teams.yaml` names sixteen `team_id`s. The pipeline treats that
field as given: the capacities `1/2/5/5/2/1` sum to sixteen, the simulation seeds
sixteen rosters, and the optimiser assigns all of them. If the real field differs
by even one team, every marginal in the bundle is a forecast of an event that is
not happening, and no check in steps 4 through 8 would notice — they all verify
internal consistency against the configured sixteen.

Confirm against the official participant list, which is outside `explorer_query`
and outside this repository. The store holds match rows, not invitations.

**STOP — owner decision required** if the official field is not exactly the
sixteen configured `team_id`s, or if it cannot be read at all. A substitution is
a config change followed by a full regeneration, not an edit to the card.

While there: the tournament format values in `config/ti2026_rules.yaml` are
tagged `reported_official`, not `official`, because their source could not be
opened. `cli_pairing_check` corroborates the structure against TI 2025, which is
the only event that has ever run it, but a rule change for 2026 would be
invisible here. Confirming those values needs the same class of source.

## 4. Roster staleness, confirmed by account set

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

## 5. Display names against the owner's list

Compare the resolved display names with `docs/ti26/owner-display-names.yaml`.
Names are cosmetic to the model: ordering is keyed on `team_id` throughout, and
the exact-tie regression tests cover the case where that used to fail. They are
what the owner submits, so they still have to be right.

**STOP — owner decision required** if the owner's list and the configured identity
mapping disagree about which organisation a `team_id` is. A display name is safe to
change only after the underlying account set has passed step 4.

## 6. Regenerate everything into one bundle

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

**The D4 in this bundle is the confounded configuration, and stays that way.** It
trains on maps before 2025-09-04, and an 18-month snapshot taken now reaches back
only to early 2025, so the held-out event gets roughly seven months of history
where production gets eighteen. The matched-window re-run in
`reports/d4_matched_window/` is the number to quote; the bundle's own D4 score is
not the pipeline's out-of-sample performance. Do not deepen the production
snapshot to fix this — the shipping card stays on the 18-month window it was
specified for, and the matched-window measurement already exists.

## 7. Verify the bundle

```
.venv/bin/python -m ti26.cli_provenance verify-run --bundle reports/runs/<run-id>
```

Fails closed on a changed input, a changed output, or a report whose first line
names a different run.

## 8. Diff the card against the prior bundle

Compare `card/recommended_card.json` with the previous bundle's, keyed on
`team_ids`, not on display name.

A changed assignment has exactly two permitted causes: fresh snapshot input, or a
separately documented corrected computation. **It is never caused by D4.** D4 is a
diagnostic; it does not select, promote or demote a card, and a change attributed
to it would be the one thing this project has consistently refused to do.

**STOP — owner decision required** if a tie-rule or tolerance change moves an
assignment.

Read the card report's "What the simulation added over a strength sort" section
while you are here. On the pinned snapshot the answer was nothing: the card and
the naive strength ladder agreed on all sixteen. Record what it says on fresh
data. If it still agrees, what is being submitted is a ranking cut into buckets,
and the closing report has to say so.

## 9. Full verification, then commit

```
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

Run pytest with NO marker filter. A slow-marked test failure was once excluded by
a `-m` filter and went unnoticed for a whole fix round.

Commit the bundle and the closing report only after all three of pytest, ruff and
`verify-run` succeed.

## 10. What the closing report must say

Render the final assignments from `card/recommended_card.json`, keyed by team id,
alongside the manifest's run id, source revision, snapshot id and store digest.
State the diff from the prior card and its cause. List anything that could not be
verified — including, from step 3, whether the field and the format were confirmed
and against what.

Then state the claim boundary, which does not improve just because the pipeline
became reproducible: the forecast-value gates did not establish predictive value,
D3b is a weak one-condition result, and the only held-out card-level test scored
1/16 against a 3.75 random baseline on a seven-month training window and 4/16 once
the window was matched to production's eighteen — barely above the baseline, below
the model's own expectation of 4.92, and exactly level with a naive strength
ladder. One event is one sample, so none of it shows the pipeline is worse than
chance; it removes the reason to believe it is better.
