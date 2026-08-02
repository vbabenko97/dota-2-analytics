# D2 build ledger — ingestion, ratings, backtest, duration fit

Branch: `d2-ingestion-ratings` (branched from `3fe75cd`), 22 commits.
Executed subagent-driven: a fresh implementer per task, spec and quality
review after every task, a whole-branch review at the end.

---

## Outcome: the forecast-value gate FAILED, and so did the floor beneath it

**Do not proceed to D3 as specified.** Spec §II makes the forecast-value gate
the decision point for whether D3–D4 happen, and it did not pass. Separately
and more seriously, no rating model cleared spec §V's rung 1.

Measured on 41,140 ingested professional maps (snapshot `20260802T165535Z`,
2025-02 to 2026-08), 28,923 out-of-sample predictions over 192 tournament
folds, 26,830 scored after excluding rows the models declined to rate:

| model | log loss | vs constant floor | accuracy | calibration slope |
|---|---|---|---|---|
| constant (ln 2) | 0.6931472 | — (floor) | 0.5212 | n/a |
| **elo** | 0.6944614 | **+0.0013142** | 0.5363 | 0.4448 |
| **glicko** | 0.6982921 | **+0.0051449** | 0.5439 | 0.4023 |
| **ewma** | 0.7065461 | **+0.0133990** | 0.5265 | 0.2126 |

Pre-registered gate (written into `config/d2_gate.yaml` before any backtest
ran): `mean(LL_elo − LL_glicko) ≥ 0.003` nats/map AND a paired bootstrap 95%
CI excluding 0. Observed margin **−0.00383**, CI **[−0.02055, 0.00614]**,
cluster bootstrap over 191 tournaments. Glicko did not beat Elo.

`cli_d2` refuses to write a card and exits 3. Per spec §X the fallback is
rung 3: public ratings (Noxville/datdota) piped into the D1 simulator.

## The negative result is trustworthy

The whole-branch review re-ran the pipeline to byte-identical output and then
ruled out, individually, every mechanism that could manufacture a false
negative:

- all four models scored on the identical population (28,923 raw / 26,830 rated)
- prediction direction and margin sign not inverted, for all three models
- refit-from-scratch per fold is mathematically equivalent to one continuous
  walk — the fold loop introduces no distortion
- rosters genuinely repeat (mean 6.23 maps per roster); ratings are not
  perpetually cold-starting
- Elo's probabilities are narrow (0.16–0.86), not clipped or extreme, so the
  loss is not coming from confident tail predictions
- `assert_no_leakage` is called on the production path; fold cutoffs verified

## What the numbers actually say, and the D3 lead

Accuracy is above 50% for all three models while log loss is worse than a coin
flip. That combination is diagnostic, not contradictory: the models rank
correctly and state their confidence far too strongly. Calibration slopes of
0.40–0.44 against a target of 1.0 mean the predicted logits are roughly 2.2×
too wide.

The spec's build plan sets D3's target at calibration slope ∈ [0.9, 1.1]. Measured, we are
at 0.40. `backtest.calibration()` already computes the slope and intercept on
every run and nothing applies them.

**This lead was deliberately not pursued in D2.** The gate was pre-registered
on uncalibrated models; fitting a calibration layer after seeing these results
and re-running the same gate is post-hoc, which is precisely what
pre-registration exists to prevent. If D3 pursues it, it needs its own gate,
pre-registered before the calibrated model is scored.

## Fitted duration model

Fitted from 41,082 real durations: `log_mean=7.5793`, `log_sigma=0.2806`,
gap coefficient −0.0015 (SE 0.0058, not material). Replaces the invented
7.65 / 0.25 and is tagged `empirical`, a fifth provenance value added to
spec §XII for this case.

Spec §XII previously implied this parameter was load-bearing because the
resolver is consulted on ~30% of rankings. That inference is now retracted:
measured against its own resampling noise floor, `log_sigma` does not move the
card resolvably. `log_mean` still matters. The §XII correction is dated.

## Known residual gaps

- The `--final-model auto` + gate-passes + selected-model-fails-floor path is
  reachable but untested. The floor gate itself is covered via explicit
  `--final-model`.
- `teams.py` resolves org name → team_id → that id's latest roster. A
  migration detector now warns, but the resolution method itself does not
  follow a roster forward across a label change.
- The TI-facing name for the ex-Tundra roster (competing as 1win, possibly
  rebranded again under Valve's gambling-sponsorship rule) should be
  re-checked before any card is published.
- Duration parameters are synced into `config/ti2026_rules.yaml` manually. A
  staleness check warns loudly; nothing threads the fit through automatically.

## Process finding: eleven tests that could not fail

Eleven tests or assertions in this build were incapable of failing under any
implementation bug. **Six of them came from the plan's own text** — the plan
was a demonstrated source of vacuous tests, not merely a vehicle for them.

Three were the same trap: a fixture where two orderings coincide, so the sort
under test is never exercised (`rating_gaps`, `latest_rosters`,
`test_rows_load_in_start_time_order`). Others: asserting a tautology; a
constant 0.5 prediction making log loss position-invariant; asserting a
magnitude smaller than the statistic's own noise floor; a test sitting above
a threshold constant so it never entered the branch it named.

Every one was found by asking of each test "what specific wrong
implementation would this catch?" and mutating when the answer was not
obvious. That question, applied routinely, is the single highest-yield
practice from this build.

---

The full task-by-task record follows, including every ruling, measurement,
and reversal made during execution.

---

# SDD ledger — plan: docs/superpowers/plans/2026-08-02-d2-ingestion-ratings-and-backtest.md

Branch: `d2-ingestion-ratings`, forked from `main` at `3fe75cd`.
Mode: subagent-driven, sequential. Strongest reviewer on Tasks 3, 5, 6, 8.

## Environment notes (carry into every dispatch)

- `uv run` is BLOCKED by the reliability plugin. Use `.venv/bin/python -m pytest`
  and `.venv/bin/ruff check` directly.
- `pyproject.toml:18` sets `pythonpath = ["src"]`, which pytest PREPENDS to
  sys.path. `PYTHONPATH=` cannot override it. Mutation testing must use
  `-o pythonpath=/tmp/...` and verify the override took effect.
- Never mutate tracked source. Mutate a copy under /tmp, then confirm
  `git status --short` is empty. A prior build left a mutation marker in
  committed source this way.
- Reliability gate blocks: force-push, shell loops in commit messages, command
  substitution in mutating commands, unpinned heredoc scripts. Write long
  commit messages to a file and use `git commit -F`.

## Pre-flight scan

Ran a fresh plan review after the eight-item revision (commit 3fe75cd).
Clean: no placeholders, sequential steps in all 8 tasks, no stale references to
the removed `paired_bootstrap` signature, no `0.8` literal in the Glicko
implementation, no hardcoded Python version, no `insert or replace` in code.

One defect found and fixed during that review, before execution: the revised
`paired_differences` zipped predictions against a filtered loss array, which
silently shifts every later pair by one. Fixed inline; pinned by
`test_a_prediction_with_no_matching_row_does_not_shift_the_pairing`.

## Open disagreement, recorded before execution

The user's item 3 asked for opponent-only RD in the expected score. The plan
keeps combined RD in `predict` (outcome prediction) and opponent-only in
`update_rating` (the Glicko-2 update step) — Glickman specifies both, for
different purposes. Pinned by `test_the_two_expected_score_forms_are_deliberately_different`.
Communicated to the user; they said "Go" without overruling. If a reviewer
flags it, this is the ruling, not a defect.

## Carried finding — applies to EVERY remaining task

The plan's verbatim code blocks do not pass this repo's ruff 0.16.1 defaults.
Task 1 hit `BLE001` (blind except), `UP017` (datetime.UTC), `I001` (import
order) and `RUF007` (prefer itertools.pairwise). The plan demands both verbatim
code AND lint clean, which is a contradiction in the plan, not implementer
error.

RULING: lint-clean wins. Implementers may apply the smallest edit that
satisfies ruff — import reordering, `datetime.UTC`, `itertools.pairwise`, and a
targeted `# noqa` for an intentional blind except at the network boundary.
Signatures, behaviour and test assertions must NOT change. Record every such
edit in the task report.

## Task log

### Task 1 — complete

- Commit: `680dbc7` (5 files, +300)
- Tests: 12 new (6 opendota, 6 snapshot); full suite 439 passed; ruff clean
- Controller verified independently: `git status` empty, one commit, expected
  file list, suite and lint re-run by me rather than taken from the report.
- Implementer note: `src/ti26/data/` and both test files already existed
  untracked from the aborted first dispatch (a sonnet agent that died on an API
  error mid-run). The implementer read them, rewrote from the brief, and
  independently reached the same lint fixes. No stale content shipped.
- Review: spec PASS, quality APPROVED. No Critical or Important findings.
  Reviewer confirmed the retry test pins the exact `[1.0, 2.0]` doubling (a
  constant or differently-scaled backoff fails it) and that the immutability
  test reads the file back and asserts the ORIGINAL bytes survive, not merely
  that an exception was raised. No test passes by construction.
- Task 1: minor (deferred): `snapshot.py` uses `gzip.compress()`, which embeds
  wall-clock mtime, so byte-identical rows written seconds apart produce
  different snapshot bytes. Harmless today (`read_snapshot` is unaffected, and
  the reproducibility constraint is about seeded RNG) but `mtime=0` would give
  free byte-determinism if raw files are ever hashed or deduped.
- Task 1: minor (deferred): the "one network seam" constraint names
  `explorer_query`, but the function that actually calls `urlopen` is
  `http_transport`. Plan-wording imprecision, not an implementer defect. The
  seam itself is intact.
- Task 1: minor (deferred): the immutability test runs serially, so it cannot
  distinguish exclusive-create from a correct-in-series `exists()`-then-write.
  The `"xb"` requirement holds by inspection, not by test. A concurrency test
  would be the only way to prove it; not worth it for a single-operator batch
  job, but the claim should not be overstated.

### Task 2 — complete

- Implementation commit: `ac3dd1b` (4 files). Suite 457 passed, ruff clean.
- Plan bug found by the implementer: my brief's Step-4/Step-8 counts (11 schema
  tests / 19 / 458) are off by one against my own verbatim test code, which
  yields 10 / 18 / 457. Documentation error in the plan, not a code defect.
