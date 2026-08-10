# Frozen Output Oracle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and register a fresh current-behavior release baseline, verify its declared inputs at its recorded Git commit, and compare later full release bundles against its complete D2/D3/D3b and machine-readable card outputs without changing prediction behavior.

**Architecture:** First, from a committed-plan, clean checkout, run the existing full release command against snapshot `20260802T165535Z` into a reserved directory containing exactly one runtime-named bundle. Then add a historical-input verification mode that shares only manifest/output checks with the existing live-tree verifier and reads each declared input as a regular Git blob at `manifest.source_revision`. A narrow oracle loads that registered bundle, cross-checks complete gate objects, and compares complete card JSON while normalizing the two display-name-keyed assignment objects to configured `team_id -> category` mappings.

**Tech Stack:** Python 3.12, standard-library `argparse`, `dataclasses`, `hashlib`, `json`, `pathlib`, `subprocess`, local Git CLI, pytest, Ruff, existing `ti26.cli_release`, `ti26.provenance`, and `ti26.gate_artifacts`.

## Global Constraints

- Execute Task 1 before any implementation edit. The approved plan documents must already be committed, and tracked plus untracked checkout status must be empty.
- Generate the baseline from the actual clean `HEAD`, snapshot `20260802T165535Z`, existing full `ti26.cli_release` defaults, and distinct run kind `ti2026-frozen-output-oracle-baseline`.
- The baseline run ID is produced by `cli_release`; do not predict, transcribe, rename, or encode it in source or tests.
- Register the baseline by reserving `reports/runs/frozen-output-oracle-baseline/` for exactly one child bundle whose directory name equals its manifest `run_id`. This is the auditable generated-path integration; do not add an empirical pointer under `config/`.
- Preserve existing `verify_run_bundle` live-tree semantics, including optional `against_revision`. Only manifest parsing, run-ID validation, output digest validation, and Markdown-prefix validation become shared helpers.
- Historical verification is offline and local-only. It resolves `manifest.source_revision` as a local Git commit and reads declared input bytes from regular Git blobs; it rejects tree and symlink modes, never checks out that revision, and never reaches the network.
- Preserve complete D2, D3, and D3b result objects. The authoritative mapping is `frozen_gate_results.json`, and every mapping member must equal its individual gate artifact.
- Preserve complete decoded `card/recommended_card.json`. Compare every non-assignment member exactly; compare `assignments` plus its configured `team_ids` mapping semantically as `team_id -> category` so display-name-only changes are irrelevant.
- Do not edit `src/ti26/cli_release.py`, any gate producer, `src/ti26/cli.py`, `src/ti26/cli_card.py`, ratings, calibration, simulation, optimization, configs, or any predictive module.
- Tests are offline and must not call a network transport.
- Every added or changed test has a docstring naming the exact implementation mutation it kills. Apply each mutation, observe the named test fail, restore the implementation, and observe it pass.
- Do not hand-author gate measurements, card assignments, team IDs, empirical counts, source revisions, or run IDs. Synthetic test-only strings, structural schema versions, and deliberately invalid synthetic hashes are not empirical claims.
- Completion requires a fresh post-change full release candidate, historical manifest verification, an actual oracle comparison, unfiltered pytest, and Ruff.

---

## File Structure

| File | Responsibility |
|---|---|
| `reports/runs/frozen-output-oracle-baseline/` | Generated, committed registration root containing exactly one full current-behavior release bundle. |
| `src/ti26/provenance.py` | Existing live verifier plus shared manifest/output checks and new Git-blob historical-input verifier. |
| `src/ti26/cli_provenance.py` | Explicit `verify-run --at-source-revision` CLI mode. |
| `src/ti26/frozen_output_oracle.py` | Registered-baseline resolution/invocation, strict manifest-bound and manifestless staged loading, stable-ID normalization, comparison, and isolated replay CLI. |
| `tests/test_provenance.py` | Isolated-Git tests for historical input verification and CLI routing. |
| `tests/test_frozen_output_oracle.py` | Real registration binding, synthetic staged-reader failures, complete-object comparisons, and CLI wiring. |
| `README.md` | Documents the opt-in historical verification command and its narrower claim. |

### Task 1: Generate and commit the current-behavior baseline before implementation

**Files:**

- Generate: `reports/runs/frozen-output-oracle-baseline/`

**Interfaces:**

- Consumes: current clean Git `HEAD`, committed snapshot `20260802T165535Z`, current configs, and existing `python -m ti26.cli_release` defaults.
- Produces: one full manifest-bound bundle under `reports/runs/frozen-output-oracle-baseline/`; its child directory name is runtime-derived and is never copied into this plan.

- [ ] **Step 1: Prove plans are committed and checkout is clean**

Run:

```bash
git status --porcelain=v1 --untracked-files=all
```

Expected: no output. Stop if any line appears; Task 1 must describe the actual clean `HEAD`, not a mixed checkout.

Run:

```bash
test ! -e reports/runs/frozen-output-oracle-baseline
```

Expected: exit zero. Stop rather than merge a second bundle into this reserved registration root.

- [ ] **Step 2: Generate the full release with a distinct run kind**

Run in the foreground so every producer exit remains visible:

```bash
git rev-parse HEAD | xargs .venv/bin/python -m ti26.cli_release --snapshot 20260802T165535Z --runs reports/runs/frozen-output-oracle-baseline --run-kind ti2026-frozen-output-oracle-baseline --source-revision
```

Expected: all non-gate producers exit zero; gate non-zero exits, if any, remain recorded evidence; the command prints one runtime-derived run ID and writes its manifest last.

- [ ] **Step 3: Verify the new bundle immediately against the same current revision**

Run:

```bash
find reports/runs/frozen-output-oracle-baseline -mindepth 1 -maxdepth 1 -type d | wc -l
```

Expected: `1`.

Run:

```bash
git rev-parse HEAD | xargs .venv/bin/python -m ti26.cli_provenance verify-run --bundle reports/runs/frozen-output-oracle-baseline/* --against-revision
```

Expected: exit zero and one canonical manifest JSON object. This is the existing live-tree verifier, run while the generating checkout is still clean.

- [ ] **Step 4: Prove the baseline card is the current corrected card**

Run:

```bash
cmp reports/runs/frozen-output-oracle-baseline/*/card/recommended_card.json reports/card_ti2026_rules/recommended_card.json
```

Expected: exit zero and no output. Any difference invalidates this attempted baseline and must be investigated before implementation begins.

- [ ] **Step 5: Commit only the generated baseline**

```bash
git add reports/runs/frozen-output-oracle-baseline
git commit -m "chore: freeze current predictive output baseline"
```

Run:

```bash
git status --porcelain=v1 --untracked-files=all
```

Expected: no output. The baseline manifest intentionally names the clean generation commit immediately before this artifact commit; Task 2 makes that historical binding durable.

### Task 2: Verify declared inputs from the manifest source commit

**Files:**

- Modify: `src/ti26/provenance.py`
- Modify: `tests/test_provenance.py`

**Interfaces:**

- Consumes: an existing run manifest, output files in its bundle, a local Git repository, and the exact lowercase commit SHA already stored in `manifest.source_revision`.
- Produces: `verify_run_bundle_at_source_revision(bundle: Path, *, repo_root: Path) -> dict[str, object]`.
- Preserves: `verify_run_bundle(bundle: Path, repo_root: Path | None = None, against_revision: str | None = None) -> dict[str, object]` and its live-file behavior.

- [ ] **Step 1: Add isolated synthetic-Git fixture helpers**

Add `subprocess` and `Path` imports as needed, then add these helpers near the existing run-manifest tests:

```python
def _git_text(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )
    return completed.stdout.decode("utf-8").strip()


def _historical_bundle(
    tmp_path: Path,
    *,
    revision_kind: str = "commit",
    declared_path: str = "input.yaml",
    wrong_input_digest: bool = False,
) -> tuple[Path, Path, Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_text(repo, "init", "--quiet")
    _git_text(repo, "config", "user.name", "Oracle Test")
    _git_text(repo, "config", "user.email", "oracle@example.invalid")
    source = repo / "input.yaml"
    source.write_text("seed: synthetic\n", encoding="utf-8")
    tree = repo / "tree"
    tree.mkdir()
    (tree / "nested.yaml").write_text("nested: synthetic\n", encoding="utf-8")
    (repo / "linked.yaml").symlink_to("input.yaml")
    _git_text(
        repo, "add", "input.yaml", "tree/nested.yaml", "linked.yaml"
    )
    _git_text(repo, "commit", "--quiet", "-m", "synthetic input")
    commit = _git_text(repo, "rev-parse", "HEAD")
    if revision_kind == "commit":
        source_revision = commit
    elif revision_kind == "blob":
        source_revision = _git_text(repo, "rev-parse", "HEAD:input.yaml")
    elif revision_kind == "tag":
        _git_text(repo, "tag", "-a", "synthetic-tag", "-m", "synthetic tag")
        source_revision = _git_text(repo, "rev-parse", "synthetic-tag")
    elif revision_kind == "missing":
        source_revision = "f" * 40
    else:
        raise AssertionError(f"unsupported synthetic revision kind: {revision_kind}")

    digest = sha256_file(source)
    if wrong_input_digest:
        digest = hashlib.sha256(b"different synthetic input").hexdigest()
    descriptor = {
        "schema_version": 1,
        "run_kind": "synthetic-historical-verification",
        "source_revision": source_revision,
        "invocation": {},
        "snapshot": {
            "snapshot_id": "synthetic",
            "manifest_path": declared_path,
            "manifest_sha256": digest,
        },
        "store": {},
        "inputs": [{"path": declared_path, "sha256": digest}],
        "runtime": {},
    }
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    report = bundle / "report.md"
    report.write_text(f"{render_report_prefix(descriptor)}\nsynthetic report\n")
    write_run_manifest(bundle, descriptor, ["report.md"])
    return repo, bundle, source, source_revision
```

