# Contributing

Maintenance covers retrospective reproducibility, provenance, documentation, and defects. New tournament forecasts and stable public APIs are not promised.

## Setup and checks

From the repository root:

```bash
uv sync --locked --python 3.13
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

Use the interpreter directly; `uv run` is blocked in this project's agent environment. Let uv update its lock. Run the full unfiltered suite, including slow tests, before claiming completion. Format changed code with Ruff, except replay-bound files. The [postmortem replay manifests](reports/postmortems/) bind the current bytes of their producer sources, replay tooling and inputs, including `pyproject.toml` and `uv.lock`, and `tests/test_replay_postmortems.py` fails if any of them changes. Changing one requires a new replay attestation. Keep unrelated formatting debt separate.

Tests must stay offline. Inject acquisition transports. OpenDota explorer and Steam news are separate query seams sharing HTTP transport.

## Evidence discipline

- Bind published measurements to their producer and identified inputs. Link results rather than copying them from memory.
- Preserve frozen forecasts, source evidence, manifests, and registrations. Use the [correction register](docs/audits/2026-08-04-correction-register.md) for corrections.
- Register gates before measuring. Never weaken, rescope, or retry them for a better answer. Non-zero gate exits are evidence.
- Diagnostics, including D4 and postmortems, cannot alter shipping decisions. Compendium categories and capacities are fixed.
- Every added or changed test must name the specific implementation mutation it kills in its docstring. Apply that mutation, observe failure, restore, and observe success. Retain this evidence.
- Preserve roster identity and strength-ranked internal labels. Producers know nothing about bundles.
- New scientific work needs separate scope and registration.

## Review and publication

Describe the problem, changed behavior, inputs, checks, and mutation evidence. Preserve unrelated changes. Machine-local agent configuration stays ignored; this document is the public contributor contract.

Review [data rights](docs/data-sources.md) and [release checks](docs/release-checklist.md). Owner approval is required for pushes, PRs, releases, visibility changes, history rewriting, and evidence deletion.
