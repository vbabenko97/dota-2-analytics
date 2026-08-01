# SDD ledger — plan: docs/superpowers/plans/2026-08-01-d1-rules-engine-and-card-generator.md

Branch: d1-rules-engine (branched from main at 88e753d)
Isolation: feature branch rather than a worktree — single-branch repo, no
remote, no concurrent work; the branch supplies the actual safety property
(no implementation commits on main).

Pre-flight scan: one conflict found and fixed in the plan before execution —
`test_config_contains_no_capacity_literals` grepped raw YAML for "capacities",
which the provenance block legitimately contains. Fixed in 88e753d.

## Environment
- `uv run` is blocked by the reliability plugin (package/build script
  indirection). Verified working substitutes, use these in every dispatch:
  - `.venv/bin/python -m pytest <args>`
  - `.venv/bin/ruff check src tests`
- venv is Python 3.13; `requires-python = ">=3.12"` is satisfied.

## Task log

Task 1: NEEDS_CONTEXT (implementer a43d5b817de494d3d) — two blockers, both real:
  (a) `uv run` blocked by plugin; resolved with the direct-venv commands above.
  (b) Implementer found a genuine plan defect:
      `derive_record_capacities(8, 3, 3, 5)` reaches a (2,1) group of size 3
      at round 4 and raises. Confirmed independently by running the test:
      `1 failed, 12 passed`. Fixture parameters were wrong, not the algorithm.
      Fixed in plan commit 8483605 (total_rounds 5 -> 3, plus two assertions).
      Brief regenerated. Implementer resumed.
Task 1: DONE (commit 701adae) — 13 passed, ruff clean.
Task 1: review — spec PASS, quality approved with findings.
  Important (plan defect, fixed by controller in 2653db8): Task 1 Interfaces
    line documented `TeamState.active`, which the code correctly omits in
    favour of `Rules.is_active(team)`. Later briefs are generated from that
    text, so Tasks 2-8 would have been written against a missing property.
  Important (code, fix round 1 dispatched): `ruff>=0.6` unpinned + `uv.lock`
    untracked -> lint outcomes not reproducible. Decision: commit uv.lock;
    do NOT add `[tool.ruff.lint] select` (default set passes and caught a
    real SIM115 issue; narrowing trades signal for churn).
Task 1: minor (deferred): `derive_category_capacities` omits zero-count
  categories from the returned dict, so a format yielding none of a category
  raises KeyError on lookup instead of reading 0. Not reachable for 16/4/4/5.
Task 1: minor (deferred): `test_config_declares_no_capacity_values` never
  checks that `record_capacities` is absent as a top-level key, so the
  anti-duplication guard is narrower than its docstring claims.
Task 1: minor (deferred): `test_random_baseline_is_derived` first assertion
  recomputes the same formula as `Rules.random_baseline` and is tautological;
  only the `== 3.75` literal is an independent check.
Task 1: nit (deferred): provenance keys mix `Rules` attribute names with raw
  config key names within one block.
Task 1: fix round 1/5 (1 addressed, 0 open — uv.lock committed and tracked,
  pins ruff==0.16.1; commits 701adae..0f87c43)
Task 1: complete (commits 8483605..0f87c43, review clean)

Task 2: DONE (commit 571207c) — 13 new tests, 26/26 suite, ruff clean.
  Implementer deviation, verified behaviour-neutral by the reviewer: dropped
  the brief's `# noqa: E731`, which RUF100 flagged as unused because E731 is
  not in this project's active ruff rule set. My plan text was wrong there.
