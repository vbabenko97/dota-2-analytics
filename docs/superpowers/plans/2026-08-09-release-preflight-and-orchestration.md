# Release Preflight and Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make releases reject invalid checkout/evidence/snapshot/roster/input state before persistent writes, publish a manifest-bound run plus an append-only published-forecast link atomically and repairably, and preserve frozen predictive output.

**Architecture:** `release_preflight.py` is a read-only admission boundary: initial Git admission → Plan-2 non-snapshot evidence validation/current-tip reconciliation → validated snapshot bytes → normalized exact-five roster reconciliation → an in-memory reconstruction of the normal store schema → complete input digests and `store_digest`. `cli_release` builds the descriptor, final run ID, publish-staging, and verification-staging paths from that result before any persistent write, structurally classifies the transaction candidate, performs the state-specific second Git admission, then persists the same reconstruction and proves its digest equal to preflight. Fresh candidates build in publish staging. Every recovery candidate replays deterministically in separate verification staging, derives exact expected bytes, and proves the preserved publish staging or final artifact equal before transition. After staged validation, the command derives canonical final manifest/link bytes, atomically publishes the exact artifact, then exclusively creates the exact link.

**Tech Stack:** Python 3.12; stdlib `subprocess`, `hashlib`, `json`, `pathlib`, dataclasses; PyYAML; pytest; Ruff; existing provenance/snapshot/oracle plus Plan 2 evidence APIs.

## Global Constraints

- Plan 3 follows frozen-output oracle and evidence-import/reconciliation plans. No change to ratings, calibration, probabilities, simulation, assignment, six categories/capacities, gate registrations/artifacts/verdicts, D4, or diagnostic authority.
- Consume Plan 2's public `load_release_evidence` and `reconcile_release_evidence` APIs; do not design or implement evidence loaders/selectors here. The generic evidence contract identifies records only by computed lower-case SHA-256 `evidence_id` under `data/evidence/<kind>/<evidence_id>/`; callers supply neither an evidence ID nor a named evidence folder. `ReleaseEvidence` returns selected current manifest/payload digest entries, exact `team_id -> tuple[int, ...]` roster accounts, and reconciled rules/field/groups/Round-1 facts without snapshot rows. Consume Plan 1's public `ti26.provenance.verify_run_bundle_at_source_revision(bundle, *, repo_root)` historical-bundle verifier rather than duplicate it here.
- **Published-format prerequisite (amended 2026-08-11).** The evidence subject Plan 3 consumes for the published format is the source-neutral `rules:ti2026:event-format:group-stage`, not the superseded `rules:ti2026:valve:published-format`, and its payload is `ti26.rules-format-extracted.v2` with per-field `source_url_key`/`span_sha256` support. Plan 3 hardcodes neither key nor schema — it reads whatever `RELEASE_SUBJECTS` and `reconcile_release_evidence` define — but it must not start before Plan 2's amended format repair is implemented, because until then the format subject is unsatisfiable by any real capture and every ordinary release would fail preflight with no owner action able to clear it. `advance_at_wins` and `eliminate_at_losses` are not part of that subject; they are compendium-derived configuration facts and Plan 3 asserts nothing about them.
- Preflight has no network, outcome, filesystem SQLite database, store/run/registry writes, or subprocess producers. It may use `sqlite3.connect(":memory:")` to reconstruct the same `SCHEMA` and `insert_rows` semantics as ingest and call `logical_store_digest`; it closes that connection before returning. This is the required read-only source of the expected store digest.
- Git admission has two phases and uses only argument vectors for `git rev-parse HEAD` and `git status --porcelain=v1 --untracked-files=all`. Phase one, before all validation, requires a full lower-case resolved HEAD equal to `--source-revision` and rejects every tracked staged or unstaged status entry, but retains exact untracked paths for phase two. After the descriptor/run ID, fixed publish/verification paths, and structural transaction candidate are known, phase two repeats both checks and again requires HEAD equal to `--source-revision`: `fresh` permits no untracked paths; `prepared_candidate` permits only the exact publish-staging subtree plus an admitted verification-scratch subtree; `artifact_published_candidate` and `complete_candidate` permit only the exact final bundle subtree, exact validated published-forecast link path, and admitted verification-scratch subtree. Verification scratch is admissible only for those three recovery candidates, only at the fixed run-owned path, and only after read-only structural validation has proved it is a safe real directory tree under the repository; an absent scratch is also valid. Any foreign untracked path, tracked change, HEAD drift, malformed/symlinked scratch, or scratch outside the repository rejects. Git's own ignored-file rules remain authoritative: ignored paths do not appear in this status call and are not inferred or reimplemented.
- Sequence: phase-one Git admission; all non-snapshot evidence/config reconciliation; `validate_snapshot` byte/digest validation; `normalize_all` on returned rows only; exact sorted five-account reconciliation against latest canonical snapshot roster; in-memory schema/insert/digest reconstruction; complete declared input validation/digests; descriptor/run-ID derivation and read-only state classification; phase-two Git admission; only then filesystem store/run/registry writes.
- Inputs: snapshot manifest, every `CONFIG_INPUTS` including `config/team_aliases.yaml`, the optional existing `groups_path` YAML, every selected evidence manifest/payload, and both independently selected groups and Round-1 evidence records. They are safe regular repo-relative files with recomputed SHA-256 values, then exact duplicate paths are collapsed and entries are sorted. Distinct path spellings that resolve to the same file fail as aliases rather than creating two names for one input. The one existing YAML may contain both `groups` and optional `round_one`; this plan does not add a second shipping input.
- Any preflight, descriptor, structural-classification, or second-admission failure leaves `data/processed/release-<sid>.sqlite`, final `--runs/<run-id>`, fixed publish staging, fixed verification staging, and `registry/forecasts` untouched, including no mkdir, deletion, subprocess producer, prefix, manifest, or link. In particular, a crash-leftover verification tree is never cleared before phase-two admission.
- A persisted-store digest mismatch publishes no **new** final artifact or link and never deletes or alters durable retry artifacts already present; it reports the conflict to stderr. It may leave the rebuilt processed store, which is not a published artifact.
- `inspect_forecast_state` performs structural classification only and returns a candidate shape, never a spec-certified transaction state: `fresh` has no final object, publish staging, link, or verification scratch; `prepared_candidate` has only one self-consistent complete publish-staging tree; `artifact_published_candidate` has a self-consistent verified final artifact and no target link; `complete_candidate` has a self-consistent verified final artifact/link and no publish staging. A recovery candidate may additionally have an absent or structurally safe fixed run-owned verification scratch left by a crash. A manifestless final directory is legacy wreckage/conflict, never `prepared`; partial or structurally inexact publish staging also conflicts. After phase-two admission and persisted-store digest equality, every recovery candidate preserves its publish/final bytes, safely clears only the distinct verification scratch, replays immutable inputs there, and derives `ExpectedPublication`. Full relative-path set, entry type, and file-byte equality—including canonical `manifest.json`—promotes a `prepared_candidate` to the spec's exact `prepared` state, an `artifact_published_candidate` to `artifact_published`, or a `complete_candidate` to `complete`. Only then may exact prepared publish staging be atomically renamed and linked; final artifacts are never overwritten. `write_run_manifest` is the final artifact file write in either staging tree before comparison/publication. Gates retain non-zero verdict semantics; all non-gates are fatal.
- Plan 1's frozen oracle is a diagnostic-only frozen-regression replay using its baseline snapshot and registered invocation while exercising current non-predictive hardening code. Normal `cli_release` never compares a release card/output to that historical baseline, and `assert_matches_frozen_output` belongs only to the frozen-regression path. `load_staged_frozen_output` still validates a staged candidate's internal gate/card structure before publication. The regression uses controlled temporary staging, compares baseline, returns, and never creates a final bundle or registry link; its oracle failure leaves no durable publication (all guaranteed and tested by Plan 1).
- **Plan 1 remains the sole public frozen-regression command: `python -m ti26.frozen_output_oracle`.** Plan 3 adds no new top-level CLI module, no new public oracle option, and no separate frozen-regression test file.

  Because ordinary `ti26.cli_release` becomes evidence-gated in this plan, the same implementation commit adds an internal `--frozen-replay` mode to `ti26.cli_release`. `replay_current_frozen_output` appends that flag to the manifest-derived `FrozenBaselineInvocation.release_args`, together with `--runs`, `--run-kind`, and `--source-revision`. The registered baseline argument tuple and the public oracle CLI remain unchanged.

  In `--frozen-replay` mode, `cli_release` rejects `--evidence-root`, `--cutoff`, and `--registry-root`; does not load evidence; does not call `preflight_release`; does not inspect or mutate the forecast registry; and does not create a published-forecast link. It still runs the recorded predictive pipeline into the caller-supplied runs root and emits a manifest-complete candidate bundle for live verification and oracle comparison.

  A baseline `--groups` argument is permitted only when it is already present in `FrozenBaselineInvocation.release_args`, having been reconstructed from the registered baseline manifest. The oracle does not accept a caller-supplied group override. This carve-out is load-bearing: Plan 1 deliberately reconstructs `--groups` from the baseline card invocation when the baseline used a group file, so a blanket rejection of every "evidence argument" would invalidate a legitimately conditioned historical baseline.
