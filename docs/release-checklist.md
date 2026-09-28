# Release checklist

Owner: Vitalii Babenko. Scope: source-repository retrospective with limited maintenance. MIT is selected for code and original documentation. The existing GitHub repository is the candidate destination. The release version is `v0.1.0`; the tag is applied after the flip.

## Prepared work

- [x] Retrospective navigation, contributor rules, citation, and replay guide.
- [x] Additive lock binding; historical manifests preserved.
- [x] Pinned offline workflow and local test network guard.
- [x] Record implementation checks and independent review at the worktree hashes in [implementation evidence](audits/2026-09-26-public-release-implementation.json). This historical receipt predates the source-permission and identity updates; committed-candidate verification is tracked below.
- [x] Observe successful CI on a clean hosted runner: [Offline CI](https://github.com/vbabenko97/dota-2-analytics/actions/runs/36248550562) passed on 6ba2c0f, and on the `main` merge commits 8cd4184 ([run](https://github.com/vbabenko97/dota-2-analytics/actions/runs/36377900869)) and fc9a35c ([run](https://github.com/vbabenko97/dota-2-analytics/actions/runs/36398367988)).
- [x] Stage D's "rejects a deliberately broken test" criterion: not exercised on hosted CI, by owner decision (2026-09-27). Locally, the replay guard failed under both of its named mutations.
- [x] Guard replay-bound bytes in the suite; see the [completion plan](superpowers/plans/2026-09-27-public-release-completion.md), Task 1.

## Publication blockers

- [x] Establish a redistribution basis for each material; see the [source-permission register](data-sources.md). Owner approval cannot replace third-party rights, so each basis is stated separately:
  - **OpenDota snapshots:** permission granted by an odota maintainer in [odota/core#2989](https://github.com/odota/core/issues/2989#issuecomment-5865765389) (2026-09-28).
  - **External analyses:** approved as they are by the owner (2026-09-28).
  - **Valve/Steam material:** no permission; published with attribution and a takedown route as accepted risk under the owner's [publication decision](data-sources.md#publication-decision). The 2026-10-11 deadline no longer gates publication.
- [x] Owner approves retained player identifiers for reproducibility, subject to source permission.
- [x] Owner reviews author-email exposure and chooses to preserve history, including the work email; new commits use the approved Gmail identity.
- [x] Record the owner-confirmed private security email in SECURITY.md.
- [x] Run history secret scans and locked-dependency advisory/license review; see the [history scan](audits/2026-09-26-publication-scan.json), [pre-commit scan](audits/2026-09-26-publication-candidate.json), and [supplement](audits/2026-09-26-publication-supplement.json). These receipts cover their recorded inputs; later edits need a new candidate receipt. Rights decisions remain open.
- [x] Verify the final candidate: [receipt](audits/2026-09-27-release-candidate-verification.json) for 0186447. It covers unfiltered tests, Ruff, all bundles, the postmortem replay, the full forecast oracle, a full-history secret scan, dependency advisories and local links (external URLs not checked). Its addendum verifies 3b1cb7c, an audit-record correction. Change rule after 3b1cb7c:
  - **Frozen:** `git diff --name-only 3b1cb7c HEAD -- src tests config data reports predictions-from-llms pyproject.toml uv.lock .github LICENSE .gitignore` stays empty.
  - **Documentation, may change:** README.md, CONTRIBUTING.md, SECURITY.md, CITATION.cff, mlsd-scorecard-ti26.md and docs/.
  - **CI:** hosted CI must pass on every published or tagged commit.
  - **History:** revised 2026-09-28. The earlier rule allowed only the receipt and this checklist to change, which contradicted the planned release-docs step. The revision widens what may change to documentation only.
- [ ] Before tagging: re-run the local-link check over all tracked markdown and record the result as a receipt addendum.
- [x] Merge the release PR with "Create a merge commit": [#38](https://github.com/vbabenko97/dota-2-analytics/pull/38) merged as 8cd4184, whose tree equals the PR head. Squash or rebase would have stranded receipt-cited SHAs.
- [x] Before the flip: the repository description and topics were updated. GitHub allows the fork pull-request approval policy only on public repositories, so it was set immediately after the flip, to all external contributors.
- [x] After the flip, confirmed by reading each setting back through the API:
  - secret scanning with push protection;
  - Dependabot alerts, with automated security-update PRs disabled (`uv.lock` is replay-bound);
  - private vulnerability reporting;
  - the "main protection" ruleset on `main`, which requires the Offline CI `verify` check and blocks deletion and force-pushes.
- [x] DOI: not wanted for `v0.1.0` (owner decision, 2026-09-28). A later release can get one if Zenodo is enabled first.
- [x] Verify a committed candidate in a clean full-history checkout; see the [SHA-bound receipt](audits/2026-09-26-committed-candidate-verification.json). This receipt and checklist completion update are local follow-up documentation outside the verified candidate commit.
- [x] Select the release version: the owner chose `v0.1.0` on 2026-09-28, matching `pyproject.toml`. The tag is applied at release, after the flip.
- [x] Explicitly authorize push, visibility change, and publication: the owner authorized each step, and the repository was made public on 2026-09-28.

No history was rewritten. Redaction or history removal needs a separate impact review and owner decision.

## Verification

Use [reproduce.md](reproduce.md) from a full-history checkout with locked dependencies. Run unfiltered pytest and Ruff, verify historical bundles, and replay postmortems into a new store. Check new links against intended publication files. Record whether the expensive forecast oracle ran; integrity checks alone do not establish execution.

Preserve original planning audits and frozen artifacts. Implementation evidence must record commands, environment, input/source hashes, mutation evidence, review findings, and hosted status. Release notes distinguish preparation from publication.

## If sensitive material is found after publication

Make the repository private to stop new access. Remove or redact the material in a new commit and record it in the release notes. Ask GitHub Support about cached views. A visibility change does not retract existing forks, clones or third-party copies. History rewriting needs the separate impact review above.
