# Public release proposal

Status: draft for owner review. Scope: a reproducible research and portfolio release, as requested by the owner. This document proposes changes; it does not authorize publication or change the frozen research decisions.

## Recommendation

Publish the repository as a retrospective case study in forecasting, evaluation, and evidence provenance. Its strongest contribution is the auditable chain from source data to decisions, including negative results and postmortems. A claim of established predictive skill is not supported by the present evaluation.

Keep the existing research layout and evidence paths. The tracked root is already coherent; local caches and agent configuration made the filesystem inventory look busier than the public tree. A directory reorganization would add risk without solving the release problems.

| Approach | Benefit | Cost / limitation | Decision |
|---|---|---|---|
| Reproducible retrospective | Readers can inspect decisions, replay evidence, and understand limitations | Requires a clear artifact index, supported environment, and publication checks | Recommended |
| General forecasting toolkit | Broader reuse across tournaments | Requires stable interfaces, format support, examples, and ongoing maintenance | Defer until there is a real second consumer |
| Hosted prediction product | Easier interactive consumption | Adds infrastructure and product obligations outside this repo's purpose | Outside this release |

Success means a fresh clone can follow the README to a bounded offline verification, then reproduce each highlighted result using identified inputs. Readers should distinguish historical forecasts, retrospective diagnostics, and future proposals without searching the entire design archive.

## Evidence and findings

The companion [ML design scorecard](../mlsd-scorecard-ti26.md) grades the research system. The [review evidence record](audits/2026-09-26-public-release-review.json) identifies the reviewed revision, commands, input hashes, and verification results. Design quality and readiness to publish are separate judgments.

| Area | Finding | Release consequence |
|---|---|---|
| Structure | `src/ti26`, `tests`, `config`, `data`, `reports`, and `docs` already separate responsibilities | Keep paths; add navigation rather than move files |
| Documentation | README describes the Swiss stage; later group and playoff postmortems are absent from the primary narrative | Present the full research lifecycle and link its evidence |
| Reproducibility | Historical run verification succeeds for the committed bundles; it checks declared Git input blobs and output bytes | Explain the limit: this is not an execution attestation or a complete snapshot/store replay |
| Postmortems | Offline post-group rebuild and playoff report reproduction succeeded; the report differs only in its printed store path. The public guide omits this recipe and postmortems lack run manifests | Publish the verified recipe and manifest bindings |
| Environment | `uv.lock` is tracked but omitted from the release descriptor's declared inputs | Bind the lock for new artifacts; preserve old manifests |
| Testing / tooling | Full unfiltered pytest and Ruff check passed. The optional formatter check reports existing debt; no tracked CI workflow exists | Add offline CI against implemented tests |
| Security / rights | No tracked license or security policy; full-history secret and dependency scans were not performed in this review | Resolve licensing and inspect publication contents before changing visibility |
| Release hygiene | No local release tags; public ownership and support expectations are undocumented | Publish an explicit release scope and maintenance policy |

Concrete evidence behind the gaps:

- [README.md](../README.md), “Architecture” and “Data provenance,” claims a single network seam and broad regenerability. [steam_news.py](../src/ti26/data/steam_news.py) explicitly implements a second source-query seam. It shares the HTTP transport, but does not route through `explorer_query`. Document acquisition separately from offline analysis; merging these modules is unnecessary.
- [cli_release.py](../src/ti26/cli_release.py), `CONFIG_INPUTS` and `input_manifest`, bind the snapshot manifest, configs, and project metadata. [provenance.py](../src/ti26/provenance.py), the bundle verifiers, validate declared inputs and outputs. [snapshot.py](../src/ti26/data/snapshot.py), `validate_snapshot`, validates the raw chunks during ingest. The public recipe needs all these steps plus a logical store digest.
- [playoff_postmortem.md](../reports/playoff_postmortem.md) names an ignored store. The [playoff design](superpowers/specs/2026-08-16-ti2026-playoff-bracket-prediction.md) records that store and explains why physical SQLite bytes may differ after rebuilding. Use a logical digest, not physical file identity, as the public comparison.
- The [older narrow CI plan](superpowers/plans/2026-08-09-narrow-ci.md) depends on a miniature release test that is not implemented. Do not copy that plan as though its prerequisites exist.

## Research presentation

Preserve the strict temporal fold construction in [backtest.py](../src/ti26/backtest.py), in-fold calibration in [calibrate.py](../src/ti26/calibrate.py), roster-based identity, immutable gate registrations, and the separation between diagnostics and shipping decisions. These are the core of the case study.

Make the public claims more precise:

- Retain the negative results and baseline comparisons. Move the series-level nominal p-value out of the headline: the [series report](../reports/series_score/series_score.md) explains that series from the same event are dependent. An iid calculation does not establish event-level predictive skill.
- Separate pre-TI2026 historical validation from retrospective TI2026 group and playoff outcomes. The [known weaknesses](ti26/2026-08-08-known-weaknesses.md) document limited target-tier evidence. The later outcomes are dependent parts of the same tournament: they share a model and teams, and group results feed playoff strengths. They are not independent replications.
- Describe category outputs as simulated marginals conditional on the fitted strengths and assumed rules. [Glicko strengths](../src/ti26/ratings/glicko.py) discard rating-deviation uncertainty before [simulation](../src/ti26/montecarlo.py). The public presentation must not imply those uncertainties have been propagated.
- Retain the narrow D3b registration history and the map-to-card calibration caveat in [cli_card.py](../src/ti26/cli_card.py). Keep D4 and postmortems explicitly diagnostic.
- Explain that external LLM cards are owner-supplied comparisons with incomplete generation provenance. Preserve the original bytes under `predictions-from-llms/`: [cli_playoff_cards.py](../src/ti26/cli_playoff_cards.py) binds both their path and digest. Do not edit their citations or market the comparison as a controlled model benchmark.
- Generate or link numerical results from identified artifacts. Remove hand-maintained test counts and stale quantitative comments; do not transcribe measurements into a new polished narrative without their producer and input binding.

Model improvement is not a release prerequisite. A broader target-population evaluation or uncertainty model belongs to a separately registered future research program. Do not weaken or rerun frozen gates to improve the public story.

## Target layout

```text
README.md                         purpose, claims, quickstart, results map
LICENSE                           owner-selected code license
CONTRIBUTING.md                    setup, evidence rules, verification, review
SECURITY.md                        real reporting channel and support scope
CITATION.cff                       owner-verified authorship and citation
pyproject.toml / uv.lock           package metadata and locked environment
.github/workflows/offline-ci.yml   reproducible offline checks
src/ti26/                         existing implementation
tests/                            existing tests
config/                           existing rules, identities, gate registrations
data/                             intentionally committed inputs and snapshots
predictions-from-llms/             immutable external source evidence
reports/                          frozen bundles and identified diagnostics
docs/README.md                    current / historical / planned navigation
docs/reproduce.md                 artifact index and offline replay recipes
docs/data-sources.md              provenance, rights, identifier disclosure
docs/release-checklist.md          publication and maintenance responsibilities
docs/ti26/                        existing research narrative and runbooks
docs/superpowers/                 existing historical specs and plans
docs/audits/                      existing audits and review evidence
```

No source moves, config renames, evidence deletions, or blanket ignore of `data/` and `reports/`. Add no empty `examples/`, `scripts/`, or governance hierarchy. Keep machine-specific agent files ignored; put contributor-facing rules in `CONTRIBUTING.md`. Add `CODEOWNERS` only after confirming a real review owner and whether automatic routing is useful.

## Staged change lists

### A — Make the public contract readable

**Files:** `README.md`, new `docs/README.md`, `docs/reproduce.md`, and `CONTRIBUTING.md`.

Rewrite the README around the retrospective and a claims/nonclaims table. Link forecast bundles, group evaluation, playoff comparison, and postmortems. In the docs index label each spec as historical, implemented, or planned. Label the near-lock runbook historical. Identify unavailable local-only context instead of publishing private notes or leaving unexplained broken links.

Transfer the actual project rules into contributor guidance: offline tests, direct interpreter commands, immutable registered gates, mutation evidence for changed tests, and producer-bound numbers. Correct the network-seam description. Give every highlighted artifact an entry with source revision, input snapshot/config, command, randomness, expected output location, and verification level.

**Accept when:** links resolve in a tracked-files-only checkout; no quickstart depends on ignored files; headline claims agree with the relevant producer and limitations. Documentation changes are independently reversible and must not modify historical evidence.

### B — Resolve publication rights and exposure

**Files:** new `LICENSE`, `SECURITY.md`, `docs/data-sources.md`; relevant `pyproject.toml` metadata; optionally `CITATION.cff` once identity details are confirmed.

Owner selects the code license and confirms redistribution treatment for OpenDota snapshots, Steam/Valve material, and owner-supplied external analyses. Keep code licensing separate from third-party data and text. Document player-account identifiers and why they are retained; do not describe these data as anonymous.

Scan the intended public tree and full reachable Git history for secrets, credentials, personal notes, and unexpected large files. Run a dependency advisory/license review against the lock. Record findings and dispositions. Inspect hosted visibility, branch protection, and reporting settings at release time; those settings were not inspected here. A finding needing history rewriting or content removal requires a specific owner decision after its impact is known.

**Accept when:** rights and exposure decisions are recorded, blocking findings resolved, and the security contact is real. A public repository alone does not grant broad reuse rights; see [GitHub licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository).

### C — Close the public reproduction chain

**Files:** `docs/reproduce.md`; new manifests for postmortem artifacts under `reports/`; narrowly scoped changes to `src/ti26/cli_release.py`, provenance helpers, and corresponding tests if required.