- Published forecast registry: `registry/forecasts/<forecast_id>.json`; canonical envelope `{"schema":"ti26.registry-record.v1","record_id":id,"payload":payload}` where `id = sha256(canonical_json_bytes({"schema":"ti26.registry-record.v1","payload":payload}))`. Payload exact keys: `kind:"published_forecast"`, `run_id`, `run_manifest:{path,sha256}`, `source_revision`, `snapshot:{manifest_path,manifest_sha256}`, `inputs`, `forecast_kind:"published"`. It binds the just-written manifest and declared inputs, does not restate output measurements, and is exclusive-create only.
- Structural transaction shape derives from the final bundle, fixed publish staging, fixed verification staging, and every registry entry, not only an expected registry path. The global scan allows other canonical, schema-valid `published_forecast` records when their canonical filename/payload match and their linked artifact passes Plan 1's `ti26.provenance.verify_run_bundle_at_source_revision(bundle, repo_root=repo_root)`: that verifier reads each record manifest's own `source_revision`, not today's checkout. It rejects symlinks, non-regular files, malformed/unsafe records, foreign schema/kind/path, or records whose linked artifact fails that historical verification; for the target run it additionally rejects duplicate/conflicting links and link-without-artifact. Target-run recovery remains live deterministic replay plus expected-byte comparison, not historical-only verification. Before durable publish, canonical expected manifest and link bytes are derived from the validated replay. For every recovery candidate, the command replays in distinct verification staging, validates it, derives expected bytes, and byte-compares the entire preserved publish/final artifact plus any target link before publishing, repairing, or returning success. It never accepts merely self-consistent changed outputs. Never overwrite a final bundle/registry artifact. Final artifact first, link last.
- Before a manifest exists, the expected `run_id` is the final bundle directory's lower-case 64-hex name, computed from the preflight `store_digest` by the unchanged release descriptor logic before creating either fixed staging path. `inspect_forecast_state` rejects any other final/publish/verification naming relationship and scans all registry entries for that ID. After publication, it additionally requires the verified manifest's `run_id` to equal the directory name; the path cannot silently nominate one run while the manifest describes another.
- Every test docstring names exact killed mutation; manually mutate, observe named focused node RED, restore, observe GREEN. Use `.venv/bin/python`, never `uv run`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/ti26/release_preflight.py` | Read-only checkout/evidence/snapshot/roster/input result and in-memory store digest. |
| `src/ti26/published_forecast.py` | Canonical registry payload, global link scan, state classification, exclusive link and repair. |
| `src/ti26/cli_release.py:17-340` | Preflight-first orchestration, unchanged producers, staging, final artifact then registry link. |
| `tests/test_release_preflight.py` | No-write, Git, evidence ordering, snapshot bytes, roster, inputs. |
| `tests/test_published_forecast.py` | Registry identity, state transitions, repair/conflict contracts. |
| `tests/test_cli_release.py` | Orchestration and deterministic miniature release. |
| `docs/ti26/near-lock-runbook.md:14-323`, `tests/test_docs.py` | Evidence import/preflight owner instructions and regression test. |

### Task 1: Define preflight checkout and input contracts

**Files:** Create `src/ti26/release_preflight.py`; create `tests/test_release_preflight.py`.

**API:**

```python
class ReleasePreflightError(ValueError):
    """Release inputs cannot safely begin persistent generation."""
@dataclass(frozen=True)
class ReleasePreflight:
    source_revision: str
    snapshot_manifest: Path
    snapshot_chunks: Sequence[ValidatedSnapshotChunk]
    normalized_rows: Sequence[MapRow]
    store_digest: dict[str, int | str]
    untracked_paths: Sequence[str]
    inputs: Sequence[dict[str, str]]
    evidence: ReleaseEvidence
def preflight_release(*, repo_root: Path, raw_root: Path, snapshot_id: str,
    source_revision: str, cutoff_utc: str, evidence_root: Path,
    rules_path: Path, teams_path: Path, groups_path: Path | None,
    config_inputs: Sequence[str], git: Callable[[Path, list[str]], str] = _git,
    load_evidence: Callable[[Path], EvidenceCatalog] = load_release_evidence,
    reconcile_evidence: Callable[..., ReleaseEvidence] = reconcile_release_evidence,
    validate_snapshot_fn: Callable[[Path, str], Sequence[ValidatedSnapshotChunk]] = validate_snapshot,
) -> ReleasePreflight:
    """Validate every release prerequisite without creating a persistent artifact."""
```

- [ ] **Step 1: Write RED tests.**

```python
def test_checked_head_rejects_source_revision_not_equal_to_head(tmp_path):
    """Kills mutation: accept --source-revision without HEAD equality."""
    with pytest.raises(ReleasePreflightError, match="source revision"):
        _checked_head(tmp_path, "b" * 40, git=git_reply("a" * 40, ""))

def test_initial_git_admission_rejects_tracked_changes_but_retains_untracked_paths(tmp_path):
    """Kills mutation: reject all untracked work before the run state can admit its own artifacts."""
    admission = _initial_git_admission(
        tmp_path, "a" * 40, git=git_reply("a" * 40, "?? reports/runs/x/manifest.json\n")
    )
    assert admission.untracked_paths == ("reports/runs/x/manifest.json",)
    with pytest.raises(ReleasePreflightError, match="tracked changes"):
        _initial_git_admission(tmp_path, "a" * 40, git=git_reply("a" * 40, " M src/ti26/cli_release.py\n"))

def test_second_git_admission_allows_only_state_owned_untracked_paths(tmp_path):
    """Kills mutation: allow a foreign untracked path during recovery admission."""
    run_id = "a" * 64
    bundle = tmp_path / "reports/runs" / run_id
    staging = tmp_path / "reports/runs" / f".{run_id}.publish"
    verification = tmp_path / "reports/runs" / f".{run_id}.verify"
    link = tmp_path / "registry/forecasts" / ("b" * 64 + ".json")
    status = "".join(
        f"?? {path.relative_to(tmp_path).as_posix()}\n"
        for path in (bundle / "manifest.json", verification / "partial.json", link)
    )
    _second_git_admission(
        tmp_path, "a" * 40, state="artifact_published_candidate",
        bundle=bundle, staging=staging, verification_staging=verification,
        admitted_verification_scratch=verification,
        allowed_link_paths=(link,),
        git=git_reply("a" * 40, status),
    )
    with pytest.raises(ReleasePreflightError, match="foreign untracked"):
        _second_git_admission(
            tmp_path, "a" * 40, state="artifact_published_candidate",
            bundle=bundle, staging=staging, verification_staging=verification,
            admitted_verification_scratch=verification,
            allowed_link_paths=(link,),
            git=git_reply("a" * 40, status + "?? notes.txt\n"),
        )

def test_second_git_admission_rechecks_head_before_persistent_writes(tmp_path):
    """Kills mutation: omit source-revision equality from phase-two Git admission."""
    phase_one = _initial_git_admission(tmp_path, "a" * 40, git=git_reply("a" * 40, ""))
    assert phase_one.untracked_paths == ()
    with pytest.raises(ReleasePreflightError, match="source revision"):
        _second_git_admission(
            tmp_path, "a" * 40, state="fresh", bundle=tmp_path / "reports/runs" / ("a" * 64),
            staging=tmp_path / "reports/runs/.candidate.publish",
            verification_staging=tmp_path / "reports/runs/.candidate.verify",
            admitted_verification_scratch=None,
            allowed_link_paths=(), git=git_reply("b" * 40, ""),
        )
    assert not (tmp_path / "data/processed").exists() and not (tmp_path / "reports/runs").exists()