All Git commands operate only on the new `tmp_path` repository and require no network.

- [ ] **Step 2: Write failing historical-verifier tests**

```python
def test_historical_source_revision_uses_git_blob_not_live_worktree(tmp_path):
    """Kills mutation: hash the live input path instead of the committed Git blob."""
    repo, bundle, source, revision = _historical_bundle(tmp_path)
    source.write_text("seed: changed only in worktree\n", encoding="utf-8")

    verified = verify_run_bundle_at_source_revision(bundle, repo_root=repo)

    assert verified["source_revision"] == revision
    with pytest.raises(RunManifestError, match="input.yaml"):
        verify_run_bundle(bundle, repo_root=repo)


@pytest.mark.parametrize(
    "revision_kind", ["missing", "blob", "tag"], ids=["missing", "blob", "tag"]
)
def test_historical_verifier_rejects_missing_or_non_commit_revision(
    tmp_path, revision_kind
):
    """Kills mutation: accept a 40-hex source revision without resolving a commit."""
    repo, bundle, _, _ = _historical_bundle(
        tmp_path, revision_kind=revision_kind
    )

    with pytest.raises(RunManifestError, match="local Git commit"):
        verify_run_bundle_at_source_revision(bundle, repo_root=repo)


@pytest.mark.parametrize(
    ("declared_path", "message"),
    [
        ("absent.yaml", "absent"),
        ("tree", "not a regular blob"),
        ("linked.yaml", "not a regular blob"),
    ],
    ids=["missing", "tree", "symlink"],
)
def test_historical_verifier_rejects_missing_or_non_blob_input(
    tmp_path, declared_path, message
):
    """Kills mutation: accept an absent path or Git tree as declared file bytes."""
    repo, bundle, _, _ = _historical_bundle(
        tmp_path, declared_path=declared_path
    )

    with pytest.raises(RunManifestError, match=message):
        verify_run_bundle_at_source_revision(bundle, repo_root=repo)


def test_historical_verifier_rejects_git_blob_digest_mismatch(tmp_path):
    """Kills mutation: read the committed blob but skip its manifest digest check."""
    repo, bundle, _, _ = _historical_bundle(tmp_path, wrong_input_digest=True)

    with pytest.raises(RunManifestError, match="sha256 mismatch: input.yaml"):
        verify_run_bundle_at_source_revision(bundle, repo_root=repo)


def test_historical_verifier_rejects_changed_output(tmp_path):
    """Kills mutation: omit shared output digest validation in historical mode."""
    repo, bundle, _, _ = _historical_bundle(tmp_path)
    report = bundle / "report.md"
    first_line = report.read_text(encoding="utf-8").splitlines()[0]
    report.write_text(f"{first_line}\nchanged output\n", encoding="utf-8")

    with pytest.raises(RunManifestError, match="report.md"):
        verify_run_bundle_at_source_revision(bundle, repo_root=repo)
```

- [ ] **Step 3: Run focused tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_provenance.py -k 'historical_source_revision_uses_git_blob or missing_or_non_commit or missing_or_non_blob or git_blob_digest or historical_verifier_rejects_changed_output' -q
```

Expected: collection fails because `verify_run_bundle_at_source_revision` is not defined.

- [ ] **Step 4: Extract only shared manifest and output validation**

Move the current manifest load/schema/run-ID code, without changing conditions or messages, into:

```python
def _load_run_manifest(bundle: Path) -> tuple[Path, dict[str, object], str]:
    root = _bundle_root(bundle)
    manifest_path = root / "manifest.json"
    try:
        if manifest_path.is_symlink():
            raise RunManifestError("run manifest must not be a symlink")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunManifestError(f"invalid run manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise RunManifestError("run manifest must be a JSON object")
    expected_keys = _RUN_DESCRIPTOR_KEYS | {"run_id", "outputs"}
    if set(manifest) != expected_keys:
        raise RunManifestError("run manifest has unsupported or missing keys")
    descriptor = {key: manifest[key] for key in _RUN_DESCRIPTOR_KEYS}
    expected_run_id = run_id(descriptor)
    if manifest["run_id"] != expected_run_id:
        raise RunManifestError("run manifest run_id does not match descriptor")
    return root, manifest, expected_run_id


def _verify_run_outputs(
    root: Path, manifest: dict[str, object], expected_run_id: str
) -> None:
    outputs = _digest_entries(root, manifest["outputs"], "output", verify=True)
    for output in outputs:
        if output["path"].endswith(".md"):
            first_line = (root / output["path"]).read_text(encoding="utf-8").split("\n", 1)[0]
            if first_line != f"<!-- ti26-run: {expected_run_id} manifest.json -->":
                raise RunManifestError(
                    f"report run reference mismatch: {output['path']}"
                )
```

Rewrite `verify_run_bundle` to call `_load_run_manifest`, perform its existing live `_digest_entries` input check, then `_verify_run_outputs`, then its existing `against_revision` comparison. Preserve that order and its public signature.

- [ ] **Step 5: Implement Git-commit and Git-blob verification**

Add `subprocess` to `src/ti26/provenance.py`, leave `_digest_entries` unchanged for live verification, and add:

```python
def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
    )


