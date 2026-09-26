# Release checklist

Owner: Vitalii Babenko. Scope: source-repository retrospective with limited maintenance. MIT is selected for code and original documentation. The existing GitHub repository is the candidate destination; no release version/tag is selected.

## Prepared work

- [x] Retrospective navigation, contributor rules, citation, and replay guide.
- [x] Additive lock binding; historical manifests preserved.
- [x] Pinned offline workflow and local test network guard.
- [x] Record implementation checks and independent review at the worktree hashes in [implementation evidence](audits/2026-09-26-public-release-implementation.json). This historical receipt predates the source-permission and identity updates; committed-candidate verification is tracked below.
- [ ] Observe successful CI on a clean hosted runner; local checks cannot establish that result.

## Publication blockers

- [ ] Establish redistribution basis for OpenDota snapshots, Valve/Steam material, and external analyses. The [source-permission register](data-sources.md) records source-specific holds and the sent OpenDota inquiry; owner approval cannot replace third-party rights.
- [x] Owner approves retained player identifiers for reproducibility, subject to source permission.
- [x] Owner reviews author-email exposure and chooses to preserve history, including the work email; new commits use the approved Gmail identity.
- [x] Record the owner-confirmed private security email in SECURITY.md.
- [x] Run history secret scans and locked-dependency advisory/license review; see the [history scan](audits/2026-09-26-publication-scan.json), [pre-commit scan](audits/2026-09-26-publication-candidate.json), and [supplement](audits/2026-09-26-publication-supplement.json). These receipts cover their recorded inputs; later edits need a new candidate receipt. Rights decisions remain open.
- [ ] Review hosted branch protection and reporting settings at release time.
- [x] Verify a committed candidate in a clean full-history checkout; see the [SHA-bound receipt](audits/2026-09-26-committed-candidate-verification.json). This receipt and checklist completion update are local follow-up documentation outside the verified candidate commit.
- [ ] Select the release version/tag after candidate verification and rights clearance.
- [ ] Explicitly authorize push, visibility change, and publication.

No history rewrite, deletion, push, tag, PR, visibility change, or publication is implied. The repository was private during read-only inspection. Redaction or history removal needs a separate impact review and owner decision.

## Verification

Use [reproduce.md](reproduce.md) from a full-history checkout with locked dependencies. Run unfiltered pytest and Ruff, verify historical bundles, and replay postmortems into a new store. Check new links against intended publication files. Record whether the expensive forecast oracle ran; integrity checks alone do not establish execution.

Preserve original planning audits and frozen artifacts. Implementation evidence must record commands, environment, input/source hashes, mutation evidence, review findings, and hosted status. Release notes distinguish preparation from publication.