Task 2: review — spec PASS, quality approved with findings.
  Reviewer confirmed `_primary_key` signs term by term against the official
  order, and that no path reaches the coin toss before the duration raise.
  Fix round 1 dispatched with two findings, both silent-degradation paths:
    A (Important): `_primary_key` silently drops opponent ids absent from the
      passed state list, under-counting criterion 3 and skewing criterion 5.
      Unreachable today (all callers pass the full list) but a natural future
      misuse, and this engine faces a differential audit where silent
      data-dependent divergence is the worst failure mode.
    B (Minor, deliberately bundled — same file, same class, one dispatch):
      `DurationResolver.average_for` returns a stale larger-sample average if
      called with a smaller `maps_played` than cached.
  Controller decision: bundling B with A rather than deferring it, because it
  is the same silent-degradation class in the same module and costs no extra
  dispatch. Recorded as a deviation from the usual minors-never-enter-the-loop
  rule.
Task 2: minor (deferred): `sorted(block, key=(duration, rng.random()))` draws
  one random per block member even when durations are distinct. Deterministic
  and idiomatic; explicitly told the implementer NOT to change it — grouping
  first would add complexity for no behavioural gain.
Task 2: minor (deferred): `consultations` increments before the
  `maps_played <= 0` raise, so failed calls count as consultations.
Task 2: nit (deferred): `_primary_key` returns a bare `tuple` annotation.
Task 2: nit (deferred): `test_ranking_is_a_permutation_of_input` checks only
  permutation, not order — a smoke check, not an ordering validation.
Task 2: fix round 1/5 (2 addressed, 0 open — unknown opponent now raises
  ValueError naming team+opponent; average_for raises DurationUnavailableError
  on shrinking maps_played; both protected items verified untouched;
  commits 571207c..5481e88)
Task 2: complete (commits 0f87c43..5481e88, review clean) — 15 in
  test_tiebreak.py, 28/28 suite, ruff clean.

Task 3: DONE (commit 58fa810) — 14/14 test_pairing.py, 42/42 suite, ruff
  clean, brief reproduced verbatim with no lint deviations.
Task 3: review — spec PASS, implementation logic verified CORRECT by an
  independent brute-force script (perfect_matchings matches (n-1)!! for
  n=4/6/8 and is duplicate-free; repeat minimisation runs on the
  post-group-filter set). All findings are about test quality, not src.
  Fix round 1 dispatched with five findings:
    A (Important): both forced-repeat tests are VACUOUS — every matching in
      each fixture ties at the same repeat count (1 and 2), so both would
      pass with repeat-filtering deleted. Replacement fixture supplied:
      prior a-b, a-c, a-d, b-c gives matchings scoring 1/1/2.
    B (Important): the determinism test exercises no randomness — the
      min-distance matching is unique (1 of 105), so rng.choice runs on a
      one-element list and the test would pass with a module-level RNG,
      violating a Global Constraint.
    C (Important): `candidates_considered` counted pre-filter; renamed to
      `total_matchings`. Declined a second post-filter count as speculative.
    D (Minor, bundled): count tests never assert matchings are distinct.
    E (Minor, bundled): `perfect_matchings` silently yields empty on odd
      input despite being a public export — same silent-degradation class
      already fixed in Task 2.
  Asked the implementer to state whether each new test FAILS when the logic
  it targets is temporarily removed.
Task 3: nit (deferred): bare KeyError when `group_of` lacks a team under
  cross_group=True; told implementer to leave it, guarding is speculative.
Task 3: fix round 1/5 (5 addressed, 0 open; commits 58fa810..680d7a2)
  Re-reviewer independently mutated the source to verify discrimination:
    - deleting the repeat-minimisation filter fails the NEW test while both
      ORIGINAL forced-repeat tests still pass, confirming the originals were
      vacuous and the replacement is not;
    - bypassing rng (`chosen = candidates[0]`) fails the new multi-way-tie
      determinism test across all 8 seeds.
  Honest caveat it volunteered: a second mutation (module-level random.choice)
  was caught in only 7 of 8 fresh-process runs, because global-RNG luck can let
  same-seed calls coincide. That is a limit of that mutation, not of the test.
