# TI 2026 correction register

Every audit document in this directory used to publish measured results as prose.
Those numbers were produced by real runs, but nothing in the repository
reproduced them: the SQLite store they came from was gitignored, no manifest tied
a report to an input, and several were computed in throwaway inline commands that
were never committed. [An external audit of `d0221dc`](2026-08-04-external-audit-of-d0221dc.md)
confirmed the substantive results by fresh execution and found that a number of
documented values had no producer at all.

The fix is not to soften the prose. It is to make the numbers regenerable and
delete the ones that are not. This register records what happened to each family
of claims. The prior narratives remain in Git history; they are not current
evidence.

## Where the numbers live now

`reports/runs/<run-id>/` holds the generated bundle. Its `manifest.json` binds
every output's SHA-256 to the source revision that produced it, the pinned raw
snapshot, the rebuilt store's logical digest, and the digest of every
configuration file consulted. Check it with:

```
.venv/bin/python -m ti26.cli_provenance verify-run --bundle reports/runs/<run-id>
```

Regenerate it from committed bytes with:

```
.venv/bin/python -m ti26.cli_release --snapshot 20260802T165535Z --source-revision <sha>
```

## Register

| claim family | status | current evidence |
|---|---|---|
| D2 forecast-value gate and constant-floor comparison | superseded | `d2/d2_gate.json` and `frozen_gate_results.json` in the run bundle |
| D3 Elo calibration gate | superseded | `d3/d3_gate.json` and `frozen_gate_results.json` |
| D3b multiplicity-corrected Glicko gate | superseded | `d3b/d3b_gate.json` and `frozen_gate_results.json` |
| Production card assignments, strengths and calibration slope | superseded | `card/recommended_card.json` and `card/card_provenance.md` |
| D4 card backtest: score, baseline, percentile, per-slot table | superseded | `d4/d4_card_backtest.json` |
| D4 simulation-count sweep | withdrawn, then reinstated with a producer | `d4/d4_card_backtest.json`, `sweep` field |
| D4 random-card control | withdrawn, then reinstated with a producer | `d4/d4_card_backtest.json`, `random_control` field |
| D4 naive strength-ladder comparator | withdrawn, then reinstated with a producer | `d4/d4_card_backtest.json`, `naive_ladder` field |
| D4 rank-correlation and displacement statistics | withdrawn, then reinstated with a producer | `d4/d4_card_backtest.json`, `rank_diagnostics` field |
| Display-name independence of the card | corrected | see below |
| Tie tolerance described as a Monte Carlo standard error | corrected | see below |
| D1 build ledger and differential audit totals | withdrawn from current prose | none; D1 predates ingestion and these runs are not regenerable |
| Rung-3 public-rating diagnostics and drift observations | withdrawn from current prose | none; `cli_rung3` requires a live network fetch that cannot be replayed offline |
| Measurements asserted in source comments (fetch timings, scored-population sizes, ranking shares) | withdrawn | the runs report these as fields; the comments no longer restate them |
| Historic commit-message measurements | immutable historical record, not current evidence | this register |

## The two corrections that changed behaviour, not just prose

**Display-name independence was false as stated.** The card was independent of
display names wherever strengths differed, which is why the existing rename tests
passed. At an exact tie the name was still the ordering key, in `canonical_labels`
for the simulation streams and in `solve_card` for byte-identical marginal rows.
The auditor renamed one of two tied teams and watched marginal rows and an
assigned slot move. Ordering now falls back to the configured team id. The
shipping card did not change: rerunning the production command before and after
gave identical assignments for all 16 teams, because float Glicko strengths do
not tie exactly. Covered by exact-tie regression tests in `tests/test_montecarlo.py`
and `tests/test_optimize.py`.

**The tie tolerance was not the standard error it was documented as.** Callers
pass the worst-case standard error of one Bernoulli marginal. The quantity
actually compared is a difference of two assignment totals, each a sum of 16
correlated marginals, whose standard error depends on a covariance this
simulation does not estimate. The numeric behaviour is unchanged; the
documentation now states what the value is and what it is not, and that it buys
reproducibility rather than accuracy.