- **Plan bug I authored, caught by me before review:** `tests/test_store.py:88`
  was `assert_no_leakage(...) is None` with no `assert` keyword — a comparison
  that is evaluated and discarded, so the test could not fail. The implementer
  preserved it verbatim under `# noqa: B015` and flagged it rather than
  silently fixing, which was the right call. Ruling: drop the ` is None` and
  the noqa, leaving the bare call; the real assertion is "does not raise".
- Review (sonnet) returned three Important findings, each with a concrete
  reproduction rather than an argument:
  1. `normalize_all` catches only `RosterSlotError`; a missing key or a
     non-numeric duration crashes the whole batch, contradicting the
     "counted tally" constraint. Reproduced both.
  2. `test_a_rejected_conflict_leaves_the_original_intact` asserts only about
     `match_id=1`, so it does not prove batch rollback. The reviewer built a
     non-atomic `insert_rows`, let `match_id=2` leak, and all three existing
     assertions still passed. Pass-by-construction.
  3. Five optional int fields are uncast in `normalize_row` while sqlite
     applies integer affinity on read, so an identical re-ingest can raise a
     spurious `ConflictingRowError`. Reviewer could not confirm reachability;
     **I can**: my earlier live probe showed `accounts` returning JSON strings
     (`'198892029'`), so Postgres bigints do serialise as strings on this API.
     Latent, cheap to close.
- Fix round 1 dispatched to the original implementer: the 6 items above plus
  tests for `has_bad_roster` and `load_rows(since=...)`.
- Task 2: minor (deferred): `','.join(_COLUMNS)` rebuilt per row inside the
  insert loop; negligible at ~3,000 rows/month.
- Task 2: minor (deferred): `# six radiant` comment at tests/test_schema.py:53
  misstates why that case is rejected (slot 5 is in neither slot set).
- Fix commit: `cee2822`. Suite 462 passed, ruff clean, tree clean. Controller
  verified the `# noqa: B015` is gone from the whole repo.
- Scoped re-review: all six findings CLOSED, no new issues. Confirmed the
  `_opt_int` cast preserves `None` (does not coerce to 0), that `has_null_team`
  still reads the raw dict, and that the new re-ingest test genuinely round-
  trips through sqlite rather than comparing two in-memory `normalize_row`
  outputs — which would not have caught the affinity bug at all.
- Task 2: minor (deferred, accepted trade-off): broadening `normalize_all` to
  `except (KeyError, TypeError, ValueError)` means a genuine programming bug
  raising `TypeError` on every row would report as a 100% `malformed_row` tally
  instead of crashing loudly. `AttributeError`/`NameError` still propagate.
  Backstop: `cli_ingest` prints the tally, and Task 8 Step 9 refuses to proceed
  if the ingested row count falls below 35,000 — a mass-failure mode would
  surface there rather than silently shipping a thin store.

### Task 3 — complete

- Implementation commit: `5bb0dfc`. 13 tests, suite 475 passed, ruff clean.
- Mutation verification ran correctly (removing `sorted()` failed
  `test_roster_id_is_order_independent`). The implementer hit a sandbox refusal
  on `rm -rf /tmp/mut`, did NOT route around it, used a differently-named
  scratch dir outside the repo and confirmed `git status` clean. Correct call.
- Review (opus, strongest tier) traced into Tasks 5, 6 and 8 to see how this
  module is consumed, and found a genuine CROSS-TASK defect that way.
- Findings accepted into fix round 1:
  - F1 Important: `continuity` divides by a hardcoded 5.0 with no validation;
    Task 5 feeds the weight unclamped into a `sqrt` that could go negative.
  - F2 Important: Task 2's `-1` missing-account sentinel survives into
    `continuity`'s set intersection, so two rosters each missing a *different*
    player count that `-1` as a shared player and inherit ~0.2 they did not
    earn.
  - F3 Important: `count=False` gates only the map tally, not the
    `_latest_by_team`/`_predecessor` mutations. No outcome leak, but an
    ORDERING leak is possible; safe today only by `run_model`'s call
    discipline, which this class neither enforces nor tests.
  - F4/F6/F7/F8 Minor: undocumented predecessor-first-wins on identical rvid;
    `history()` dead (no caller anywhere in the plan) so being deleted;
    `accounts()` untested; the cross-process test adds no discriminating power
    (sha1 and int-hash are both unsalted) so it becomes a golden-digest test;
    alias investigation moved from the ephemeral report into the config.
- **Carried to Task 5's dispatch:** `GlickoModel.predict` calls
  `observe(row, count=False)` without the `skip_reason` guard that `update`
  applies, so bad-roster rows reach the roster index through the prediction
  path. Must be fixed when Task 5 is written.
- Task 3: minor (deferred): `continuity_with_predecessor`'s
  `_accounts.get(previous, ())` fallback is unreachable under the current
  single-writer design — dead defensive code, harmless.
- Plan bug: Task 3 brief Step 4 says "PASS (9 tests)" but the brief's own code
  block defines 13. Third count error in the plan; documentation only.
- Fix commit: `65d9640`. 18 roster tests, suite 480 passed, ruff clean.
  Implementer re-ran mutation checks and confirmed F1 and F2 are each
  independently load-bearing (reverting either fails exactly its own test).
- Scoped re-review: all 8 CLOSED, no regressions. Specifically confirmed:
  the sentinel filter uses `a >= 0` on BOTH sides (not `!= -1`, which would be
  too narrow, and not `a > 0`, which would wrongly drop account id 0); the
  length validation runs on the RAW lists so filtering a sentinel out of a
  5-element roster does not trip the new ValueError; and the pinned golden
  digest `c0b104983120c180` was recomputed independently and matches.
- **Alias question settled with live data:** Team Vision and PVISION were
  concurrently active for ~352 days, so they cannot be a sequential rebrand.
  `aliases: []` stands, now with a dated four-pair investigation ledger in
  `config/team_aliases.yaml`.