Task 3: INCIDENT — the re-reviewer stopped mid-run and left MUTATION_B2 in the
  tracked file src/ti26/pairing.py despite being told not to. Controller
  restored via `git checkout --`; nothing was committed; suite back to 45.
  Second resume was told to mutate a /tmp copy instead — tree verified clean
  afterwards. Lesson for later dispatches: state the no-mutation rule AND
  verify `git status` after any reviewer that was allowed to run code.
Task 3: complete (commits 5481e88..680d7a2, review clean) — 17 in
  test_pairing.py, 45/45 suite, ruff clean. Plan text updated to match the
  `total_matchings` rename and the odd-input raise (plan commit 251c8c7).

Task 4: DONE (commit c4f0cb1) — 9/9 test_series.py, 54/54 suite, ruff clean,
  brief reproduced verbatim, no deviations. Implemented on haiku (12 tool
  calls) — cheapest tier is adequate when the brief carries complete code.
Task 4: review — spec PASS. Reviewer verified the closed-form math
  numerically, confirmed `p` is computed once before the map loop (so no
  correlation leaks between maps), confirmed both RNG tests discriminate, and
  checked the statistical tolerance: true p ~ 0.6461, SE ~ 0.00338, so
  abs=0.015 is ~4.4 SE — comfortable, not flaky.
  Fix round 1 dispatched with one finding:
    (Important) `simulate_series` validates nothing while `series_win_prob`
      guards best_of != 3. Even/non-positive best_of produce plausible-looking
      nonsense (best_of=4 -> need=3). Odd values DO generalise correctly
      (best_of=5 -> first to 3), so the fix is to reject even and non-positive
      values, not to force symmetry with the Bo3-only closed form.
  Controller decision: declined making `series_win_prob` accept Bo5 — the
  closed form genuinely does not generalise and approximating would be worse
  than raising. Asked for a docstring recording why the two guards differ, so
  the next reader does not "fix" the asymmetry in the wrong direction.
Task 4: nit (deferred): a test comment cross-references the design doc's
  manual-adjustment table, unverifiable from the diff alone.
Task 4: fix round 1/5 (1 addressed, 0 open; commits c4f0cb1..1535b78)
  Re-reviewer traced the guard predicate itself rather than only running the
  three new tests, confirming `best_of <= 0 or best_of % 2 == 0` is a genuine
  odd-and-positive check and not a whitelist that would pass the same tests.
  Bo5 test uses unequal strengths and 500 trials — not vacuous. Tree clean.
Task 4: complete (commits 251c8c7..1535b78, review clean) — 12 in
  test_series.py, 57/57 suite, ruff clean.

Task 5: DONE_WITH_CONCERNS (commit 694a46a) — 17/17 test_swiss.py, 74/74
  suite, ruff clean, brief verbatim, all four self-review risk points clean.
Task 5: review — spec PASS. Reviewer independently confirmed: one
  DurationResolver per tournament reused across rounds; maximize_distance True
  for exactly the (1,3) group at round 5 and never at round 4; was_repeat
  captured before the opponent append; bucket key includes initial_group only
  for rounds 2-3; RNG draw order deterministic under sorted(buckets, key=str).
  Fix round 1 dispatched with one Important + one bundled Minor:
    (Important) `test_every_round_achieves_the_minimum_possible_repeat_count`
      is a TAUTOLOGY. choose_pairing filters candidates to repeats == fewest,
      then reports repeat_count and min_possible_repeats from that same set,
      so the equality holds for any input. SIXTH vacuous test found on this
      project — and this one was mine, written into the plan as the
      replacement for the "repeats never occur" claim it was meant to fix.
      Replacement spec: replay the log, rebuild buckets and prior opponents,
      brute-force perfect_matchings, compare against the LOGGED pairings.
      Required mutation proof on a /tmp copy, tracked files untouched.
    (Minor, bundled) both round-5 distance tests use only seed 12, which
      happens to give repeat_count == 0 in all three buckets, so a
      repeat-vs-distance conflict is never exercised at integration level.
  Declined as cosmetic: hoisting resolver.bind() out of the round loop;
  marking the 200-sim test slow (0.07s, would leave the default run).

