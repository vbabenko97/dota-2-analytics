# D3 rung-3 build report: public-ratings fallback strength source

Branch: `d3-rung3-public-ratings`, forked from `main` at `8eba3db`.

## Why this exists

D2 measured elo (0.6944614 nats) and glicko (0.6982921 nats) BOTH worse than
the constant 50/50 floor (0.6931472 nats) on 26,830 out-of-sample maps
(`docs/audits/2026-08-02-d2-build-ledger.md`). `cli_d2` correctly refuses to
ship a card from either. Spec X's rung 3 -- public external ratings piped
straight into the D1 simulator -- is the prescribed fallback.

Rung 3's named source, "Noxville, datdota", is unreachable from this
environment: HTTP 403 to every access path tried (browser-emulating fetch,
curl under multiple User-Agents, and the Internet Archive's own crawler),
and Noxville's public dataset dead since 2020-12-29
(`docs/audits/2026-08-02-rung3-source-research.md`, already-completed
research, not repeated here). OpenDota's own `team_rating` table is used
instead, via the existing `explorer_query` network seam -- no new network
path.

## What was built

- `src/ti26/data/opendota.py`: added `TEAM_RATING_QUERY`, a parameterised
  `select team_id, rating, wins, losses, last_match_time from team_rating
  where team_id in ({team_ids})`. Reuses `explorer_query`/`http_transport`;
  zero new network paths.
- `src/ti26/public_ratings.py` (new): frozen `PublicRating` dataclass
  (`team_id, rating, wins, losses, last_match_time`, plus `games`,
  `is_thin`, `stale_days(now)`, `is_stale(now)` -- `now` is always a
  parameter, never `datetime.now()` internally); `parse_ratings` (defensive
  int/float casts, since OpenDota serialises bigint columns as JSON
  strings); `strengths_from_ratings` (zero-centred logit conversion,
  `logit_per_elo` overridable); `scale_sensitivity_sweep` (mirrors
  `ti26.duration.sensitivity_sweep`'s noise-floor discipline exactly: the
  first sweep entry is the baseline, `noise_floor` is the MAX of three
  pairwise max-abs-deltas from baseline reruns at seeds `seed`, `seed+1`,
  `seed+2`, every entry carries a shared `noise_floor` and a `resolvable`
  flag, and the docstring states a delta at or below the floor is not
  evidence of an effect).
- `src/ti26/cli_rung3.py` (new): loads `config/ti2026_teams.yaml`, fetches
  ratings via an injected `transport` parameter (defaults to
  `http_transport`), refuses (SystemExit, no files written) if any
  configured team lacks a `team_rating` row, writes
  `reports/strengths_public.csv` (`team,strength`, exactly 16 rows), runs
  the scale-sensitivity sweep (0.5x/1.0x/2.0x the conventional /400
  divisor), fits a *separate* Elo model over the full local D2 store
  (`data/processed/d2.sqlite`, same method `cli_d2`'s final fit uses) purely
  as spec V rung 6's sanity anchor (rank correlation + top-4 set overlap
  against rung-3's own ordering -- reported, not gated on), prints implied
  map win probabilities for the strongest-vs-weakest pair and two mid-table
  adjacent pairs, writes `reports/rung3_provenance.md` and
  `reports/rung3_scale_sensitivity.json`, then invokes `ti26.cli`'s `main`
  with `--strengths reports/strengths_public.csv` to produce the actual
  card (`reports/recommended_card.json`, `reports/category_probabilities.csv`).
- `docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md` §X: dated
  correction (2026-08-02) recording that rung 3's named source is
  unreachable, what was used instead, and that the scale is tagged
  `inferred`.
- `tests/test_public_ratings.py` (9 tests), `tests/test_cli_rung3.py`
  (5 tests, injected transport, no network).

## Design decisions and why

- **Current configured `team_id` only, no roster-following, no blending**
  (controller decision, implemented as stated): `ratings = {t.name:
  by_id[t.team_id] for t in teams}`, a direct lookup, nothing more.
- **Scale conversion `math.log(10) / 400.0`**, matching `LOGIT_PER_ELO` in
  `src/ti26/ratings/elo.py`. Labelled `inferred` in the module docstring,
  the CLI's own docstring, the printed provenance report, and the spec
  correction -- OpenDota documents no divisor for `team_rating`.
- **`THIN_GAMES_THRESHOLD = 200`**: separates the six known-thin TI 2026
  teams (max observed 185 games, this run) from the next-smallest
  established team (Team Yandex, 295 games) with a wide margin either side.
  Not tuned to hit a target count -- verified against the real run below.
- **`STALE_DAYS_THRESHOLD = 30.0`**: sits in the observed gap between the
  "recently active" cluster (<=20 days) and the "long inactive" cluster
  (>=34 days) across the 16 configured teams. Not tuned to hit a target
  count.

## Test results

- New: 9 (`test_public_ratings.py`) + 5 (`test_cli_rung3.py`) = 14 passed.
- Full suite, **no marker filter**: `.venv/bin/python -m pytest -q` ->
  **610 passed, 0 failed** (13m19s; four pre-existing `test_cli_d2.py`
  end-to-end tests account for most of that, unchanged by this branch).
- `.venv/bin/python -m ruff check .` -> **All checks passed.**
- No test in either new file touches the network: `test_cli_rung3.py`
  injects a fake `transport` callable exactly like `tests/test_opendota.py`
  does for `explorer_query`; `test_public_ratings.py` never imports
  `opendota` at all.
- Three new tests (`test_writes_16_strength_rows_and_a_card_from_our_team_names`,
  `test_thin_and_stale_teams_are_flagged_in_the_provenance_report`,
  `test_elo_anchor_reports_a_real_rank_correlation_and_top4_overlap`) and
  two in `test_public_ratings.py` (the two `scale_sensitivity_sweep` tests)
  are marked `@pytest.mark.slow` (14-27s each, running real Monte Carlo /
  Elo fits), matching this repo's existing convention for `test_cli_d2.py`'s
  full end-to-end tests. They still run in the unfiltered suite above.

## Test-quality self-check: a vacuous test found and fixed by mutation

Per the brief's instruction to prove the important tests by mutation and
report each mutation's actual output, all four (zero-centring, scale
conversion, thin-history threshold, staleness computation) were mutated in
an in-repo scratch copy (`.mutscratch/src/ti26/...`, never `/tmp` -- running
scripts from `/tmp` is blocked in this environment -- fully removed
afterward via explicit non-recursive `rm`/`rmdir`, confirmed by
`git status --short` showing no residue) and run via
`.venv/bin/python -m pytest -o pythonpath=.mutscratch/src tests/test_public_ratings.py`.
The pythonpath override was itself verified first: a deliberate
`raise RuntimeError(...)` inserted at the top of the scratch copy's
`public_ratings.py` produced that exact error at collection time, proving
the override was live before any real mutation was trusted.

**Mutation 1 -- zero-centring removed** (`return r.rating * logit_per_elo`
instead of `(r.rating - mean) * logit_per_elo`): exactly
`test_strengths_from_ratings_centres_scales_and_preserves_order` failed --
`strengths["B"]` (rating equal to the 3-team mean) came out `8.059...`
instead of `0.0`. 1 failed, 8 passed.

**Mutation 2 -- wrong divisor** (`LOGIT_PER_ELO = math.log(10) / 380.0`
instead of `/400.0`): **this is where a real vacuous-test bug was found and
fixed.** The spacing assertion in
`test_strengths_from_ratings_centres_scales_and_preserves_order` originally
read `strengths["C"] - strengths["B"] == pytest.approx(200.0 *
LOGIT_PER_ELO)` -- comparing against the imported (and therefore also
mutated) module constant, so both sides of the comparison shifted together
and the assertion stayed true under the wrong divisor. Only
`test_logit_per_elo_matches_the_repo_own_elo_convention` failed (1 failed,
8 passed) -- the spacing test passed **incorrectly**. Fixed by hardcoding
the expected value independently (`200.0 * math.log(10) / 400.0`, a
literal, not the imported name). Re-run after the fix: **2 failed** (the
same constant test, plus now the spacing test too, correctly), 7 passed.
This is exactly the "test that cannot fail" trap this codebase's own D2
build repeatedly found (11 such tests, six from plan text) -- caught here
by actually running the required mutation rather than trusting the test by
inspection.

**Mutation 3 -- thin-history threshold off-by-one** (`self.games <=
threshold` instead of `<`): exactly
`test_is_thin_boundary_exactly_at_the_threshold` failed --
`exactly_at.is_thin()` (200 games) returned `True` instead of `False`. 1
failed, 8 passed.

**Mutation 4a -- staleness divisor wrong** (`_DAY_SECONDS = 3600.0`, hours
not seconds-per-day): exactly `test_stale_days_conversion_and_is_stale_boundary`
failed -- `ten_days_ago.stale_days(now)` came out `240.0` (24x too large)
instead of `10.0`. 1 failed, 8 passed.

**Mutation 4b -- staleness boundary flipped** (`self.stale_days(now) >
threshold` instead of `>=`): the same test failed again --
`exactly_at.is_stale(now)` (exactly 30.0 days) returned `False` instead of
`True`. 1 failed, 8 passed.

All four mutations were reverted; `.venv/bin/python -m pytest -q
tests/test_public_ratings.py tests/test_cli_rung3.py` was re-run against
the restored tracked source afterward (14 passed), and `git status --short`
confirmed no tracked file was touched by the mutation exercise.

## The real run

`.venv/bin/python -m ti26.cli_rung3` (live network call to
`api.opendota.com/api/explorer`, real local store
`data/processed/d2.sqlite`):

```
rung3: 16 teams rated, 6 thin, 3 stale
rung3: Elo rank correlation 0.9088, top-4 overlap 4/4
rung3: scale sweep resolvable=True
rung3: card written to reports/recommended_card.json
```

16 of 16 configured teams had a `team_rating` row -- no refusal path
exercised for real.

**Thin (6, under 200 games):** 1win (23), GamerLegion (185), HULIGANI (21),
LGD Gaming (62), Nigma Galaxy (58), Team Resilience (77) -- exactly the six
teams flagged in the source research, derived from the live data rather
than hardcoded.

**Stale (3, >=30 days):** HULIGANI (36.0d), Team Resilience (46.3d), Team
Vision (38.9d). Two of the three (HULIGANI, Team Resilience) are also thin
-- consistent with the source research's framing of "two of the six thin
teams are also stale". Team Vision is stale but NOT thin (501 games) --
an independent finding, not a contradiction.

**Scale-sensitivity sweep verdict: the divisor IS resolvably distinguishable
from noise.** Noise floor 0.01090 (three baseline reruns at seeds 0/1/2,
`n_sims=20000`). At 0.5x the conventional divisor (200): max abs delta
0.21785 (resolvable). At 2.0x (800): max abs delta 0.13790 (resolvable).
**This differs from D2's duration `log_sigma` finding**, where the
equivalent sweep found the parameter did NOT move the card resolvably.
Here it does -- the inferred `/400` divisor is not a cosmetic choice; a
materially different (but equally plausible, since neither is documented)
divisor produces a measurably different card. This is the central risk the
brief asked this sweep to surface, and it surfaced a real, non-trivial
effect rather than a null result.

**Elo-ordering anchor: strong agreement.** Spearman rank correlation
0.9088 over the same 16 teams; top-4 sets are IDENTICAL (BoomBoys, Team
Falcons, Team Vision, Team Yandex) by both public rating and locally-fitted
Elo. No sign error or wildly-wrong-scale signature per spec V rung 6.

**Implied map win probabilities** (plausibility check): Team Vision (rating
1553.33, strongest) vs HULIGANI (1183.59, weakest) -> 0.8936 for Team
Vision. Two mid-table adjacent pairs: Vici Gaming vs OG -> 0.5663; OG vs LGD
Gaming -> 0.5047. All plausible -- no inversion, no saturation at the
extremes for a merely-large (not enormous) rating gap.

**The card** (`reports/recommended_card.json`, `--card-sims 250000 --seed
1`, model-implied expected score **6.7729** vs random baseline 3.75):

| team | category |
|---|---|
| Team Vision | 4-0 |
| BoomBoys | 4-1 |
| Team Yandex | 4-1 |
| Aurora Gaming | elim_win |
| Team Falcons | elim_win |
| Team Liquid | elim_win |
| Team Spirit | elim_win |
| Vici Gaming | elim_win |
| 1win | elim_loss |
| GamerLegion | elim_loss |
| LGD Gaming | elim_loss |
| Nigma Galaxy | elim_loss |
| OG | elim_loss |
| Team Resilience | 1-4 |
| Xtreme Gaming | 1-4 |
| HULIGANI | 0-4 |

All artifacts (`reports/`) are gitignored per this repo's existing
convention (generated output, not tracked) and were not committed; only
source, tests, docs and the config-adjacent spec correction were.

## Concerns

1. **The scale conversion is resolvably load-bearing and still unverifiable.**
   The sweep proves the card would look different under an equally
   plausible alternative divisor, and nothing in this environment can
   check which one (if either) is correct -- OpenDota does not document
   it, and the source that might (datdota/Noxville) is unreachable. This
   is reported, not fixed, per the brief; a reader relying on this card
   should weigh it accordingly.
2. **The Elo anchor is reassuring but not proof.** 0.9088 correlation and
   4/4 top-4 overlap rule out a sign error or a wildly wrong scale, but
   Elo itself lost to the constant floor in D2 -- strong agreement between
   two models that both reflect the same underlying game results is
   expected even if both are compressed/miscalibrated in the same
   direction. It cannot validate the absolute scale, only the ordering.
3. **`--elo-k` defaults to 20.0 in `cli_rung3.py` rather than reading
   `config/d2_gate.yaml`'s pre-registered `elo_k`.** For this run they are
   the same value (20.0), so it made no difference here, but a future
   change to the gate config's `elo_k` would silently desynchronise the
   anchor from D2's own Elo. Minor, since the anchor is diagnostic-only and
   not gated on.
4. **Test I was initially unsure could fail, until mutation proved
   otherwise:** the scale-conversion spacing assertion in
   `test_strengths_from_ratings_centres_scales_and_preserves_order` --
   documented above as a real vacuous-test bug, found and fixed during this
   build via the required mutation exercise, not merely by inspection.

## Update 2026-08-03: observed-recent-form diagnostic (branch `d3-rung3-public-ratings`)

### Why this exists

A user challenge on one card assignment (Xtreme Gaming at 1-4) exposed that
this report had no independent read on whether the public ratings are sane:
the Elo anchor (section above) compares a rating to a rating, and it missed
the problem because our own Elo also underrates thin-history rosters. A
direct observation of what each roster has actually been doing catches what
a rating-vs-rating comparison cannot.

### What was built

- `src/ti26/public_ratings.py`: `ObservedForm` (frozen dataclass: `wins,
  losses, n, rate, ci_low, ci_high, implied, verdict`), `wilson_interval`
  (95% Wilson score CI, `z` overridable), `classify_form_verdict` (strict
  `<`/`>` against the CI bounds; `"no data"` when `n == 0`), and
  `observed_recent_form` (ties it together: counts a roster's maps by
  `roster_version_id` -- never `team_id` -- within a `window_days` window
  measured back from a passed-in `reference_time`, never `datetime.now()`).
  `implied` is the mean of `ti26.series.map_win_prob(s_self, s_other)` over
  the other 15 teams' strengths -- the existing logistic is reused, not
  reimplemented.
- `src/ti26/cli_rung3.py`: a new step 3(d) computes `observed_recent_form`
  over the full local store (`resolve_rosters`, the same resolution
  `teams.py`'s other callers use), renders a new "## Observed recent form
  (diagnostic only)" section in `reports/rung3_provenance.md` (table +
  the two mandated caveat paragraphs: opposition strength not controlled,
  and that all current deviations point one way and are ambiguous between
  the `/400` divisor and the schedule confound), and prints one stdout
  summary line (`rung3: observed form N consistent, N above implied, N
  below implied`).
- No existing line computing `ratings`, `strengths`, `strengths_path`, or
  the `cli_main(...)` card invocation was touched -- confirmed by `git diff
  211ee4a -- src/ti26/cli_rung3.py src/ti26/public_ratings.py`: zero deleted
  or modified lines in either file, only additions.
- `tests/test_public_ratings.py`: 6 new tests. `tests/test_cli_rung3.py`: 1
  new test (report wiring + stdout reconciliation).

### Test results

- New: 6 (`test_public_ratings.py`) + 1 (`test_cli_rung3.py`) = 7 added.
- Full suite, **no marker filter**: `.venv/bin/python -m pytest -q` ->
  **618 passed, 0 failed**.
- `.venv/bin/python -m ruff check .` -> **All checks passed.**

### Mutation proofs (required four)

All four performed against an in-repo scratch copy of the real source
(`.mutscratch/src/ti26/...`, never `/tmp`), with the pythonpath-override
sanity check run first (a `raise RuntimeError("scratch-copy-live-sanity-
check")` inserted at the top of the scratch copy's `public_ratings.py`
reproduced exactly that error at collection under `-o
pythonpath=.mutscratch/src`, proving the override was live before any
mutation was trusted). Each mutation was applied, tested, reverted, and the
scratch copy re-verified clean (15 passed) before moving to the next.
Command for all four: `.venv/bin/python -m pytest -q -o
pythonpath=.mutscratch/src tests/test_public_ratings.py`. The scratch
directory was fully removed afterward via explicit non-recursive `rm`
(every file named individually, no glob/loop) and `rmdir`; `git status
--short` showed no residue and no tracked file touched.

1. **Wilson interval -- wrong `z`** (`WILSON_Z_95 = 1.0` instead of `1.96`):
   `test_wilson_interval_matches_hand_verified_values` failed --
   `wilson_interval(50, 100)`'s low bound came out `0.4502481404895005`
   instead of the hand-verified `0.4038298286`. **1 failed, 14 passed.**
2. **Verdict boundary -- `<` to `<=`** (`classify_form_verdict`'s `if
   implied <= ci_low` instead of `<`): `test_classify_form_verdict_boundary_
   and_label_swap` failed at the exact-boundary case --
   `classify_form_verdict(0.60, 0.60, 0.80, n=10)` returned `"form ABOVE
   implied"` instead of `"consistent"`. **1 failed, 14 passed.**
3. **Roster-following count -- by `team_id` instead of `roster_version_id`**
   (`_roster_record` rewritten to match `r.radiant_team_id == 100` /
   `r.dire_team_id == 100`, the fixture's configured id, instead of the
   roster hash): `test_observed_recent_form_counts_by_roster_version_id_
   not_team_id` failed -- the fixture (current roster X spans team_ids 99
   -> 100; a different, older roster Y also played under the current id
   100) came out `(0, 3, 3)` instead of the correct `(2, 1, 3)`: it missed
   roster X's two wins recorded under the OLD id 99 and wrongly counted
   roster Y's two losses recorded under the current id. **1 failed, 14
   passed.**
4. **Window cutoff ignored** (the `start_time` bounds check in
   `_roster_record` replaced with `if False: continue`):
   `test_observed_recent_form_respects_the_window_cutoff` failed -- a map 91
   days back (outside the 90-day window) was wrongly counted, giving `(2,
   0, 2)` instead of the correct `(1, 0, 1)`. **1 failed, 14 passed.**

### The real run

`.venv/bin/python -m ti26.cli_rung3` (live network call to
`api.opendota.com/api/explorer`, real local store
`data/processed/d2.sqlite`):

```
rung3: 16 teams rated, 6 thin, 3 stale
rung3: Elo rank correlation 0.9088, top-4 overlap 4/4
rung3: scale sweep resolvable=True
rung3: observed form 11 consistent, 5 above implied, 0 below implied
rung3: card written to reports/recommended_card.json
```

**Table matches the brief's reference numbers.** The `observed`/`n`/`95%
Wilson CI` columns -- computed only from the frozen local store -- are
byte-for-byte identical to the brief's table for all 16 teams (e.g. Team
Vision: `0.762, 80, [0.659, 0.842]`; HULIGANI: `0.487, 39, [0.339, 0.638]`).
The **verdict** column and the 11/5/0 summary also match exactly, including
which five teams are flagged (OG, LGD Gaming, Nigma Galaxy, Team Resilience,
HULIGANI, all "form ABOVE implied", none below).

**`strength`/`implied` differ slightly from the brief's literal numbers**
(e.g. BoomBoys strength 0.748 here vs 0.842 in the brief; Vici Gaming -0.136
vs -0.009) -- traced to live OpenDota data drift between the brief's
2026-08-02 snapshot and this 2026-08-03 run, not to this change: the
regenerated "Per-team ratings" table shows BoomBoys' games moved
1218(687/531) -> 1219(687/532), Team Falcons 858(555/303) -> 859(556/303),
Vici Gaming 2622(1561/1061) -> 2624(1562/1062) -- new matches were recorded
upstream in the intervening day. `strength`/`implied` depend on the live
`team_rating` call; `observed`/`n`/CI depend only on the unchanged local
store, which is exactly why the latter match exactly and the former don't.

**Card confirmation.** A literal live-vs-live byte comparison of
`recommended_card.json`/`strengths_public.csv` against the copies already
sitting in `reports/` (gitignored, generated the day before) is NOT
byte-identical, for the same data-drift reason. To isolate the actual
question -- did THIS CHANGE alter the strength/divisor/card computation --
two direct checks were run instead:
1. `git diff 211ee4a -- src/ti26/cli_rung3.py src/ti26/public_ratings.py`
   contains zero deleted or modified lines in either file; every change is
   an addition.
2. A controlled A/B: the pre-change code (`git show 211ee4a:...`, in an
   in-repo scratch copy) and the current code were each run with an
   IDENTICAL fixed, synthetic (non-network) rating payload against the same
   real local store. `recommended_card.json` and `strengths_public.csv`
   from both runs are **sha256-identical**
   (`22250c72...6b267` and `a2f82e43...ca8911` respectively, matching on
   both sides). This proves the card/strength/divisor computation is
   unchanged by this diagnostic; the scratch copy was removed the same way
   as the mutation exercise, confirmed by `git status --short`.

### Concerns

1. **Same scale-conversion risk as before, now with a second, independent
   signal pointing at it.** All five current "form ABOVE implied" teams sit
   in the bottom half of the field and none point the other way -- exactly
   the asymmetric pattern the `/400` divisor's over-spreading of strengths
   would produce (an over-spread bottom half would be rated too far below
   its true relative strength). It is equally consistent with the schedule
   confound (bottom-half teams facing weaker regional circuits). This data
   cannot separate the two explanations, and the report says so explicitly.
2. **Opposition strength is not controlled**, by design and as stated in the
   report: each `observed` figure is against whatever that roster actually
   played, not the TI field. This diagnostic is not a ranking and was never
   used to override any strength, the divisor, or the card.