def _historical_input_entries(entries: object) -> list[dict[str, str]]:
    if not isinstance(entries, list):
        raise RunManifestError("input must be a list")
    result: list[dict[str, str]] = []
    paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise RunManifestError("input entry must contain path and sha256")
        path_text = entry["path"]
        if not isinstance(path_text, str) or not path_text or "\\" in path_text:
            raise RunManifestError("input path must be a non-empty POSIX-relative path")
        relative = PurePosixPath(path_text)
        if (
            not relative.parts
            or relative.is_absolute()
            or ".." in relative.parts
            or "." in relative.parts
            or relative.as_posix() != path_text
        ):
            raise RunManifestError("input path must be a non-empty POSIX-relative path")
        digest = entry["sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise RunManifestError(f"input has an invalid sha256: {path_text}")
        if path_text in paths:
            raise RunManifestError(f"input has a duplicate path: {path_text}")
        paths.add(path_text)
        result.append({"path": path_text, "sha256": digest})
    return result


def _git_blob(repo_root: Path, revision: str, path: str) -> bytes:
    listing = _git(repo_root, "ls-tree", "-z", revision, "--", path)
    records = [record for record in listing.stdout.split(b"\0") if record]
    if listing.returncode != 0 or not records:
        raise RunManifestError(f"input absent at source_revision: {path}")
    try:
        header, raw_path = records[0].split(b"\t", 1)
        mode, kind, _ = header.split(b" ", 2)
        listed_path = raw_path.decode("utf-8")
    except (UnicodeDecodeError, ValueError) as exc:
        raise RunManifestError(f"invalid Git tree entry for input: {path}") from exc
    if len(records) != 1 or listed_path != path:
        raise RunManifestError(f"input absent at source_revision: {path}")
    if kind != b"blob" or mode not in {b"100644", b"100755"}:
        raise RunManifestError(
            f"input is not a regular blob at source_revision: {path}"
        )
    object_name = f"{revision}:{path}"
    blob = _git(repo_root, "cat-file", "blob", object_name)
    if blob.returncode != 0:
        raise RunManifestError(f"cannot read input blob at source_revision: {path}")
    return blob.stdout


def verify_run_bundle_at_source_revision(
    bundle: Path, *, repo_root: Path
) -> dict[str, object]:
    """Verify declared inputs as Git blobs at the manifest's source commit."""
    root, manifest, expected_run_id = _load_run_manifest(bundle)
    try:
        repository = repo_root.resolve(strict=True)
    except OSError as exc:
        raise RunManifestError("invalid repository root") from exc
    revision = manifest["source_revision"]
    commit_type = _git(repository, "cat-file", "-t", revision)
    if commit_type.returncode != 0 or commit_type.stdout != b"commit\n":
        raise RunManifestError(
            f"source_revision is not a local Git commit: {revision}"
        )
    for entry in _historical_input_entries(manifest["inputs"]):
        blob = _git_blob(repository, revision, entry["path"])
        if hashlib.sha256(blob).hexdigest() != entry["sha256"]:
            raise RunManifestError(f"input sha256 mismatch: {entry['path']}")
    _verify_run_outputs(root, manifest, expected_run_id)
    return manifest
```

This resolves the manifest’s exact object ID locally. It does not accept a branch name, perform a checkout, or fall back to live bytes.

- [ ] **Step 6: Run focused and existing verifier tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_provenance.py -k 'verify_run_bundle or historical_' -q
```

Expected: PASS, including existing live-tree behavior and all historical cases.

- [ ] **Step 7: Prove every new historical test kills its mutation**

Temporarily replace `_git_blob(...)` in the historical verifier with `(repository / entry["path"]).read_bytes()`:

```bash
.venv/bin/python -m pytest tests/test_provenance.py::test_historical_source_revision_uses_git_blob_not_live_worktree -q
```

Expected: FAIL because the live edit is hashed. Restore Git-blob loading.

Temporarily replace the exact `cat-file -t` type check with `cat-file -e f"{revision}^{{commit}}"`:

```bash
.venv/bin/python -m pytest 'tests/test_provenance.py::test_historical_verifier_rejects_missing_or_non_commit_revision[tag]' -q
```

Expected: FAIL because an annotated-tag object ID peels to a commit and is incorrectly accepted as if the manifest named the commit object itself. Restore the exact type check.

Temporarily delete the Git tree-entry `kind` and `mode` rejection:

```bash
.venv/bin/python -m pytest 'tests/test_provenance.py::test_historical_verifier_rejects_missing_or_non_blob_input[tree]' -q
```

Expected: FAIL because a Git tree is not rejected with the required non-blob error. Restore the type check.

Run the same mutation against the symlink case:

```bash
.venv/bin/python -m pytest 'tests/test_provenance.py::test_historical_verifier_rejects_missing_or_non_blob_input[symlink]' -q
```

Expected: FAIL because a Git symlink blob is not rejected as a non-regular input. Restore the type/mode check.

Temporarily delete the SHA-256 comparison:

```bash
.venv/bin/python -m pytest tests/test_provenance.py::test_historical_verifier_rejects_git_blob_digest_mismatch -q
```

Expected: FAIL because the wrong declared digest is accepted. Restore the comparison.

Temporarily delete `_verify_run_outputs(...)` from the historical verifier:

```bash
.venv/bin/python -m pytest tests/test_provenance.py::test_historical_verifier_rejects_changed_output -q
```

Expected: FAIL because the changed report is accepted. Restore output verification and rerun all six mutation commands; expected PASS.

- [ ] **Step 8: Commit historical verification**

```bash
git add src/ti26/provenance.py tests/test_provenance.py
git commit -m "feat: verify run inputs at source revision"
```

### Task 3: Expose historical verification as an explicit CLI mode

**Files:**

- Modify: `src/ti26/cli_provenance.py`
- Modify: `tests/test_provenance.py`
- Modify: `README.md`

**Interfaces:**

- Consumes: `verify_run_bundle_at_source_revision(bundle: Path, *, repo_root: Path)` from Task 2.
- Produces: `python -m ti26.cli_provenance verify-run --bundle PATH --repo-root PATH --at-source-revision`.
- Preserves: default `verify-run` live-tree mode and `--against-revision` behavior.

- [ ] **Step 1: Write the failing CLI-routing test**

```python
def test_verify_run_cli_at_source_revision_uses_committed_blobs(
    tmp_path, capsys
):
    """Kills mutation: parse --at-source-revision but call the live verifier."""
    repo, bundle, source, revision = _historical_bundle(tmp_path)
    source.write_text("seed: live-only CLI edit\n", encoding="utf-8")

    exit_code = provenance_main(
        [
            "verify-run",
            "--bundle",
            str(bundle),
            "--repo-root",
            str(repo),
            "--at-source-revision",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["source_revision"] == revision
```

- [ ] **Step 2: Run the CLI test to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_provenance.py::test_verify_run_cli_at_source_revision_uses_committed_blobs -q
```

Expected: FAIL because `--at-source-revision` is unrecognized.

- [ ] **Step 3: Add the mutually exclusive opt-in and route it**

Import `verify_run_bundle_at_source_revision`. Replace the standalone `--against-revision` argument with one mutually exclusive group:

```python
verification_mode = verify_run.add_mutually_exclusive_group()
verification_mode.add_argument(
    "--against-revision",
    default=None,
    help="require the manifest to name the supplied revision while checking live inputs",
)
verification_mode.add_argument(
    "--at-source-revision",
    action="store_true",
    help="read declared inputs as local Git blobs at manifest.source_revision",
)
```

Route only the opt-in mode to the new verifier:

```python
if args.at_source_revision:
    if repo_root is None:
        repo_root = Path.cwd()
    verified = verify_run_bundle_at_source_revision(
        Path(args.bundle), repo_root=repo_root
    )
else:
    verified = verify_run_bundle(
        Path(args.bundle),
        repo_root=repo_root,
        against_revision=args.against_revision,
    )
_print_json(verified)
```

Update `README.md` beside the current `verify-run` example with this exact distinction:

````markdown
Use live-tree verification for a bundle expected to describe the current checkout. To verify a committed historical bundle without requiring today’s config bytes to match, read each declared input from its recorded local Git commit:

```bash
.venv/bin/python -m ti26.cli_provenance verify-run \
  --bundle reports/runs/frozen-output-oracle-baseline/* \
  --repo-root . \
  --at-source-revision
```

Historical mode proves declared input blobs and present output bytes match the manifest. It does not prove the generating process executed that commit or bind undeclared dependencies and runtime files.
````

- [ ] **Step 4: Run CLI and provenance tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_provenance.py::test_verify_run_cli_at_source_revision_uses_committed_blobs tests/test_provenance.py::test_verify_run_bundle_rejects_a_changed_declared_input -q
```

Expected: both PASS; opt-in mode reads Git, default mode still reads the live input.

- [ ] **Step 5: Prove the CLI test kills its mutation**

Temporarily route both branches through `verify_run_bundle`:

```bash
.venv/bin/python -m pytest tests/test_provenance.py::test_verify_run_cli_at_source_revision_uses_committed_blobs -q
```

Expected: FAIL with the changed live `input.yaml`. Restore historical routing and rerun; expected PASS.

- [ ] **Step 6: Commit the CLI mode and documentation**

```bash
git add src/ti26/cli_provenance.py tests/test_provenance.py README.md
git commit -m "feat: expose source-revision bundle verification"
```

### Task 4: Resolve and load the registered complete baseline

**Files:**

- Create: `src/ti26/frozen_output_oracle.py`
- Create: `tests/test_frozen_output_oracle.py`

**Interfaces:**

- Consumes: the sole bundle under `reports/runs/frozen-output-oracle-baseline/`, `verify_run_bundle_at_source_revision`, and `load_frozen_gate_artifact`.
- Produces: `FrozenOutputOracleError(ValueError)`; `FrozenOutput(gates: dict[str, dict[str, object]], card: dict[str, object])`; `FrozenBaselineInvocation(snapshot_id: str, release_args: tuple[str, ...])`; `registered_baseline_bundle(*, repo_root: Path) -> Path`; `registered_baseline_invocation(*, repo_root: Path) -> FrozenBaselineInvocation`; `load_frozen_output(bundle: Path, *, repo_root: Path) -> FrozenOutput`; `load_current_baseline(*, repo_root: Path) -> FrozenOutput`.

- [ ] **Step 1: Write failing real-registration tests**

Import `PurePosixPath` and `from ti26 import frozen_output_oracle as oracle` along with the public symbols under test.

```python
def test_registered_baseline_is_the_sole_runtime_named_bundle():
    """Kills mutation: resolve registration from the generic reports/runs root."""
    repo_root = Path.cwd()
    bundle = registered_baseline_bundle(repo_root=repo_root)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))

    assert bundle.parent == repo_root / BASELINE_ROOT
    assert bundle.name == manifest["run_id"]
    assert manifest["run_kind"] == BASELINE_RUN_KIND


def test_registration_rejects_any_second_immediate_child(tmp_path, monkeypatch):
    """Kills mutation: count only child manifest files and ignore extra children."""
    registration = tmp_path / "registration"
    (registration / "manifest-child").mkdir(parents=True)
    (registration / "manifest-child" / "manifest.json").write_text("{}\n")
    (registration / "extra-child").mkdir()
    monkeypatch.setattr(oracle, "BASELINE_ROOT", registration)

    with pytest.raises(FrozenOutputOracleError, match="one child bundle"):
        registered_baseline_bundle(repo_root=tmp_path)


def test_registered_baseline_invocation_is_derived_from_manifest(monkeypatch):
    """Kills mutation: replay with cli_release defaults instead of manifest values."""
    repo_root = Path.cwd()
    bundle = registered_baseline_bundle(repo_root=repo_root)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    for key in (
        "card_sims",
        "card_seed",
        "min_train",
        "sweep_sims",
        "sweep_seeds",
        "random_samples",
        "random_seed",
    ):
        value = manifest["invocation"][key]
        manifest["invocation"][key] = (
            value + 1 if isinstance(value, int) else f"{value},synthetic"
        )
    monkeypatch.setattr(
        oracle,
        "verify_run_bundle_at_source_revision",
        lambda *_, **__: manifest,
    )
    baseline = registered_baseline_invocation(repo_root=repo_root)
    args = dict(zip(baseline.release_args[::2], baseline.release_args[1::2]))

    assert baseline.snapshot_id == manifest["snapshot"]["snapshot_id"]
    assert args["--snapshot"] == baseline.snapshot_id
    assert args["--raw"] == PurePosixPath(
        manifest["snapshot"]["manifest_path"]
    ).parent.parent.as_posix()
    for option, key in (
        ("--card-sims", "card_sims"),
        ("--card-seed", "card_seed"),
        ("--min-train", "min_train"),
        ("--sweep-sims", "sweep_sims"),
        ("--sweep-seeds", "sweep_seeds"),
        ("--random-samples", "random_samples"),
        ("--random-seed", "random_seed"),
    ):
        assert args[option] == str(manifest["invocation"][key])


def test_current_baseline_loads_complete_manifest_declared_gate_and_card_objects():
    """Kills mutation: reconstruct predictive output from selected JSON members."""
    repo_root = Path.cwd()
    bundle = registered_baseline_bundle(repo_root=repo_root)
    output = load_current_baseline(repo_root=repo_root)
    frozen = json.loads(
        (bundle / "frozen_gate_results.json").read_text(encoding="utf-8")
    )

    assert output.gates == frozen["gates"]
    for gate in ("d2", "d3", "d3b"):
        individual = json.loads(
            (bundle / gate / f"{gate}_gate.json").read_text(encoding="utf-8")
        )
        assert output.gates[gate] == individual
    assert output.card == json.loads(
        (bundle / "card" / "recommended_card.json").read_text(encoding="utf-8")
    )
```

- [ ] **Step 2: Run real-registration tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py -k 'registered_baseline or registration_rejects or current_baseline_loads_complete' -q
```

Expected: collection fails because `ti26.frozen_output_oracle` does not exist.

- [ ] **Step 3: Implement runtime registration resolution and complete loading**

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ti26.gate_artifacts import load_frozen_gate_artifact
from ti26.provenance import verify_run_bundle_at_source_revision

BASELINE_ROOT = Path("reports/runs/frozen-output-oracle-baseline")
BASELINE_RUN_KIND = "ti2026-frozen-output-oracle-baseline"
_GATE_OUTPUTS = {
    gate: f"{gate}/{gate}_gate.json" for gate in ("d2", "d3", "d3b")
}
_FROZEN_GATES_OUTPUT = "frozen_gate_results.json"
_CARD_OUTPUT = "card/recommended_card.json"


class FrozenOutputOracleError(ValueError):
    """A bundle cannot substantiate or match the frozen predictive output."""


@dataclass(frozen=True)
class FrozenOutput:
    gates: dict[str, dict[str, object]]
    card: dict[str, object]


@dataclass(frozen=True)
class FrozenBaselineInvocation:
    snapshot_id: str
    release_args: tuple[str, ...]


def registered_baseline_bundle(*, repo_root: Path) -> Path:
    root = repo_root / BASELINE_ROOT
    try:
        children = sorted(root.iterdir())
    except OSError as exc:
        raise FrozenOutputOracleError(
            f"cannot read baseline registration root: {root}"
        ) from exc
    if (
        len(children) != 1
        or children[0].is_symlink()
        or not children[0].is_dir()
    ):
        raise FrozenOutputOracleError(
            "baseline registration requires exactly one child bundle"
        )
    bundle = children[0]
    try:
        manifest = verify_run_bundle_at_source_revision(
            bundle, repo_root=repo_root
        )
    except ValueError as exc:
        raise FrozenOutputOracleError(f"invalid registered baseline: {bundle}") from exc
    if manifest["run_kind"] != BASELINE_RUN_KIND:
        raise FrozenOutputOracleError("registered baseline has the wrong run_kind")
    if manifest["run_id"] != bundle.name:
        raise FrozenOutputOracleError("registered baseline directory is not its run_id")
    return bundle


def registered_baseline_invocation(
    *, repo_root: Path
) -> FrozenBaselineInvocation:
    bundle = registered_baseline_bundle(repo_root=repo_root)
    manifest = verify_run_bundle_at_source_revision(bundle, repo_root=repo_root)
    snapshot = manifest.get("snapshot")
    invocation = manifest.get("invocation")
    if not isinstance(snapshot, dict) or not isinstance(invocation, dict):
        raise FrozenOutputOracleError("baseline invocation metadata is invalid")
    snapshot_id = snapshot.get("snapshot_id")
    manifest_path = snapshot.get("manifest_path")
    if not isinstance(snapshot_id, str) or not isinstance(manifest_path, str):
        raise FrozenOutputOracleError("baseline snapshot metadata is invalid")
    snapshot_manifest = PurePosixPath(manifest_path)
    if (
        snapshot_manifest.name != "manifest.json"
        or snapshot_manifest.parent.name != snapshot_id
    ):
        raise FrozenOutputOracleError("baseline snapshot path is inconsistent")
    release_args = [
        "--snapshot", snapshot_id,
        "--raw", snapshot_manifest.parent.parent.as_posix(),
    ]
    for option, key in (
        ("--card-sims", "card_sims"),
        ("--card-seed", "card_seed"),
        ("--min-train", "min_train"),
        ("--sweep-sims", "sweep_sims"),
        ("--sweep-seeds", "sweep_seeds"),
        ("--random-samples", "random_samples"),
        ("--random-seed", "random_seed"),
    ):
        value = invocation.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise FrozenOutputOracleError(
                f"baseline invocation value is invalid: {key}"
            )
        release_args.extend((option, str(value)))
    producers = invocation.get("producers")
    if not isinstance(producers, list):
        raise FrozenOutputOracleError("baseline producer invocation is invalid")
    card_commands = [
        command
        for command in producers
        if isinstance(command, list) and command and command[0] == "ti26.cli_card"
    ]
    if len(card_commands) != 1:
        raise FrozenOutputOracleError("baseline card invocation is invalid")
    card_command = card_commands[0]
    group_positions = [
        index for index, value in enumerate(card_command) if value == "--groups"
    ]
    if group_positions:
        if len(group_positions) != 1 or group_positions[0] + 1 >= len(card_command):
            raise FrozenOutputOracleError("baseline group invocation is invalid")
        group_path = card_command[group_positions[0] + 1]
        if not isinstance(group_path, str):
            raise FrozenOutputOracleError("baseline group path is invalid")
        release_args.extend(("--groups", group_path))
    return FrozenBaselineInvocation(snapshot_id, tuple(release_args))


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrozenOutputOracleError(f"unreadable oracle JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FrozenOutputOracleError(f"oracle JSON object required: {path}")
    return value


def load_frozen_output(bundle: Path, *, repo_root: Path) -> FrozenOutput:
    try:
        verify_run_bundle_at_source_revision(bundle, repo_root=repo_root)
        artifact = load_frozen_gate_artifact(bundle / _FROZEN_GATES_OUTPUT)
    except ValueError as exc:
        raise FrozenOutputOracleError(f"invalid oracle bundle: {bundle}") from exc
    return FrozenOutput(
        gates=artifact["gates"],
        card=_load_json_object(bundle / _CARD_OUTPUT),
    )


def load_current_baseline(*, repo_root: Path) -> FrozenOutput:
    return load_frozen_output(
        registered_baseline_bundle(repo_root=repo_root), repo_root=repo_root
    )
```

`PurePosixPath` is already in the Step 3 import block above. Task 5 adds shared staged required-file and aggregate/constituent checks. Do not add predictive imports.

- [ ] **Step 4: Run real-registration tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py -k 'registered_baseline or registration_rejects or current_baseline_loads_complete' -q
```

Expected: PASS even though the live checkout is newer than the baseline source revision, because declared baseline inputs are read from that source commit.

- [ ] **Step 5: Prove all four tests kill their mutations**

Temporarily change the registration constant to the generic runs root:

```python
BASELINE_ROOT = Path("reports/runs")
```

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_registered_baseline_is_the_sole_runtime_named_bundle -q
```

Expected: FAIL because the generic runs root does not contain the one registered
baseline child required by the test. Restore
`Path("reports/runs/frozen-output-oracle-baseline")`.

Temporarily enumerate only `root.glob("*/manifest.json")` and ignore other immediate children:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_registration_rejects_any_second_immediate_child -q
```

Expected: FAIL because the extra child is accepted. Restore exact child enumeration.

Temporarily replace the manifest-derived predictive values with `cli_release` parser defaults:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_registered_baseline_invocation_is_derived_from_manifest -q
```

Expected: FAIL if any frozen invocation value differs; the test's expected values all come from the loaded baseline manifest. Restore manifest derivation.

Temporarily replace `gates=artifact["gates"]` with verdict-only objects:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_current_baseline_loads_complete_manifest_declared_gate_and_card_objects -q
```

Expected: FAIL because complete individual gate objects no longer match. Restore complete objects and rerun all four commands; expected PASS.

- [ ] **Step 6: Commit registered baseline loading**

```bash
git add src/ti26/frozen_output_oracle.py tests/test_frozen_output_oracle.py
git commit -m "feat: load registered frozen output baseline"
```

### Task 5: Share strict internal checks with a provenance-free staged reader

**Files:**

- Modify: `src/ti26/frozen_output_oracle.py`
- Modify: `tests/test_frozen_output_oracle.py`

**Interfaces:**

- Consumes: `load_frozen_output(bundle: Path, *, repo_root: Path)` from Task 4.
- Produces: `load_staged_frozen_output(staging: Path) -> FrozenOutput`, which validates required regular files, aggregate/card JSON, and aggregate/individual equality but deliberately makes no provenance claim; manifest-bound loading performs historical provenance and manifest-membership checks first, then calls the same internal reader.

- [ ] **Step 1: Add a miniature Git-backed oracle-bundle fixture**

```python
def _synthetic_gate(gate: str) -> dict[str, object]:
    return gate_result_payload(
        gate=gate,
        verdict="PASS",
        exit_code=0,
        registration="synthetic",
        conditions={"synthetic": {"value": "synthetic", "passed": True}},
        method="synthetic",
        n_maps=0,
        excluded={},
        config={},
    )


def synthetic_oracle_bundle(
    tmp_path: Path,
    *,
    omit_file: str | None = None,
    omit_manifest_output: str | None = None,
    card_bytes: bytes = b"{}\n",
    frozen_gate_bytes: bytes | None = None,
    replace_gate: str | None = None,
) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git_text(repo_root, "init", "--quiet")
    _git_text(repo_root, "config", "user.name", "Oracle Test")
    _git_text(repo_root, "config", "user.email", "oracle@example.invalid")
    source = repo_root / "input.txt"
    source.write_text("synthetic input\n", encoding="utf-8")
    _git_text(repo_root, "add", "input.txt")
    _git_text(repo_root, "commit", "--quiet", "-m", "synthetic oracle input")
    revision = _git_text(repo_root, "rev-parse", "HEAD")

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    paths: dict[str, Path] = {}
    for gate in ("d2", "d3", "d3b"):
        path = bundle / gate / f"{gate}_gate.json"
        path.parent.mkdir()
        write_gate_result(path, _synthetic_gate(gate))
        paths[gate] = path
    frozen_gate_path = bundle / "frozen_gate_results.json"
    write_frozen_gate_artifact(
        paths, frozen_gate_path, source_revision=revision
    )
    if frozen_gate_bytes is not None:
        frozen_gate_path.write_bytes(frozen_gate_bytes)
    card_path = bundle / "card" / "recommended_card.json"
    card_path.parent.mkdir()
    card_path.write_bytes(card_bytes)
    if replace_gate is not None:
        changed = _synthetic_gate(replace_gate)
        changed["registration"] = "changed synthetic registration"
        write_gate_result(paths[replace_gate], changed)
    if omit_file is not None:
        (bundle / omit_file).unlink()

    descriptor = {
        "schema_version": 1,
        "run_kind": "synthetic-oracle",
        "source_revision": revision,
        "invocation": {},
        "snapshot": {
            "snapshot_id": "synthetic",
            "manifest_path": "input.txt",
            "manifest_sha256": sha256_file(source),
        },
        "store": {},
        "inputs": [{"path": "input.txt", "sha256": sha256_file(source)}],
        "runtime": {},
    }
    outputs = sorted(
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if (
            path.is_file()
            and path.relative_to(bundle).as_posix() != omit_manifest_output
        )
    )
    write_run_manifest(bundle, descriptor, outputs)
    return bundle, repo_root
```

Define the same `_git_text` helper shown in Task 2 inside this test module. The fixture writes all mutations before `write_run_manifest`, calls it exactly once, and therefore remains manifest-valid without copying the production bundle.

- [ ] **Step 2: Write six failing staged-reader tests**

```python
def test_reader_rejects_required_output_not_declared_by_manifest(tmp_path):
    """Kills mutation: read conventional paths without requiring manifest membership."""
    bundle, repo_root = synthetic_oracle_bundle(
        tmp_path, omit_manifest_output="d3/d3_gate.json"
    )

    with pytest.raises(FrozenOutputOracleError, match="d3/d3_gate.json"):
        load_frozen_output(bundle, repo_root=repo_root)


def test_staged_reader_loads_manifestless_complete_objects(tmp_path):
    """Kills mutation: require provenance verification in the staged reader."""
    bundle, _ = synthetic_oracle_bundle(tmp_path)
    frozen = json.loads(
        (bundle / "frozen_gate_results.json").read_text(encoding="utf-8")
    )
    card = json.loads(
        (bundle / "card" / "recommended_card.json").read_text(encoding="utf-8")
    )
    (bundle / "manifest.json").unlink()

    output = load_staged_frozen_output(bundle)

    assert output == FrozenOutput(gates=frozen["gates"], card=card)


def test_staged_reader_rejects_missing_required_file(tmp_path):
    """Kills mutation: skip required-file checks without a run manifest."""
    bundle, _ = synthetic_oracle_bundle(
        tmp_path, omit_file="d3/d3_gate.json"
    )
    (bundle / "manifest.json").unlink()

    with pytest.raises(FrozenOutputOracleError, match="d3/d3_gate.json"):
        load_staged_frozen_output(bundle)


def test_reader_rejects_card_json_that_is_not_an_object(tmp_path):
    """Kills mutation: accept a JSON array as complete card machine output."""
    bundle, repo_root = synthetic_oracle_bundle(tmp_path, card_bytes=b"[]\n")

    with pytest.raises(FrozenOutputOracleError, match="JSON object"):
        load_frozen_output(bundle, repo_root=repo_root)


def test_reader_translates_invalid_frozen_gate_artifact_error(tmp_path):
    """Kills mutation: leak gate-artifact ValueError outside the oracle API."""
    bundle, repo_root = synthetic_oracle_bundle(
        tmp_path, frozen_gate_bytes=b"[]\n"
    )

    with pytest.raises(FrozenOutputOracleError, match="invalid frozen gate artifact"):
        load_frozen_output(bundle, repo_root=repo_root)


def test_reader_rejects_gate_disagreeing_with_frozen_aggregate(tmp_path):
    """Kills mutation: trust the aggregate without cross-checking individual gates."""
    bundle, repo_root = synthetic_oracle_bundle(tmp_path, replace_gate="d3")

    with pytest.raises(FrozenOutputOracleError, match="d3/d3_gate.json"):
        load_frozen_output(bundle, repo_root=repo_root)
```

- [ ] **Step 3: Run staged-reader tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py -k 'required_output_not_declared or staged_reader or card_json_that_is_not or invalid_frozen_gate_artifact or gate_disagreeing' -q
```

Expected: collection fails because `load_staged_frozen_output` does not exist.

- [ ] **Step 4: Implement shared ordered internal checks**

Add a strict staged-root resolver and shared internal reader, then replace `load_frozen_output` with:

```python
def _staged_root(staging: Path) -> Path:
    try:
        if staging.is_symlink() or not staging.is_dir():
            raise FrozenOutputOracleError(
                "staged output must be a directory, not a symlink"
            )
        return staging.resolve(strict=True)
    except OSError as exc:
        raise FrozenOutputOracleError(f"invalid staged output: {staging}") from exc


def _required_staged_files(staging: Path) -> tuple[Path, dict[str, Path]]:
    root = _staged_root(staging)
    paths: dict[str, Path] = {}
    required = {*_GATE_OUTPUTS.values(), _FROZEN_GATES_OUTPUT, _CARD_OUTPUT}
    for relative in sorted(required):
        path = root
        for part in PurePosixPath(relative).parts:
            path /= part
            if path.is_symlink():
                raise FrozenOutputOracleError(
                    f"staged oracle path must not use a symlink: {relative}"
                )
        if not path.is_file():
            raise FrozenOutputOracleError(
                f"staged oracle requires a regular file: {relative}"
            )
        paths[relative] = path
    return root, paths


def load_staged_frozen_output(staging: Path) -> FrozenOutput:
    """Validate internal output agreement without asserting provenance."""
    _, paths = _required_staged_files(staging)
    try:
        artifact = load_frozen_gate_artifact(paths[_FROZEN_GATES_OUTPUT])
    except ValueError as exc:
        raise FrozenOutputOracleError(
            f"invalid frozen gate artifact: {paths[_FROZEN_GATES_OUTPUT]}"
        ) from exc
    gates = artifact["gates"]
    for gate, output in _GATE_OUTPUTS.items():
        if _load_json_object(paths[output]) != gates[gate]:
            raise FrozenOutputOracleError(
                f"frozen gate artifact disagrees with {output}"
            )
    return FrozenOutput(
        gates=gates,
        card=_load_json_object(paths[_CARD_OUTPUT]),
    )


def load_frozen_output(bundle: Path, *, repo_root: Path) -> FrozenOutput:
    try:
        manifest = verify_run_bundle_at_source_revision(bundle, repo_root=repo_root)
    except ValueError as exc:
        raise FrozenOutputOracleError(f"invalid oracle bundle: {bundle}") from exc
    declared = {entry["path"] for entry in manifest["outputs"]}
    required = {*_GATE_OUTPUTS.values(), _FROZEN_GATES_OUTPUT, _CARD_OUTPUT}
    missing = sorted(required - declared)
    if missing:
        raise FrozenOutputOracleError(f"bundle lacks oracle output(s): {missing}")
    return load_staged_frozen_output(bundle)
```

The manifest-bound stages are: historical manifest/input/output verification, required output membership, then the shared physical required-file, aggregate schema, constituent equality, and card-object checks. The staged entry point starts at physical required-file validation and ignores any `manifest.json`; its docstring and API name explicitly deny a provenance claim. Do not reorder manifest-bound file reads ahead of provenance verification.

- [ ] **Step 5: Run staged-reader tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py -k 'required_output_not_declared or staged_reader or card_json_that_is_not or invalid_frozen_gate_artifact or gate_disagreeing' -q
```

Expected: all six PASS.

- [ ] **Step 6: Prove all six tests kill their named mutations**

Temporarily delete the `missing` check:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_reader_rejects_required_output_not_declared_by_manifest -q
```

Expected: FAIL because the undeclared individual gate is accepted. Restore the check.

Temporarily make `load_staged_frozen_output` call `verify_run_bundle_at_source_revision`:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_staged_reader_loads_manifestless_complete_objects -q
```

Expected: FAIL because manifestless staging is incorrectly required to make a provenance claim. Restore the provenance-free reader.

Temporarily omit `"d3"` from `_GATE_OUTPUTS`, removing both its required-file and constituent checks:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_staged_reader_rejects_missing_required_file -q
```

Expected: FAIL because the absent D3 constituent is accepted. Restore the complete gate mapping.

Temporarily replace `if not isinstance(value, dict)` with `if value is None`:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_reader_rejects_card_json_that_is_not_an_object -q
```

Expected: FAIL because the card array is accepted. Restore object validation.

Temporarily remove the `except ValueError` translation around `load_frozen_gate_artifact`:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_reader_translates_invalid_frozen_gate_artifact_error -q
```

Expected: FAIL because raw `ValueError` escapes. Restore translation.

Temporarily delete the aggregate/individual equality loop:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_reader_rejects_gate_disagreeing_with_frozen_aggregate -q
```

Expected: FAIL because the changed D3 object is accepted. Restore the loop and rerun all six node commands; expected PASS.

- [ ] **Step 7: Commit strict staged loading**

```bash
git add src/ti26/frozen_output_oracle.py tests/test_frozen_output_oracle.py
git commit -m "test: reject incomplete frozen output oracle inputs"
```

### Task 6: Compare complete output with configured stable team IDs

**Files:**

- Modify: `src/ti26/frozen_output_oracle.py`
- Modify: `tests/test_frozen_output_oracle.py`

**Interfaces:**

- Consumes: `FrozenOutput`, `load_current_baseline`, and `load_frozen_output`.
- Produces: `assignment_slots_by_team_id(card: dict[str, object]) -> dict[str, str]`; `assert_matches_frozen_output(baseline: FrozenOutput, candidate: FrozenOutput) -> None`; `main(argv: list[str] | None = None) -> int`.
- CLI: `python -m ti26.frozen_output_oracle --candidate PATH --repo-root PATH`.

- [ ] **Step 1: Add exact test-only mutation helpers**

```python
from copy import deepcopy
from dataclasses import replace


def replace_gate_member_without_known_measurement(
    output: FrozenOutput, gate: str
) -> FrozenOutput:
    gates = deepcopy(output.gates)
    registration = gates[gate]["registration"]
    assert isinstance(registration, str)
    gates[gate]["registration"] = f"{registration} [oracle test mutation]"
    return replace(output, gates=gates)


def replace_non_assignment_card_member_without_known_measurement(
    output: FrozenOutput,
) -> FrozenOutput:
    card = deepcopy(output.card)
    note = card["note"]
    assert isinstance(note, str)
    card["note"] = f"{note} [oracle test mutation]"
    return replace(output, card=card)


def rename_one_card_display_name_without_changing_team_id(
    output: FrozenOutput,
) -> FrozenOutput:
    card = deepcopy(output.card)
    assignments = card["assignments"]
    team_ids = card["team_ids"]
    assert isinstance(assignments, dict) and isinstance(team_ids, dict)
    name = next(iter(assignments))
    renamed = f"{name} [oracle test rename]"
    while renamed in assignments:
        renamed = f"{renamed}_"
    card["assignments"] = {
        renamed if key == name else key: value
        for key, value in assignments.items()
    }
    card["team_ids"] = {
        renamed if key == name else key: value
        for key, value in team_ids.items()
    }
    return replace(output, card=card)


def move_one_assignment_to_another_existing_category(
    output: FrozenOutput,
) -> FrozenOutput:
    card = deepcopy(output.card)
    assignments = card["assignments"]
    assert isinstance(assignments, dict)
    name = next(iter(assignments))
    current_category = assignments[name]
    alternate_category = next(
        category
        for category in assignments.values()
        if category != current_category
    )
    assignments[name] = alternate_category
    return replace(output, card=card)
```

Every selected real field, name, ID, and alternate category is derived from the loaded registered baseline.

- [ ] **Step 2: Write failing comparator and CLI tests**

```python
def test_comparator_rejects_change_anywhere_in_complete_gate_result():
    """Kills mutation: compare only gate verdicts and ignore other result members."""
    baseline = load_current_baseline(repo_root=Path.cwd())
    candidate = replace_gate_member_without_known_measurement(baseline, "d2")

    with pytest.raises(FrozenOutputOracleError, match="d2"):
        assert_matches_frozen_output(baseline, candidate)


def test_comparator_rejects_changed_non_assignment_card_member():
    """Kills mutation: compare assignments but ignore other card JSON members."""
    baseline = load_current_baseline(repo_root=Path.cwd())
    candidate = replace_non_assignment_card_member_without_known_measurement(
        baseline
    )

    with pytest.raises(FrozenOutputOracleError, match="non-assignment"):
        assert_matches_frozen_output(baseline, candidate)


def test_comparator_keys_assignments_by_stable_team_id_not_display_name():
    """Kills mutation: compare assignment dictionaries by display-name keys."""
    baseline = load_current_baseline(repo_root=Path.cwd())
    renamed = rename_one_card_display_name_without_changing_team_id(baseline)

    assert_matches_frozen_output(baseline, renamed)


def test_comparator_rejects_category_change_for_same_stable_team_id():
    """Kills mutation: compare only stable-ID membership and ignore its category."""
    baseline = load_current_baseline(repo_root=Path.cwd())
    changed = move_one_assignment_to_another_existing_category(baseline)

    with pytest.raises(FrozenOutputOracleError, match="team_id"):
        assert_matches_frozen_output(baseline, changed)


def test_oracle_cli_invokes_complete_comparator(monkeypatch, tmp_path):
    """Kills mutation: return CLI success without calling the output comparator."""
    baseline = load_current_baseline(repo_root=Path.cwd())
    changed = replace_non_assignment_card_member_without_known_measurement(
        baseline
    )
    monkeypatch.setattr(oracle, "load_current_baseline", lambda **_: baseline)
    monkeypatch.setattr(oracle, "load_frozen_output", lambda *_, **__: changed)

    with pytest.raises(FrozenOutputOracleError, match="non-assignment"):
        oracle.main(
            ["--candidate", str(tmp_path / "candidate"), "--repo-root", "."]
        )
```

- [ ] **Step 3: Run comparison tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py -k 'comparator or oracle_cli' -q
```

Expected: collection fails because comparison and CLI interfaces do not exist.

- [ ] **Step 4: Implement stable-ID and complete-object comparison**

```python
def assignment_slots_by_team_id(card: dict[str, object]) -> dict[str, str]:
    assignments = card.get("assignments")
    team_ids = card.get("team_ids")
    if not isinstance(assignments, dict) or not isinstance(team_ids, dict):
        raise FrozenOutputOracleError(
            "card requires assignments and configured team_ids objects"
        )
    if set(assignments) != set(team_ids):
        raise FrozenOutputOracleError("card assignment and team_id names disagree")
    slots: dict[str, str] = {}
    for name, category in assignments.items():
        team_id = team_ids[name]
        if (
            not isinstance(team_id, str)
            or not team_id
            or not isinstance(category, str)
            or not category
        ):
            raise FrozenOutputOracleError("card assignment identity is invalid")
        if team_id in slots:
            raise FrozenOutputOracleError(f"duplicate card team_id: {team_id}")
        slots[team_id] = category
    return slots


def _card_without_assignments(card: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in card.items()
        if key not in {"assignments", "team_ids"}
    }


def assert_matches_frozen_output(
    baseline: FrozenOutput, candidate: FrozenOutput
) -> None:
    for gate in ("d2", "d3", "d3b"):
        if candidate.gates.get(gate) != baseline.gates.get(gate):
            raise FrozenOutputOracleError(f"frozen gate output changed: {gate}")
    baseline_slots = assignment_slots_by_team_id(baseline.card)
    candidate_slots = assignment_slots_by_team_id(candidate.card)
    if _card_without_assignments(candidate.card) != _card_without_assignments(
        baseline.card
    ):
        raise FrozenOutputOracleError("frozen card non-assignment JSON changed")
    if candidate_slots != baseline_slots:
        raise FrozenOutputOracleError(
            "frozen card assignment changed by configured team_id"
        )
```

This exact-compares all decoded non-assignment card members, including objective, seeds, sim counts, bracket assumptions, and note. Only `assignments` and `team_ids` are projected to `team_id -> category`; display names are not identity.

- [ ] **Step 5: Add the actual oracle CLI**

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare a full release bundle with the frozen output baseline"
    )
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    baseline = load_current_baseline(repo_root=repo_root)
    candidate = load_frozen_output(Path(args.candidate), repo_root=repo_root)
    assert_matches_frozen_output(baseline, candidate)
    print("frozen output oracle: match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Add `import argparse` to the module and `from ti26 import frozen_output_oracle as oracle` to the test module.

- [ ] **Step 6: Run comparison tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py -k 'comparator or oracle_cli' -q
```

Expected: all five PASS.

- [ ] **Step 7: Prove all five tests kill their named mutations**

Temporarily compare only `candidate.gates[gate]["verdict"]`:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_comparator_rejects_change_anywhere_in_complete_gate_result -q
```

Expected: FAIL because the changed registration is ignored. Restore complete comparison.

Temporarily make `_card_without_assignments` return an empty object:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_comparator_rejects_changed_non_assignment_card_member -q
```

Expected: FAIL because the changed note is ignored. Restore complete projection.

Temporarily compare raw `assignments` dictionaries:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_comparator_keys_assignments_by_stable_team_id_not_display_name -q
```

Expected: FAIL because a display-name-only rename is reported as output drift. Restore stable-ID normalization.

Temporarily return `{team_id: "present" for team_id in team_ids.values()}` from `assignment_slots_by_team_id`:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_comparator_rejects_category_change_for_same_stable_team_id -q
```

Expected: FAIL because the category move is ignored. Restore `team_id -> category`.

Temporarily return zero from `main` before `assert_matches_frozen_output`:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_oracle_cli_invokes_complete_comparator -q
```

Expected: FAIL because the changed candidate is accepted. Restore the comparator call and rerun all five node commands; expected PASS.

- [ ] **Step 8: Commit the comparator and CLI**

```bash
git add src/ti26/frozen_output_oracle.py tests/test_frozen_output_oracle.py
git commit -m "feat: compare frozen output by stable team identity"
```

### Task 7: Add the Plan-1-owned isolated replay contract

**Files:**

- Modify: `src/ti26/frozen_output_oracle.py`
- Modify: `tests/test_frozen_output_oracle.py`
- Modify: `README.md`

**Interfaces:**

- Consumes: `registered_baseline_invocation`, current clean Git `HEAD`, the existing `ti26.cli_release`, existing live `verify_run_bundle`, `load_current_baseline`, `load_frozen_output`, and `assert_matches_frozen_output`.
- Produces: `replay_current_frozen_output(*, repo_root: Path, runs_root: Path, source_revision: str) -> None` and CLI mode `python -m ti26.frozen_output_oracle --replay-root PATH --source-revision SHA --repo-root PATH`.
- Contract: `runs_root` must be an absent path outside `repo_root`. The helper proves `source_revision` is the clean current `HEAD`, launches existing `cli_release` with the manifest-derived baseline snapshot and predictive arguments plus a distinct candidate run kind, requires exactly one generated child, live-verifies it against that revision, compares it through the actual oracle, and removes only that newly created root on success. A release, verification, or comparison failure preserves that isolated root for diagnosis. Existing `cli_release` also rebuilds its `data/processed/release-{snapshot_id}.sqlite` path; `.gitignore` excludes `data/processed/`, so this allowed derived-store side effect does not dirty Git status, but it is durable and is not part of `runs_root`. The replay never writes a forecast registry or a repository run registration. Normal release orchestration never calls this helper.

- [ ] **Step 1: Write failing isolated-replay tests**

```python
def test_isolated_replay_uses_registered_args_and_live_verifies_before_compare(
    tmp_path, monkeypatch
):
    """Kills mutation: compare the candidate before live manifest verification."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    runs_root = tmp_path / "candidate-root"
    revision = "a" * 40
    invocation = FrozenBaselineInvocation(
        snapshot_id="synthetic",
        release_args=("--snapshot", "synthetic"),
    )
    baseline = FrozenOutput(gates={}, card={})
    candidate = FrozenOutput(gates={}, card={})
    events: list[object] = []
    monkeypatch.setattr(oracle, "_clean_head_revision", lambda _: revision)
    monkeypatch.setattr(
        oracle,
        "registered_baseline_invocation",
        lambda **_: invocation,
    )

    def fake_release(root, argv):
        events.append(("release", tuple(argv)))
        (runs_root / "runtime-derived").mkdir(parents=True)
        return 0

    monkeypatch.setattr(oracle, "_run_release", fake_release)
    monkeypatch.setattr(
        oracle,
        "verify_run_bundle",
        lambda *_, **__: events.append("live-verify") or {},
    )
    monkeypatch.setattr(
        oracle,
        "load_current_baseline",
        lambda **_: events.append("baseline") or baseline,
    )
    monkeypatch.setattr(
        oracle,
        "load_frozen_output",
        lambda *_, **__: events.append("candidate") or candidate,
    )
    monkeypatch.setattr(
        oracle,
        "assert_matches_frozen_output",
        lambda *args: events.append("compare"),
    )

    replay_current_frozen_output(
        repo_root=repo_root,
        runs_root=runs_root,
        source_revision=revision,
    )

    release = events[0]
    assert release[0] == "release"
    assert release[1] == (
        *invocation.release_args,
        "--runs", str(runs_root),
        "--run-kind", CANDIDATE_RUN_KIND,
        "--source-revision", revision,
    )
    assert events[1:] == ["live-verify", "baseline", "candidate", "compare"]
    assert not runs_root.exists()


def test_isolated_replay_failure_preserves_its_temp_bundle(
    tmp_path, monkeypatch
):
    """Kills mutation: delete the replay root in a finally block after failure."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    runs_root = tmp_path / "candidate-root"
    revision = "a" * 40
    monkeypatch.setattr(oracle, "_clean_head_revision", lambda _: revision)
    monkeypatch.setattr(
        oracle,
        "registered_baseline_invocation",
        lambda **_: FrozenBaselineInvocation(
            snapshot_id="synthetic",
            release_args=("--snapshot", "synthetic"),
        ),
    )

    def fake_release(root, argv):
        (runs_root / "runtime-derived").mkdir(parents=True)
        return 0

    monkeypatch.setattr(oracle, "_run_release", fake_release)
    monkeypatch.setattr(oracle, "verify_run_bundle", lambda *_, **__: {})
    monkeypatch.setattr(
        oracle, "load_current_baseline", lambda **_: FrozenOutput({}, {})
    )
    monkeypatch.setattr(
        oracle, "load_frozen_output", lambda *_, **__: FrozenOutput({}, {})
    )

    def fail_comparison(*_):
        raise FrozenOutputOracleError("drift")

    monkeypatch.setattr(
        oracle, "assert_matches_frozen_output", fail_comparison
    )

    with pytest.raises(FrozenOutputOracleError, match="drift"):
        replay_current_frozen_output(
            repo_root=repo_root,
            runs_root=runs_root,
            source_revision=revision,
        )

    assert runs_root.is_dir()
    assert not (repo_root / "reports" / "forecast_registry").exists()


def test_replay_cli_routes_to_isolated_helper(tmp_path, monkeypatch, capsys):
    """Kills mutation: parse replay flags but return without invoking the helper."""
    revision = "a" * 40
    calls = []
    monkeypatch.setattr(
        oracle,
        "replay_current_frozen_output",
        lambda **kwargs: calls.append(kwargs),
    )

    exit_code = oracle.main(
        [
            "--replay-root", str(tmp_path / "candidate-root"),
            "--source-revision", revision,
            "--repo-root", str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert calls == [
        {
            "repo_root": tmp_path.resolve(),
            "runs_root": tmp_path / "candidate-root",
            "source_revision": revision,
        }
    ]
    assert capsys.readouterr().out == "frozen output replay: match\n"
```

- [ ] **Step 2: Run replay tests to verify RED**

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py -k 'isolated_replay or replay_cli' -q
```

Expected: collection fails because the isolated replay interfaces do not exist.

- [ ] **Step 3: Implement the isolated replay helper**

Add `shutil`, `subprocess`, and `sys` imports, import existing `verify_run_bundle`, and add:

```python
CANDIDATE_RUN_KIND = "ti2026-frozen-output-oracle-candidate"


def _clean_head_revision(repo_root: Path) -> str:
    status = subprocess.run(
        [
            "git", "-C", str(repo_root), "status", "--porcelain=v1",
            "--untracked-files=all",
        ],
        check=False,
        capture_output=True,
    )
    if status.returncode != 0 or status.stdout:
        raise FrozenOutputOracleError("frozen replay requires a clean Git checkout")
    head = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
    )
    if head.returncode != 0:
        raise FrozenOutputOracleError("cannot resolve replay source revision")
    return head.stdout.decode("ascii").strip()