## FINDING THAT CHANGES THE PROJECT, not just this task
The design doc's claim that duration ties are "rare" is FALSE, measured.
  300/300 simulated tournaments consulted the duration resolver; 5748 lookups
  over 1200 ranking calls = 4.79 per call, ~30% of 16 teams, every round from
  2 onward. Reported by the implementer, independently reproduced by the
  reviewer with an instrumented run.
  Cause is structural: criteria 1-5 are coarse integers and small-denominator
  rationals over 4-5 games and cannot separate 16 teams. REAL TI standings
  share this property, so Valve's published order also reaches duration often.
  Consequence: the placeholder log-normal (provenance `arbitrary`, our
  invention) is steering ~30% of every ranking, and ranking drives pairing
  distance and elimination pick order. Durations memoise per team, so an early
  lucky draw persists all tournament.
  Action taken: spec section XII rewritten (commit 3981a60) to state the
  measurement, retain lazy evaluation as still-correct, and require D2 to fit
  the duration model from the `duration` column already in the raw schema, or
  else report a sensitivity sweep over log_sigma.
  NOT a bias in an obvious direction — teams are exchangeable a priori — but a
  meaningful share of simulated standings is decided by a fabricated
  parameter and must not be reported as skill-driven.

Task 5: fix round 1/5 (2 addressed, 0 open; commits 694a46a..67ce814)
  PROCESS DEVIATION, recorded deliberately: the scoped re-reviewer truncated
  mid-run twice (harness issue, not judgement). Rather than spend a third
  dispatch, the controller verified both findings directly. Evidence:
    A — independence: `grep -n "repeat_count|min_possible_repeats|
        total_matchings" tests/test_swiss.py` returns ONLY docstring lines
        71-72; the test never reads a logged count.
        correctness: read tests/test_swiss.py:55-121. `opponents_before_round`
        replays the log for priors; buckets rebuilt from
        `records_before_round` + `RULES.is_active` + the within_group key
        rule; `independent_min_repeats_for_bucket` brute-forces
        `perfect_matchings` with the cross_group filter; compares against the
        LOGGED pairings. Sweeps 20 seeds x rounds 2-5.
        discrimination: implementer's /tmp mutation (repeat filter disabled)
        produced 17 mismatches across seeds 0-19.
    B — tests/test_swiss.py:216-220 and the 3-1 twin now assert the zero-repeat
        precondition with an explanatory message, and still compare spread
        against every matching from `perfect_matchings`.
  Suite 74/74, ruff clean, `git status --short src tests` empty.
Task 5: complete (commits 1535b78..67ce814, 0 parked)
  Note: an odd-sized bucket would now RAISE inside the new test via Task 3's
  odd-input guard rather than silently skipping — a useful side effect.
Task 5: nit (deferred): `resolver.bind(states)` re-invoked each round (same
  dict object); declined as cosmetic.
Task 5: nit (deferred): `test_stronger_teams_finish_higher_on_average` runs
  200 simulations without the `slow` marker; declined, it costs 0.07s and
  marking it would drop it from the default run.

Task 6: DONE (commit 6c90ad4) — 13/13 test_elimination.py, 87/87 suite, ruff
  clean. One declared deviation: `sorted(x)[0]` -> `min(x)` for ruff FURB192,
  behaviour-neutral. Implementer verified its rational-selection test is not
  vacuous (rank-order first t11 differs from alphabetical weakest t01 under
  seed 2) and volunteered `test_choosers_act_in_ranking_order` as its weakest.