def test_git_admission_uses_repository_equivalent_ignore_rules(tmp_path):
    """Kills mutation: replace Git status with hand-written ignore matching."""
    repo = init_git_repo(tmp_path, gitignore=Path(".gitignore").read_bytes())
    (repo / "data/processed").mkdir(parents=True)
    (repo / "data/processed/release.sqlite").write_bytes(b"ignored")
    (repo / "reports/runs/candidate").mkdir(parents=True)
    (repo / "reports/runs/candidate/manifest.json").write_text("{}", encoding="utf-8")
    admission = _initial_git_admission(repo, git_head(repo))
    assert admission.untracked_paths == ("reports/runs/candidate/manifest.json",)

def test_digest_inputs_hashes_bytes_and_collapses_exact_duplicate_paths(tmp_path):
    """Kills mutation: retain duplicate declared paths as separate manifest inputs."""
    path = tmp_path / "input.txt"
    path.write_text("bound", encoding="utf-8")
    assert _digest_inputs(tmp_path, ["input.txt", "input.txt"]) == [
        {"path": "input.txt", "sha256": sha256_file(path)}
    ]
```

- [ ] **Step 2: Run RED.** Run `.venv/bin/python -m pytest tests/test_release_preflight.py -k 'head or git_admission or ignore_rules or digest_inputs' -q`; expect collection failure, no module.

- [ ] **Step 3: Minimal implementation.** Implement `_git`, `_checked_head` (the standalone HEAD/source-revision equality helper the first RED test calls directly; both admission helpers use it), `_initial_git_admission`, `_second_git_admission`, and `_digest_inputs`. Both Git helpers call `["rev-parse", "HEAD"]` and `["status", "--porcelain=v1", "--untracked-files=all"]`, validate the lower-case 40-hex HEAD and source-revision equality, parse porcelain records, and reject tracked staged/unstaged changes. Initial admission returns exact untracked repo-relative paths rather than rejecting them. The second helper repeats the source-revision equality check and takes the structurally classified state plus the exact `bundle`, publish `staging`, fixed `verification_staging`, classifier-returned `admitted_verification_scratch: Path | None`, and validated target-link paths. It accepts no untracked path for `fresh`; for `prepared_candidate` it accepts only descendants of publish staging and, when non-`None`, the already classified verification scratch; for `artifact_published_candidate`/`complete_candidate` it accepts only descendants of the final bundle, the exact target-link paths, and, when non-`None`, that already classified scratch. The fixed path alone does not authorize scratch that appeared after classification. It never deletes verification scratch. It must compare the status result itself, not glob the filesystem or implement `.gitignore`; ignored files are absent by Git definition. `_digest_inputs(repo_root, paths)` accepts repo-relative path strings, uses Plan-2 path-safety logic, rejects two distinct spellings that resolve to one file, recomputes hashes, and returns sorted exact-duplicate-collapsed entries. Do not call snapshot/evidence yet.

- [ ] **Step 4: Run GREEN and mutation proof.** For each named test separately, apply its one docstring mutation, run that exact node RED, restore, then rerun that node GREEN. This includes removing phase-two source-revision equality and observing `test_second_git_admission_rechecks_head_before_persistent_writes` fail while phase one sees `A` and phase two returns `B`. Finally rerun Step 2; expect PASS.

- [ ] **Step 5: Commit.** Run `git add src/ti26/release_preflight.py tests/test_release_preflight.py` then `git commit -m "feat: add release checkout preflight"`.

### Task 2: Compose evidence-first snapshot and exact-roster validation

**Files:** Modify `src/ti26/release_preflight.py`, `tests/test_release_preflight.py`.

- [ ] **Step 1: Write RED tests.**

```python
def test_preflight_reconciles_non_snapshot_evidence_before_snapshot(tmp_path):
    """Kills mutation: validate raw snapshot before rules/field/draw reconciliation."""
    events: list[str] = []
    with pytest.raises(ReleasePreflightError, match="rules"):
        preflight_release(**kwargs(tmp_path, load_evidence=recording_load(events), reconcile_evidence=rejecting_reconcile(events), validate_snapshot_fn=recording_snapshot(events)))
    assert events == ["load-evidence", "reconcile"]

def test_preflight_rejects_evidence_roster_not_equal_to_latest_normalized_accounts(tmp_path):
    """Kills mutation: compare team IDs/roster hashes rather than exact sorted five accounts."""
    with pytest.raises(ReleasePreflightError, match="roster accounts"):
        preflight_release(**release_kwargs(tmp_path, evidence_rosters={101: (1,2,3,4,99)}))

def test_preflight_never_normalizes_unvalidated_snapshot_bytes(tmp_path):
    """Kills mutation: read/decode snapshot directly instead of validate_snapshot."""
    with pytest.raises(ReleasePreflightError, match="sha256 mismatch"):
        preflight_release(**release_kwargs(tmp_path, tamper_snapshot=True))

def test_preflight_binds_aliases_draw_file_and_both_selected_draw_records(tmp_path):
    """Kills mutation: omit the aliases configuration from declared release inputs."""
    result = preflight_release(**release_kwargs(tmp_path, groups_path=tmp_path / "data/groups.yaml"))
    paths = {x["path"] for x in result.inputs}
    assert {"config/team_aliases.yaml", "data/groups.yaml"} <= paths
    for component in ("groups", "round_one"):
        manifest = result.evidence.selected[component].selected.root / "manifest.json"
        assert manifest.relative_to(tmp_path).as_posix() in paths

def test_preflight_binds_every_selected_evidence_payload(tmp_path):
    """Kills mutation: hash only evidence manifests, not their captured payload bytes."""
    result = preflight_release(**release_kwargs(tmp_path, git=git_reply("a" * 40, "")))
    assert [x["path"] for x in result.inputs] == sorted(x["path"] for x in result.inputs)
    roster_record = result.evidence.selected["rosters"].selected.root
    expected = {
        "data/raw/S/manifest.json",
        "config/ti2026_rules.yaml",
        (roster_record / "manifest.json").relative_to(tmp_path).as_posix(),
        (roster_record / "rosters.json").relative_to(tmp_path).as_posix(),
    }
    assert expected <= {x["path"] for x in result.inputs}

def test_preflight_in_memory_digest_equals_persisted_ingest_digest(tmp_path):
    """Kills mutation: derive the run ID from rows reconstructed differently than the persisted store."""
    result = preflight_release(**release_kwargs(tmp_path, git=git_reply("a" * 40, "")))
    persisted = open_store(tmp_path / "persisted.sqlite")
    try:
        insert_rows(persisted, result.normalized_rows)
        assert result.store_digest == logical_store_digest(persisted)
    finally:
        persisted.close()

def test_preflight_digest_changes_when_a_normalized_store_value_changes(tmp_path):
    """Kills mutation: digest only row identifiers instead of the actual reconstructed store."""
    result = preflight_release(**release_kwargs(tmp_path, git=git_reply("a" * 40, "")))
    changed = [replace(result.normalized_rows[0], radiant_win=not result.normalized_rows[0].radiant_win)]
    assert _in_memory_store_digest(changed) != result.store_digest
