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

**Do not delay this step hoping for a fuller tail.** Measured on 2026-08-09
across the two committed snapshots, five days apart: of 421 maps in the last 30
days, 3 had not arrived when the earlier snapshot was taken, all on its single
final day. Waiting buys about one day of completeness and nothing else. The
thin recent evidence is real -- 14.0 maps/day against 76.2 over the whole window
-- and is a fact the forecast has to carry, not one a later snapshot fixes.

Once the fresh snapshot is committed, re-run the comparison against the previous
one, which is the same check on a longer arm:

```
.venv/bin/python -m ti26.cli_snapshot_lag \
  --older 20260807T182355Z --newer <snapshot-id-from-above> --out reports/snapshot_lag
```

**STOP -- owner decision required** if `dropped_maps` is anything but zero. That
means a match present in the earlier snapshot is absent from the later one, so
the source rewrote history, and every backfill number in the report becomes
unsafe to read.

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

**Done once already, on 2026-08-07.** All sixteen configured teams matched the
published field exactly — seven direct invites and nine qualifier winners — under
four rebrands (BetBoom→BoomBoys, 1w→Iron Wing, PARIVISION→Team Vision,
L1GA→HULIGANI). Five rounds, sixteen teams, Bo3 throughout and the 3/10/3
advancement split were corroborated; the win and loss thresholds, the tiebreak
order and the two-groups-of-eight structure were not, and Valve's own page still
returns no body. The evidence is recorded in `config/ti2026_rules.yaml`.

**Do it again anyway.** That check ran six days before the deadline. A withdrawal
or a substitution after it would land in exactly the blind spot this step exists
to cover, and the earlier pass is not evidence about the field on lock day.

## 3b. Re-fetch the rules page, and diff it

**This step exists because the rules changed under us once already.** On
2026-08-08 the TI 2026 page had no Swiss Pairing Rules section in the morning
and a complete one by evening. The engine spent that day modelling TI 2025's
format — wrong ranking criteria, wrong Round 5, wrong elimination round — and
nothing in the repository could have noticed, because every check here verifies
internal consistency against the configured rules.

The page is JavaScript-rendered, so a plain HTTP fetch returns a heading with no
body. Render it:

```
https://www.dota2.com/esports/ti15/tirules
```

Diff `The International: Group Stage Rules` through `The International: Seeding`
against [the 2026-08-08 archive](2026-08-08-ti2026-rules-fetched.md).

**STOP — owner decision required** if anything differs. Every value tagged
`valve_rules_page_2026_08_08` in `config/ti2026_rules.yaml` derives from that
archive, and a changed rule invalidates the bundle rather than merely dating it.

Re-archive the fetched text with the new date whether or not it changed, so the
next run diffs against the most recent read rather than the first one.

## 4. Roster staleness, confirmed by account set

```
.venv/bin/python -m ti26.cli_d2 --store data/processed/release.sqlite --skip-card --out /tmp/staleness
```

`cli_d2` runs `teams.check_roster_staleness` and prints a warning naming every
configured team whose accounts now appear under a different `team_id`. Five such
migrations were already present on the pinned snapshot, four of which appeared in
a single burst on 2026-07-31, so expect more rather than fewer.

**Expect a second, unrelated warning here and do not act on it.** A fresh
snapshot refits the duration model, so `cli_d2` will very likely report that
`config/ti2026_rules.yaml`'s `duration_model` does not match this run's fit, and
will tell you to sync the config and re-run before trusting the card. That
instruction is for the build sequence, not for this runbook: the config value is
the one the card was built on, and syncing it mid-run is what would make the two
disagree. Note the fitted values, finish the runbook, and update the config
afterwards if you want the next run to start clean.

Duration is a live TI 2026 tiebreak criterion — sixth, shorter is better — so it
is not inert and cannot simply be ignored. It is consulted only by ties that
survive five criteria, which is rare.

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

**Known real roster change, recorded 2026-08-10: LGD fields Topson as a standin
for the banned TaiLung** — see [the standin note](2026-08-10-lgd-standin-topson.md).
This check cannot see it unless LGD plays official maps with the standin before
the snapshot. Do not edit the configured roster or add an alias for it. Under
the current pipeline the closing report carries it as a limitation; if the
hardening slice's release preflight is live and roster evidence is imported by
lock day, it is instead a preflight failure that stops the release — resolving
that stop is an owner decision recorded in the standin note, not an edit.

## 5. Display names against the owner's list

Compare the resolved display names with `docs/ti26/owner-display-names.yaml`.
Names are cosmetic to the model: ordering is keyed on `team_id` throughout, and
the exact-tie regression tests cover the case where that used to fail. They are
what the owner submits, so they still have to be right.

**STOP — owner decision required** if the owner's list and the configured identity
mapping disagree about which organisation a `team_id` is. A display name is safe to
change only after the underlying account set has passed step 4.

## 5b. Check for a published group draw and for Round 1 pairings

**These are two separate publications and they may not arrive together.** The
2026 rules make Round 1 organiser-set rather than derived from group membership,
so the groups can be announced first and the opening matchups later. Check for
both; take whichever exists.