Task 6: review — spec PASS, no Critical/Important. Reviewer confirmed by
  reasoning plus a 300-seed check that top_record picks (3,2) as choosers and
  (2,3) as pool; available_when_choosing snapshotted before removal; RATIONAL
  maximises the chooser's own win probability; one DurationResolver with the
  full 16-team list; softmax_temp plumbed end to end. Agreed the implementer's
  weak-test self-call was correct.
  Fix round 1 dispatched with two guards, both the never-degrade-silently
  contract already enforced in Tasks 2-4:
    A: `top_record` + `!= top_record` would silently pool a THIRD undecided
       record group if a future config produced one. Assert exactly two
       undecided records and equal chooser/pool counts.
    B: `math.exp(p / softmax_temp)` unguarded — 0 raises a bare
       ZeroDivisionError and a NEGATIVE temperature silently inverts the
       preference so NOISY would favour the STRONGEST opponent.
  Required mutation proof per new test.
Task 6: minor (deferred): `test_every_team_gets_exactly_one_category` only
  checks all 16 ids present; largely subsumed by the capacities test.
Task 6: nit (deferred): one loop iteration compares a chooser against the
  opponent it already picked — trivially true, no signal.
Task 6: nit (deferred): seed-reproducibility covered only for RATIONAL, not
  NOISY/RANDOM.
Task 6: nit (deferred): `test_choosers_act_in_ranking_order` sizes [5,4,3,2,1]
  follow mechanically from pool drainage; kept because it still catches
  snapshot/removal-ordering bugs and no stronger version exists that does not
  duplicate other tests.
Task 6: fix round 1/5 (2 addressed, 0 open; commits 6c90ad4..865b643)
  Re-reviewer reproduced PRE-FIX behaviour from `git show 6c90ad4:` and
  confirmed the defect exactly: negative softmax_temp computed weights
  silently with NO exception; zero raised a bare ZeroDivisionError rather
  than ValueError. Guard A checks BOTH conditions (exactly two undecided
  records AND equal chooser/pool counts), not half. Guard B validates on
  entry to run_elimination, so RATIONAL and RANDOM callers are covered too.
  Documented gap accepted: guard A's count-mismatch branch has no dedicated
  test because it is unreachable through real Swiss runs given the even-split
  invariant in derive_record_capacities.
Task 6: complete (commits 67ce814..865b643, review clean) — 16 in
  test_elimination.py, 90/90 suite, ruff clean.

Task 7: DONE (commit 0a9a893) — 14 new / 104 suite, ruff clean. The
  implementer mutation-tested ITS OWN tests unprompted and surfaced two gaps:
    (Important) MUTATION B: a legal-but-suboptimal capacity-respecting greedy
      passes ALL SEVEN optimize tests. So the suite proves the card is LEGAL
      but never that it is OPTIMAL — and optimality is the only reason the
      Hungarian solver exists. Most consequential finding of the build:
      the recommended card and the model-implied expected score both rest
      on it. This is the EIGHTH pass-by-construction defect on this project.
    (Minor) `test_policy_choice_is_plumbed_through` passes when `policy` is
      silently dropped — it only checks a row sums to 1, true under any policy.
  Fix round 1 dispatched:
    A: brute-force ground truth on SMALL instances (solve_card takes
       `capacities`, so 4 teams / 2 non-zero categories is legal), 200+ random
       seeded matrices plus one adversarial fixture where greedy is provably
       worse. Must re-run mutation B and confirm the new test now FAILS.
    B: assert RANDOM vs RATIONAL produce DIFFERENT marginals under the same
       seed with differentiated strengths.
  Told the implementer explicitly that the brief's 14/104 acceptance counts
  predate these tests and must not cap the work.
