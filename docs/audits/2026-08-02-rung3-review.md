# Independent review: branch `d3-rung3-public-ratings` (base `8eba3db`, HEAD `90a5907`)

Reviewer had no prior involvement in this branch. Verified directly against
source and by mutation; controller-reported suite/lint status (618 passed,
ruff clean, tree clean) taken as given per instructions and not re-run.

## Verdicts

**CORRECTNESS: FAIL**
**QUALITY: CHANGES REQUESTED**

---

## Findings

### Critical

**1. `cli_rung3.py:328-334` — the "Observed recent form" verdict paragraph is a hardcoded literal, not computed from the data it describes, and is provably false against this branch's own test fixture.**

The report body contains:

```python
(
    "**All five current deviations point the same way** (form above "
    "implied, all in the bottom half) with none below. Noise would be "
    ...
),
```

This is static text, unrelated to `form_consistent`/`form_above`/`form_below`
(computed at lines 185-188 and correctly used in the *next* paragraph and
the stdout line at 351-364). It transcribes the specific finding from the
2026-08-02 live run recorded in the build report, then ships it as
permanent boilerplate.

Reproduced: ran the exact fixture used by
`test_observed_recent_form_section_appears_with_caveats_and_reconciling_counts`
(`tests/test_cli_rung3.py:251`) standalone. Real computed distribution:

```
rung3: observed form 16 consistent, 0 above implied, 0 below implied
```

yet the emitted report simultaneously states, verbatim, "All five current
deviations point the same way ... with none below." Zero above, not five;
16 consistent, not 0. The existing test only asserts the literal string is
*present* (`tests/test_cli_rung3.py:275`) and separately checks the stdout
counts sum to 16 — it never cross-checks the prose against the numbers, so
this passes today and will keep passing regardless of what the live data
says on any future run, including the run that generates the card actually
used at TI 2026. This is the exact "prose asserting what the code does not
compute" defect class the D2 ledger flags repeatedly
(`docs/audits/2026-08-02-d2-build-ledger.md`, e.g. the duration-sync and
Tundra-note incidents) — recurring here, unfixed by review.

Impact: does not corrupt `strengths_public.csv` or `recommended_card.json`
(confirmed: the diagnostic is write-only, computed after `strengths_path` is
already written, never feeding back — settled decision 4 holds). It does
corrupt the provenance report, which is the artifact a human reads to judge
whether a card built on volatile public ratings (see Finding on item 6
below) is safe to publish. A reader trusting this paragraph on the actual
pre-lock run gets a specific, false claim about the direction and count of
deviations.

Fix: interpolate `form_above`/`form_below`/bottom-half membership into this
paragraph, or drop the specific count/direction claim and only describe the
mechanism generically.

### Important

**2. `tests/test_cli_rung3.py:186-213` (`test_elo_anchor_reports_a_real_rank_correlation_and_top4_overlap`) cannot catch a hardcoded `top4_overlap`.**

The assertion `assert 0 <= int(m2.group(1)) <= 4` accepts any integer in
range, including a constant. Verified by mutation: in an isolated scratch
copy (`.mutscratch/src`, removed after, `git status --short` confirmed
clean before and after), changed `cli_rung3.py:160` from
`top4_overlap = len(top4_public & top4_elo)` to `top4_overlap = 0`, then ran
this exact test with `-o pythonpath=.mutscratch/src`:

```
1 passed in 5.20s
```

The pythonpath override was independently confirmed live first (a
`raise RuntimeError` inserted at module scope in the scratch copy reproduced
at collection, then removed). This is the same "test that cannot fail"
category the D2 build found eleven instances of; the docstring even names
"a hardcoded 0" as the exact bug it claims to catch, but does not. The
`rank_corr` half of the same test (`not math.isnan(...)`) has the identical
weakness against a hardcoded non-NaN constant, though less central since a
NaN is the likelier failure mode for a genuinely broken correlation calc.

**3. `parse_ratings` (`src/ti26/public_ratings.py:102-122`) crashes with an unhandled `TypeError` on a present-but-null rating/wins/losses/last_match_time field, rather than the designed refusal.**

The priority brief explicitly asks to verify the refusal path holds "when
the explorer returns a row with a null/absent rating rather than omitting
the row entirely." Reproduced directly:

```
rows = [{"team_id": "123", "rating": None, "wins": 10, "losses": 5, "last_match_time": "1000"}]
parse_ratings(rows)
# TypeError: float() argument must be a string or a real number, not 'NoneType'
```

The run does still halt with no card and no fabricated strength — the core
safety property holds, and no test or manual check found a path where a
null numeric field produces a silently-substituted default. But this exact,
foreseeable OpenDota response shape (a row present with a null field, as
opposed to the row being entirely absent) is untested and produces a raw,
unhandled `TypeError` deep in the parser instead of the clear, tested
`SystemExit` message the "omitted row" path gets
(`src/ti26/cli_rung3.py:126-133`). An operator reading this crash at the
lock deadline gets a stack trace, not "N teams have no team_rating row."

