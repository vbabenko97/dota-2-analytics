# Differential audit: independent reference vs `src/ti26`

Scratch workspace: `/tmp/ti26-audit` (outside the repo, untouched by git).
Repo files touched: **none** — `git status --short src tests` is empty
(confirmed before and after this audit).

## Method / timeline (the part that makes this worth anything)

1. Wrote `/tmp/ti26-audit/refimpl/{models,pairing,standings,engine}.py`
   from the rules spec text only. Did not open, grep, or list anything
   under `src/ti26/`. I did glance at the repo's top-level directory
   listing (`AGENTS.md, config, docs, gpt-pro-output.md, pyproject.toml,
   reports, src, tests, uv.lock`) and the filenames inside
   `.superpowers/sdd/2026-08-01-d1-rules-engine-and-card-generator/`
   (task briefs, review diffs, `progress.md`) — I did **not** open the
   contents of any of those either, since they almost certainly narrate
   the implementation's own reasoning and provenance choices, which would
   have compromised independence just as much as reading `src/ti26/`
   directly.
2. Wrote `/tmp/ti26-audit/tests/{test_pairing,test_standings,test_engine}.py`
   (22 tests) against that reference implementation only.
3. Ran `python3 -m pytest tests/` in `/tmp/ti26-audit` — **22/22 passed**.
4. **Only at this point** did I run `find src/ti26 -name "*.py"` and start
   reading `src/ti26/{types,rules,pairing,swiss,tiebreak,elimination,series,
   cli,montecarlo,optimize}.py` and `config/ti2026_rules.yaml`. This is the
   exact point the method constraint requires me to disclose.
5. Wrote `/tmp/ti26-audit/tests/test_differential.py` (14 tests) importing
   both the repo's `ti26` package (via its own `.venv`, which already has
   `src` on `sys.path` per `pyproject.toml`) and my `refimpl` package.
   Ran with `.venv/bin/python -m pytest /tmp/ti26-audit/tests/test_differential.py`
   from the repo root — **14/14 passed**.
6. Also ran the repo's own suite as a baseline:
   `.venv/bin/python -m pytest tests/test_pairing.py tests/test_swiss.py
   tests/test_tiebreak.py tests/test_elimination.py` — **65/65 passed**.

All reference/differential code lives under `/tmp/ti26-audit/`, not in the
repo.

## Summary

- **2 confirmed behavioural disagreements**, both traced to the same kind
  of cause: the spec is silent on a mechanism (round-1 pairing method;
  what "ranking" means for the pairing-distance metric) and each
  implementation filled the gap differently.
- On reflection, in **both** disagreements I now believe the repo's
  reading is better supported by the literal spec text than my own
  reference's reading was. I did not force this conclusion — it fell out
  of writing the comparison and re-reading the given spec text side by
  side with what each engine actually does.
- Everywhere the two engines were fed **identical, disambiguated** inputs
  (same numeric rank, same hard-constraint predicate, same prior-opponent
  set, same tiebreak stats), they agreed exactly: forced-repeat handling,
  repeat-avoidance-beats-distance ordering, the cross-group hard
  constraint (including the ERROR path), round-5 max/min distance
  selection, the forced 1/2/5/5/2/1 record distribution, tiebreak levels
  1–6 in the standings chain, and genuine (non-fake) randomness at both
  the pairing tie-break and the standings coin toss.

## Disagreement 1: round-1 pairing method

**Reference (mine):** treats round 1 as the same general
bucket-and-pair algorithm applied once, to each 8-team initial group as a
single bucket (all 0-0, no repeats possible yet). With no repeats to
avoid, the only live criterion is ranking-distance minimisation over a
fixed pre-tournament seed, which always yields the seed-adjacent
matching `{1v2, 3v4, 5v6, 7v8}` — deterministically, for every RNG seed.

**Repo (`src/ti26/swiss.py:random_round_one_schedule`, `random_initial_groups`):**
shuffles each group's members uniformly at random, then pairs
consecutive shuffled entries. No seed/rank distance is consulted at all.

**Triggering input / evidence** (`test_disagreement_round1_pairing_method`
in `/tmp/ti26-audit/tests/test_differential.py`): 8 teams `T1..T8` (seed
order = list order) in one group, 40 RNG seeds (0–39).
- Repo output: `random_round_one_schedule` produced **more than one**
  distinct pairing set across the 40 seeds (i.e., genuinely varies), and
  the seed-adjacent pairing `{T1-T2, T3-T4, T5-T6, T7-T8}` occurred only
  as one outcome among several, by chance.
- Reference output: `select_pairing` produced `{T1-T2, T3-T4, T5-T6, T7-T8}`
  for **every one** of the 40 seeds (zero variance).