This step exists because step 6's invocation is unconditional. Until 2026-08-09
the only thing standing between a published draw and a card that ignored it was
remembering to add a flag — and the premise of this document is that memory
under deadline pressure is not a reliable subsystem.

Look for: the two groups of eight, and the eight Round 1 matchups. Sources are
outside `explorer_query` and outside this repository, same class as step 3.

**Status as of 2026-08-10: Round 1 is published, the groups are not** — the
reverse of the arrival order this step anticipated. All eight matchups are
archived in [the schedule archive](2026-08-10-ti2026-schedule-fetched.md);
neither Valve page labels the groups, and the accepted input cannot represent
Round 1 without them (`load_group_draw` requires `groups:` always). Re-check
both pages on the day; do not derive groups from the broadcast time blocks.

**Recorded owner policy (2026-08-10) for this state: hard stop.** If the groups
are still unpublished at regeneration time, do not run step 6 unconditioned —
that would knowingly discard a published Round 1 — and do not modify
`load_group_draw` to accept Round 1 alone, which is a predictive-behavior
change requiring its own reviewed amendment. Stop and put the decision to the
owner. The expected resolution is the groups publishing before lock day, since
Rounds 2–4 cannot run without them.

**If neither has been published:** run step 6 unchanged, then confirm the card
averaged over draws rather than silently taking one:

```
.venv/bin/python -c "import json,sys; c=json.load(open(sys.argv[1])); \
  print(c['group_draw'], c['groups'], c['round_one_supplied'])" \
  reports/runs/<run-id>/card/recommended_card.json
```

`None None False` is the correct unconditioned state. Anything else means a draw
reached the card and this step missed it.

**If either has been published**, write it to `data/ti2026_groups.yaml` —
`groups:` always, `round_one:` only if the matchups are out — archive the source
page alongside the rules archive, commit the file, and pass it in step 6:

```
.venv/bin/python -m ti26.cli_release \
  --snapshot <snapshot-id> --source-revision $(git rev-parse HEAD) \
  --groups data/ti2026_groups.yaml
```

`data/`, not `config/`: the draw is an external fact like the snapshot, not a
setting, and `CONFIG_INPUTS` is asserted to equal `config/*.yaml` exactly, so a
file dropped there turns the suite red at step 9 in the middle of the run.

`cli_release` hashes the draw into the manifest as a declared input, so
`verify-run` fails closed if it is edited afterwards. It reaches the CARD only —
never D4, whose event had its own groups.

**STOP — owner decision required** if any of these is true:

- the published draw cannot be represented exactly by the accepted input:
  unequal groups, not exactly two, an odd group, a Round 1 pairing across
  groups, or a name that is not in the configured field. `load_group_draw`
  refuses all of these rather than forecasting a bracket that does not exist —
  do not reshape the draw to fit;
- the groups contradict the sixteen confirmed in step 3;
- Round 1 is published but conditioning on it changes the card materially. Diff
  with and without using `card-diff` from step 8 and let the owner choose; a
  known fact should be used, but not discovered as a surprise after submission.

## 6. Regenerate everything into one bundle

```
.venv/bin/python -m ti26.cli_release \
  --snapshot <snapshot-id-from-step-1> \
  --source-revision $(git rev-parse HEAD)
```

This rebuilds the store from the committed chunks, runs D2, D3, D3b, the card,
D4, `cli_data_health` and `cli_external_cards`, builds the frozen-gate artifact,
re-renders the card report against it, and writes
`reports/runs/<run-id>/manifest.json` hashing every output.

The last two joined the bundle on 2026-08-09, so **this run id will not match
the shape of any earlier bundle's** — the id derives from the producer list. A
non-zero exit from either stops the run, unlike a gate's, whose non-zero exit is
its verdict.

Add `--groups data/ti2026_groups.yaml` if step 5b found a published draw.

Run it AFTER committing the code and the snapshot, so `--source-revision` names a
commit that actually contains the producers. The bundle is then a second commit.

A gate that fails exits non-zero. That is expected evidence and the driver records
it. Do not rerun a gate with different arguments to change its verdict.

**If this run is interrupted, just run it again.** A bundle counts as finished
only once `manifest.json` is written, which happens last; an unfinished directory
is replaced with a printed notice, and a finished one is still refused outright.
Before 2026-08-08 an interrupted run left a directory that blocked every retry
with nothing to clear it, which cost a manual recovery mid-regeneration. Expect
the whole command to take tens of minutes.

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

```
.venv/bin/python -m ti26.cli_provenance card-diff \
  --a reports/runs/<previous-run-id>/card/recommended_card.json \
  --b reports/runs/<run-id>/card/recommended_card.json
```

This step said "compare, keyed on team_ids, not on display name" and gave no way
to do it; it was a hand comparison until 2026-08-09. The command keys on team id
itself, so a rebrand — four teams rebranded before this field was confirmed —
shows up as `renamed_without_moving` rather than as two spurious differences.

`only_in_a` and `only_in_b` are the ones to read first. A non-empty pair means
the two cards are not about the same sixteen teams, which is a field change, not
a forecast change.