```

`release_kwargs` creates the synthetic evidence and snapshot fixtures before returning production-call arguments; `evidence_rosters` and `tamper_snapshot` are fixture setup controls, not `preflight_release` parameters. The fixture's latest row for canonical team 101 contains `(1,2,3,4,5)` and includes a rebrand alias: names/organisation IDs cannot decide this test.

- [ ] **Step 2: Run RED.** Run `.venv/bin/python -m pytest tests/test_release_preflight.py -k 'non_snapshot or evidence_roster or unvalidated or aliases or payload' -q`; expect failure because composition is absent.

- [ ] **Step 3: Minimal implementation.** In `preflight_release`: `_initial_git_admission`; `catalog=load_evidence(evidence_root)`; `evidence=reconcile_evidence(catalog, cutoff_utc=cutoff_utc, rules_path=rules_path, teams_path=teams_path, groups_path=groups_path)`; `chunks=tuple(validate_snapshot_fn(raw_root,snapshot_id))`; `rows,rejected=normalize_all([raw for c in chunks for raw in c.rows])`; fail on rejected rows; `_assert_exact_rosters(rows,evidence.roster_accounts,teams_path,repo_root / "config/team_aliases.yaml")`; `_in_memory_store_digest(rows)`; construct all entries (snapshot/config/optional draw YAML/evidence) and `_digest_inputs`; return the rows, digest, retained untracked paths, and all other result fields. `_in_memory_store_digest` opens `sqlite3.connect(":memory:")`, executes the public `SCHEMA` through `open_store`-equivalent initialization, calls the public `insert_rows` once for the normalized rows, obtains `logical_store_digest`, and closes it; it creates no path or database file. `_assert_exact_rosters` is local and uses only public `load_aliases` and `canonical_team_id`: project each normalized `MapRow` side to `(canonical_team_id, sorted_accounts, start_time, match_id)`, retain the maximum `(start_time, match_id)` per canonical ID, then require equality with each exact five-account evidence tuple. Add a public-API-only test with a team alias and a swapped account. Wrap errors in `ReleasePreflightError`. This equality deliberately preserves the frozen shipping model: current `cli_card` derives its effective roster from the latest normalized snapshot row. If current external roster evidence differs, stop before writes; do not inject the evidence roster into `cli_card`, synthesize maps, or otherwise change strengths in this pre-TI slice.

- [ ] **Step 4: Run GREEN and mutation proof.** Rerun Step 2; expect PASS. Move validation before reconciliation, replace tuple equality with roster hash equality, replace `validate_snapshot` with `read_snapshot`, omit aliases, omit the local draw YAML, omit either selected draw evidence record, omit evidence payload entries, use a different schema/insert path for the in-memory digest, and omit a stored value from that digest separately; corresponding nodes fail. Restore and rerun PASS.

- [ ] **Step 5: Commit.** Run `git add src/ti26/release_preflight.py tests/test_release_preflight.py` then `git commit -m "feat: validate release evidence and roster accounts"`.

### Task 3: Implement append-only published forecast transaction

**Files:** Create `src/ti26/published_forecast.py`; create `tests/test_published_forecast.py`.

**API:**

```python
class PublishedForecastError(ValueError):
    """Published forecast registry state is malformed or conflicting."""
@dataclass(frozen=True)
class PublishedForecast:
    forecast_id: str
    path: Path
    payload: dict[str, object]
@dataclass(frozen=True)
class ForecastStructure:
    candidate: Literal[
        "fresh", "prepared_candidate", "artifact_published_candidate", "complete_candidate"
    ]
    allowed_link_paths: tuple[Path, ...]
    verification_scratch: Path | None
@dataclass(frozen=True)
class ExpectedPublication:
    staging: Path          # validated replay tree carrying every expected artifact byte
    bundle: Path           # final bundle target directory
    manifest_bytes: bytes  # canonical manifest.json bytes, written last into staging
    forecast_id: str
    link_path: Path        # registry/forecasts/<forecast_id>.json
    link_bytes: bytes      # canonical exclusive-create registry record
def forecast_payload(manifest: dict[str,object], bundle: Path, repo_root: Path) -> dict[str,object]:
    """Return exact canonical payload for this verified run manifest."""
def inspect_forecast_state(*, bundle: Path, staging: Path,
    verification_staging: Path, registry_root: Path, repo_root: Path) -> ForecastStructure:
    """Classify structural candidate shape only; do not certify expected bytes."""
def expected_publication(staging: Path, bundle: Path, registry_root: Path,
    repo_root: Path) -> ExpectedPublication:
    """Validate staged outputs and derive exact final manifest and link bytes."""
def verify_expected_publication(expected: ExpectedPublication, *, artifact: Path,
    link: Path | None, state: Literal["prepared", "artifact_published", "complete"]) -> None:
    """Require the whole target artifact and optional link equal replayed expected bytes."""
def publish_forecast_link(expected: ExpectedPublication) -> PublishedForecast:
    """Exclusively create the exact pre-derived link after exact artifact publication."""
```

Test helpers such as `valid_expected_publication`, `self_consistent_prepared_publication`, and `install_valid_transaction_state` return a test-file fixture wrapper that carries an `ExpectedPublication` plus the transaction paths and convenience accessors the tests call (`.staging`, `.bundle`, `.link`, `.verification_staging`, `.state_args()`); the wrapper is defined in the test file and is not part of the production API above.

- [ ] **Step 1: Write RED state-machine tests.**

```python
def test_manifestless_final_directory_is_legacy_conflict_not_prepared(tmp_path):
    """Kills mutation: classify arbitrary manifestless final-dir wreckage as resumable staging."""
    bundle, staging, verification, root = transaction_paths(tmp_path)
    bundle.mkdir(parents=True)
    with pytest.raises(PublishedForecastError, match="legacy"):
        inspect_forecast_state(bundle=bundle, staging=staging,
            verification_staging=verification, registry_root=root / "registry", repo_root=root)

def test_structural_prepared_candidate_rejects_extra_publish_staging_file(tmp_path):
    """Kills mutation: accept an extra file in the fixed staging tree."""
    expected = valid_expected_publication(tmp_path)
    prepare_exact_staging(expected)
    assert inspect_forecast_state(**expected.state_args()).candidate == "prepared_candidate"
    (expected.staging / "foreign").write_text("x", encoding="utf-8")
    with pytest.raises(PublishedForecastError, match="unexpected"):
        inspect_forecast_state(**expected.state_args())

def test_prepared_requires_full_replay_equality_before_publication(tmp_path):
    """Kills mutation: certify self-consistent prepared bytes without replay equality."""
    prepared = self_consistent_prepared_publication(tmp_path, card_variant="changed")
    replayed = replay_expected_publication(prepared, card_variant="registered")
    assert inspect_forecast_state(**prepared.state_args()).candidate == "prepared_candidate"
    with pytest.raises(PublishedForecastError, match="expected bytes"):
        verify_expected_publication(
            replayed, artifact=prepared.staging, link=None, state="prepared"
        )

def test_recovery_candidate_allows_fixed_safe_verification_scratch(tmp_path):
    """Kills mutation: reject run-owned verification scratch left by a recovery crash."""
    expected = valid_expected_publication(tmp_path)
    prepare_exact_staging(expected)
    expected.verification_staging.mkdir(parents=True)
    (expected.verification_staging / "partial.json").write_text("{}", encoding="utf-8")
    structure = inspect_forecast_state(**expected.state_args())
    assert structure.candidate == "prepared_candidate"
    assert structure.verification_scratch == expected.verification_staging

def test_fresh_candidate_rejects_verification_scratch(tmp_path):
    """Kills mutation: admit verification scratch when no recovery artifact owns it."""
    expected = valid_expected_publication(tmp_path)
    expected.verification_staging.mkdir(parents=True)
    with pytest.raises(PublishedForecastError, match="verification scratch"):
        inspect_forecast_state(**expected.state_args())

def test_recovery_candidate_rejects_symlinked_verification_scratch(tmp_path):
    """Kills mutation: accept a symlink as fixed verification scratch."""
    expected = valid_expected_publication(tmp_path)
    prepare_exact_staging(expected)
    target = tmp_path / "scratch-target"
    target.mkdir()
    expected.verification_staging.symlink_to(target, target_is_directory=True)
    with pytest.raises(PublishedForecastError, match="symlink"):
        inspect_forecast_state(**expected.state_args())

def test_recovery_candidate_rejects_malformed_verification_scratch(tmp_path):
    """Kills mutation: accept a non-directory fixed verification scratch path."""
    expected = valid_expected_publication(tmp_path)
    prepare_exact_staging(expected)
    expected.verification_staging.parent.mkdir(parents=True, exist_ok=True)
    expected.verification_staging.write_text("not a tree", encoding="utf-8")
    with pytest.raises(PublishedForecastError, match="verification scratch"):
        inspect_forecast_state(**expected.state_args())

def test_recovery_candidate_rejects_out_of_root_verification_path(tmp_path):
    """Kills mutation: skip repository-containment validation for verification staging."""
    expected = valid_expected_publication(tmp_path)
    prepare_exact_staging(expected)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-verify"
    with pytest.raises(PublishedForecastError, match="repository"):
        inspect_forecast_state(**{
            **expected.state_args(), "verification_staging": outside,
        })

def test_artifact_published_retry_requires_replayed_expected_bytes_before_link_repair(tmp_path):
    """Kills mutation: repair a link for a self-consistent artifact without exact replay equivalence."""
    expected = valid_expected_publication(tmp_path)
    publish_final_artifact(expected)
    assert inspect_forecast_state(**expected.state_args()).candidate == "artifact_published_candidate"
    with pytest.raises(PublishedForecastError, match="expected bytes"):
        verify_expected_publication(
            expected.with_changed_staged_output(), artifact=expected.bundle,
            link=None, state="artifact_published",
        )
    verify_expected_publication(
        expected, artifact=expected.bundle, link=None, state="artifact_published"
    )
    linked = publish_forecast_link(expected)
    assert inspect_forecast_state(**expected.state_args()).candidate == "complete_candidate"
    assert json.loads(linked.path.read_text())["record_id"] == linked.forecast_id