def _run_release(repo_root: Path, argv: tuple[str, ...]) -> int:
    return subprocess.run(
        [sys.executable, "-m", "ti26.cli_release", *argv],
        cwd=repo_root,
        check=False,
    ).returncode


def _sole_generated_bundle(runs_root: Path) -> Path:
    try:
        children = sorted(runs_root.iterdir())
    except OSError as exc:
        raise FrozenOutputOracleError(
            f"cannot read isolated replay root: {runs_root}"
        ) from exc
    if (
        len(children) != 1
        or children[0].is_symlink()
        or not children[0].is_dir()
    ):
        raise FrozenOutputOracleError(
            "isolated replay must produce exactly one child bundle"
        )
    return children[0]


def replay_current_frozen_output(
    *, repo_root: Path, runs_root: Path, source_revision: str
) -> None:
    try:
        repository = repo_root.resolve(strict=True)
    except OSError as exc:
        raise FrozenOutputOracleError("invalid replay repository root") from exc
    if not runs_root.is_absolute():
        raise FrozenOutputOracleError("isolated replay root must be an absolute path")
    candidate_root = runs_root.resolve(strict=False)
    if candidate_root == repository or repository in candidate_root.parents:
        raise FrozenOutputOracleError("isolated replay root must be outside repository")
    if candidate_root.exists() or candidate_root.is_symlink():
        raise FrozenOutputOracleError("isolated replay root must not already exist")
    if _clean_head_revision(repository) != source_revision:
        raise FrozenOutputOracleError(
            "replay source revision must equal the clean current HEAD"
        )
    invocation = registered_baseline_invocation(repo_root=repository)
    argv = (
        *invocation.release_args,
        "--runs", str(candidate_root),
        "--run-kind", CANDIDATE_RUN_KIND,
        "--source-revision", source_revision,
    )
    if _run_release(repository, argv) != 0:
        raise FrozenOutputOracleError("isolated cli_release replay failed")
    candidate_bundle = _sole_generated_bundle(candidate_root)
    verify_run_bundle(
        candidate_bundle,
        repo_root=repository,
        against_revision=source_revision,
    )
    baseline = load_current_baseline(repo_root=repository)
    candidate = load_frozen_output(candidate_bundle, repo_root=repository)
    assert_matches_frozen_output(baseline, candidate)
    shutil.rmtree(candidate_root)
