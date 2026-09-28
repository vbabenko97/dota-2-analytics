# Release checklist

Owner: Vitalii Babenko. Scope: source-repository retrospective with limited maintenance. MIT is selected for code and original documentation. The existing GitHub repository is the candidate destination; no release version/tag is selected.

## Prepared work

- [x] Retrospective navigation, contributor rules, citation, and replay guide.
- [x] Additive lock binding; historical manifests preserved.
- [x] Pinned offline workflow and local test network guard.
- [x] Record implementation checks and independent review at the worktree hashes in [implementation evidence](audits/2026-09-26-public-release-implementation.json). This historical receipt predates the source-permission and identity updates; committed-candidate verification is tracked below.
- [x] Observe successful CI on a clean hosted runner: [Offline CI](https://github.com/vbabenko97/dota-2-analytics/actions/runs/36248550562) passed on 6ba2c0f. Re-observe on the merge commit.
- [x] Stage D's "rejects a deliberately broken test" criterion: not exercised on hosted CI, by owner decision (2026-09-27). Locally, the replay guard failed under both of its named mutations.
- [x] Guard replay-bound bytes in the suite; see the [completion plan](superpowers/plans/2026-09-27-public-release-completion.md), Task 1.

## Publication blockers

- [ ] Establish redistribution basis for OpenDota snapshots, Valve/Steam material, and external analyses. The [source-permission register](data-sources.md) records source-specific holds and the sent OpenDota inquiry; owner approval cannot replace third-party rights. The owner's [publication decision](data-sources.md#publication-decision) sets a 2026-10-11 deadline. After it, the repository is published with attribution and a takedown route as accepted risk.
- [x] Owner approves retained player identifiers for reproducibility, subject to source permission.
- [x] Owner reviews author-email exposure and chooses to preserve history, including the work email; new commits use the approved Gmail identity.
- [x] Record the owner-confirmed private security email in SECURITY.md.
- [x] Run history secret scans and locked-dependency advisory/license review; see the [history scan](audits/2026-09-26-publication-scan.json), [pre-commit scan](audits/2026-09-26-publication-candidate.json), and [supplement](audits/2026-09-26-publication-supplement.json). These receipts cover their recorded inputs; later edits need a new candidate receipt. Rights decisions remain open.
- [x] Verify the final candidate: [receipt](audits/2026-09-27-release-candidate-verification.json) for 0186447. It covers unfiltered tests, Ruff, all bundles, the postmortem replay, the full forecast oracle, a full-history secret scan, dependency advisories and local links (external URLs not checked). Its addendum verifies 3b1cb7c, an audit-record correction. Commits after 3b1cb7c may touch only the receipt and this checklist.
- [ ] Merge the release PR with "Create a merge commit". Squash or rebase would strand receipt-cited SHAs.
- [ ] Before the flip: update the repository description and topics; require approval for fork pull-request workflows from outside collaborators.
- [ ] After the flip: enable secret scanning with push protection, Dependabot alerts (no update PRs; `uv.lock` is replay-bound), private vulnerability reporting, and a ruleset on `main` requiring Offline CI.
- [ ] If a DOI is wanted: enable Zenodo after the flip and before the first GitHub Release.
- [x] Verify a committed candidate in a clean full-history checkout; see the [SHA-bound receipt](audits/2026-09-26-committed-candidate-verification.json). This receipt and checklist completion update are local follow-up documentation outside the verified candidate commit.
- [ ] Select the release version/tag after candidate verification and rights clearance.
- [ ] Explicitly authorize push, visibility change, and publication.

No history rewrite, deletion, push, tag, PR, visibility change, or publication is implied. The repository was private during read-only inspection. Redaction or history removal needs a separate impact review and owner decision.

## Verification

Use [reproduce.md](reproduce.md) from a full-history checkout with locked dependencies. Run unfiltered pytest and Ruff, verify historical bundles, and replay postmortems into a new store. Check new links against intended publication files. Record whether the expensive forecast oracle ran; integrity checks alone do not establish execution.

Preserve original planning audits and frozen artifacts. Implementation evidence must record commands, environment, input/source hashes, mutation evidence, review findings, and hosted status. Release notes distinguish preparation from publication.

## If sensitive material is found after publication

Make the repository private to stop new access. Remove or redact the material in a new commit and record it in the release notes. Ask GitHub Support about cached views. A visibility change does not retract existing forks, clones or third-party copies. History rewriting needs the separate impact review above.
