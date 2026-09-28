# Public Release Completion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Steps marked **OWNER** are decisions or actions only the owner may take; never perform them autonomously.

**Goal:** Take `vbabenko97/dota-2-analytics` from a private release candidate (`codex/public-release` at `6ba2c0f`) to a public, verified, tagged retrospective without changing a frozen or replay-bound byte.

**Architecture:** No restructuring. The candidate already implements stages A–D of the [public release plan](../../public-release-plan.md). What remains is one guard test, documentation corrections, a design re-review, owner rights decisions, and a fixed merge → verify → configure → flip → tag sequence.

**Tech stack:** Python ≥3.12 (release target 3.13), uv lock, pytest, Ruff, GitHub Actions, `gh`.

**Spec:** [public release plan](../../public-release-plan.md) (stages A–E), [release checklist](../../release-checklist.md), [data sources](../../data-sources.md). Basis: a seven-lens review of `6ba2c0f` on 2026-09-27 (plan status, repository surface, code quality, ML design, exposure, rights, fresh-reader replay). An adversarial verifier re-checked every finding. The review transcripts are not committed. Each finding below cites evidence that a reader can re-check.

## Global constraints

- **Frozen bytes never change:** `reports/runs/**`, `reports/postmortems/**`, tracked reports, `data/raw/**`, `data/evidence/**`, `predictions-from-llms/**`.
- **Replay-bound bytes never change.** `load_and_verify_manifest` in [cli_replay_postmortems.py](../../../src/ti26/cli_replay_postmortems.py#L92-L147) hashes the *current* bytes of every path listed in `producer_source_files`, `replay_tooling`, `inputs` and `frozen_output` of the [postmortem manifests](../../../reports/postmortems/). The set includes `pyproject.toml`, `uv.lock`, both replay tools and most producer modules. Editing any of them breaks the documented replay. Consequences:
  - No repository-wide `ruff format`. It would rewrite bound modules such as `src/ti26/teams.py`.
  - No `pyproject.toml` version or metadata edit.
  - No lock bump, whether manual or from a Dependabot PR.

  List the set with:
  ```bash
  .venv/bin/python -c "import json; print('\n'.join(sorted({e['path'] for k in ('group', 'playoff') for f in ('producer_source_files', 'replay_tooling', 'inputs') for e in json.load(open(f'reports/postmortems/{k}-replay.manifest.json'))[f]})))"
  ```
- **No history rewriting.** `verify_run_bundle_at_source_revision` in [provenance.py](../../../src/ti26/provenance.py#L301-L321) and the replay wrapper resolve manifest-bound commit SHAs. `git-filter-repo` would orphan them without changing a manifest byte.
- **Owner-only actions:** push, PR, merge, branch or file deletion, visibility, repository settings, tag or release, DOI, rights decisions.
- Use `.venv/bin/python`, never `uv run`. Make edits with the Edit tool, not `sed`.
- Every added test names the implementation mutation it kills and is seen failing under that mutation before it is committed.
- Add no unbound numbers to docs; link producer artifacts and receipts instead.
- A completion claim requires unfiltered `.venv/bin/python -m pytest -q` and `.venv/bin/python -m ruff check .` on the claimed tree.

## Where the candidate stands

| Stage | Status at `6ba2c0f` | Evidence |
|---|---|---|
| A — public contract | Met, except five dead links to the private `gpt-pro-output.md` | [forecast design spec](../specs/2026-08-01-ti2026-forecast-design.md) lines 34, 339, 516, 591, 599; disclosed in [docs index](../../README.md) line 13 |
| B — rights and exposure | Exposure re-scan of all local refs reported no findings; rights **held** | [source-permission register](../../data-sources.md); the re-scan is not yet in a receipt (Task 5) |
| C — reproduction chain | Met. A fresh worktree reproduced every documented step, including corrupted-input rejection and the optional full forecast oracle | [committed-candidate receipt](../../audits/2026-09-26-committed-candidate-verification.json) covers `4e993a7`; the 2026-09-27 run is not yet in a receipt (Task 5) |
| D — offline CI | Shipped, pinned and green on `6ba2c0f`. The accept criterion "rejects a deliberately broken test" has never been exercised | [Hosted run](https://github.com/vbabenko97/dota-2-analytics/actions/runs/36248550562) (`gh run view 36248550562`; Task 5 records it in a receipt). `ci_execution` in the [implementation receipt](../../audits/2026-09-26-public-release-implementation.json) records that CI had not run at implementation time |
| E — publish | Open: rights, merge, settings, version, authorization | [release checklist](../../release-checklist.md) lines 15–23 |

## Gaps

**Blockers**

1. **`main` is the public front page and lacks the candidate.** `git ls-tree -r --name-only main` shows no LICENSE, SECURITY.md, CONTRIBUTING.md, CITATION.cff or workflow. `git show main:README.md` hardcodes measurements. Flipping visibility before the merge publishes the wrong repository.
2. **The rights hold has no exit rule.** Removing a file from HEAD does not unpublish it, because public history carries every past blob. The real choice is per repository, not per file (decision D1).

**Major**

3. **Replay-bound bytes are unguarded in CI.** CI never runs `cli_replay_postmortems`. The only test that loads a real manifest ([test_manifest_rejects_a_changed_bound_input](../../../tests/test_replay_postmortems.py#L50-L66)) zeroes `inputs[0]` and expects an input mismatch. It therefore fails on a producer or tooling edit only by accident of check order, and passes when any other input changes, including `pyproject.toml` and `uv.lock`. [CONTRIBUTING.md](../../../CONTRIBUTING.md) says "Format changed code with Ruff", which invites exactly that breakage.
4. **Verification is not current.**
   - The committed receipt binds `candidate_sha` `4e993a7`, not `6ba2c0f` and not the future merge.
   - The last full-history secret scan ([publication scan](../../audits/2026-09-26-publication-scan.json)) is scoped to `56b653e`, before the candidate commits existed.
5. **The merge method is unconstrained.** The repository allows squash, rebase and merge commits, and `delete_branch_on_merge` is false (`gh api repos/vbabenko97/dota-2-analytics`). A squash or rebase followed by branch cleanup leaves the SHAs cited by the receipts reachable from no ref.
6. **The design scorecard is stale.** [mlsd-scorecard-ti26.md](../../../mlsd-scorecard-ti26.md) reviews `56b653e` (`reviewed_source_revision` in the [review evidence](../../audits/2026-09-26-public-release-review.json)). Its "Top fix" has shipped in [reproduce.md](../../reproduce.md), and its CI and release rows are contradicted by the green run. A stale self-review is the first thing a skeptical reader will find.
7. **No post-publication incident note.** Nothing states what happens if sensitive material is found after the flip, or that making the repository private again does not retract forks or clones.
8. **The stage D rejection criterion has never been exercised** (see the stage table).

**Minor**

- The checklist still shows hosted CI as unobserved.
- [Release notes](../../release-notes.md) say "unpublished" and "no … hosted CI success".
- [reproduce.md](../../reproduce.md) omits the bundle-enumeration command, the success signal of `verify-run`, and a warning that the replay runs silently for minutes.
- The README never expands "TI" or "compendium".
- The GitHub description still says "Swiss group stage", and no topics are set.
- Private vulnerability reporting is off (HTTP 404), while [SECURITY.md](../../../SECURITY.md) calls it "not verified".
- The fork-PR workflow approval setting is not exposed by the API and must be checked in the web UI.
- CI has no scheduled run, so bit-rot in a rarely touched repository goes unnoticed.
- Eight remote branches are already merged (`git branch -r --merged origin/main`).
- The verbatim [external audit](../../audits/2026-08-04-external-audit-of-d0221dc.md) contains absolute local-path links. Do not edit it; annotate it in the index.
- Local-only refs (Codex checkpoints under `refs/codex/`, this review's `worktree-wf_f36197b1-802-7` branch) must never be pushed. Push named refs only; never use `--mirror` or `--all`.

**Deliberately not doing**

- **Directory moves:** manifests bind paths.
- **Moving the scorecard:** it is not bound, but the move gains nothing.
- **pyproject classifiers:** this is not a distributed library, and the file is replay-bound.
- **Repository-wide formatting:** it would rewrite bound modules.
- **`.gitattributes`:** [Linguist](https://github.com/github-linguist/linguist/blob/main/docs/how-linguist-works.md) already excludes data and prose languages from language statistics.
- **Splitting `evidence.py` before release:** it is not bound, so this is safe after release, provided an `evidence_id` regression check covers `data/evidence/**`.
- **`git-filter-repo`, re-running registered gates, issue/PR templates, CODEOWNERS.**

## Owner decisions

| # | Decision | Recommendation | Blocks |
|---|---|---|---|
| D1 | Publication path under the rights hold | **A:** set a deadline for the OpenDota reply, repost the inquiry through a durable public channel, and after the deadline publish this repository with full history, attribution and a takedown-on-request statement. This is risk acceptance, not clearance. The alternatives are **B**, a fresh-history public repository without held materials (it loses `--at-source-revision` verification and the postmortem replay; medium-to-large effort), and **C**, staying private and publishing a write-up. | Task 7 |
| D2 | Valve rules-page captures and the Steam news response under A | Keep them with a visible Valve/Steam name-and-link attribution in [data sources](../../data-sources.md), or ask Valve for permission. Removing them from HEAD alone changes nothing. | Task 7 |
| D3 | The two analyses in `predictions-from-llms/` | Review both for verbatim third-party passages. Under route A there is no per-file hold: approve them as they are, or switch to route B, before the D1 deadline. Their bytes are replay inputs and digest-bound in `data/ti2026_playoff_cards.yaml`, so any edit requires a new attestation, and history keeps the old bytes. | Task 7 |
| D4 | Merge method | Create a merge commit, matching every earlier PR in this repository. Keep `codex/public-release` until the tag exists. | Task 7 |
| D5 | Version | Tag `v0.1.0`, which equals the bound `pyproject.toml` version. Add `version` and `date-released` to `CITATION.cff`, which is not bound. | Task 7 |
| D6 | Hosted settings | Before the flip: update description and topics, and require approval for fork PR workflows from all outside collaborators. After the flip: enable secret scanning with push protection, Dependabot **alerts** only (no update PRs), private vulnerability reporting, and a ruleset on `main` requiring Offline CI. | Task 7 |
| D7 | DOI | Optional. Zenodo archives only public repositories, and only releases created after its toggle is enabled. | Task 7 |
| D8 | Cleanup | Delete the eight merged remote branches after the tag. Discard the untracked compression outputs: their own scorecards reported negligible word savings. Remove this review's worktree and branch. | — |
| D9 | Stage D evidence | Authorize a scratch branch carrying a deliberately failing test, observe red, then delete it. Otherwise, record the criterion as not exercised. | Task 6 |
| D10 | Incident wording | Approve the checklist paragraph in Task 2. | Task 2 |

**Recorded 2026-09-27:**

- **D1:** route A with a 2026-10-11 deadline ([publication decision](../../data-sources.md#publication-decision)).
- **Remote actions:** the agent may push `codex/public-release` and open the release PR after Task 5. The owner merges and flips visibility.
- **D9:** not exercised.
- **D8:** compression outputs and the review worktree removed; the merged remote branches are deleted after the tag.
- **D6:** default applied in SECURITY.md.
- **Still open:** D3, D5, D7, and the D6 settings themselves.

Evidence for D1–D2 (non-authoritative; not legal advice):

- The [YASP data dump](https://academictorrents.com/details/5c5deeb6cfe1c944044367d2e7465fd8bd2f4acf), from OpenDota's predecessor, is licensed CC BY-SA 4.0 and asks for attribution.
- Current OpenDota data terms could not be retrieved by automated fetch (JavaScript-rendered pages). Check them in a browser.
- The [Valve legal terms](https://www.valvesoftware.com/en/legal) state "you may not copy, republish … or distribute any Materials except as specifically provided herein".
- The [Steam Web API terms](https://steamcommunity.com/dev/apiterms) require Valve name, logo and links "on any Web page incorporating the Steam Web API"; whether that covers a static archive is unclear.

---

### Task 1: Guard replay-bound bytes

**Files:**
- Modify: `tests/test_replay_postmortems.py` (append one test)
- Modify: `CONTRIBUTING.md` ("Setup and checks" paragraph)

**Interfaces:**
- Consumes: `ti26.cli_replay_postmortems.load_and_verify_manifest(path: Path, repo_root: Path) -> dict[str, object]`
- Produces: `test_committed_replay_manifests_match_the_tree`, which CI runs through the unfiltered suite

- [ ] **Step 1: Append the test**

```python
@pytest.mark.parametrize("kind", ["group", "playoff"])
def test_committed_replay_manifests_match_the_tree(kind):
    """Kills mutation: edit a replay-bound file (reformat teams.py, touch pyproject.toml).

    The postmortem manifests bind producer sources, replay tooling and inputs by
    their current bytes. CI does not run the replay itself, so without this check a
    formatting pass or a lock bump would silently break the documented recipe.
    """
    repo_root = Path(__file__).parents[1]
    load_and_verify_manifest(
        repo_root / f"reports/postmortems/{kind}-replay.manifest.json", repo_root
    )
```

- [ ] **Step 2: Run it and confirm it passes on the current tree**

Run: `.venv/bin/python -m pytest -q tests/test_replay_postmortems.py`
Expected: all pass. Both manifests verified at `6ba2c0f` during the review.

- [ ] **Step 3: Apply the input mutation and confirm it fails**

With the Edit tool, append one blank line to `pyproject.toml`. Run the same command.
Expected: FAIL with `input sha256 mismatch: pyproject.toml`. Restore with `git checkout -- pyproject.toml`.

- [ ] **Step 4: Apply the producer mutation and confirm it fails**

Run: `.venv/bin/python -m ruff format src/ti26/teams.py`, then the test command.
Expected: FAIL with `producer source sha256 mismatch: src/ti26/teams.py`. Restore with `git checkout -- src/ti26/teams.py`, then confirm the test passes again.

- [ ] **Step 5: Amend CONTRIBUTING.md**

Replace `Format changed code with Ruff; keep unrelated formatting debt separate.` with:

```markdown
Format changed code with Ruff, except replay-bound files. The [postmortem replay manifests](reports/postmortems/) bind the current bytes of their producer sources, replay tooling and inputs, including `pyproject.toml` and `uv.lock`, and `tests/test_replay_postmortems.py` fails if any of them changes. Changing one requires a new replay attestation. Keep unrelated formatting debt separate.
```

- [ ] **Step 6: Verify and commit**

Run the unfiltered `pytest -q` and `ruff check .` (both clean). Commit the two files with a message that records both observed mutation failures.

### Task 2: Documentation corrections (docs only; no bound file)

**Files:** `docs/release-checklist.md`, `docs/reproduce.md`, `README.md`, `docs/README.md`, `docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md`, `SECURITY.md` (after D6), `docs/data-sources.md` (after D1 and D2)

- [ ] **Step 1: Update `docs/release-checklist.md`**

Replace the hosted-CI line with:
`- [x] Observe successful CI on a clean hosted runner: [Offline CI](https://github.com/vbabenko97/dota-2-analytics/actions/runs/36248550562) passed on 6ba2c0f. Re-observe on the merge commit.`

Replace the "Review hosted branch protection…" item with:

```markdown
- [ ] Verify the final candidate (see the completion plan, Task 5). Commits after the verified SHA may touch only the receipt and this checklist.
- [ ] Merge the release PR with "Create a merge commit". Squash or rebase would strand receipt-cited SHAs.
- [ ] Before the flip: update the repository description and topics; require approval for fork pull-request workflows from outside collaborators.
- [ ] After the flip: enable secret scanning with push protection, Dependabot alerts (no update PRs; `uv.lock` is replay-bound), private vulnerability reporting, and a ruleset on `main` requiring Offline CI.
- [ ] If a DOI is wanted: enable Zenodo after the flip and before the first GitHub Release.
```

Append the section below. The owner approves its wording (D10).

```markdown
## If sensitive material is found after publication

Make the repository private to stop new access. Remove or redact the material in a new commit and record it in the release notes. Ask GitHub Support about cached views. A visibility change does not retract existing forks, clones or third-party copies. History rewriting needs the separate impact review above.
```

- [ ] **Step 2: Update `docs/reproduce.md`**

After "Repeat with each historical bundle directory containing a manifest.", add:

```markdown
List them with `git ls-files -- 'reports/runs/**/manifest.json'`. Success is exit status 0; the command prints the verified manifest as JSON.
```

In "Group and playoff replay", add: `The command prints nothing until it finishes; expect several minutes. It fails before rendering if any replay-bound file differs from its recorded bytes.`

- [ ] **Step 3: Update `README.md`**

Gloss the first sentence without adding numbers, e.g. "Research pipeline for forecasting the Compendium prediction card of The International 2026 (TI, Dota 2's annual championship) …".

- [ ] **Step 4: Update `docs/README.md`**

In the audit archive sentence, add: `The [external audit](audits/2026-08-04-external-audit-of-d0221dc.md) is verbatim; its absolute local-path links do not resolve outside the author's machine.`

- [ ] **Step 5: Fix the dead links in the forecast design spec**

In the spec, replace each `[gpt-pro-output.md](../../../gpt-pro-output.md)` with `` `gpt-pro-output.md` (private, unpublished) ``. Change link syntax only.

- [ ] **Step 6: Apply decision-dependent edits (after D1, D2, D6)**

- `docs/data-sources.md`: record the D1 path and the reply deadline; add the Valve/Steam attribution line.
- `SECURITY.md`: name the chosen reporting channels and drop "not verified".

- [ ] **Step 7: Verify and commit**

Confirm that every relative link in the tracked `.md` files resolves against `git ls-files`. Run the unfiltered `pytest -q` and `ruff check .`. Commit.

### Task 3: Design re-review at the release tree

**Files:**
- Create: `docs/audits/<date>-release-design-rereview.json` (mirror the key structure of the [review evidence](../../audits/2026-09-26-public-release-review.json); do not edit that file)
- Modify: `mlsd-scorecard-ti26.md`

- [ ] **Step 1: Re-grade every rubric dimension**

Re-grade each dimension of the ml-system-design-review rubric against the tree from Tasks 1–2, citing file evidence. Start from the review's proposals, treated as judgments to challenge:

| Dimension | Before | Proposed |
|---|---|---|
| Problem framing | B+ | A- |
| Cost of mistakes | B | B+ |
| Metrics | B- | B+ |
| Reproducibility | B- | B+ |
| Serving and release | C | B- |
| Monitoring and ownership | C+ | B- |

Other dimensions stay unchanged. Challenge the Metrics proposal in particular: the presentation improved, but the measurement design did not change.

- [ ] **Step 2: Compute the aggregate with code**

Compute the aggregate with the same arithmetic as the previous evidence file, and record the command in the JSON. Never type the average by hand.

- [ ] **Step 3: Update the scorecard**

Update the verdict, grades, Top fix (the rights hold is the likely candidate) and the evidence link. Then confirm the scorecard's average equals the JSON value using a `python3 -c` comparison.

- [ ] **Step 4: Verify and commit**

Run the unfiltered `pytest -q` and `ruff check .`, then commit.

### Task 4: OWNER — rights gate (D1–D3)

- [ ] Record each decision and its evidence in `docs/data-sources.md` (Task 2, Step 6). Nothing in Task 7 starts until D1 is recorded.

### Task 5: Final candidate verification and receipt

Run in a fresh detached worktree or a full-history clone **outside `/tmp`**, because the reliability gate blocks executing from `/tmp`. For example: `git worktree add --detach ../ti26-release-verify <sha>`.

- [ ] `uv sync --locked --python 3.13`, then the unfiltered `pytest -q` and `ruff check .`.
- [ ] `verify-run --at-source-revision` for every bundle listed by `git ls-files -- 'reports/runs/**/manifest.json'`.
- [ ] `cli_replay_postmortems` into a new absent store, per [reproduce.md](../../reproduce.md).
- [ ] Optional: the full forecast oracle, per [reproduce.md](../../reproduce.md). Record its wall-clock time in the receipt, not in prose.
- [ ] `trufflehog git --no-update --no-verification --json --results=unverified,unknown file://<repo>`. Confirm it covers every ref that will be public: `git for-each-ref refs/heads refs/remotes/origin refs/tags`.
- [ ] A dependency advisory query using the [supplement](../../audits/2026-09-26-publication-supplement.json) `command`. Regenerate the requirement list from `uv.lock` and compare it with that file's `requirements`.
- [ ] Link resolution over the tracked `.md` files.
- [ ] Write `docs/audits/<date>-release-candidate-verification.json`, mirroring the key set of the [existing receipt](../../audits/2026-09-26-committed-candidate-verification.json) plus `frozen_output_oracle` and `dependency_advisories`. Bind both `candidate_sha` and `git_tree`. Commit the receipt and the checklist tick only. Confirm with `git diff --name-only <candidate_sha> HEAD`.

### Task 6: OWNER — stage D rejection evidence (D9)

- [ ] If authorized: push a scratch branch with one deliberately failing test, record the red run URL in the checklist, then delete the branch.
- [ ] If not authorized: mark the criterion "not exercised" in the checklist. Do not claim it.

### Task 7: OWNER — merge and publish sequence (order matters)

- [ ] **1. Open the PR** from `codex/public-release` to `main`. Run `gh auth switch --user vbabenko97` first.
- [ ] **2. Merge with "Create a merge commit".**
- [ ] **3. Check the merged tree.** Confirm the push CI on `main` is green, and that `git diff --name-only <verified_sha> <merge_sha>` lists only the Task 5 receipt and the checklist. With `main` an ancestor of the branch, the merge tree equals the branch tree.
- [ ] **4. Apply the D6 "before the flip" settings.**
- [ ] **5. Flip visibility to public.**
- [ ] **6. Apply the D6 "after the flip" settings**, then enable Zenodo if D7 is chosen.
- [ ] **7. Prepare the release docs** in a docs-only PR merged with a merge commit:
  - `docs/release-notes.md`: drop "— unpublished", and replace the closing sentence with the tag, date, CI run and receipt links.
  - `CITATION.cff`: add `version` and `date-released`.
- [ ] **8. Tag and release.** Tag `v0.1.0` on that merge commit and create a GitHub Release linking the notes and the receipt.
- [ ] **9. Clean up per D8.** Push named refs only.

### Task 8: Post-release (optional)

- [ ] Add a monthly `schedule:` trigger to `.github/workflows/offline-ci.yml` (`.github/` is not bound).
- [ ] Split `src/ti26/evidence.py` behind an `evidence_id` regression test over `data/evidence/**`.
- [ ] Format unbound files only; the new guard test catches mistakes.

## Acceptance

The public `main` equals a tree verified by a committed receipt. Hosted CI is green on it. The replay-bound guard is in the suite. Every D-decision is recorded. The tag and the release exist. No frozen or replay-bound byte changed: `git diff 6ba2c0f <tag> -- reports data predictions-from-llms` is empty, and the Task 1 guard passes.