- Task 3: minor (deferred): the PVISION ledger comment frames the 4/5 account
  overlap as "coincidental / unrelated", which is stronger than the evidence.
  By this codebase's own `continuity` metric 4/5 reads as 0.8 — the value its
  tests treat as a normal single substitution. What the evidence actually
  supports is the narrower "not a *sequential* rebrand", which is the only
  claim the alias mechanism models. Worth one line of tightening; not worth a
  fix round for a comment.

### Task 4 — complete

- Implementation commit: `9d05a5e`. 11 new tests, suite 491 passed, ruff clean.
  Counts matched the brief exactly for the first time.
- Controller verified `grep -rn "0\.003" src/` returns nothing — the
  pre-registered threshold exists only in `config/d2_gate.yaml`.
- Findings accepted into fix round 1:
  - F1 Important: `LOGIT_PER_ELO` hardcodes `/400` while `EloModel` accepts a
    configurable `scale` that `predict()` honours. Any non-default scale makes
    `strengths()` inconsistent with that instance's own probabilities — the
    degenerate-simulation failure the logit constraint exists to prevent.
  - F2 Important, **a test I wrote that cannot fail**:
    `assert sum(strengths.values()) == approx(0.0)` is a tautology, since
    subtracting a mean always sums to zero. The reviewer found and empirically
    confirmed the invariant that actually matters — Elo is zero-sum, so the
    centring point is always exactly 1500, which is what makes strengths from
    differently-sized fits comparable — and nothing asserted it.
  - F3 Important: `EwmaModel._rate` is sample-size blind; 1 win and 200 wins
    both clip to `1 - eps`. This is not cosmetic: a FLOOR baseline that emits
    0.999999 takes a catastrophic log-loss hit on one upset, which flatters
    every model above it and makes "beats the naive baseline" hollow. Fixing
    with Laplace smoothing over the decayed counts.
  - F4/F5 Minor: `ConstantModel.skipped` is dead state faking parity with the
    other two models; redundant `return None`; duplicated clip-then-logit.
- Deferred, to verify at Task 8: `strengths()` omits never-rated rosters, so a
  bare `strengths[rvid]` would KeyError. The reviewer traced Task 8's
  `team_strengths`, which guards with `if rvid in strengths` and falls back to
  0.0. Confirm when Task 8 lands.
- Task 4: minor (deferred): `test_repeated_wins_increase_predicted_probability_monotonically`
  uses `seen == sorted(seen)`; equivalent to a non-decreasing assertion, just
  less readable. No change needed.
- Fix commit: `81f14ee`. Suite 494 passed, ruff clean.
- **Process deviation, recorded deliberately:** I did NOT dispatch a scoped
  re-review for this fix round. Instead I verified all five fixes myself by
  direct inspection: `logit_per_point = math.log(10) / self._scale` (elo.py:50),
  the `sum(...) ≈ 0` tautology replaced by
  `test_strengths_centring_point_is_stable_across_differently_sized_fits`,
  Laplace `(wins + 1.0) / (total + 2.0)` (simple.py:48) plus
  `test_ewma_is_more_confident_about_a_longer_winning_streak`,
  `ConstantModel.skipped` deleted (only `EwmaModel` retains it, correctly), and
  the `_logit` helper extracted. The implementer additionally reverted each fix
  and confirmed the two new tests fail against pre-fix code. Reason for the
  deviation: every item was mechanically checkable and I checked each one; a
  dispatched re-review would have added latency without adding evidence. The
  whole-branch review still covers this diff.
- Note: the EWMA Laplace change alters model BEHAVIOUR, not just structure. It
  was accepted because EwmaModel is a floor whose purpose is to make "beats a
  naive baseline" meaningful, and a sample-size-blind floor emitting 0.999999
  takes a catastrophic log-loss hit on one upset, flattering everything above
  it. Recorded here because it is a deliberate deviation from the plan text.

### Task 5 — complete

- Implementation commit: `468de4d`. 18 tests, suite 512 passed, ruff clean.
  The Glickman reference fixture reproduced on the FIRST run with no tuning.
- The mandatory carried fix from Task 3 was applied: `predict` now guards with
  `skip_reason` before `observe`, so a `has_bad_roster` row carrying the `-1`
  sentinel can no longer pollute the index through the prediction path.
- Review (opus) independently re-derived the Glickman fixture from source
  (1464.0507 / 151.5165 / 0.0599960), traced the idle-inflation curve
  numerically (197.24 → 200.25 at idle=10 → 208.23 at idle=40 → capped at 350
  by idle≈988; smooth, monotonic, no premature clamping), and proved the
  inheritance recursion is bounded to depth 1. My `_epoch` corruption concern
  was a false alarm — `predict` never calls `_period_of`.
- **A claim I wrote in the plan is FALSE, and the reviewer proved it by
  mutation.** The plan says the Glickman fixture is "the ONLY test that can
  catch an algebra error in the volatility iteration." It ran three plausible
  transcription bugs in `f(x)` — `tau` for `tau**2`, dropping the square on the
  denominator, and a sign-flipped numerator — and ALL THREE passed inside the
  test's tolerances. Cause is arithmetic, not sloppiness: for this fixture's
  inputs `exp(a) ≈ 0.0036` is negligible against `phi_sq + v ≈ 3.10`, so near
  the root `f(x)` is dominated by the `(x - a)/tau**2` term and the delicate
  algebra barely participates. Glickman's own worked example is simply not a
  stress case for his own solver.
  Fix: a test that transcribes `f(x)` INDEPENDENTLY from the paper and asserts
  the returned volatility actually solves it (`|f(ln(sigma'^2))| < 1e-9`), on
  an input where the exponential term is material — a confident favourite
  (1900, 30) losing to (1500, 30), giving delta^2 ≈ 120 against phi^2+v ≈ 12.
  That input also takes the previously untested `delta_sq > phi_sq + v` bracket
  branch, closing both findings with one test.
- Also fixing: `strengths()`, `rating_deviations()` and `activity_report()`
  silently call `flush()`, so a future mid-period diagnostic call would force a
  PARTIAL period through `update_rating` and fragment it — a silent violation
  of the "periods, not matches" constraint.
- Deferred: the 100-iteration cap returns without signalling non-convergence;
  `fb - fa` has no zero guard (both shared with Glickman's published
  algorithm); two unreachable `.get(..., default)` fallbacks; `rating_of` with
  an `at_period` earlier than `_last_period` silently treats the negative gap
  as no-idle.
- **Carry to Task 6 and Task 8 review:** `roster_index` defaults to `None`, so
  inheritance is silently OFF unless the caller passes one. The plan's factory
  does pass `RosterIndex(aliases)`, but if that wiring is ever dropped the
  model degrades with no error. Verify it ships wired.
- Fix commit: `ca7927b`. 20 glicko tests, suite 514 passed, ruff clean.
- The implementer **pushed back on my suggested test input** and was right to.
  I proposed a single loss for a (1900, 30) favourite; it verified numerically
  that this still leaves the exponential term negligible at the root — the same
  failure mode as the original fixture — and substituted a 100x-repeated-loss
  scenario instead.