**Which is correct, and why:** the spec says only "Round 1 pairings are
set within those groups" — it does not say pairings are computed by the
same distance-minimising procedure used for later rounds, and it gives no
seeding/ranking concept to seed round 1 with in the first place (my
reference imported a fixed "pre-tournament seed" notion from outside the
given text — see Disagreement 2). Re-reading `swiss.py`, `run_swiss`
accepts optional `groups=` and `round_one=` overrides, and
`montecarlo.py`'s `category_marginals` calls `run_swiss(strengths, rules,
rng)` with **neither** supplied — i.e. in the tool's actual pipeline, the
initial draw is treated as *unknown* and marginalised over via uniform
randomization, consistent with `cli.py`'s own comment "D1 has no
ingestion, so strengths are an input" (seeding data isn't ingested
either). That is a coherent design for a probability-generating tool with
no real seeding data, and it is *more* faithful to the literal text (which
never describes a round-1 algorithm) than my reference's choice to
retrofit the general algorithm onto round 1. I judge the repo's approach
better here; my reference's assumption was a plausible but ultimately
weaker reading.

## Disagreement 2: what "ranking" means for the pairing-distance metric

**Reference (mine):** used a **fixed pre-tournament seed** (1..16,
assigned once, never recomputed) as the "rank" for the pairing-distance
criterion, on the basis of general public knowledge of how Valve/PGL
Swiss formats define pairing seed distance — this is background domain
knowledge, not something in the spec text I was given.

**Repo (`src/ti26/swiss.py:run_swiss`, `tiebreak.py:rank_teams`):**
recomputes the **full live standings** (the entire 6-criterion tiebreak
chain, including duration and, if necessary, a coin toss) at the start of
every round, and uses each team's position in that freshly recomputed
ordering as `rank_index` for the pairing-distance calculation.

**Triggering input / evidence**
(`test_disagreement_rank_source_changes_the_chosen_matching`): 4 teams
`T1..T4`, all tied on `(wins=2, losses=1)` (one shared bucket), each with
one distinct dummy opponent whose `series_wins` are crafted to
`{T1: 100, T3: 90, T2: 80, T4: 70}` — so live-standings order (by
tiebreak criterion 3, opponent wins descending) is `T1, T3, T2, T4`,
while a fixed pre-tournament seed order is `T1, T2, T3, T4`.
- Repo (`choose_pairing` using `rank_teams`'s live order): selects
  `{T1-T3, T2-T4}` (minimum distance under live order = 2).
- Reference (`select_pairing` using fixed seed order): selects
  `{T1-T2, T3-T4}` (minimum distance under seed order = 2).

These are **different physical matchings for the identical underlying
tournament state** — not an RNG-alignment artifact (both distances are
uniquely minimal in their own metric, no tie-break was needed).

**Which is correct, and why:** the spec text given to me defines exactly
one notion of ranking — the standings tiebreak chain — and never
mentions a separate "seed." Reusing the standings machinery the text
already defines for the pairing-distance metric is the more textually
economical reading; introducing an unstated, external "fixed seed"
concept (as I did) is the larger leap. I now think the repo's reading is
better supported by the given text than my own reference's reading. I
also flag a secondary, textually-real ambiguity the repo does not fully
resolve either: since `rank_teams` includes a coin toss for teams still
tied after every deterministic criterion, a bucket's *internal* pairing
preference can, in principle, depend on that coin toss, i.e. on
randomness twice-removed from "ranking." I did not find a spec sentence
that rules this in or out.

## Ambiguities catalogue (both readings, repo's choice, my read)

| # | Ambiguity | My reading | Repo's reading | My assessment |
|---|---|---|---|---|
| 1 | Round-1 pairing method | Same general algorithm on the whole group → seed-adjacent, deterministic | Uniform-random shuffle-and-pair; real draw is an optional override never exercised by the actual pipeline | Repo's is better supported by the literal text (see above) |
| 2 | "Ranking" for pairing distance | Fixed pre-tournament seed (external domain knowledge) | Live standings position, recomputed every round via the full tiebreak chain | Repo's is better supported by the literal text (see above) |
| 3 | Initial group (A/B) assignment method | Not exercised as a distinct choice in my engine (I take groups as a constructor input) | Uniform-random half-split (`random_initial_groups`), also overridable | Spec is silent; both are placeholders. No disagreement in principle since my engine also treats it as an input. |
| 4 | Round 4's `(0,3)` bucket: the loser is also eliminated (→ `(0,4)`), by the same rationale as round 5's named exception — should max-distance apply there too? | My engine's `_maximise_distance` checks `round_no == 5` only, literally — I had **not** consciously identified the round-4 case as parallel until I read `config/ti2026_rules.yaml`'s comment on it | Explicitly recognised in the yaml comment, and **deliberately not enabled** (`max_distance_at_round_4: inferred`) — `max_distance_elimination_rounds = [5]` only | I agree with the repo's conservative choice, but I disclose I only noticed this edge case *after* reading their comment, not independently beforehand — see correlated-error section |
| 5 | Opponent-list accounting for tiebreak criteria 3 & 5: per-match (repeats counted twice) vs deduplicated-by-opponent | Per-match, no dedup | Per-match, no dedup (`sum(o.series_wins for o in known)` where `known` is built straight from `team.opponents`, a list that can contain a repeat) | Agreement — see correlated-error section, this is my top candidate for a *shared* rather than independently-verified reading |
| 6 | Snapshot of opponent's wins used in standings: final tally vs point-in-time | Final tally (only ever computed once, post-Swiss) | Same in effect: `rank_teams` reads whatever `series_wins` the opponent currently holds, which is final by the time the elimination round calls it, and necessarily provisional mid-tournament (no other option exists) | Not really an independent ambiguity — forced by when the computation runs, in both engines |
| 7 | Elimination-round opponent-choice heuristic ("teams choose") | Injectable callback; shipped default picks weakest remaining team by standings position | Injectable `ChoicePolicy` (`RATIONAL` / `NOISY` / `RANDOM`); default `RATIONAL` picks the opponent maximising the chooser's own Bradley-Terry win probability | Both agree this is outside the rules text (the spec never describes *how* a team decides); different placeholder heuristics, repo's is better-grounded (uses actual strength, not just standings position) but neither is "the" rule |
| 8 | Duration generative model for full random simulations | Not modelled at all — durations are an external input to my engine | Per-team-per-map log-normal sampling, shared distribution parameters (`log_mean=7.65`, `log_sigma=0.25`), lazily drawn only when a tie survives 5 criteria | Explicitly tagged `arbitrary` by the repo; outside rules scope either way |

## Provenance-tag review (`config/ti2026_rules.yaml`)

| Tag | Value | My assessment |
|---|---|---|
| `n_teams`, `total_rounds`, `advance_at_wins`, `eliminate_at_losses` | `official` | Agree — directly stated in the given spec ("Sixteen teams... at most five rounds... four match wins... four match losses") |
| `tiebreak_order` | `official` | Agree — the 7-item list is a literal transcription of the spec's tiebreak chain, in the same order |
| `within_group_rounds: [2,3]` | `official` | Agree — literal ("Rounds 2 and 3 pair within the initial groups") |
| `cross_group_rounds: [4]` | `official` | Agree — literal ("Round 4 pairs across the groups") |
| `max_distance_when_loser_eliminated: [5]` | `official` | Agree the text literally names round 5; see ambiguity #4 for the round-4 edge case this framing leaves open (which the repo itself flags, separately, as `inferred` and not enabled) |
| `record_capacities`, `category_capacities` | `logically_forced` | Agree, and independently proved: for 8-team initial groups, no team can reach 4 wins/losses within 3 rounds, so every round-1–3 record bucket splits exactly in half regardless of match outcomes, forcing the round-3 per-group distribution to exactly `1×(3-0), 3×(2-1), 3×(1-2), 1×(0-3)`. Combining two identically-shaped groups at round 4 therefore always yields **exactly balanced** cross-group buckets (`2, 6, 6, 2`), which is also why the cross-group hard-constraint "no legal matching" error is mathematically unreachable in the full 16-team/2×8/5-round format — both engines still correctly implement the error path (verified directly against artificially-imbalanced buckets, since full-tournament dynamics can never produce one) |
| `max_distance_at_round_4: inferred` (not enabled) | Agree with the decision; see ambiguity #4 and the correlated-error note below for how I arrived at agreement |
| `coin_toss_resolution: arbitrary` | Agree — the spec only says "coin toss," with no structure; some random resolution is unavoidable, only its exact mechanics are unconstrained |
| `repeat_avoidance_is_soft: official` | Agree — literal ("repeats are avoided where possible but ARE permitted when no repeat-free matching exists") |
| `duration_model: arbitrary` | Agree — a Monte Carlo input model, not a rule |

One gap I'd flag (not a bug): round-1 pairing method and initial-group
assignment method (ambiguities #1 and #3) have **no provenance entry** in
the yaml at all — they live only as default-argument behaviour in
`swiss.py`. Given the yaml's own stated purpose ("single source of truth
for rules that could differ from our reading of Valve's published text"),
I'd have expected a tag such as `round1_pairing_when_unspecified:
arbitrary` there too.

## What I could not test, and why

- **Exact RNG-stream/bit-identical output.** Both engines enumerate
  perfect matchings via structurally identical recursion, but my
  reference explicitly canonically sorts tied candidates before calling
  `rng.randrange`, while the repo calls `rng.choice` directly on the
  filtered-but-unsorted candidate list. I did not verify whether the two
  orders coincide for any given seed (I did not need to — the task
  explicitly allows structural comparison here) — so I can only say both
  correctly select *from the same valid tied set*, not that they select
  the *same element* for a given seed.
- **`montecarlo.py`, `optimize.py`, `cli.py`.** These are the Monte-Carlo
  aggregation and Hungarian-assignment card-generation layers built on
  top of the rules engine, not the rules engine itself. Out of scope for
  this audit by the task's own framing ("tournament rules engine").
- **Real TI26 seeding/strength data.** The tool has no ingestion path yet
  (`cli.py`'s own comment); I cannot check either engine's initial-group
  or round-1 behaviour against an actual announced draw because none
  exists in this repo.
- **`DurationResolver`'s log-normal parameters** against real Dota 2 game
  durations — explicitly tagged `arbitrary` by the repo itself, and a
  data-modelling question, not a rules question.
- **`ChoicePolicy.NOISY`** (softmax-weighted opponent selection) — not
  differential-tested numerically; it's an unspecified-by-the-rules
  team-behaviour model (see ambiguity #7), and a dedicated statistical
  test of its softmax weighting wasn't in the required scenario list.

## Correlated-error assessment

I am a Claude model auditing another Claude model's implementation, so
agreement is weaker evidence than it would be from a genuinely
independent system. Concretely:

- **The two confirmed disagreements are reassuring evidence against pure
  mirroring.** On round-1 pairing method and on what "ranking" means for
  pairing distance, my reference and the repo made different choices —
  meaning at least in these two spots, independent reasoning actually
  happened rather than one system's habits leaking into the other's
  supposedly-independent design. That said, on reflection I now lean
  toward the repo's reading being better on *both* points, which is
  itself worth being honest about: it may mean the repo's authors reasoned
  more carefully here, or it may mean I'm now anchored by having seen
  their code and am rationalising agreement after the fact. I can't fully
  rule out the latter from inside this same session.
- **Best candidate for genuine correlated bias: per-match (non-
  deduplicated) accounting of opponents for tiebreak criteria 3 and 5**
  (ambiguity #5). Both implementations independently reached for "just
  iterate the opponents-per-match list, don't deduplicate" — the simplest
  possible reading of "total wins of previous opponents," and exactly the
  kind of default a competent implementer (human or model) reaches for
  without being prompted to consider the alternative. I did not
  independently entertain the deduplicated reading before comparing; I
  only noticed it was even a live alternative while writing this report.
- **Second candidate: the round-4 `(0,3)`-bucket max-distance question**
  (ambiguity #4). I want to be precise about the order of events here: my
  reference engine's code *happens* to match the repo's conservative
  choice (round-5-literal, not generalised to round 4), but I did not
  consciously reason about the round-4 case at all until I read the
  repo's own yaml comment flagging it. That means this particular
  agreement is **not** independent corroboration — it's one data point,
  not two, and I'm disclosing that rather than counting it as confirming
  evidence.
- **Lower risk:** the core matching-selection algorithm (hard constraint
  → fewest repeats → distance min/max → random tie-break), the standings
  tiebreak levels 1–6, and the forced record-distribution invariant are
  all either (a) close paraphrases of unambiguous spec sentences, or (b)
  independently, mathematically provable from the format's parameters
  (the record-distribution invariant) rather than matters of textual
  interpretation at all — agreement here is much stronger evidence of
  correctness than agreement on a genuinely open reading would be.

## Test artifacts

- `/tmp/ti26-audit/refimpl/` — independent reference implementation
  (models, pairing, standings, engine), written before any `src/ti26`
  code was read.
- `/tmp/ti26-audit/tests/test_pairing.py`,
  `/tmp/ti26-audit/tests/test_standings.py`,
  `/tmp/ti26-audit/tests/test_engine.py` — 22 tests, all passing, run via
  `python3 -m pytest tests/` before `src/ti26` was ever opened.
- `/tmp/ti26-audit/tests/test_differential.py` — 14 tests comparing the
  reference against `src/ti26`, run via
  `.venv/bin/python -m pytest /tmp/ti26-audit/tests/test_differential.py`
  from the repo root; all 14 passing.
- Repo's own suite (`tests/test_pairing.py`, `tests/test_swiss.py`,
  `tests/test_tiebreak.py`, `tests/test_elimination.py`) — 65/65 passing,
  run as a baseline sanity check, unmodified.
- `git status --short src tests` — empty, confirmed before writing this
  report.