**Ignore `objective_a` versus `objective_b`.** Each is computed under its own
marginals, so the number rises with confidence rather than with accuracy. The
output says so in `objective_note` for the same reason it is repeated here.

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

## 9b. If the card cannot ship: the rung-3 fallback

**Rehearsed end to end on 2026-08-09.** Until then this path existed, was
covered by tests, and had never been executed against the real world. It works,
but not in the way the one-line description in the strengthening plan implied,
and the differences all matter under a deadline.

Reach for this only when the normal path cannot produce a card at all: a
producer that cannot run, a store that will not rebuild, a roster that will not
resolve. **A failing GATE is not a trigger.** D2 and D3 already fail; that is
recorded evidence, not a build failure, and the card ships from calibrated
Glicko anyway.

```
.venv/bin/python -m ti26.cli_rung3 \
  --store data/processed/release-<snapshot-id>.sqlite \
  --out reports/rung3_<snapshot-id>
```

Roughly three minutes at production sim counts. It writes
`strengths_public.csv`, `rung3_scale_sensitivity.json`, `rung3_provenance.md`
and the card.

**It needs the network, through the same seam as step 1.** If the network is
why you are here, rung 3 is not available and you go to 9c.

**It needs the store too**, for the Elo-ordering anchor and the observed-form
diagnostic. If the store is the problem, the run stops after writing
`strengths_public.csv` and tells you the exact command to finish the card
without it. Take that offer only knowing what it costs: the anchor and the
observed-form check are the only two independent checks on a rating conversion
whose divisor this project has never been able to document. A card produced that
way must say, wherever it is published, that neither ran.

**Rung-3 rehearsal figures are one-off past observations, not reproducible
evidence, and are labelled that way wherever they appear below.** Rung 3 reads a
live table through the network, so its output cannot be replayed offline and is
not committed — the correction register withdrew rung-3 figures from project
prose for exactly that reason, and `cli_rung3`'s own boundary-proximity note
already uses this labelling for the same constraint. Everything below tells you
what to look at and gives the command that computes it for your run; a rehearsal
figure appears only as a statement about 2026-08-09, never as a prediction about
lock day.

**Read these three before publishing anything from it:**

- **Thin and stale counts** in `rung3_provenance.md`, and the run's own last
  stdout lines, which print them. The public table's per-team evidence is not
  uniform and it does not announce that unless you look. On the rehearsal a
  substantial minority of the field was flagged.
- **The scale-sensitivity sweep**, `rung3_scale_sensitivity.json`. The `/400`
  divisor is inferred by convention, not documented by OpenDota. If any
  non-baseline row has `"resolvable": true`, that undocumented constant moves
  the card by more than resampling noise does — rung 3's central assumption is
  then load-bearing rather than incidental. **It was `true` on the rehearsal.**
- **The Elo rank correlation and top-4 overlap.** Sanity anchors, not
  agreements; neither was perfect on the rehearsal.

**The rung-3 card is a different card, not a degraded copy of the same one.**
Diff it against the card you would otherwise have shipped, keyed on team id:

```
.venv/bin/python -m ti26.cli_provenance card-diff \
  --a reports/runs/<run-id>/card/recommended_card.json \
  --b reports/rung3_<snapshot-id>/recommended_card.json
```

On 2026-08-09, at identical sim count and seed, half the assignments moved. That
is one observation against one snapshot, not a rate — but it is enough to expect
a different forecast rather than a rounding difference.

**STOP — owner decision required** before submitting a rung-3 card. It is a
different forecast from a source with no backtest, not a fallback rendering of
the one that was verified.

**Do not compare the two cards' `optimizer_marginal_objective`.** The rehearsal's
rung-3 card scored higher than the shipping card, and that is not evidence it is
better. The objective is the optimiser's expected score under *its own*
marginals, so more extreme strengths buy a higher number whether or not they are
more accurate. A flat strength vector would score near the 3.75 random baseline
and a confidently wrong one would score well. It measures confidence, not skill.

**There is no manifest.** Rung 3 is not a run bundle: no source revision, no
store digest, no config digests, and `verify-run` does not apply to it. Record
the fetch timestamp from `rung3_provenance.md` — the `team_rating` table is live
and continuously updated, so that timestamp is the only thing identifying which
version of the source the card came from.

## 9c. If there is no network either

The last resort is the card generator fed a `team,strength` CSV directly. It
touches nothing external.

```
.venv/bin/python -m ti26.cli \
  --strengths <team,strength CSV> --rules config/ti2026_rules.yaml \
  --n-sims 250000 --seed 1 --out reports/manual_<date>
```

**Verified on 2026-08-09:** fed the shipping card's own
`strengths_calibrated.csv` at the same sim count and seed, this path reproduced
the shipping card exactly — all 16 assignments and the objective to four
decimals. So the generator is sound and the only question is where the strengths
come from.

Sim count is not a detail here. The same strengths at 2,000 sims instead of
250,000 moved 4 of 16 slots. If you cut it to save time, say so on the card.

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