```

The only recursive removal target is the exact absent-before-call path resolved above, created by this invocation, outside `repo_root`, and removed only after verification and comparison succeed. Do not catch failures and do not clean the path on failure. This helper intentionally preserves existing `cli_release` behavior: it may rebuild the ignored derived store at `data/processed/release-{snapshot_id}.sqlite`; it does not isolate or remove that store.

- [ ] **Step 4: Extend the existing CLI without changing candidate comparison**

Replace the single required `--candidate` argument with these exact parser declarations, then keep the Task 6 candidate branch unchanged after the replay guards:

```python
mode = parser.add_mutually_exclusive_group(required=True)
mode.add_argument("--candidate")
mode.add_argument("--replay-root")
parser.add_argument("--source-revision")
parser.add_argument("--repo-root", default=".")
args = parser.parse_args(argv)
repo_root = Path(args.repo_root).resolve()

if args.replay_root is not None:
    if args.source_revision is None:
        parser.error("--replay-root requires --source-revision")
    replay_current_frozen_output(
        repo_root=repo_root,
        runs_root=Path(args.replay_root),
        source_revision=args.source_revision,
    )
    print("frozen output replay: match")
    return 0
if args.source_revision is not None:
    parser.error("--source-revision is valid only with --replay-root")
```

Document this committed Plan 1 replay interface in `README.md` next to historical verification:

````markdown
After a non-predictive change, run the frozen regression from a clean committed checkout into an absent path outside the repository:

```bash
git rev-parse HEAD | xargs .venv/bin/python -m ti26.frozen_output_oracle \
  --replay-root /private/tmp/ti26-frozen-output-oracle-replay \
  --repo-root . \
  --source-revision
