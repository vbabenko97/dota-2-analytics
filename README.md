# ti26 — TI 2026 Swiss-stage compendium forecasting

Forecasts which of sixteen teams land in each of The International 2026's
compendium prediction categories, and solves the capacity-constrained assignment
that maximises expected score on the card.

The compendium card has six categories with fixed capacities:

| category | slots |
|---|---|
| `4-0` | 1 |
| `4-1` | 2 |
| elimination round winner | 5 |
| elimination round loser | 5 |
| `1-4` | 2 |
| `0-4` | 1 |

Assigning at random scores 3.75 of 16 in expectation (Σk²/16).

## State of the results — read this first

This project's instrumentation is stronger than its model. Both halves of that
sentence are load-bearing.

- **No raw rating model beats a coin flip out-of-sample.** Rolling log loss over
  26,830 maps: constant 0.69315, Elo 0.69446, Glicko 0.69802. All worse than the
  floor. Only Glicko *after* a 0.405 calibration shrinkage clears it, by 0.00673
  nats/map — the information content of a flat 55.8% per-map edge.
- **Card-level skill is undetectable.** Matched-window backtest on TI 2025:
  pipeline 4/16, naive strength-sort 4/16, random 3.75. n = 1 event. On the
  TI 2026 field, after the rules correction below, the pipeline's card is
  identical to the strength sort on all 16 slots.
- **One positive out-of-sample result.** Series-level scoring on TI 2025:
  36/58 = 62.1%, one-sided p = 0.0435. One series from failing its own
  pre-registered threshold.
- **A card is not a measuring instrument.** Noxville's card, published the night
  before TI 2025 with his own Glicko-2 model, scored 5/16 — and a random card
  matches or beats that 31% of the time. You need 7/16 to reach p ≈ 0.05.
  Nobody was close. Read the card score as a headline, not as evidence.
- **The tournament rules moved on 2026-08-08.** Valve published TI 2026's Group
  Stage Rules mid-day; they differ from TI 2025's in four places, including a
  ranking criterion and the entire elimination-round mechanism. The engine is
  reconciled against [the fetched text](docs/ti26/2026-08-08-ti2026-rules-fetched.md),
  and the near-lock runbook now re-fetches and diffs that page.

Full accounting in [docs/ti26/2026-08-08-known-weaknesses.md](docs/ti26/2026-08-08-known-weaknesses.md).
What to do about it: [docs/ti26/2026-08-08-strengthening-plan.md](docs/ti26/2026-08-08-strengthening-plan.md).

Every one of those findings was read off a report this project generated about
itself. That is the point of the architecture below.

## Architecture

```
OpenDota explorer  ──►  raw snapshot  ──►  SQLite store  ──►  Glicko fit
   (one seam)          (hashed, committed)   (rebuildable)      (per roster)
                                                                    │
                                                                    ▼
                                                          calibration slope
                                                                    │
                                                                    ▼
   card  ◄──  assignment solver  ◄──  category marginals  ◄──  Swiss simulation
                (scipy LSA)            (250k tournaments)     (5 rounds + elim)
```

Three properties are enforced rather than intended:

**One network seam.** [`data/opendota.py`](src/ti26/data/opendota.py) is the only
module that contacts a remote host, and its transport is injectable. The test
suite never reaches the network.

**Statistical identity follows the roster, not the organisation.** A team is the
SHA-1 of its five sorted account ids. A roster change starts a new rating that
inherits from its predecessor in proportion to shared players. An organisation's
old results do not credit its new five.

**Every published number is regenerable from committed bytes.** A run bundle
under `reports/runs/<run-id>/` carries a manifest binding each output's SHA-256
to the source revision, the pinned raw snapshot, the store's logical digest, and
the digest of every config file consulted.

```bash
.venv/bin/python -m ti26.cli_provenance verify-run --bundle reports/runs/<run-id>
```

Use live-tree verification for a bundle expected to describe the current checkout. To verify a committed historical bundle without requiring today’s config bytes to match, read each declared input from its recorded local Git commit:

```bash
.venv/bin/python -m ti26.cli_provenance verify-run \
  --bundle reports/runs/frozen-output-oracle-baseline/* \
  --repo-root . \
  --at-source-revision
```

Historical mode proves declared input blobs and present output bytes match the manifest. It does not prove the generating process executed that commit or bind undeclared dependencies and runtime files.

After a non-predictive change, run the frozen regression from a clean committed checkout into an absent path outside the repository:

```bash
git rev-parse HEAD | xargs .venv/bin/python -m ti26.frozen_output_oracle \
  --replay-root /private/tmp/ti26-frozen-output-oracle-replay \
  --repo-root . \
  --source-revision
```

The command reuses the baseline manifest's snapshot and predictive arguments, live-verifies the temporary candidate, compares complete frozen output, and removes the temporary root on success. It publishes no registered release bundle or registry entry. Existing `cli_release` still rebuilds its ignored `data/processed/release-{snapshot_id}.sqlite` derived store. Failure preserves the isolated candidate root for diagnosis. Normal release does not call this command.

## Getting started

`uv run` is not used here. Call the interpreter directly.

```bash
uv sync                                    # create .venv from uv.lock
.venv/bin/python -m pytest -q              # 913 tests, no network
.venv/bin/python -m ruff check .
```

Rebuild the store from committed snapshot bytes — no network needed:

```bash
.venv/bin/python -m ti26.cli_ingest \
  --raw data/raw --snapshot 20260802T165535Z \
  --store data/processed/release.sqlite
```

Produce a full hash-bound bundle (gates, card, diagnostics, manifest):

```bash
.venv/bin/python -m ti26.cli_release \
  --snapshot 20260802T165535Z --source-revision $(git rev-parse HEAD)
```

A failing gate exits non-zero. That is expected evidence, recorded in the
bundle, never retried with different arguments.

## Commands

| command | what it does |
|---|---|
| `cli_ingest` | Snapshot the explorer, load a snapshot into the store |
| `cli_d2` | Rolling backtest; the pre-registered Elo-vs-Glicko gate |
| `cli_d3` | Calibration gate (Elo) |
| `cli_d3b` | Multiplicity-corrected Glicko gate — the one that PASSES |
| `cli_card` | The production card from calibrated Glicko strengths |
| `cli_d4` | Card backtest against TI 2025 — diagnostic, never a gate |
| `cli_series_score` | Score the strengths against all 58 TI 2025 series |
| `cli_data_health` | What the training corpus actually contains |
| `cli_snapshot_lag` | Is a thin recent tail real, or rows that had not arrived? |
| `cli_external_cards` | Score expert cards published before TI 2025 against the frozen truth |
| `cli_pairing_check` | Check the bracket rules against the only event that ran them |
| `cli_ladder_check` | What does the simulation add over sorting by strength? |
| `cli_schedule_sensitivity` | How much does the pairing rule move the card? |
| `cli_release` | Run every producer into one manifest-bound bundle |
| `cli_provenance` | Verify a bundle; diff two cards; generate snapshot manifests |
| `cli_rung3` | Fallback strength source (public ratings) |

Diagnostics cannot promote, demote or alter the shipping card. Only registered
gates decide anything, and only in the direction they were registered.

## Layout

```
src/ti26/
  data/        the network seam, snapshots, SQLite store, row schema
  ratings/     Elo, Glicko-2, constant/EWMA baselines
  swiss.py     Swiss rounds, pairing, group constraints
  elimination.py  the separate elimination round
  tiebreak.py  the published six-criterion ranking
  montecarlo.py   category marginals over simulated tournaments
  optimize.py  capacity-constrained assignment
  cli_*.py     one producer per command above
config/        rules, teams, aliases, gate registration — every value tagged with provenance
data/raw/      pinned, hashed snapshots (committed)
docs/          specs, audits, runbooks, weaknesses, plan
reports/runs/  content-addressed run bundles
tests/         913 tests; each names the mutation it kills
```

## Documentation

- [Design spec](docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md) — the 12-section ML system design
- [Known weaknesses](docs/ti26/2026-08-08-known-weaknesses.md) — what is wrong, ranked, with sources
- [Strengthening plan](docs/ti26/2026-08-08-strengthening-plan.md) — what to do about it
- [Near-lock runbook](docs/ti26/near-lock-runbook.md) — the ten steps for regeneration day
- [Correction register](docs/audits/2026-08-04-correction-register.md) — what happened when numbers had no producer
- [Published format rules](docs/ti26/2026-08-08-published-format-rules.md) — the format, and which parts are still assumed

Agent working rules live in `CLAUDE.md` and `AGENTS.md`. Both are deliberately
untracked — they are machine-local agent state, not project source — so they are
absent from a fresh clone. The rules that matter to a human reader are the two
under Conventions below, and the evidence discipline described throughout
`docs/`.

## Glossary

The gate names are opaque from outside. They are numbered by the order they were
registered, not by importance.

| term | meaning |
|---|---|
| **D2** | Registered gate: does Glicko beat Elo on rolling out-of-sample log loss? **FAILS.** Also carries the spec-V constant-floor check, which all models fail. |
| **D3** | Registered gate: is Elo calibrated? **FAILS** on all three conditions. |
| **D3b** | Registered gate: is calibrated Glicko better than the constant baseline, with a Bonferroni-corrected interval? **PASSES** — the only gate that does, and the reason the card ships from calibrated Glicko. |
| **D4** | Diagnostic (never a gate): score the whole card pipeline against TI 2025's real outcome. |
| **rung 3** | The documented fallback strength source: OpenDota's public `team_rating` table instead of our own fit. |
| **run bundle** | `reports/runs/<run-id>/` — every producer's output plus a manifest binding each file's SHA-256 to the source revision, snapshot, store digest and config digests. |
| **roster version id** | SHA-1 of a team's five sorted account ids. The unit of statistical identity. |
| **RD** | Glicko rating deviation — per-team uncertainty. Computed, and then discarded by `strengths()`; see weakness §2c. |
| **marginal** | P(team lands in category), estimated over 250,000 simulated tournaments. |
| **calibration slope** | Fitted slope of observed outcome on predicted logit. 1.0 is perfect; below 1.0 is overconfidence. |

## Conventions

Two rules explain most of what looks unusual here.

**If you cannot bind a number, delete it rather than qualify it.** Every number
in a report, docstring, comment or commit message is computed by the code that
emits it, from an input the manifest identifies. Prose that restates a
measurement from memory is the failure this project already had once.

**A test you have not seen fail is not evidence.** Every test names, in its
docstring, a specific mutation to the implementation that it kills — and that
mutation was applied and observed failing before the test was committed.