**4. Nothing in the branch warns that the card is sensitive to live, same-day OpenDota rating drift; the centering scheme also couples every team's reported strength to every other configured team's daily movement.**

Answering the brief's item 6 directly:

- *Mechanism, not a bug*: `strengths_from_ratings` (`public_ratings.py:125-139`)
  centres on `mean(ratings of exactly these 16 teams)` every run, which is a
  prior, documented decision (`docs/audits/2026-08-02-rung3-source-research.md`
  section 4), not something this branch introduced. It has a real
  consequence, though: any single configured team's day-to-day rating
  change (real, since `team_rating` updates continuously) shifts the shared
  mean by `Δr / 16`, which nudges every *other* team's reported strength by
  that same amount even though their own raw rating never moved. This is
  the exact signature the brief measured — 13 unmoved teams shifting by an
  identical `+0.0085` — and is inherent to mean-centring over a fixed small
  N, not an implementation defect; nothing in the diff amplifies it further
  (`strengths_from_ratings` uses `len(ratings)` correctly, no double-counting
  found).
- The BoomBoys/Falcons gap collapse (0.2189 → 0.0146) is dominated by their
  own two individual rating deltas (≈0.111 and ≈−0.094, summing to ≈0.205,
  matching the observed gap change), not by the uniform re-centring term —
  a real, resolvable data-drift effect on top of the already-flagged
  divisor risk, not a new one.
- *What is missing*: no code path prints the ratings' fetch timestamp into
  `rung3_provenance.md`, computes a margin-to-category-boundary diagnostic,
  or states in the report that `team_rating` is a live, continuously
  updated table whose snapshot can differ materially between two runs
  hours apart — confirmed absent by reading the full report-generation
  block (`cli_rung3.py:190-357`). The existing scale-sensitivity sweep
  addresses divisor uncertainty only; it says nothing about same-divisor,
  different-day drift in the raw ratings themselves. A card regenerated the
  day before the lock could plausibly flip a near-tied category boundary
  (as BoomBoys/Falcons already nearly did) with no flag anywhere telling
  the reader this happened or could happen again.

### Minor

**5. `test_logit_per_elo_matches_the_repo_own_elo_convention` (`tests/test_public_ratings.py:204-208`) does not test what its docstring claims.** It asserts `LOGIT_PER_ELO == math.log(10)/400.0`, a literal recomputed in the test file — it never imports or references `ti26.ratings.elo`, which in fact has no such named constant at all (`EloModel` computes `math.log(10) / self._scale` inline from an instance attribute, default 400.0). Not vacuous (it does fail under a wrong divisor), but the docstring overstates what it cross-checks; effectively redundant with the spacing assertion in `test_strengths_from_ratings_centres_scales_and_preserves_order`.

**6. `_roster_record`'s exact 90-day boundary is untested.** `test_observed_recent_form_respects_the_window_cutoff` covers 89 (inside) and 91 (outside) days but not exactly `window_days` days back, where the inclusive `<=`/`>=` comparison (`public_ratings.py:304`) is actually exercised. Low severity, one-line fixture change.

---

## What was verified clean

- `strengths_from_ratings` zero-centring, order preservation, and the
  `math.log(10)/400.0` scale conversion match `EloModel`'s own convention
  and are pinned by literals independent of the module's own constant, per
  the settled decisions — no issue found beyond Finding 4's inherent
  centring coupling.
- Wilson interval formula (`public_ratings.py:244-260`) matches the
  standard closed-form reference exactly (independently re-derived and
  checked numerically against the textbook n=100/wins=50 case and the
  brief's own n=80/wins=61 case); boundary behavior at n=1 (all-win,
  all-loss) and the exact-CI-equality verdict boundary are correct and
  tested (`classify_form_verdict` uses strict `<`/`>`, confirmed by
  mutation in the build report and independently here).
- The refusal path for a *missing* `team_rating` row (as opposed to a
  present-but-null one, Finding 3) is solid, tested both directions, and
  cannot be bypassed — verified by reading `cli_rung3.py:126-133` and its
  test.
- Type coercion: every numeric field from the explorer (`team_id`,
  `rating`, `wins`, `losses`, `last_match_time`) is cast defensively with
  `int()`/`float()`, confirmed against the documented bigint-as-string
  behavior; no downstream sort or comparison operates on an uncast string.
- No team is dropped, reordered, or silently defaulted between the
  explorer rows, `strengths_from_ratings`, the CSV, and the card — direct
  dict lookups keyed by team name throughout, verified by reading
  `cli_rung3.py:104-146` and D1's `_load_strengths` consumer
  (`src/ti26/cli.py:13-38`), which is also keyed by name, not position.
- Settled decision 4 (observed-form diagnostic never overrides a rating or
  the card) holds structurally: `strengths_path` is written before the
  diagnostic runs, and the diagnostic's own output is never read back into
  `strengths` or the card invocation.