## Two published numbers the producers do not reproduce

Regenerating the withdrawn D4 diagnostics from committed producers reproduced
most of them exactly -- the observed score, the random baseline, the
simulation-count sweep's nine scores in order, and the displacement partition.
Two did not, and both are recorded here rather than silently replaced.

**The random-card control.** The producer gives a different mean over 200,000
samples than the document published. It is the same quantity estimated from a
different RNG stream; both agree with the theoretical baseline, and neither is
wrong. The original had no recorded seed because it had no producer. The current
one does, so it is reproducible from now on.

**The rank correlation.** The producer's value differs materially from the
published one, and this is not a seeding difference. The committed producer
computes Spearman with average tied ranks, which this data requires: five teams
always share `elim_win`. The published figure came from an ad-hoc calculation
whose tie convention was never written down, and the external auditor reproduced
it only by independently making the same unstated choice.

This is the clearest illustration in the project of what an unbound number costs.
The statistic had a name, two defensible definitions, and no record of which one
was meant. Agreement between two ad-hoc calculations looked like confirmation and
was not.

## The rating model was wrong, and the apparatus did not notice

Added 2026-08-06. An external audit of the reproducibility work found that
`GlickoModel` charged one Glicko-2 variance increment per period too many, in
three separate places. Correcting it moved every number the model produces,
swapped two of the sixteen card assignments, and withdrew the claim that all
sixteen were stable across simulation seeds. Details are in
[the closing report](2026-08-04-reproducibility-closing-report.md).

The part that belongs in this register is not the defect. It is that everything
built to catch exactly this kind of problem reported success throughout.

`verify-run` exited 0 on the committed bundle the whole time, because every check
it performs is internal: the declared inputs and outputs still hashed to what the
manifest said, the run id still derived from the descriptor, every report still
named its own run. All true, all irrelevant to whether the code still produced
those numbers. The suite of 819 tests passed on the corrected model as readily as
on the defective one, because no test pinned the per-period deviation growth rate;
the two conventions agree at a one-period gap and every fixture used one. And the
gate artifacts were frozen precisely so their numbers could not drift, which meant
they went on describing a model that no longer existed.

Provenance answers "is this bundle internally consistent". It does not answer "is
this bundle still what the code produces", and the second question is the one that
mattered. `verify-run --against-revision` now asks it.

## A headline number that was mostly a configuration defect

Added 2026-08-07. D4's 1/16 was quoted throughout this project as the pipeline's
only out-of-sample result. It was measured on a training window 41% the size of
production's -- 16,958 maps over 6.8 months against 41,140 over 17.7 -- because
the pinned snapshot did not reach back far enough to give the held-out event a
matched window. Re-run on a 30-month snapshot with the window matched by
construction, the score is **4/16**.

This one is worth separating from the register's usual material. It was not a
claim outrunning evidence, and nothing was misreported: every number was
correctly computed and correctly labelled. The defect was in the experiment, and
it was stateable without reference to the result -- *the backtest trains on 41% of
production's data* would have been equally true had it returned 12/16. That is
the test that distinguishes fixing a misconfiguration from re-running until the
answer improves, and it is why the re-run was registered in advance, run once,
and published beside the original rather than in place of it.

What the correction does not do is rescue the conclusion. 4/16 is barely above
the 3.75 random baseline, sits at the 23rd percentile of the model's own
predictive distribution, and exactly matches what a naive strength ladder scores.
One claim is withdrawn outright: that the pipeline scored worse the more
precisely it optimised. That came from the sweep under the short window; under
the matched window the sweep is flat at 4.

The lesson for this register is that a number can be reproducible, manifest-bound,
correctly computed and still answer the wrong question. Provenance discipline
catches numbers that do not come from the code. It does not catch a well-built
measurement of something other than what you meant to measure.

## The machinery downstream of the ratings does not do anything