Start with documentation and existing commands. Identify `data/raw/20260816T115509Z` as the post-group snapshot and specify rebuilding into a new empty store. Compare its logical digest with the recorded expected input before running the playoff postmortem. This review successfully exercised that path; the report matched after normalizing only the printed store path. Document that normalization explicitly or choose a stable relative path in the recipe. Do not mask arbitrary report differences. Bind each postmortem to its exact source revision, raw snapshot or tracked frozen inputs, config, lock, invocation, and output hash. A checksum of the report alone is not sufficient provenance.

Bind `uv.lock` in newly produced descriptors. Preserve the old manifest schema/bytes and historical verification behavior. Prefer a small additive descriptor change over the larger planned registry/preflight architecture. Maintain the existing rule that producers know nothing about bundles; a wrapper can attach artifact provenance after production. A new run identity is expected when declared inputs change; scientific output equivalence is the invariant.

Publish a replay ladder:

| Level | Reader action | What it proves |
|---|---|---|
| Artifact integrity | `cli_provenance verify-run --at-source-revision` for indexed bundles, with full Git history available | Declared historical input blobs and current output hashes |
| Input reconstruction | `cli_ingest --snapshot ...` into a new store, then `cli_provenance store-digest` | Raw chunk integrity and normalized logical input equality |
| Forecast replay | Existing frozen output oracle in a clean checkout and a new external replay directory | Registered decisions and roster-keyed card assignments agree under the documented environment |
| Retrospective replay | Group and playoff postmortem commands with their indexed inputs and manifests | Highlighted diagnostic reports reproduce at their declared comparison level |

Keep full forecast replay an explicit expensive option; measure its runtime before promising a duration. Start with the runtime recorded in the evidence, then expand the supported environment only after testing. Installation can require package downloads; analysis and tests must be offline after setup. Use `uv sync --locked` to refuse an out-of-date lock, followed by `.venv/bin/python`; see [uv lock checking](https://docs.astral.sh/uv/concepts/projects/sync/).

**Accept when:** a clean checkout with no pre-existing processed data completes each supported recipe; store digests match; both group and playoff reports reproduce and have manifests binding inputs, outputs, and any comparison normalization; a corrupted input is rejected; old bundles still verify; frozen decisions remain unchanged. Any new test must satisfy the repository's mutation RED/GREEN rule. Historical gate failure remains valid evidence, not a reason to modify a threshold.

### D — Automate the checks that actually exist

**Files:** new `.github/workflows/offline-ci.yml`; supporting tests only for uncovered release invariants.

Use the locked environment and a documented supported Python version. Run Ruff and the full unfiltered suite for the release check. Use existing offline snapshot/provenance/oracle tests for a small reproduction check; inspect test names before selecting them. If a fixture-sized release test is necessary, implement and validate it explicitly rather than reference the absent test from the old plan. Assert that tests cannot reach the network.

Keep expensive full replay manual or scheduled, without turning diagnostic results into shipping gates. Do not require all historical statistical gates to exit successfully. A fast PR subset may supplement the full release run after runtime is measured; it cannot replace final unfiltered verification.

Pin third-party Actions to verified commit SHAs and set minimal token permissions, following [GitHub Actions security guidance](https://docs.github.com/en/actions/reference/security/secure-use). Record the baseline formatter debt separately; a repository-wide formatting pass is optional and should be isolated from scientific and provenance changes.

**Accept when:** workflow executes successfully on a clean runner, rejects a deliberately broken test/input during development, and requires no API credential or live data fetch. Revert the workflow independently if needed; retain offline local commands.

### E — Package and publish the reviewed revision

**Files:** `docs/release-checklist.md`, release notes, verified citation metadata, and any final metadata updates.

Record the source revision, supported environment, verification evidence, artifact index, known limitations, and maintenance scope. Set a release tag only after the owner chooses the version and public identity. Publicize results as an auditable case study; clearly state that maintenance is retrospective unless the owner commits to future tournaments.

**Accept when:** A–D are complete, the actual candidate revision passes the commands below, and an unfamiliar reader can follow the reproduction guide. Push, visibility changes, release publication, and any archive/DOI registration require explicit owner authorization. No package-registry publication, hosted service, container stack, or new experiment framework is required.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

## Dependencies and decisions

A and B can proceed independently. C uses A's artifact index; D follows C's stable verification contract. E depends on all preceding release criteria. Keep each change list reviewable and reversible; never replace frozen artifacts to make a new implementation look historically correct.

Owner decisions remain the code license, third-party redistribution terms, public author/contact identity, supported maintenance scope, and publication destination/version. These do not prevent preparing the concrete changes. The recommended default is a source repository release with frozen evidence and a limited maintenance statement.

The review did not run a full frozen forecast replay, reproduce every historical diagnostic, audit every line, or inspect remote hosting controls. It does not certify absence of secrets or prove predictive skill. Verification results and any baseline failures are recorded in the companion evidence file rather than inferred from documentation.