- **Controller-verified the central claim rather than accepting it.** I built
  the `tau` vs `tau*tau` mutant in a scratch copy at /tmp/mut5d (using
  `-o pythonpath=`, since PYTHONPATH cannot override pytest's ini setting) and
  ran both tests against it:
      FAILED test_volatility_solution_satisfies_glickmans_published_equation
      assert 8.592900450308822 < 1e-09
      1 failed, 1 passed, 18 deselected
  The new test catches the mutation with a residual of 8.59 against a 1e-9
  bound; the Glickman fixture passes the same mutant. The discrimination claim
  holds. `git status` confirmed empty afterwards — tracked source untouched.
  Note: `rm -rf` is refused by the reliability gate, so the scratch tree was
  left in place rather than routing around the refusal.

### Task 6 — fix round 1 in progress

- Implementation commit: `176593e`. 26 tests, suite 540 passed, ruff clean.
- The implementer self-reported two gaps before any reviewer saw the diff, both
  confirmed: `run_model` has ZERO test references (verified by grep), and the
  two-stage bootstrap's ragged-padding path is never falsified because the
  `clustered()` fixture gives every tournament an identical series count.
- Review (opus): spec PASS, quality CHANGES REQUESTED. **The most consequential
  review of the build — it found a live correctness bug in the gate machinery.**
- **FIX 1, Critical: the two-stage bootstrap CI depends on `memory_budget`.**
  Reviewer verified with numbers: same seed, same data, budget 2,000,000 gives
  [0.004685, 0.016273] and budget 50 gives [0.005080, 0.016120]. Cause is that
  the two-stage branch interleaves `rng.integers` then `rng.random` against ONE
  shared generator once per batch, so splitting draws shifts the stream. The
  single-stage branch is invariant precisely because it makes only one kind of
  call. Fix: two independent generators, one per index type.
  The test meant to catch this used 40 tournaments, above the single-stage
  threshold, so it only ever exercised the safe branch.
- FIX 2, Important: `Prediction.rated`/`.reason` are set in `run_model` and then
  never read. Rows the model refused to train on — null_team and bad_roster,
  ~6.7%+ of maps — are scored anyway, from sentinel rosters, straight into the
  gate margin and CI. Filtering to `rated=True`, with excluded counts reported
  by reason. Trade-off recorded: null_team rows have valid rosters and only lack
  an org id, so this discards some good evaluation data; chosen for train/test
  consistency, to be revisited in D3 with real counts.
- FIX 3, Important: `calibration` returns `(1.0, 0.0)` on a singular Hessian —
  indistinguishable from perfect calibration. Returning NaN instead.
- **FIX 4, Important — another test of mine that cannot fail.** In
  `test_losses_align_by_match_id_not_by_position`, model b predicts a constant
  0.5, and log loss at 0.5 is position-invariant, so reversing the list cannot
  change the result under either a correct or a broken implementation. That is
  the FIFTH vacuous test found in this build.
- FIX 5/6, Important: the gate's both-conditions test never isolates either
  condition (both sub-cases trip both reasons, and one does so because model B
  is simply far worse, not "swamped by noise" as my comment claimed); and
  `test_clustered_interval_is_wider_than_the_iid_one` does not test what its
  docstring claims — a series-only bootstrap ignoring tournaments entirely also
  clears the 1.5x bar (1.69x vs the shipped 1.62x), because the fixture has no
  between-tournament correlation.
- FIX 9/10, Minor: `league_id=None` collapses to one shared sentinel, merging
  all null-league rows into a fake mega-tournament — the exact anti-pattern the
  adjacent comment warns about for `series_id`; and the gate reports "CI
  includes 0" even when the interval is entirely negative (verified on a
  fixture giving [-0.912, -0.590]).
- Reviewer confirmed several things are CORRECT and need no change: `s_idx` can
  never exceed a tournament's series count (`rng.random()` is [0,1)), the mask
  excludes padding from both numerator and denominator, no zero denominator is
  reachable, and **self-leakage is structurally impossible** — `as_of` is
  defined from a league's own earliest row, so no row of that league can ever
  land in its own training slice regardless of how spread out the league is.
- Deferred: O(F·n) repeated scans (measured 0.27s + 0.14s on 41,400 rows / 300
  leagues, dwarfed by the per-fold refit); and whether one OpenDota `league_id`
  really equals one tournament — needs the real ingested distribution, Task 8.


### Task 6 — fix round 1 (implementer, 10 items)

Commit `4c05d4a`. Controller-verified independently, not taken from the report:
full suite 557 passed (`.venv/bin/python -m pytest -q`), `ruff check .` clean,
working tree clean, HEAD = 4c05d4a. `tests/test_backtest.py` grew 26 -> 43.