Added 2026-08-07, from three committed diagnostics run after the Glicko
correction. None of them gates anything.

The spec's pairing acceptance criterion -- reproduce TI 2025's pairings from
actual results -- was never discharged, and it has now been discharged and
failed. The structural rules reproduce the event exactly, which nothing had
previously established. The within-bucket pairing preference does not: it matches
4 of the 11 buckets where it had a choice, and the real bracket follows neither
that rule nor its opposite nor conventional Swiss folding.

Then the sensitivity analysis the spec also asked for, and also never got, showed
that this costs nothing. Signal-to-noise 1.08 -- discarding the ranking-distance
criterion entirely moves marginals less than re-seeding does, and changes no
assignment.

Then the comparison nobody had run: at the production seed the shipped card is
identical to sorting the teams by strength and cutting the ranking into the
capacities. All sixteen assignments, objective gap exactly 0.0. At other seeds
twelve of sixteen agree and the four that differ are not the same four, so the
pipeline's departures from a sort are sampling noise.

The register's concern has always been claims outrunning evidence. This is the
inverse and worth recording as such: an elaborate apparatus, correctly built and
faithfully reproduced, whose output equals a spreadsheet sort. Nothing here was
overclaimed -- the reports never said the simulation was load-bearing. Nobody had
checked, and it took three producers to find out that the honest description of
the deliverable is much shorter than the pipeline that produces it.

`cli_card` now reports this itself, so it cannot go unnoticed again.

## The rules the whole simulation implements were never read

Added 2026-08-08. The project owner supplied a transcript of the published format
rules — the archived copy this repository had never had — and it disagreed with
the implementation in four places: two ranking criteria transposed, one ranking
criterion invented outright, distance maximisation applied in the wrong round,
and the elimination round modelled as a choice teams do not get. Details are in
[the closing report](2026-08-04-reproducibility-closing-report.md) and
[the rules document](../ti26/2026-08-08-published-format-rules.md).

The register's usual material is claims outrunning evidence. This is a different
failure and worth separating. Nothing here was overclaimed: the values were
tagged `reported_official` precisely because nobody could open the source, and
that tag was accurate. The problem is that the tag was treated as a disclosure
and then filed away. For a week the project audited the *rating* model to four
decimal places while the rules it fed were wrong in four places, because ratings
were checkable offline and rules were not.

Two lessons the earlier entries do not cover.

**An honest "unverified" tag is not a substitute for verifying.** `explorer_query`
could not reach the rules, so the question was recorded as an owner task and left
there. It took one paste to settle. The cost of asking was one message; the cost
of not asking was every marginal the project produced.

**Tests can encode the defect and still be good tests.** Every ranking test
passed under both the correct and the transposed criterion order, because each
varied one criterion and left the other tied — so the suite pinned the
implementation without ever discriminating it from the published rule. The new
test puts the two criteria in direct conflict and is the only one that fails
under the transposition. Coverage of a behaviour is not evidence the behaviour is
right.

A third thing, which is mine rather than the project's: on implementing the
elimination rule I measured its distance metric on overall ranking position,
noticed correctly that it is invariant there, and concluded the rule must be
per-pair rather than concluding the metric was wrong. I reported a finding on
that basis and withdrew it the same day. Noticing that a measurement makes a rule
vacuous is a reason to doubt the measurement first.

## What is still unverified

- The pre-registration timing of D3b as a one-condition test rests on commit
  chronology and prose. Git shows margin and slope were measured before the D3b
  code existed. No independently timestamped preregistration artifact exists, and
  none can be created after the fact.
- The historical before/after counts quoted for the display-name fix and for the
  tie-tolerance change have no retained input/output pair and are not
  reproducible. They are withdrawn rather than restated.
- Real-world team identity — that a given OpenDota `team_id` is the organisation
  the owner will submit under a given name — is not decidable from the store.
  `teams.check_roster_staleness` shows account-set overlap; a human confirms
  identity. See the near-lock runbook.