def test_link_without_matching_manifest_is_rejected(tmp_path):
    """Kills mutation: accept a target registry link without its final artifact."""
    expected = valid_expected_publication(tmp_path)
    write_canonical_target_link(expected)
    with pytest.raises(PublishedForecastError, match="link without artifact"):
        inspect_forecast_state(**expected.state_args())

def test_global_orphan_link_is_found_even_when_its_filename_is_not_predicted(tmp_path):
    """Kills mutation: limit registry scanning to the predicted target filename."""
    expected = valid_expected_publication(tmp_path)
    orphan = valid_expected_publication(tmp_path, run_id="b" * 64)
    write_canonical_target_link(orphan)
    with pytest.raises(PublishedForecastError, match="link without artifact"):
        inspect_forecast_state(**expected.state_args())
```

Add these concrete tests, each with the exact mutation docstring and the stated manual mutation/fail/restore/pass cycle:

```python
def test_forecast_state_rejects_malformed_registry_document(tmp_path):
    """Kills mutation: treat malformed registry JSON as an absent registry entry."""
    expected = valid_expected_publication(tmp_path)
    malformed = write_canonical_target_link(expected)
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(PublishedForecastError, match="malformed"):
        inspect_forecast_state(**expected.state_args())

def test_forecast_state_rejects_duplicate_global_links(tmp_path):
    """Kills mutation: inspect only the expected registry filename for a run ID."""
    expected = valid_expected_publication(tmp_path)
    publish_final_artifact(expected)
    write_canonical_target_link(expected)
    write_canonical_target_conflict(expected, inputs=alternate_bound_inputs(expected))
    with pytest.raises(PublishedForecastError, match="conflict"):
        inspect_forecast_state(**expected.state_args())

def test_forecast_state_rejects_link_digest_byte_conflict(tmp_path):
    """Kills mutation: accept a registry manifest digest that differs from artifact bytes."""
    expected = valid_expected_publication(tmp_path)
    write_canonical_target_conflict(expected, manifest_sha256="b" * 64)
    with pytest.raises(PublishedForecastError, match="digest"):
        inspect_forecast_state(**expected.state_args())

def test_complete_rejects_foreign_kind_registry_entry(tmp_path):
    """Kills mutation: accept a foreign-kind registry record in a canonical filename."""
    expected = valid_expected_publication(tmp_path)
    publish_final_artifact(expected)
    publish_forecast_link(expected)
    foreign = write_foreign_kind_record_with_canonical_filename(expected.forecast_dir)
    with pytest.raises(PublishedForecastError, match="unexpected"):
        inspect_forecast_state(**expected.state_args())
    foreign.unlink()

def test_complete_rejects_registry_symlink(tmp_path):
    """Kills mutation: accept a symlink in the registry directory."""
    expected = valid_expected_publication(tmp_path)
    publish_final_artifact(expected)
    first = publish_forecast_link(expected)
    before = first.path.read_bytes()
    expected.forecast_dir.joinpath("bad-link").symlink_to(first.path)
    with pytest.raises(PublishedForecastError, match="symlink"):
        inspect_forecast_state(**expected.state_args())
    assert first.path.read_bytes() == before

def test_global_scan_allows_another_canonical_published_forecast(tmp_path):
    """Kills mutation: reject every registry record other than the target run's link."""
    expected = valid_expected_publication(tmp_path)
    publish_final_artifact(expected)
    publish_forecast_link(expected)
    other = valid_expected_publication(tmp_path, run_id="b" * 64)
    publish_final_artifact(other)
    publish_forecast_link(other)
    assert inspect_forecast_state(**expected.state_args()).candidate == "complete_candidate"

def test_global_scan_uses_historical_verifier_for_other_record_after_live_input_changes(tmp_path, monkeypatch):
    """Kills mutation: validate another published run with live-tree verify_run_bundle."""
    expected = valid_expected_publication(tmp_path)
    publish_final_artifact(expected)
    publish_forecast_link(expected)
    other = historical_expected_publication(tmp_path, run_id="b" * 64)
    publish_final_artifact(other)
    publish_forecast_link(other)
    mutate_live_declared_input(other)
    monkeypatch.setattr(published_forecast, "verify_run_bundle", lambda *_1, **_2: pytest.fail("live verifier"))
    calls: list[Path] = []
    monkeypatch.setattr(published_forecast, "verify_run_bundle_at_source_revision", historical_verifier_spy(calls))
    assert inspect_forecast_state(**expected.state_args()).candidate == "complete_candidate"
    assert calls == [other.bundle]
```

For each test, change the named implementation predicate, run its one test and observe failure, restore it, and rerun it green before proceeding.

- [ ] **Step 2: Run RED.** Run `.venv/bin/python -m pytest tests/test_published_forecast.py -q`; expect collection failure.

- [ ] **Step 3: Minimal implementation.** Import Plan 1's `verify_run_bundle_at_source_revision` from `ti26.provenance`. Derive a lower-case 64-hex run ID, final bundle path, one fixed publish-staging path, and one distinct fixed verification-staging path before mutation. `inspect_forecast_state` takes both staging paths and performs read-only structural classification only. It returns `fresh`, `prepared_candidate`, `artifact_published_candidate`, or `complete_candidate` through `ForecastStructure`; it cannot certify expected bytes before a replay exists. A manifestless final directory is legacy/conflict, never staging. A prepared candidate must be a self-consistent complete publish-staging tree, but that fact alone does not make it the spec's `prepared` state. Partial or structurally invalid publish staging conflicts; replay comparison later rejects a structurally valid but byte-inexact candidate. Verification scratch is absent for `fresh`; each recovery candidate permits either no scratch or one real, non-symlink, run-owned tree at the exact fixed verification path. Validate the verification path and every existing ancestor/entry as a safe repository descendant; reject a non-directory root, special entry, unsafe path, malformed present manifest, or any overlap/ancestor relationship with publish staging or the final bundle. Its contents may be incomplete because it is disposable crash scratch, but no classifier or admission step deletes them.

  The candidate-production order is exact for both fresh generation and recovery replay: producers → frozen aggregate and final-card rerender plus report prefixing → staged internal JSON validation through `load_staged_frozen_output` → derive and write canonical `manifest.json` last → atomic artifact publication → exclusive-create the canonical link last. `expected_publication` runs only after the staged internal validation, writes/derives the canonical manifest and link bytes, and returns safe final paths plus the complete expected artifact tree. For `prepared_candidate`, replay into verification staging and pass the preserved publish staging to `verify_expected_publication(state="prepared")`; compare the complete relative-path set, entry types, and every file byte, including `manifest.json`. Only equality establishes exact `prepared`, after which atomically rename the preserved publish staging and create the link. For `artifact_published_candidate` and `complete_candidate`, compare the final artifact and absent/present target link against the same replay-derived expectation before repair/success. Never replay into, modify, or overwrite preserved publish/final bytes.

  Scan the registry directory itself: for every non-target canonical `published_forecast` record at its canonical filename, resolve its safe bundle path and call `verify_run_bundle_at_source_revision(record_bundle, repo_root=repo_root)`, so its own manifest `source_revision` binds input verification. Do not call live-tree `verify_run_bundle` for other records; later live-input changes must not block a new release. Reject symlinks, non-regular files, malformed/unsafe documents, foreign schema/kind/path, and target-run duplicate/link-only/conflicting state. Target recovery remains deterministic live replay plus `verify_expected_publication` byte comparison. All staging/final/registry paths must be safe descendants of `repo_root`. Test helpers always write canonical filename/payload pairs and build genuinely manifest-valid staged bundles through the existing manifest writer; they never pass arbitrary bytes as `manifest.json` or bypass the appropriate verifier.

- [ ] **Step 4: Run GREEN and mutation proof.** Rerun Step 2; expect PASS. For every Step-1 node, apply only the exact mutation named by that node's docstring, run that node and observe RED, restore, then run the same node GREEN. Do not use one broad mutation or one combined test as evidence for multiple predicates. Finally rerun Step 2; expect PASS.

- [ ] **Step 5: Commit.** Run `git add src/ti26/published_forecast.py tests/test_published_forecast.py` then `git commit -m "feat: link published forecast artifacts"`.

### Task 4: Rewire cli release in preflight/oracle/transaction order

**Files:** Modify `src/ti26/cli_release.py:17-340`, `tests/test_cli_release.py`, `src/ti26/frozen_output_oracle.py` (append `--frozen-replay` to `replay_current_frozen_output`'s argument list only — `registered_baseline_invocation`, `FrozenBaselineInvocation.release_args`, and the oracle CLI surface stay untouched), `tests/test_frozen_output_oracle.py` (update the one pre-amendment argv expectation and add `test_frozen_replay_argv_binds_only_recorded_baseline_arguments`; no new test file is created).

- [ ] **Step 1: Write RED orchestration tests.**

```python
def test_preflight_failure_touches_no_store_run_or_registry(tmp_path, monkeypatch, capsys):
    """Kills mutation: create the processed-store directory before preflight succeeds."""
    marker = tmp_path / "runs" / "x" / "keep"; marker.parent.mkdir(parents=True); marker.write_text("keep")
    monkeypatch.setattr(cli_release, "preflight_release", lambda **_: (_ for _ in ()).throw(ReleasePreflightError("field")))
    with pytest.raises(SystemExit): cli_release.main(minimal_argv(tmp_path))
    assert "field" in capsys.readouterr().err
    assert marker.read_text() == "keep"
    assert not (tmp_path / "processed").exists() and not (tmp_path / "registry").exists()