Environment note: `uv run` is now blocked by the reliability gate ("package or
build script indirection"). Use `.venv/bin/python -m pytest` and
`.venv/bin/python -m ruff check .` for all future tasks; pass this to every
implementer and reviewer dispatch.

Implementer-reported, to be confirmed by re-review rather than trusted:
- FIX 1 pre-fix bug reproduced to 6 decimals matching the reviewer's numbers;
  fixed code claimed batch-invariant.
- FIX 4 a positional reimplementation fails the repaired test, passes the old.
- FIX 6 a series-only stand-in clears the OLD test's 1.5x bar at 1.69x (matches
  the reviewer's own number) but scores 1.0x against the NEW test, failing it.
- FIX 2 implemented as directed; `GateResult.excluded` now carries counts by
  reason. Implementer agreed with the conservative rule and flagged the same
  trade-off unprompted: `null_team` rows lose real evaluation signal,
  `bad_roster` rows genuinely have none.
- Side effect, disclosed not hidden: `test_fold_integrity_rejects_a_league_appearing_twice`
  had `n_train=1` in its `Fold` literal where the true value is `0` — a
  pre-existing bad fixture never checked before this round. Corrected to `0`.
  Re-review must confirm the test still isolates the duplicate-league failure.
- No lint deviations were needed for any fix-round change.

Scoped re-review dispatched (opus) with executable-proof requirements on FIX 1
(batch invariance across budgets + the repaired test actually crosses below
MIN_TOURNAMENTS_FOR_SINGLE_STAGE), FIX 4 and FIX 6 (each must FAIL against a
deliberately broken stand-in), plus a regression sweep: rated filter applied to
BOTH paired models, no test edited to match shifted RNG output, and a
can-this-test-fail check on every test added in the diff.

### Task 6 — re-review round 1: ALL 10 FIXED

Opus re-review verified every fix with an INDEPENDENTLY WRITTEN mutant rather
than the implementer's reported numbers:
- FIX 1: float-identical intervals across 10 memory_budgets (10 .. 2,000,000)
  on a 4-tournament fixture, genuinely below the threshold of 30. Identical to
  the last bit, not merely to 6 decimals.
- FIX 2: mutation-reverted `_aligned` fails its pinning test; a cross-model
  rated mismatch raises `MisalignedPredictionsError` instead of silently
  misaligning the pair. The pairing hazard I was worried about is closed.
- FIX 4: the reviewer's own positional mutant fails the repaired test and
  PASSES the old one -- confirming the old test was vacuous, independently.
- FIX 6: the reviewer's own series-only mutant clears the OLD test at 1.69x
  (matching both the original finding and the implementer's claim, so that
  number is now corroborated twice) and scores exactly 1.0x on the new test.
- FIX 8: a no-mask mutant is numerically identical to the test's unmasked
  reference and fails the width assertion; shipped code is wider.
- FIX 3, 5, 7, 9, 10: fixed and each pinned by a named test.

### Task 6 — controller-fixed Minor, then COMPLETE

Commit `52a808b`. The re-review found a SIXTH vacuous test:
`test_gate_result_exposes_excluded_prediction_counts` used a fixture with zero
unrated predictions, so `excluded == {}` passed identically whether
`evaluate_gate` wired up `excluded_by_reason` or hardcoded an empty dict
(`src/ti26/backtest.py:435`).

Not deferred to the final review, despite being Minor: that tally is the ONLY
evidence a reader has that the gate scored a filtered population, and it is
precisely the instrument Task 8 needs to revisit the FIX 2 `null_team`
trade-off with real counts. A fake instrument would make that ruling
unrevisitable.

Fixed directly (one test, no source change): appends 3 `null_team` + 2
`bad_roster` predictions to both sides, requires them to surface by reason and
`n_maps` to drop by 5. Killed a `excluded={}` mutant:
`assert {} == {'null_team': 3, 'bad_roster': 2}` FAILED, real code passes.

Task 6: complete. Full suite 557 passed, ruff clean.

Running tally of vacuous tests found in this build: 6.

### Task 7 — implementer round 0, DONE_WITH_CONCERNS

Commit `6d19f16`. `src/ti26/duration.py` + `tests/test_duration.py`, plus the
`empirical` provenance tag in spec XII (Step 5). Suite: 565 passed, 1 FAILED.

The failure is MINE, and the implementer's diagnosis understated it. It
reported `test_sensitivity_sweep_detects_that_log_sigma_moves_the_card` getting
max_abs_delta 0.0041 against a required >0.005, checked 5 seeds and a 3x
sample, and called the threshold miscalibrated.

Controller ran the control the implementer did not — SAME sigma, DIFFERENT
seeds, n_sims=20000, tied strengths:

    sigma 0.05 -> 1.20, tied:    0.00500 - 0.00925  (seeds 5,6,7)
    sigma 0.05 -> 1.20, spread:  0.00610 - 0.00695  (seeds 5,6,7)
    SAME sigma, different seed:  0.01065   <-- exceeds every sigma delta

Pure resampling noise is LARGER than any sigma-varying delta. The statistic has
no signal above noise; spread strengths do not rescue it. The implementer's own
"3x sample shrinks the delta to 0.0024" agrees — as noise falls the measured
effect falls with it, the signature of a true effect near zero.

Mechanism: `DurationResolver` averages iid lognormal draws per team, so scaling
log_sigma scales all 16 teams' noise equally and the ranking distribution is
near-invariant. Varying sigma also desynchronises the RNG stream, so the shared
seed buys almost no common-random-numbers variance reduction.

Root cause in the SPEC, not the code: spec XII said the duration model "is
load-bearing, not decorative", conflating "the resolver is consulted on 4.79
lookups per ranking, ~30% of the field" (true, measured) with "the log_sigma
parameter moves the card" (false). Only the first was ever measured.

USER RULING (AskUserQuestion): report a noise floor. `sensitivity_sweep` gains
`noise_floor` (baseline sigma re-run under seed+1) and `resolvable`
(delta > floor), additive to the declared shape. The magnitude assertion is
replaced by structural assertions that can fail. Spec XII gets a dated
correction preserving the 4.79 measurement but retracting the inference.

Two implementer concerns ADJUDICATED IN ITS FAVOUR, no action:
- `config/ti2026_rules.yaml` correctly left unchanged. Fabricating fitted
  values with no ingested data is the exact failure spec XII warns about;
  Step 6's own `git add` omits the file. Belongs to Task 8's runner. Reviewer
  will be told so it is not raised as a spec gap.
- `MapRow.duration` is `int`, not `int | None` — `store.py:14` says
  `integer not null`. My dispatch briefing was wrong; the implementer checked
  the schema instead of trusting me, which is the correct behaviour.

### Task 7 — fix round 1 (noise floor) verified, then task review

Commit `1eb38aa`. Controller-verified: full suite with NO marker filter 566
passed 0 failed, ruff clean, tree clean. No `mark.slow` remains in
`tests/test_duration.py`, so the repaired sensitivity test runs by default
rather than rotting behind a marker.

Task review (opus, spec + quality): **SPEC PASS**, **QUALITY CHANGES REQUESTED**.
Interfaces, the `empirical` tag, and the spec XII correction all match the
brief, with the authorized `noise_floor`/`resolvable` extension.

Controller's two pre-flagged concerns both resolved by measurement:
- CONFIRMED — `log_sigma` means two different statistical quantities depending
  on the branch. Reviewer measured a 5.82% relative gap (0.2657 marginal vs
  0.2502 residual) when `material=True`.
- DISMISSED — truncation bias at [600, 9000] removes <= 1.2e-4 tail mass at
  every parameter set checked. My concern was unfounded; quantified, not
  hand-waved. No estimator change.

### Task 7 — fix round 2 dispatched, four findings

- FIX A (Important): `log_sigma` becomes ALWAYS marginal; new
  `residual_log_sigma` carries the conditional quantity. Matters because
  `DurationResolver` (`tiebreak.py:33-54`) draws unconditionally with no gap
  term, and Task 8 writes this field into the rules config — a conditional
  sigma there understates real dispersion. Also fixes `n`, which reported
  `len(usable)` even when the regression ran on the smaller `paired` subset.
  Materiality logic explicitly unchanged (residual is the right denominator).
- FIX B (Important): the `rating_gaps` ordering test used
  `start_time = 100 + match_id`, so chronological and match_id orderings are
  identical and the test passes under either sort key. SEVENTH vacuous test in
  this build. Reviewer confirmed by mutation that the orderings diverge on a
  conflicting fixture.
- FIX C (Important): `noise_floor` is one seed-pair draw measured ranging
  0.0193-0.0370 across seed pairs 0-9 (1.9x spread) while the docstring calls
  it a stable property of sample size. A floor landing low produces false
  `resolvable=True` — the exact error the noise floor exists to prevent.
  Directed: three baseline runs, take the MAX pairwise delta, and say in the
  docstring that the floor is itself variable.
- FIX D (Minor): `assert result[1]["max_abs_delta"] >= 0.0` is guaranteed by
  `abs()`. EIGHTH vacuous assertion.

Running tally of vacuous tests/assertions found in this build: 8.
Of those, 6 were authored from my own plan text.

### Task 7 — re-review round 2: ALL FIXED. Task 7 COMPLETE.

Commit `8ebcd1d`. Controller-verified: full suite (no marker filter) 568 passed
0 failed, ruff clean, tree clean.

Re-review wrote its OWN mutants rather than accepting the implementer's:
- FIX A: both halves now pin INDEPENDENTLY, which is what mattered — the
  implementer's first attempt had them entangled (the combined mutation failed
  on `n` before `log_sigma` could be isolated). Verified separately:
  `log_sigma=residual` fails `0.2502 == 0.26565 +/-1e-9`; `n=len(usable)` fails
  `20500 == 20000` (`duration.py:110-118`).
- FIX B: a match_id-only sort fails the new test (`gaps[5]`=0.2236 vs 0.0)
  while the OLD test still passes unchanged — direct proof the original was
  blind, not merely weak.
- FIX C: max-of-three confirmed, constant across entries.
- FIX D: tautology replaced with two independently falsifiable assertions.

FIX C hardening, re-measured across seeds 0-9 at n_sims=3000:
    single draw (round 1):  min 0.0193  max 0.0370  spread 0.0177  ratio 1.92x
    max-of-three (round 2): min 0.0290  max 0.0370  spread 0.0080  ratio 1.28x
Spread down ~55%; mean floor up 0.0259 -> 0.0338. Conservative in the intended
direction: a floor that lands low manufactures false `resolvable=True`.

No new defects. No consumer of `DurationFit.n` exists outside `duration.py`,
so the `n` semantics change is contained. `residual_log_sigma` is NaN on both
non-regression paths and is never compared with `==`.

MINOR, deferred to the whole-branch review (not a defect): the noise-floor test
runs 5.00s wall-clock, longer than every test this repo DOES mark
`@pytest.mark.slow` (1.3-4.0s), while itself being unmarked. The marker
convention is now inconsistent. Left unmarked deliberately — an unmarked test
runs by default, and this build has already seen a marked test hide a real
failure.

### Task 8 — dispatched (opus)

BASE = `8ebcd1d`. Brief is 890 lines, the largest of the eight. Dispatch carries
the full consumed-interface surface from Tasks 1-7 plus D1's card CLI flags,
since no earlier task's implementer context is available to it.

Two hazards called out explicitly in the dispatch:
- `GlickoModel.strengths()` is keyed by ROSTER VERSION ID, not team id, and
  calling it flushes the current rating period.
- `DurationFit.log_sigma` is the MARGINAL sigma and is what belongs in
  `ti2026_rules.yaml`; writing `residual_log_sigma` there would understate
  duration dispersion by ~6% (measured, Task 7 FIX A).
- D1's `cli.py` invents a synthetic t00..t15 ladder when `--strengths` is
  omitted. That silent fallback is the exact bug revision item 1 exists to
  close, so `cli_d2` MUST pass `--strengths`.

The dispatch also hands the implementer the full catalogue of this build's
eight vacuous-test patterns, and states plainly that the brief it is reading
is a demonstrated source of them (six of the eight came from plan text).

### Task 8 — round 0, DONE. The pipeline ran for real.

Commit `514cb71`. Controller-verified: full suite (no marker filter) 581 passed
0 failed, ruff clean, tree clean.

Real end-to-end run: 41,140 maps ingested (snapshot 20260802T165535Z, 19 months
2025-02 to 2026-08, 0 rejected). Store at `data/processed/d2.sqlite`, 9.9MB,
gitignored. Artifacts in `reports/`.

