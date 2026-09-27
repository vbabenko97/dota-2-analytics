# ti26 — reproducible forecast retrospective

Research pipeline for forecasting the compendium prediction card of The International 2026 (TI, Dota 2's annual world championship): a one-shot, locked assignment of teams to placement categories. It covers the forecasts, historical validation, and group/playoff postmortems. Its contribution is an auditable chain from inputs to decisions, including negative results. Maintenance is retrospective only.

## Claims and limits

| Evidence | Interpretation |
|---|---|
| [Historical validation and weaknesses](docs/ti26/2026-08-08-known-weaknesses.md) | Raw rating models did not clear the constant baseline; calibrated Glicko cleared the narrowly registered D3b gate. Repeat-event card skill remains unproven. |
| [Series scoring](reports/series_score/series_score.md) | Positive historical diagnostic; within-event dependence limits its nominal significance calculation. |
| [Group postmortem](reports/card_postmortem.md) and [playoff postmortem](reports/playoff_postmortem.md) | Dependent diagnostics from the same tournament, not independent replications. Group results feed playoff strengths. |
| [External playoff cards](data/ti2026_playoff_cards.yaml) | Owner-supplied comparisons with incomplete generation provenance, not a controlled model benchmark. Original [LLM evidence](predictions-from-llms/) is frozen. |
| Simulated category marginals | Conditional on point strengths and assumed rules. Glicko rating-deviation uncertainty is not propagated. Map calibration does not establish card calibration. |

Registered gates remain immutable. Diagnostics cannot promote, demote, or change the shipping card. Measurements live in producer artifacts rather than copied headline numbers.

## Start here

Install from the lock, then call the interpreter directly. Setup may download packages; analysis and verification use committed inputs offline. Release verification targets Python 3.13; the package floor is declared in [pyproject.toml](pyproject.toml).

```bash
uv sync --locked --python 3.13
.venv/bin/python -m ti26.cli_provenance verify-run \
  --bundle reports/runs/frozen-output-oracle-baseline/61c63f4aa32c573cdbc7e4abe48e08308801f1ff3cb8e5629a4ae446d5d22b6b \
  --repo-root . --at-source-revision
```

Use a clone with full Git history. Historical verification checks declared source-revision input blobs and current output bytes. It does not attest original execution or bind undeclared dependencies.

The [reproduction guide](docs/reproduce.md) covers store reconstruction, postmortems, artifact bindings, and optional expensive forecast replay.

## Research and artifact map

- [Corrected Swiss forecast](reports/card_ti2026_rules/recommended_card.json) and [provenance](reports/card_ti2026_rules/card_provenance.md).
- [Historical bundles](reports/runs/): manifests bind source revisions, snapshots, store digests, declared inputs, and outputs. New descriptors also bind the lock; old manifests retain their original scope.
- [Group evaluation](reports/card_postmortem.md), [playoff cards](data/ti2026_playoff_cards.yaml), and [playoff evaluation](reports/playoff_postmortem.md). [Replay manifests](reports/postmortems/) are retrospective attestations, not original run provenance.
- [Documentation index](docs/README.md): implemented work, historical registrations, and future plans.
- [Correction register](docs/audits/2026-08-04-correction-register.md): corrections to earlier unsupported claims.

## Architecture

```text
OpenDota acquisition → hashed raw snapshot → rebuilt SQLite store
                                             ↓
                                  roster ratings → calibration
                                             ↓
                              simulation → constrained card assignment
                                             ↓
                                  frozen forecast → postmortem
```

Acquisition uses injectable [OpenDota explorer](src/ti26/data/opendota.py) and [Steam news](src/ti26/data/steam_news.py) query seams sharing HTTP transport. Analysis uses pinned inputs. Local tests deny Python socket connections and transmissions; CI additionally isolates each verification command in a network namespace.

Statistical identity follows the roster, not the organisation. Internal simulation labels follow strength rank. Producers emit reports independently; release orchestration attaches bundle references afterwards.

Layout is preserved: `src/ti26/` for implementation, `config/` for registrations, `data/` for inputs, `reports/` for evidence, and `docs/` for research history.

## Contributing and reuse

Read [CONTRIBUTING.md](CONTRIBUTING.md) for mutation evidence, bound measurements, and offline checks.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

Code and original documentation use [MIT](LICENSE). Third-party data/text retain separate rights; see [data sources](docs/data-sources.md). Player identifiers are not anonymous. See [security policy](SECURITY.md), [citation](CITATION.cff), and [release checklist](docs/release-checklist.md). Publication remains conditional on unresolved checklist items.