```

The command reuses the baseline manifest's snapshot and predictive arguments, live-verifies the temporary candidate, compares complete frozen output, and removes the temporary root on success. It publishes no registered release bundle or registry entry. Existing `cli_release` still rebuilds its ignored `data/processed/release-{snapshot_id}.sqlite` derived store. Failure preserves the isolated candidate root for diagnosis. Normal release does not call this command.
````

- [ ] **Step 5: Run replay tests to verify GREEN**

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py -k 'isolated_replay or replay_cli' -q
```

Expected: all three PASS.

- [ ] **Step 6: Prove all three tests kill their named mutations**

Temporarily move `verify_run_bundle(...)` below `assert_matches_frozen_output(...)`:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_isolated_replay_uses_registered_args_and_live_verifies_before_compare -q
```

Expected: FAIL because recorded order no longer places live verification before loading and comparison. Restore the order.

Temporarily put `shutil.rmtree(candidate_root)` in a `finally` block:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_isolated_replay_failure_preserves_its_temp_bundle -q
```

Expected: FAIL because diagnostic state is erased after comparator failure. Restore success-only cleanup.

Temporarily return from the replay CLI branch without calling `replay_current_frozen_output`:

```bash
.venv/bin/python -m pytest tests/test_frozen_output_oracle.py::test_replay_cli_routes_to_isolated_helper -q
```