Task 7: accepted as-is (implementer's own call, verified): 
  `test_each_category_column_sums_to_its_capacity` restates Task 6's per-run
  invariant BUT its mutation showed it still catches aggregation-layer bugs
  in montecarlo.py — kept.
Task 7: fix round 1/5 (2 addressed, 0 open; commits 0a9a893..bd660cb)
  Re-reviewer verified the brute-force reference is INDEPENDENT (itertools
  permutations + hand-written payoff sum; never calls solve_card internals or
  scipy.linear_sum_assignment) and CORRECT (hand-enumerated the adversarial
  fixture's C(4,2)=6 subsets: greedy 2.48, optimum 3.46, both reproduce).
  Re-ran both mutations itself: property test mismatched 88/200; policy test
  gave rational == randomised under the dropped-policy mutation.
Task 7: TOOLING TRAP worth remembering — pytest's `pythonpath = ["src"]` in
  pyproject silently re-resolves to the REAL tracked src, so a /tmp mutation
  copy needs a PYTHONPATH override or the "mutation" test runs against
  unmutated code and passes, looking like the test failed to discriminate.
  The Task 7 re-reviewer hit this and worked around it explicitly.
Task 7: complete (commits 865b643..bd660cb, review clean) — 106/106 suite
  (1 slow deselected), ruff clean.

Task 8: DONE (commit 5459dd5) — 417 passed full suite incl. slow, ruff clean,
  no capacity literals in src, reports/ gitignored and untracked.
  Helper extraction done as directed: records_before_round,
  opponents_before_round, independent_min_repeats_for_bucket and the new
  assert_rounds_hit_independent_repeat_minimum live ONLY in
  tests/swiss_replay.py, imported by test_swiss.py and test_invariants.py.
  CLI end-to-end: model_implied_expected_score 6.9885 vs 3.75 baseline.
  Reviewer recomputed at n_sims=20000 -> 6.9712, judged plausible not buggy
  (adjacent logit gap 0.15 -> Bo3 edge ~0.556; top-vs-bottom 2.25 -> ~0.975).
  Implementer self-flagged two weak tests, both ACCEPTED as-is:
    - test_renaming_teams_maps_every_row_through_the_bijection passes because
      the bijection preserves sort order and hence the RNG stream. Confirmed
      empirically: an order-REVERSING bijection gives 92/96 mismatched cells.
      Only the slow strength-permutation test proves real equivariance.
    - test_exactly_eight_teams_advance is forced by derived capacities and is
      subsumed by test_category_counts_are_always_exact.
  Duration consultation measured a third time, independently: 23.9%
  (9561/40000 ranking instances over 500 equal-strength tournaments).
Task 8: review — spec PASS. Fix round 1 dispatched with two findings:
    A (Important) cli.py never validates len(strengths) == rules.n_teams.
      Reviewer ran three cases against real code: 10 teams -> IndexError in
      random_round_one_schedule; 17 -> same; 12 -> runs the FULL Monte Carlo
      and only then dies with NoLegalPairingError. solve_card's own
      "teams cannot fill slots" guard is DEAD CODE for this path.
    B (Minor) test_probability_rows_and_columns_are_consistent's column-sum
      half is an exact structural identity with no sampling noise, so
      pytest.approx is meaningless there. TENTH pass-by-construction defect.
      Sharpest detail: the docstring of a test TWO FUNCTIONS AWAY in the same
      file already says column sums "hold by construction and prove nothing".
      The warning was written down and the defect shipped next to it.
      Row-sum half is real and stays.
Task 8: fix round 1/5 (2 addressed, 0 open; commits 5459dd5..34a2a3c)
  CORRECTION TO THE RECORD, raised by the implementer and independently
  verified by the re-reviewer across seeds 0/1/42/999 and an even-count sweep
  2..32: the 12-team case does NOT fail "after the full Monte Carlo" as the
  Task 8 reviewer stated. It fails on iteration 0 for every seed, structurally
  — the 6/6 group split forces every round-2 bucket to size 3. n=32 is the
  ONLY mismatched count that completes Monte Carlo and reaches solve_card's
  "32 teams cannot fill 16 slots" guard. The implementer refused to adopt the
  reviewer's phrasing silently; both parties then reproduced it.
  Monkeypatch test verified to assert genuine non-invocation of
  category_marginals, not merely to pass.
Task 8: complete (commits bd660cb..34a2a3c, review clean) — 420 full suite,
  417 not-slow, ruff clean.

## ALL EIGHT TASKS COMPLETE
Branch d1-rules-engine, 88e753d..34a2a3c, 20 commits, 420 tests green.
Remaining: whole-branch review (most capable model), then the Codex
differential audit of the Swiss rules engine.

## CODEX AUDIT BLOCKED — substituted, disclosed
The reliability policy gate refused to execute the Codex companion script
("execution of a script outside the project"). No attempt was made to route
around it; a blocked execution path is a policy decision, not an obstacle to
engineer past.
Substitute launched: an independent reference implementation written by a
DIFFERENT model tier (opus; implementers were sonnet/haiku) from a prose rules
spec, forbidden from reading src/ti26/ until its own implementation passes its
own tests, and required to report the exact point it first read the source.
WHAT IS PRESERVED: independence of derivation. The reference comes from the
spec, not the code, so it still catches transcription errors, misread rules,
and edge-case bugs.
WHAT IS LOST: vendor diversity. Both engines are Claude-authored, so a rule
misread for the same reason by both models would go undetected. The agent was
told to name any rule where it suspects correlated error rather than reporting
agreement as proof of correctness.
If the user wants true cross-vendor differential testing, Codex must be
invoked outside this harness.

## FINAL WHOLE-BRANCH REVIEW — 4 findings, ONE fix wave queued
Branch otherwise sound: 420/420, ruff clean, no capacity literals, provenance
tags present and tested, Hungarian solver verified against brute force, spec
XII duration text judged honest, `grep -rn "rare|almost no" src/` finds no
stale framing.

1. IMPORTANT/CRITICAL — DurationResolver is NOT shared across the swiss ->
   elimination boundary. `run_swiss` (swiss.py:77) and `run_elimination`
   (elimination.py:73) each construct their own; no SwissRun field carries it.
   The elimination ranking, which sets chooser PICK ORDER, therefore redraws
   every team's durations from scratch and discards all group-stage samples.
   At the measured 24-30% tie rate this is live in every tournament.
   It also makes MY OWN spec XII correction partly false: it claims durations
   "persist, memoised per team and extended as maps accumulate", which is true
   within the group stage and false across the boundary. Code is wrong, not
   the spec's intent — a team's average duration should span the whole event.
   No test covers the boundary; `DurationResolver(` appears at exactly two
   call sites and nothing shares an instance.

2. IMPORTANT (upgraded from Task 1 Minor, ruling overturned) — zero-count
   categories are omitted from `derive_category_capacities`, and
   `solve_card` indexes `capacities[c]` for EVERY Category member, so a format
   with zero of some category raises a bare KeyError at card-solving time.
   My "not reachable for 16/4/4/5" defence is weaker than claimed: the derive
   functions are EXPLICITLY tested for cross-format generalisation
   (test_rules.py 8/3/3/3), so this is latent, not dead.

3. IMPORTANT — `rules.tiebreak_order` is loaded, TESTED against the official
   seven, and NEVER CONSUMED. `tiebreak.py` hardcodes the same order
   independently and does not import Rules. The YAML is documentation only;
   editing it silently does nothing, and the test gives false confidence that
   config drives behaviour. Eleventh defect of the family — a test asserting
   a value nothing reads.

4. IMPORTANT (my "nit" ruling overturned, correctly) — the Round 5 distance
   tests use only seed 12, where repeat_count==0 in every bucket, so
   repeat-vs-distance CONFLICT at Round 5 is never exercised. The design
   doc's own audit mandate requires forced repeats AND Round 5 max-distance
   covered TOGETHER, so this is in scope, not cosmetic.

CONFIRMED CORRECT, controller ruling upheld: keeping
`test_each_category_column_sums_to_its_capacity` in test_montecarlo.py — it
exercises the tally/n_sims aggregation layer, a different layer from the
per-run invariant that was cut from test_invariants.py.

DELIBERATE SEQUENCING: the fix wave is HELD until the differential audit
finishes. The audit is differential-testing `run_elimination` right now;
changing resolver behaviour mid-audit would either manufacture spurious
disagreements or mask real ones. A stable target is worth the wait.