Four implementer deviations, all evidence-backed, ALL ACCEPTED:
- The brief's verbatim `cli_d2.py` calls `final.flush()` unconditionally, which
  crashes on every gate-FAIL run because `EloModel` has no `flush()`. A FAIL is
  a legitimate expected outcome, not an edge case — confirmed live, since the
  real run hit exactly that path. Guarded with hasattr, matching `run_model`.
- Three of the brief's own `test_cli_d2.py` cases omitted `--teams`/`--skip-card`
  and so depended on the ambient teams config in a way no state of that file
  could satisfy for all three at once. Added `--skip-card`.
- `http_transport` needed a non-default User-Agent: OpenDota returns 403 to
  urllib's default UA and 200 to any other, confirmed both ways on one URL.
- `test_rules.py`'s provenance allowlist needed `empirical` — the brief
  pre-authorized this as a test defect rather than grounds to revert the fit.

### Task 8 — CRITICAL controller finding: nothing beats the spec V floor

Computed from `reports/backtest_metrics.csv`, all four models on identical
n=28923:

    constant (ln 2)  0.6931472    (verified: math.isclose to ln 2)
    elo              0.6944614    +0.0013142 WORSE than floor
    glicko           0.6982921    +0.0051449 WORSE
    ewma             0.7065461    +0.0133990 WORSE

Spec §V verbatim: "Ordered floor-to-ceiling. Each must be beaten on rolling
out-of-sample log loss to justify the next." Rung 1 is the constant 50/50
model. EVERY rating model loses to a coin flip.

`cli_d2` measures this and never enforces it — `selected = args.final_model`
(`cli_d2.py:93`) is a plain flag. So the card shipped from Elo while
`d2_gate.md`'s own Consequence section said to ship the rung-3 fallback. The
report contradicted the runner.

Not the implementer's error: the brief never specified a floor gate. It is a
plan/spec gap that only became visible once real numbers existed. The
pre-registered gate (Elo vs Glicko) was necessary but not sufficient — it
compared two models to each other and never to the floor beneath both.

Diagnosis, recorded for D3: calibration slopes 0.2126 / 0.4448 / 0.4023 against
1.0, with accuracy ABOVE 50% for all three (0.5265 / 0.5363 / 0.5439). The
ranking carries signal; the probability scale is roughly 2.2x too wide.
`calibration()` computes slope and intercept on every run and nothing applies
them.

USER RULING (AskUserQuestion): enforce the floor, ship rung 3. NO calibration
layer now — applying it after seeing these results and re-running the same
pre-registered gate is post-hoc, which is what pre-registration exists to
prevent. Calibration becomes D3 with its own pre-registration.

Fix dispatched: floor gate in `cli_d2`, refusal to write a card from a
disqualified model, distinct non-zero exit, self-consistent `d2_gate.md`, and a
floor-comparison table. Tests must cover BOTH directions of the gate and must
not assert on the real run's numbers, which change on re-ingest.

Also asked the implementer to reconsider (not merely keep) the brief's
outcome-invariant `constant` log-loss assertion it flagged: that value is now
the floor every other model is judged against, so it is load-bearing in a way
it was not when the brief was written.

### Task 8 — team list sent for independent fact-check

The 16-team TI 2026 field was resolved by one agent's web research. That is a
Rule 9 exhaustiveness claim gating the actual deliverable, so it is being
re-checked by a fresh context-isolated agent given only the claim — no
reasoning trail. Entries flagged for scrutiny: Team Yandex, Vici Gaming
(long inactive), GamerLegion (a CS org), and "LGD Gaming" recorded as a South
American team formed from a former HEROIC roster, which would be a different
entity from the Chinese LGD. Also checking the Tundra/"1win" sponsor change
the implementer could not resolve, and the Nigma Galaxy roster handoff behind
the one alias added.

### Task 8 — independent fact-check of the 16-team field: PASS with two errors

Fresh context-isolated agent, given only the claim and no reasoning trail.

CONFIRMED CORRECT: all 16 orgs, the 7-invite/9-qualifier split, and the format
(16-team single Swiss, Aug 13-16, all Bo3; top 3 straight to playoffs, 4th-13th
to an elimination round). Every entry I flagged as suspicious checked out —
Team Yandex is a real EEU invite; Vici Gaming genuinely qualified via China's
second slot; GamerLegion does have an active Dota division and won NA; and
"LGD Gaming" is the Chinese org, which signed the SA ex-HEROIC roster in late
May, so both of the implementer's notes were true simultaneously. Its ambiguity
ledger was sound.

TWO ERRORS, both then resolved against our own store rather than by argument.

**Tundra Esports is stale.** The org exited Dota 2 on 2026-06-01; the roster
moved to 1win and the TI invite followed the roster. (Valve's TI15 sponsorship
rules are what forced BetBoom -> BoomBoys; 1win is likewise a gambling brand,
so the TI-facing name may be another rebrand — re-check before publishing.)

Queried by ACCOUNTS, the identical five
`[86698277, 93618577, 136829091, 331855530, 346412363]` appear under three
team_ids:

    8291895 (Tundra Esports)  189 maps  2025-10-14 .. 2026-05-18
    10150413                   24 maps  2026-05-19 .. 2026-05-30
    10182357                   21 maps  2026-07-07 .. 2026-08-02

All three yield the SAME rvid `e0492e01c08d07f5`. The rating already spans all
234 maps: account-derived identity carried through two org changes unaided.
`strengths.csv` has the right rvid and `prior_driven=False`. So the STRENGTH is
correct and only the display NAME is wrong. The implementer's resolution method
(org name -> team_id -> that id's last roster) worked here ONLY because the
roster did not change after 05-18; that limitation is now to be documented.

**The Nigma alias note asserts what our data contradicts.** The note claims the
7554697 -> 10136357 handoff is "a genuine roster change, not a duplicate — 3 of
5 accounts carry over". Measured at the 05-08 -> 05-09 handoff:
`continuity = 1.000, leaving [], joining []` — both sides are roster
`3e38bebcf099aea5`, identical five accounts. A pure duplicate team_id, exactly
the category the note denies.

The real change is later and INSIDE one team_id: `3e38bebcf099aea5` ->
`3ea16a8a0fbc3023`, last old map 2026-06-03, first new 2026-06-21, both under
10136357; 140297552 and 418942836 leave, 111620041 and 210053851 join. That is
the 3/5 the note cites, attached to the wrong event. The fact-check
independently dated the public SumaiL/Lorenof change to ~2026-06-08, fitting
the June transition and not the May one.

Directed: correct the note; reconsider whether the alias earns its place at all
(both sides of the May handoff already share one rvid, and an org-level alias
does nothing for a change that never crosses a team_id boundary); confirm the
June roster inherits its prior rather than restarting from 1500/350.

Both errors were found by QUERYING the store, not by reasoning about it. A
config note asserting a continuity figure the data disagrees with is worse than
no note — it looks like evidence.

### Task 8 — fix rounds 1 and 2 verified

`aefac3c` (floor gate + team ledger corrections), `64cd61c` (sweep restored,
map counts corrected). Controller-verified at `64cd61c`: full suite no marker
filter 583 passed 0 failed, ruff clean, tree clean, `duration_sensitivity.json`
back in `reports/`.

Round 1 delivered:
- Floor gate in `cli_d2`. `cleared` requires STRICTLY lower log loss — a tie is
  not a beat, which is the correct reading of spec V. Refuses to write a card
  and does NOT silently substitute another model. Exits 3.
- `d2_gate.md` now states one consistent outcome with a floor-comparison table,
  where before its Card and Consequence sections contradicted each other.
- Nigma alias REMOVED, proven a no-op empirically rather than by argument:
  fitting Glicko over the full store with and without it yields the identical
  strength 2.324358513350741. Ledger corrected to describe the real May
  duplicate vs the June roster change.
- Tundra entry repointed to team_id 10182357, display name "1win".
- Cross-reference the implementer found unprompted: team_id 10150413, the
  Tundra roster's middle identity, is the SAME id Task 3's alias ledger
  investigated as a candidate HULIGANI predecessor and correctly declined. Two
  unrelated identities under one OpenDota id; both investigations independently
  reached the right answer.
- Constant-model assertion STRENGTHENED rather than merely kept: since
  `ConstantModel` always predicts exactly 0.5 its log loss is exactly ln(2),
  not an estimate, so the tolerance tightened to `abs=1e-9`. Now genuinely
  pins the floor value the new gate depends on.

Round 2, both controller-found:
- REGRESSION the floor fix introduced: `sensitivity_sweep` and
  `duration_sensitivity.json` sat inside the floor-cleared branch, so on this
  data they never ran. That breaks the user's revision item 5 (a sweep nobody
  runs cannot report anything) and matters MORE on the fallback path, since the
  fitted duration model still ships into `ti2026_rules.yaml` as `empirical` and
  the rung-3 card runs against those same rules. Now computed on both paths,
  labelled "diagnostic only, not endorsed: disqualified elo strengths".