Expected: FAIL because `calls` remains empty. Restore routing and rerun all three node commands; expected PASS.

- [ ] **Step 7: Commit the isolated replay contract**

```bash
git add src/ti26/frozen_output_oracle.py tests/test_frozen_output_oracle.py README.md
git commit -m "feat: add isolated frozen output replay"
```

## Final Verification

- [ ] **Run the complete focused suites**

```bash
.venv/bin/python -m pytest tests/test_provenance.py tests/test_frozen_output_oracle.py -q
```

Expected: PASS.

- [ ] **Prove the implementation checkout is committed and clean before generating a candidate**

```bash
git status --porcelain=v1 --untracked-files=all
```

Expected: no output.

Run:

```bash
test ! -e /private/tmp/ti26-frozen-output-oracle-candidate
```

Expected: exit zero. This exact temporary root is reserved for the following run; stop if it already exists.

- [ ] **Generate, live-verify, and compare a fresh full post-change candidate through the Plan 1 replay**

```bash
git rev-parse HEAD | xargs .venv/bin/python -m ti26.frozen_output_oracle --replay-root /private/tmp/ti26-frozen-output-oracle-candidate --repo-root . --source-revision
```

Expected: the existing full `cli_release` completes with the baseline manifest's snapshot and predictive arguments, the candidate passes live manifest verification against current `HEAD`, the actual complete-object oracle prints `frozen output replay: match`, and the isolated root is removed after success.