def test_normal_release_never_invokes_historical_frozen_oracle(tmp_path, monkeypatch):
    """Kills mutation: block a valid near-lock release with the historical frozen-regression oracle."""
    install_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_release, "assert_matches_frozen_output", lambda *_: pytest.fail("wrong oracle"), raising=False)
    assert cli_release.main(minimal_argv(tmp_path)) == 0

def test_prepared_replays_before_publishing_preserved_staging(tmp_path, monkeypatch):
    """Kills mutation: publish a prepared candidate without deterministic replay equality."""
    install_preflight(monkeypatch, tmp_path)
    prepared = install_valid_transaction_state(tmp_path, state="prepared_candidate")
    before = tree_bytes(prepared.staging)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        cli_release, "_run", deterministic_replay_runner(prepared.verification_staging, calls)
    )
    assert cli_release.main(minimal_argv(tmp_path)) == 0
    assert calls and tree_bytes(prepared.bundle) == before

def test_prepared_replay_mismatch_never_publishes_candidate(tmp_path, monkeypatch, capsys):
    """Kills mutation: publish self-consistent prepared bytes that differ from replay."""
    install_preflight(monkeypatch, tmp_path)
    prepared = install_valid_transaction_state(
        tmp_path, state="prepared_candidate", card_variant="changed"
    )
    monkeypatch.setattr(
        cli_release, "_run",
        deterministic_replay_runner(prepared.verification_staging, card_variant="registered"),
    )
    with pytest.raises(SystemExit):
        cli_release.main(minimal_argv(tmp_path))
    assert "expected bytes" in capsys.readouterr().err
    assert prepared.staging.exists() and not prepared.bundle.exists() and not prepared.link.exists()

def test_recovery_crash_scratch_survives_admission_then_is_rebuilt(tmp_path, monkeypatch):
    """Kills mutation: clear verification scratch before phase-two Git admission."""
    install_preflight(monkeypatch, tmp_path)
    prepared = install_valid_transaction_state(tmp_path, state="prepared_candidate")
    prepared.verification_staging.mkdir(parents=True)
    crash_marker = prepared.verification_staging / "crash.partial"
    crash_marker.write_text("partial", encoding="utf-8")
    publish_bytes = tree_bytes(prepared.staging)

    def admit(*args, **kwargs):
        assert crash_marker.read_text(encoding="utf-8") == "partial"
        assert tree_bytes(prepared.staging) == publish_bytes

    monkeypatch.setattr(cli_release, "_second_git_admission", admit)
    monkeypatch.setattr(
        cli_release, "_run",
        replay_runner_asserting_clean_scratch(prepared.verification_staging, crash_marker),
    )
    assert cli_release.main(minimal_argv(tmp_path)) == 0
    assert tree_bytes(prepared.bundle) == publish_bytes