- The corrected Tundra note repeated the Nigma failure mode: it quoted 447 maps
  (team_id 8291895's ALL-ROSTERS total) inside a sentence describing the
  five-account roster, whose real count is 189. 189+24+21=234 matched the
  note's own total; 447 did not. Now both figures are present and labelled as
  distinct populations, and 2025-02-08 is confirmed as the team_id's first map
  rather than the roster's.

`strengths.csv` stays withheld on the refusal path — it is the card's direct
input, and writing it invites running the card manually from a disqualified
model. The sweep only ever needed the dict in memory.

### Task 8 — full spec+quality review dispatched (opus, strongest per user)

Range `8ebcd1d..64cd61c`, 3 commits. Seven controller rulings fenced off as
settled. Attention directed at: floor-gate tie handling and both-direction
tests, reachability of the non-zero exit, determinism across re-runs, whether
`teams.py`'s org-name-first resolution fails SILENTLY for a team whose roster
changed after its last map under the configured id, and cross-file consistency
between `d2_gate.md`, `backtest_metrics.csv` and `duration_fit.json`.

### Task 8 — full review: SPEC PASS, then fix round 3. Task 8 COMPLETE.

Review verified determinism by ACTUALLY re-running `cli_d2` twice against the
live 41,140-map store: exit 3 both times, `diff -rq` zero differences, stdout
byte-identical. Card generation confirmed unreachable except on the
floor-cleared branch, so the synthetic t00..t15 ladder can never ship.

Fix round 3, commit `61256a5`. Controller-verified: full suite no marker filter
590 passed 0 failed, ruff clean, tree clean.

- NINTH vacuous test, mutation-confirmed by the reviewer:
  `test_latest_roster_wins_over_an_earlier_one` used a fixture already in
  chronological order, so deleting the `sorted()` it claims to test changed
  nothing. Same trap as `rating_gaps` in Task 7. Fixed, and the implementer
  applied the question to its neighbours and found a TENTH on its own —
  `test_unrated_rosters_get_the_average_prior_and_are_named` had a
  single-entry list that never exercised its own `sorted()`. Both
  mutation-confirmed.

- ROSTER MIGRATION DETECTOR built (`teams.py`). Forward account search for the
  same roster under a later different team_id, plus a plain staleness report.
  Chose WARN over hard-fail, correctly: three known-benign duplicate ids are
  indistinguishable from a migration by data alone, and a false positive would
  block a correct run days before the 2026-08-13 lock.

  Run against all 16 configured teams: 5 hits, ZERO requiring a config change.
  Xtreme Gaming / HULIGANI / Team Resilience reconfirmed as known duplicates.
  Two NEW findings, both independently verified by the controller against the
  store rather than accepted:

  * LGD Gaming: configured 10150538 and detected 10208068 both field rvid
    `16963a41ac6a1b2e`, continuity 1.000, ranges OVERLAP (05-26..08-01 vs
    07-31..08-01). Overlap = concurrent = duplicate, not migration. This is
    exactly the signature specified to separate the two cases: the Tundra ids
    were sequential and non-overlapping. Configured id still active through
    08-01. Correct call, no change.
  * Team Vision: current roster `c298aa3eb4837f25` appears under 9572001
    (05-08..06-25) and 9824702 (05-26..07-19). Overlapping, so duplicate. The
    configured id is ~3.5 weeks staler, but identical rvid means the rating
    merges anyway — the same mechanism that protected the Tundra strength. The
    detector also found the PRE-EXISTING ledger entry was itself wrong:
    PVISION's roster is bit-for-bit identical from 2026-05-26, not the 4/5
    overlap previously recorded. Corrected.

  The detector works and its duplicate-vs-migration classification is sound on
  every case in the real data.

- Controller resolved the review's one "cannot verify" item directly:
  `run_model` (`backtest.py:147-157`) populates all six provenance fields.
  Not a gap.

DEFERRED to the whole-branch review, with measurements, NOT fixed:

Suite runtime went 2:06 -> 4:33. Four `test_cli_d2.py` tests take 55-63s each,
~85% of total. Cause is structural, not `--card-sims` (three of the four
already pass 3000): `noise_store` builds 3,600 rows across ~41 leagues, so
~40 folds x 4 models refit from scratch. That is the cost of the "test the
production call path" global constraint.

Not fixed deliberately. Shrinking the fixture risks making the floor test
FLAKY, and a flaky floor gate is worse than a slow one — that test is what
proves elo (0.7185) loses to the constant floor (0.6931) on zero-signal data.
The real defect is the marker convention, which is now inverted: these
55-63s tests are unmarked while `test_invariants.py` and `test_montecarlo.py`
mark 1.3-4.0s tests `@pytest.mark.slow`. That spans files from D1 and multiple
D2 tasks, so it is a whole-branch question, not a Task 8 fix.

Running tally of vacuous tests/assertions found in this build: 10.
Six of the ten came from my own plan text.

### Whole-branch review — CHANGES REQUIRED, but the negative result HOLDS

19 commits, `3fe75cd..61256a5`, reviewed on opus.

**The single most important verdict: the FAIL is genuine.** The reviewer
independently re-ran `cli_d2` against the live store and got byte-identical
reports, then ruled out, one at a time, every mechanism that could manufacture
a false negative:
- same scored population across all four models (28923 raw / 26830 rated)
- prediction direction and margin sign NOT inverted, for all three models
- refit-from-scratch per fold is mathematically equivalent to one continuous
  walk — the fold loop is not distorting anything
- rosters DO repeat: mean 6.23 maps per roster, so ratings are not perpetually
  cold-starting
- Elo's probabilities are NARROW (0.16-0.86), not extreme or clipped — so the
  loss is not coming from confident tail predictions
- no leakage, fold-construction or units error anywhere

Conclusion: the models are directionally correct and overconfident
(calibration slope 0.21-0.45, accuracy above 50%). That is the textbook way a
forecaster beats a coin flip on accuracy and loses to it on log loss. The
result is a property of the data and the models, not a bug.

Six findings, all latent, none invalidating the above:
- IMPORTANT `cli_d2.py:135-137` — "auto" falls back to Elo (rung 2) on gate
  failure; spec X says public ratings (rung 3) are the default when the
  forecast-value gate fails. Latent only because Elo also fails the floor.
  Untested for gate-fails-but-model-clears-floor, which is reachable on other
  data. Directed: converge both failure paths on the same refusal.
- IMPORTANT `cli_d2.py:256-264` — the card reads duration parameters from the
  static rules YAML, not the fit computed in the same run, and the comment
  claims a sync that does not exist. Live hazard before the 08-13 lock: any
  re-ingest refits, and the card would silently use the prior run's values.
  Same defect class as the two config notes corrected earlier — an assertion
  in prose that the code does not honour.
- IMPORTANT `GateResult.excluded` computed, never printed. THIS ONE IS MINE:
  I repaired a vacuous test in Task 6 specifically so this would be a real
  instrument for Task 8 to revisit the null_team exclusion with real counts,
  and then never required Task 8 to surface it. The gate reports 28923 maps
  and 26830 compared; the ~2100 difference is currently unexplained to a
  reader. Directed into `d2_gate.md`.
- MINOR ELEVENTH vacuous test, mutation-confirmed:
  `test_store.py::test_rows_load_in_start_time_order` confounds match_id order
  with start_time order. Third instance of the identical trap, after
  `rating_gaps` and `latest_rosters`.
- MINOR `check_roster_staleness`'s earliest-hit tie-break has zero coverage —
  mutating to latest-hit passes all 22 relevant tests. Newest code on the
  branch, and it guards the real team list.
- MINOR `n_predictions` in `backtest_metrics.csv` is the raw count (28923),
  not the scored population (26830), while sitting in the same table as the
  log-loss values the floor comparison depends on.

Network seam, leakage-assertion wiring, and reports/config artifact
consistency all checked CLEAN across the whole branch.

**Slow markers — resolution adopted.** Broaden the marker definition from its
current narrow scope ("Monte Carlo convergence" / "hits the real API") to
"disproportionately slow for a dev loop; always run at final verification",
then mark the four 55-84s `test_cli_d2.py` tests. Fixtures are NOT shrunk: the
floor test's validity rests on the measured elo-vs-constant gap and a flaky
floor gate is worse than a slow one. Condition attached, from the Task 7
incident where a slow-marked failing test was excluded from the brief's own
verification runs for a full round: the marker's documentation must state that
final verification runs unfiltered.

Running tally of vacuous tests/assertions found in this build: 11.

### Final fix round — all six landed, `f722465`

Controller-verified: unfiltered 593 passed 0 failed; `-m "not slow"` 585 passed
8 deselected in **19.4s** (was 4:40). Ruff clean, tree clean.

Confirmed live in the artifacts, not just in the diff:
- FIX C: `d2_gate.md` now carries the exclusion arithmetic — 28923 total minus
  2093 excluded is 26830 compared, and ALL 2093 are `null_team` with zero
  `bad_roster`. That is 7.2%, consistent with spec III's measured null-team
  rate. The instrument I built in Task 6 is finally being read.
- FIX A: refusal wording now cites the gate-forced rung 3 explicitly — "spec X:
  rung 3 is the default on a failed gate, never a quiet fallback to rung 2".
- FIX B: "Config staleness check" line present and currently matching.
- FIX F: `n_scored` column added alongside `n_predictions`.
- Five `@pytest.mark.slow` markers on `test_cli_d2.py`.

FIX B — implementer DECLINED the auto-thread and argued instead of complying,
which is the behaviour I want. Its case: the documented Step 10->11->13
workflow deliberately builds a card on the outgoing config before manual sync,
so a mid-workflow mismatch is sometimes expected rather than always a bug;
auto-threading would require touching D1's `cli.py`, outside this branch.
Shipped a staleness check with a stdout WARNING plus a report line, and fixed
the comment that falsely claimed automatic sync. Accepted — the hazard is now
visible rather than silent.

### Risk FIX A introduces — sent to scoped re-review as the priority item

FIX A makes gate-failure refuse BEFORE the floor logic is consulted. On this
data the gate always fails, so the floor refusal no longer fires on the `auto`
path at all. The question is whether the spec V floor gate is now DEAD CODE.

It should still be reachable via an explicit `--final-model`, or via a gate
that passes while the selected model loses to the floor. "Should" is not good
enough for a gate that exists because of an explicit user ruling — if it can
never fire, that ruling has been quietly undone. Re-review directed to
enumerate every reaching path and confirm each is covered by a test that can
fail.

### Controller-authored commit `3782998` (docs only, outside the re-review range)

The D1 differential audit (`docs/audits/2026-08-01-d1-differential-audit.md`)
twice states the duration model is "explicitly tagged `arbitrary` by the repo
itself" at 7.65 / 0.25. This branch made both statements false. Same defect
class held against every agent this build: prose asserting what the code no
longer supports.

Added as a DATED ADDENDUM, not an edit to the findings — an audit is a record
of the tree it examined, and its scoping decision not to check the duration
parameters was correct at the time. The addendum also closes the audit's
"no ingestion path yet" limitation and records the two measured results
bearing on its open questions. Nothing in the D1 rules engine it examined was
found wrong by D2. Ruff clean, tree clean.

### Scoped re-review STALLED — controller verified the priority item directly

The scoped re-review agent stalled after 600s with no report written. Rather
than resume a stalled agent on the question that gates merge, the controller
answered it directly from the source.

**VERDICT: the spec V floor gate is NOT dead code.**

`gate_forced_rung3` is assigned only inside `if selected == "auto"`
(`cli_d2.py:152-164`), so with an explicit `--final-model` it is always False
and `card_refused = gate_forced_rung3 or not floor[selected]["cleared"]` falls
through to the floor condition. Two paths reach a floor refusal:

1. Explicit `--final-model X` where X loses to the floor. TESTED —
   `test_disqualified_final_model_writes_no_card_and_exits_with_the_floor_code`
   passes `--final-model elo`; run in isolation, passes in 52.67s, asserting
   `rc == NO_CARD_EXIT` (3) and the absence of both `strengths.csv` and
   `recommended_card.json`.
2. `--final-model auto` + gate PASSES (selected becomes glicko) + glicko fails
   the floor. Reachable, NOT tested — needs a fixture where Glicko beats Elo
   yet both lose to the constant. Narrow residual, recorded not fixed.

Additionally: the floor CHECK and its report table run unconditionally,
independent of which refusal fires, so the floor evidence is never suppressed.
Only the refusal message varies. A single `NO_CARD_EXIT = 3` covers both
reasons, as directed — a caller cannot distinguish them by exit code, but the
report names which fired, and both mean the same thing operationally.

Fixes A, B, C and F confirmed directly in the generated artifacts (see the
previous entry). FIX B's corrected comment read in full and is accurate: it
states plainly that `cli.main` calls `load_rules` itself and cannot receive
this run's fitted values, that the sync is manual, and why hard-failing would
break the documented Step 10->11 sequence.

Narrow re-check dispatched for the two items not independently verified —
FIX D's and FIX E's mutation claims — plus a vacuity sweep limited to commit
`f722465`. Scope deliberately kept small; breadth is what stalled the last
agent, and the new dispatch is instructed to write its report file early and
update as it goes so partial results survive an interruption.

### Narrow re-check: FIX D and E CONFIRMED, no vacuous tests in f722465

Independent mutants, not the implementer's numbers:
- FIX D: `order by start_time, match_id` -> `order by match_id` fails exactly
  `test_rows_load_in_start_time_order` (`assert [3000, 1000, 2000] ==
  [1000, 2000, 3000]`). Full filtered suite 1 failed / 584 passed against
  baseline 585 — no masking, no other test flips.
- FIX E: tie-break flip (`ts <` -> `ts >`, `teams.py:208,212`) fails exactly
  `test_the_earliest_migration_hit_is_reported_not_the_latest`
  (`assert 888 == 999`). The claimed test already existed; nothing missing.
- FIX A independently pinned: reverting `gate_forced_rung3` to `False`
  produces `rc=0` and a written card ("generated from elo strengths"), and
  `test_gate_failure_under_auto_forces_rung_3_even_if_the_model_clears_the_floor`
  correctly fails `assert 0 == 3`. Note that test covers the exact combination
  the whole-branch review said was untested.
- Every test added in `f722465` PINS something. None vacuous. Tally stays 11.

### GAP the narrow check surfaced — three fixes have NO tests

`grep` for `excluded|n_scored|duration_stale|Config staleness|WARNING` across
`tests/test_cli_d2.py` returns exactly ONE hit: the migration WARNING at line
188. So FIX B (duration staleness warning + report line), FIX C (exclusion
counts and arithmetic in `d2_gate.md`) and FIX F (`n_scored` column) are all
unpinned. Verified by reading generated artifacts, which proves they work now
and nothing about tomorrow.

FIX C is the sharpest instance. I repaired a vacuous test in Task 6
specifically so `GateResult.excluded` would be a real instrument, then
directed Task 8 to surface it — and the surfacing has no test. The same
"instrument built, never consumed" pattern the whole-branch review found,
one level further out.

Final dispatch: one test each, all fast (`--skip-card`, following
`test_reported_verdict_agrees_with_the_reported_numbers`, NOT the 55s card
tests). Assertions must pin RELATIONSHIPS not literals — total minus summed
exclusions equals compared; `n_scored` equals the rated count and is less than
`n_predictions` when unrated rows exist; staleness driven BOTH ways. Each must
be proven to fail against a mutation of the thing it pins.