- [ ] **Prove success left no candidate or repository publication**

```bash
test ! -e /private/tmp/ti26-frozen-output-oracle-candidate
git status --porcelain=v1 --untracked-files=all
```

Expected: both commands exit zero with no output. The replay created no repository run registration or forecast registry entry. Git remains clean because the rebuilt derived store is under ignored `data/processed/`. On failure, do not run this absence assertion: retain the exact isolated root for diagnosis.

- [ ] **Run required unfiltered repository verification after the candidate proof**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

Expected: both commands exit zero; do not use `-k` or `-m`.

- [ ] **Confirm candidate generation did not dirty the repository**

```bash
git status --porcelain=v1 --untracked-files=all
```

Expected: no output.

## Honest Claim Boundary

- Historical verification proves the manifest source revision itself is a local commit object, each declared input path is a regular non-symlink blob at that commit with the declared digest, current bundle outputs match their declared digests, the run ID is correct, and Markdown prefixes name that run ID.
- It does not prove the release process actually executed the named commit. That claim rests on Task 1’s clean-checkout, `git rev-parse HEAD` piping, immediate live verification, corrected-card byte comparison, and commit sequence; Git blobs alone cannot attest process execution.
- It does not provide a source, dependency, interpreter, installed-file, native-library, host, environment, or undeclared-input closure. The manifest’s runtime fields are metadata, not a byte-complete runtime attestation.
- The oracle proves preservation of the bound D2/D3/D3b objects and machine-readable card semantics only. It does not claim improved prediction quality, model correctness, or stronger gate evidence.
- Isolated replay creates no registered run bundle or forecast-registry entry, but existing `cli_release` may rebuild the durable ignored `data/processed/release-{snapshot_id}.sqlite` derived store. A clean Git status does not prove that ignored file was absent or unchanged.

## Self-Review

- Baseline identity: no baseline run ID appears in this document. Task 1 derives it from the clean release descriptor, registers exactly one runtime-named bundle, verifies it immediately, and byte-compares its card with the current corrected report.
- Historical binding: Task 2 requires the exact 40-hex manifest source revision object to have Git type `commit`, rejects missing/blob/tag revisions, rejects absent/tree/symlink inputs, hashes regular blob bytes, and reuses manifest/run-ID/output/Markdown checks without changing live verification.
- Full output: Tasks 4–6 load the authoritative full frozen-gate mapping, cross-check all three complete individual results, load the entire card JSON object, exact-compare every non-assignment field, compare assignments through configured stable team IDs, and expose the provenance-free staged reader required by Plan 3.
- Synthetic feasibility: each miniature fixture initializes an isolated local Git repository, commits its declared input before creating the descriptor, mutates outputs before the single `write_run_manifest` call, and never copies a full production bundle.
- Dependency order: baseline generation precedes implementation; historical verification precedes oracle loading; staged validation precedes comparison; Task 7 exposes a Plan-1-owned isolated replay usable immediately after Plan 2; normal Plan 3 release remains free of historical comparison.
- Scope: implementation files are provenance, provenance CLI, oracle, tests, README, and the generated baseline. No task edits a predictive producer, config, or release orchestration.
- Mutation accounting: Task 2 has five test functions covering nine parameterized cases and six mutation commands; Task 3 has one and one; Task 4 has four and four; Task 5 has six and six; Task 6 has five and five; Task 7 has three and three.
- Limit disclosure: the plan explicitly denies process-execution proof and undeclared dependency/runtime closure.
- Placeholder and type consistency: baseline registration enumerates exactly one immediate child and validates its manifest `run_id`; replay discovers exactly one runtime-derived candidate child; every public signature consumed later exactly matches its producing task.