def test_complete_retry_replays_to_verification_staging(tmp_path, monkeypatch):
    """Kills mutation: return success for complete state without verification-staging replay."""
    install_preflight(monkeypatch, tmp_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(cli_release, "_run", lambda argv, _: calls.append(argv) or 0)
    install_valid_transaction_state(tmp_path, state="complete_candidate")
    assert cli_release.main(minimal_argv(tmp_path)) == 0
    assert calls

def test_artifact_published_retry_replays_to_verification_staging(tmp_path, monkeypatch):
    """Kills mutation: repair an artifact-published link without verification-staging replay."""
    install_preflight(monkeypatch, tmp_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(cli_release, "_run", lambda argv, _: calls.append(argv) or 0)
    calls.clear()
    install_valid_transaction_state(tmp_path, state="artifact_published_candidate")
    assert cli_release.main(minimal_argv(tmp_path)) == 0
    assert calls

def test_persisted_ingest_digest_must_equal_preflight_digest(tmp_path, monkeypatch, capsys):
    """Kills mutation: delete a durable retry artifact after a persisted digest mismatch."""
    install_preflight(monkeypatch, tmp_path, store_digest={"sha256": "a" * 64})
    durable = install_valid_transaction_state(tmp_path, state="artifact_published_candidate")
    monkeypatch.setattr(cli_release, "logical_store_digest", lambda _: {"sha256": "b" * 64})
    with pytest.raises(SystemExit) as exited:
        cli_release.main(minimal_argv(tmp_path))
    assert exited.value.code == 2
    assert "preflight store digest" in capsys.readouterr().err
    assert durable.bundle.exists() and not durable.link.exists()

def test_d2_nonzero_gate_verdict_is_retained_without_aborting(tmp_path, monkeypatch):
    """Kills mutation: treat a registered D2 blocked verdict as a producer failure."""
    install_preflight(monkeypatch, tmp_path)
    install_runner(monkeypatch, d2_verdict="blocked", d2_exit=1, d4_exit=0)
    assert cli_release.main(minimal_argv(tmp_path)) == 0
    artifact = load_frozen_gate_artifact(
        only_bundle(tmp_path / "runs") / "frozen_gate_results.json"
    )
    assert artifact["gates"]["D2"]["verdict"] == "blocked"

def test_d4_nonzero_process_exit_aborts_release(tmp_path, monkeypatch):
    """Kills mutation: ignore a D4 producer-process failure."""
    install_preflight(monkeypatch, tmp_path)
    install_runner(monkeypatch, d2_verdict="pass", d2_exit=0, d4_exit=1)
    with pytest.raises(SystemExit):
        cli_release.main(minimal_argv(tmp_path))
    assert not list((tmp_path / "runs").rglob("manifest.json"))
```

These two focused nodes preserve the D2 gate/non-gate distinction: a registered D2 non-zero verdict is evidence retained in the frozen gate artifact, while D4 process failure is an operational failure and D4 never changes the card.

- [ ] **Step 2: Run RED.** Run `.venv/bin/python -m pytest tests/test_cli_release.py -k 'preflight_failure or frozen or prepared or replay or recovery_crash or gate' -q`; expect failure.

- [ ] **Step 3: Minimal implementation.** Parse evidence-root/cutoff/registry-root plus the new `--frozen-replay` flag, and retain the existing optional `--groups` argument. `--frozen-replay` is the internal diagnostic route Plan 1's cross-plan obligation requires: it skips `preflight_release`, evidence loading, `inspect_forecast_state`, second admission, and every registry read or write, and runs the unchanged predictive pipeline into the caller's `--runs` root with the manifest written last, so the oracle can verify and compare the candidate. In the same commit, extend the oracle's appended argument list in `replay_current_frozen_output` with `--frozen-replay` (recorded `release_args` and the oracle CLI surface stay untouched) and update the single pre-amendment argv expectation in Plan 1's existing `tests/test_frozen_output_oracle.py::test_isolated_replay_uses_registered_args_and_live_verifies_before_compare` to include the flag. Do not rewrite `registered_baseline_invocation` and do not alter the contents of `FrozenBaselineInvocation.release_args`.

  Construct the parser with `allow_abbrev=False`: a provenance-sensitive CLI must not accept an abbreviated long option whose meaning changes when a future option is added. Do **not** place `--frozen-replay`, `--evidence-root`, `--cutoff`, and `--registry-root` in one `argparse` mutually exclusive group — such a group permits only one member to appear, and ordinary release needs all three live-evidence arguments together, so it would reject valid normal invocations. Validate the mode after parsing instead:

```python
if args.frozen_replay:
    forbidden = {
        "--evidence-root": args.evidence_root,
        "--cutoff": args.cutoff,
        "--registry-root": args.registry_root,
    }
    supplied = [name for name, value in forbidden.items() if value is not None]
    if supplied:
        parser.error(
            "--frozen-replay cannot be combined with " + ", ".join(supplied)
        )
else:
    missing = [
        name
        for name, value in {
            "--evidence-root": args.evidence_root,
            "--cutoff": args.cutoff,
            "--registry-root": args.registry_root,
        }.items()
        if value is None
    ]
    if missing:
        parser.error("ordinary release requires " + ", ".join(missing))
```

  `--groups` is deliberately absent from both lists. It is permitted in replay mode only because it may already be present in `FrozenBaselineInvocation.release_args`, reconstructed from the registered baseline manifest; the oracle never accepts a caller-supplied group override, and rejecting it here would invalidate a legitimately conditioned historical baseline.

  For ordinary invocations (no `--frozen-replay`), call `preflight_release` immediately after `repo_root`; use its revision, snapshot, rows, input digests, retained `untracked_paths`, and expected `store_digest` to build the unchanged descriptor, run ID, final bundle path, fixed publish-staging path, and distinct fixed verification-staging path before creating a store or bundle. Pass both staging paths to structural-only `inspect_forecast_state` before `_run`, then pass `structure.candidate`, `structure.allowed_link_paths`, the fixed verification path, and `structure.verification_scratch` as the only admitted scratch to `_second_git_admission`. Treat a manifestless final directory, link-only state, unexpected entry, malformed scratch, or overlapping/out-of-root/symlink path as conflict; never delete any of them during classification or admission. This deliberately inverts the current `cli_release.main` behavior that `shutil.rmtree`s and silently replaces a final bundle directory lacking `manifest.json` (the 2026-08-08 interrupted-run fix): delete that auto-replace branch and its justifying comment as part of this step — recovery now goes through classification, replay, and byte-proof, and wreckage that classifies as conflict is an owner decision. The runbook's "an unfinished directory is replaced with a printed notice" sentence is updated to match in Task 6's docs step. Create the persistent store by the existing `cli_ingest` route, reopen it read-only, and require its complete `logical_store_digest` object to equal `preflight.store_digest` before any producer, scratch reset, or publication. A mismatch reports stderr, creates no **new** final artifact/link, and preserves durable retry artifacts; do not silently replace the descriptor digest.

  Keep `fresh` behavior on publish staging. Its exact order is: producers → frozen aggregate and final-card rerender plus report prefixing → staged internal JSON validation through `load_staged_frozen_output` → derive and write canonical `manifest.json` last → atomically publish the exact staging tree → exclusive-create `publish_forecast_link` last. For every recovery candidate, only after phase-two admission and store-digest equality, revalidate that the exact verification path is a safe, real repository descendant disjoint from and not an ancestor/descendant of publish staging or the final bundle; safely remove only that path if the classifier admitted crash scratch, recreate it, and replay there in the same order through canonical manifest derivation. Never clear or write the preserved publish staging/final artifact. Derive `ExpectedPublication`, then call `verify_expected_publication`: `prepared_candidate` compares the entire preserved publish-staging tree as `state="prepared"`; `artifact_published_candidate` compares the final tree as `state="artifact_published"`; `complete_candidate` compares the final tree and link as `state="complete"`. Any byte/type/path mismatch preserves durable bytes and fails. After equality, remove verification staging; atomically rename exact prepared publish staging before exclusive link creation, repair only the absent artifact-published link, or return complete success. Thus a crash during replay leaves admissible scratch, while every successful `complete` state has no temporary object.

  `load_staged_frozen_output` always performs staged internal validation. Normal release never calls `assert_matches_frozen_output`. The public frozen-regression command remains Plan 1's `python -m ti26.frozen_output_oracle` driving `replay_current_frozen_output`; do not add a `cli_frozen_regression` module, a `tests/test_frozen_regression.py` file, or any second public frozen-regression entry point — Plan 1 already owns and tests the non-publishing, temporary-staging, cleanup-on-success, preserve-on-failure semantics. The internal `--frozen-replay` mode on the existing `cli_release` is not such an entry point: it is a flag on a command this plan already modifies, it adds no module and no public oracle option, and its tests live in `tests/test_cli_release.py` and `tests/test_frozen_output_oracle.py`.

  Plan 3's obligations here are: `test_normal_release_never_invokes_historical_frozen_oracle` (above) proves ordinary release never touches the comparator; the final-verification oracle replay (Task 6 Step 5) proves Plan 3's changes did not move frozen output; and three tests prove live evidence never gates the replay.

  `test_frozen_replay_mode_rejects_evidence_arguments` (`Kills mutation: accept --evidence-root alongside --frozen-replay.`) — run the rejection separately for each of `--evidence-root`, `--cutoff`, and `--registry-root`, plus at least one combination of two. The mutation removes the post-parse mode validation and must demonstrate that an evidence argument reaches the diagnostic path.

  `test_frozen_replay_ignores_live_evidence_tips` (`Kills mutation: route the frozen replay through preflight_release or load_release_evidence.`) — import a newer roster tip and a newer draw tip into the fixture evidence root, then monkeypatch every one of `load_release_evidence`, `reconcile_release_evidence`, `preflight_release`, `inspect_forecast_state`, and `publish_forecast_link` to `pytest.fail`. Success must prove all four: a candidate bundle was emitted under the supplied temporary runs root; no repository run was published; no registry directory or link was created; and the live evidence bytes appear nowhere in the candidate manifest.

  `test_frozen_replay_argv_binds_only_recorded_baseline_arguments` (`Kills mutation: append evidence or registry arguments to the replayed invocation.`) — capture the argv `replay_current_frozen_output` passes to `cli_release` and assert it is exactly:

```python
(
    *invocation.release_args,
    "--runs", str(runs_root),
    "--run-kind", CANDIDATE_RUN_KIND,
    "--source-revision", revision,
    "--frozen-replay",
)
```

  and additionally assert the absence of each live-evidence option by name:

```python
assert "--evidence-root" not in captured
assert "--cutoff" not in captured
assert "--registry-root" not in captured
```

  The converse — ordinary shipping consumes current evidence and fails closed on mismatch — is already owned by the Task 1–4 preflight tests; do not duplicate it here. Ordinary release must continue to prove, through those tests, that it always reconciles evidence, always performs both Git admissions, always runs transaction-state classification, always publishes artifact first and link last, never invokes `assert_matches_frozen_output`, and never enters `--frozen-replay` mode implicitly. For a `ReleasePreflightError` or transaction error in `cli_release`, `print(str(exc), file=sys.stderr)` then `raise SystemExit(2)`: tests inspect stderr, never `pytest.raises(..., match=...)` on `SystemExit`. No producer receives new predictive arguments.

- [ ] **Step 4: Run GREEN and mutation proof.** Rerun Step 2; expect PASS. For every Step-1 node, apply only its docstring's exact mutation, run that node RED, restore, and rerun it GREEN. The crash-scratch node must specifically prove that moving scratch deletion before `_second_git_admission` fails; the prepared nodes separately prove replay is mandatory and mismatched self-consistent staging remains unpublished. Finally rerun Step 2; expect PASS.

- [ ] **Step 5: Commit.** Run `git add src/ti26/cli_release.py tests/test_cli_release.py` then `git commit -m "feat: preflight and publish release transaction"`.

### Task 5: Add exact deterministic miniature release proof

**Files:** Modify `tests/test_cli_release.py`.

- [ ] **Step 1: Write required test.**

```python
def test_miniature_release_is_deterministic_and_verifiable(tmp_path, monkeypatch):
    """Kills mutation: emit nondeterministic published bytes for identical fixture repositories."""
    left, right = identical_miniature_repos(tmp_path)
    bundles = []
    for repo in (left, right):
        monkeypatch.chdir(repo)
        monkeypatch.setattr(cli_release, "_run", deterministic_fake_producer_runner(repo))
        assert cli_release.main(miniature_argv(repo)) == 0
        bundle = only_bundle(repo / "reports/runs")
        bundles.append(bundle)
        assert verify_run_bundle(bundle, repo_root=repo)
        assert inspect_forecast_state(**expected_state_args(repo, bundle)).candidate == "complete_candidate"
    assert tree_bytes(bundles[0]) == tree_bytes(bundles[1])

def test_miniature_prepared_recovery_replays_in_separate_scratch(tmp_path, monkeypatch):
    """Kills mutation: replay a prepared recovery into preserved publish staging."""
    repo = isolated_miniature_repo(tmp_path)
    prepared = leave_complete_publish_staging(repo)
    trace = run_traced_release(repo, monkeypatch)
    assert trace.replay_root == prepared.verification_staging
    assert trace.publish_staging_bytes_before_rename == prepared.original_bytes

def test_miniature_artifact_published_recovery_requires_expected_bytes(tmp_path, monkeypatch):
    """Kills mutation: repair an artifact-published link without replay byte equality."""
    repo = isolated_miniature_repo(tmp_path)
    state = leave_artifact_published(repo)
    with pytest.raises(SystemExit):
        run_traced_release(repo, monkeypatch, replay_variant="changed")
    assert not state.link.exists()

def test_miniature_complete_recovery_requires_expected_bytes(tmp_path, monkeypatch):
    """Kills mutation: return complete success without replay byte equality."""
    repo = isolated_miniature_repo(tmp_path)
    state = leave_complete(repo)
    with pytest.raises(SystemExit):
        run_traced_release(repo, monkeypatch, replay_variant="changed")
    assert state.bundle.exists() and state.link.exists()

def test_miniature_crash_scratch_is_cleared_only_after_admission(tmp_path, monkeypatch):
    """Kills mutation: remove fixed verification scratch before phase-two admission."""
    repo = isolated_miniature_repo(tmp_path)
    state = leave_prepared_with_partial_verification_scratch(repo)
    trace = run_traced_release(repo, monkeypatch)
    assert trace.scratch_existed_at_second_admission
    assert trace.scratch_was_clean_at_first_replay_write
```

`identical_miniature_repos` creates two distinct clean repositories and two distinct registries from byte-identical fixture source. It sets the same fixed Git identity, commit timestamp, and committed source bytes so both resolve to the same source revision; it must not point two working trees at one registry. Each fixture contains Plan-1 baseline/input bytes and minimal Plan-2 evidence/raw/config, including independently selected groups and Round-1 evidence and the one existing draw YAML containing both fields. Fake producers write deterministic complete baseline gate/card JSON plus required deterministic diagnostics; real preflight result consumption, in-memory/persisted digest equality, fixed staging, staged internal validation, frozen-gate artifact, canonical staged manifest, atomic final publication, and `publish_forecast_link` must execute. Assert the exact normal-release order: producers → frozen aggregate/card rerender plus prefixing → staged internal JSON validation → canonical manifest write last → atomic artifact publication → link last. Ordinary miniature release proves it never invokes the historical frozen oracle. A separate frozen-regression miniature calls Plan 1's `replay_current_frozen_output(repo_root=<miniature repo>, runs_root=<outside-repo scratch>, source_revision=<miniature HEAD>)` against the fixture's committed Plan-1 baseline, proves that call is the one that exercises the oracle, and proves both success and failure leave no final bundle or registry link in the miniature repo — through Plan 1's API, not a reimplementation. Wrap `write_run_manifest` and `load_staged_frozen_output` to assert each staging tree is internally validated before its one canonical manifest write.

The focused recovery miniatures use one isolated repository each and one mutation per node. For a prepared candidate, preserve its complete publish staging, retain any fixed safe crash scratch through classification and phase-two admission, clear/rebuild only verification staging afterward, replay there through manifest-last derivation, byte-compare the entire publish-staging tree to `ExpectedPublication`, remove verification staging, then atomically publish the preserved tree and create the link last. Partial or structurally invalid publish staging conflicts; a structurally valid but byte-inexact candidate fails only after replay comparison. For `artifact_published_candidate`, require the same separate replay and final-tree equality before link repair. For `complete_candidate`, require replay plus final-tree/link equality before idempotent success. A malformed, symlinked, out-of-root, or fresh-state verification path conflicts and is never deleted. The structural/global tests separately reject a manifestless final directory, malformed/foreign-kind registry entry, or symlink, while allowing another canonical schema-valid published-forecast link only after `verify_run_bundle_at_source_revision` validates it at that record's own manifest revision—even if the live declared input has since changed. The cross-repository equality assertion compares the two independently produced final bundles.

- [ ] **Step 2: Run RED.** Run `.venv/bin/python -m pytest tests/test_cli_release.py -k 'miniature' -q`; expect failure.

- [ ] **Step 3: Add test-only helpers.** Keep them in this test file; no production test switch. Wrap manifest/link calls to prove order.

- [ ] **Step 4: Run GREEN and mutation proof.** Rerun Step 2; expect PASS. For each miniature node, apply only its docstring's exact mutation, run that exact node RED, restore, and rerun it GREEN. The deterministic node's sole mutation is adding `time.time()` to fake output; other invariants rely on their focused nodes rather than adding alternatives to this docstring. Finally rerun Step 2; expect PASS.

- [ ] **Step 5: Commit.** Run `git add tests/test_cli_release.py` then `git commit -m "test: prove deterministic miniature release"`.

### Task 6: Update near-lock runbook and final verification

**Files:** Modify `docs/ti26/near-lock-runbook.md:14-323`, `tests/test_docs.py`.

- [ ] **Step 1: Write RED doc test.**

```python
def test_near_lock_runbook_imports_evidence_before_preflight_release():
    """Kills mutation: leave manual rules/roster/draw confirmation after generation starts."""
    text = Path("docs/ti26/near-lock-runbook.md").read_text()
    assert text.index("cli_evidence_import") < text.index("ti26.cli_release")
    assert "git rev-parse HEAD" in text and "--source-revision" in text
    assert "preflight failure leaves no processed store or run bundle" in text
    assert "published draw evidence" in text and "unpublished draw evidence" in text
    assert "one draw YAML" in text and "Round 1" in text
```

- [ ] **Step 2: Run RED.** Run `.venv/bin/python -m pytest tests/test_docs.py -k 'imports_evidence_before_preflight' -q`; expect failure.

- [ ] **Step 3: Update docs.** Require owner capture/import of current rules, field, exact roster account sets, published-draw evidence, and unpublished-draw evidence first; explain that groups and Round 1 have independent evidence states while the existing one draw YAML carries both shipping fields. Describe clean tracked-and-untracked HEAD, Plan-2 current evidence, the two-stage roster boundary, no-write failure, distinct publish/verification staging, structural candidates versus exact transaction states, and global registry validation (other verified canonical forecast records are allowed only when `verify_run_bundle_at_source_revision` verifies them against each record's own manifest revision; malformed, unsafe, foreign-kind, and broken links reject). Document that recovery scratch survives read-only classification and phase-two admission, then is safely cleared/rebuilt without touching preserved publish/final bytes. Require deterministic verification replay and whole-tree/manifest equality before a prepared candidate may atomically publish, before `artifact_published` link repair, and before `complete` success; artifact publication remains before link creation. State that legacy manifestless final directories require owner recovery, replacing the runbook step-6 sentence "an unfinished directory is replaced with a printed notice" with the new classification/replay/owner-recovery contract. Preserve owner external-source boundary, gates/non-gates, the diagnostic-only frozen-regression oracle (Plan 1's `python -m ti26.frozen_output_oracle`; never normal release and never publication), verify-run and full suite.

- [ ] **Step 4: GREEN/mutate/commit.** Rerun Step 2; expect PASS. Move import after release then remove no-write sentence; test fails each time; restore PASS. Run `git add docs/ti26/near-lock-runbook.md tests/test_docs.py` then `git commit -m "docs: require release evidence preflight"`.

- [ ] **Step 5: Final verification.** Run `.venv/bin/python -m pytest tests/test_release_preflight.py tests/test_published_forecast.py tests/test_cli_release.py tests/test_frozen_output_oracle.py tests/test_docs.py -q`, then `.venv/bin/python -m pytest -q`, then `.venv/bin/python -m ruff check .`; each expected PASS. Then prove Plan 3 moved no frozen output by running the same isolated oracle replay the index requires after each non-predictive plan (all Task commits present, clean checkout):

```bash
test ! -e /private/tmp/ti26-plan3-frozen-replay
git rev-parse HEAD | xargs .venv/bin/python -m ti26.frozen_output_oracle --replay-root /private/tmp/ti26-plan3-frozen-replay --repo-root . --source-revision
```

Expected: exit 0 and removal of the replay root; no registered run or forecast link is created. On failure, stop — do not adjust the oracle, baseline, or any predictive producer to make it pass. For a genuinely generated run, use the exact bundle directory printed by that `cli_release` invocation as `--bundle` to `.venv/bin/python -m ti26.cli_provenance verify-run`, expecting exit 0; do not invent a run ID or modify the complete artifact. Commit only verification changes actually made by this plan.
