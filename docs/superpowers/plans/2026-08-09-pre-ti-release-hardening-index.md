# Pre-TI Release Hardening Plan Index

> **For agentic workers:** Execute the linked plans in dependency order. Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` inside each plan. Do not start a dependent plan until its predecessor's completion checks are green and committed.

```yaml
specification_review: approved
architecture_blockers: none
implementation_plan_handoff: unblocked
slice: pre_ti_release_hardening
predictive_change_authorized: false
```

The authority for this slice is the approved [three-plane forecasting-system design](../specs/2026-08-09-three-plane-forecasting-system-design.md). These plans implement only its pre-TI hardening section. They do not implement historical event fixtures, longitudinal evaluation, candidate models, calibration changes, simulation-convergence research, model promotion, or any post-TI predictive work.

## Required execution order

```text
frozen-output oracle
        |
        v
evidence import and reconciliation
        |
        v
release preflight and orchestration
        |
        v
narrow offline CI
```

1. [Frozen output oracle](2026-08-09-frozen-output-oracle.md)

   Generate and commit a fresh current-behavior baseline before oracle code changes, add historical source-revision verification, and provide strict manifest-bound and manifestless readers. The oracle compares complete frozen gate objects and complete card output while normalizing assignments by configured team ID. Its isolated replay runs only as a diagnostic and changes no predictive producer.

2. [Evidence import and reconciliation](2026-08-09-evidence-import-and-reconciliation.md)

   Add offline, content-addressed evidence records; source registration; positive and negative observation semantics; current-at-cutoff supersession; normalized rules, participant, exact-roster, groups, and Round-1 contracts; and pure release reconciliation. It imports only owner-supplied local bytes and cannot contact a source.

3. [Release preflight and orchestration](2026-08-09-release-preflight-and-orchestration.md)

   Consume Plans 1 and 2 in a fail-before-write release boundary. Require actual clean `HEAD`, reconcile all non-snapshot evidence before reading the snapshot, validate exact roster accounts against the frozen model's effective snapshot roster, bind every selected input, validate staged output before writing its manifest, atomically publish the complete artifact, then create the append-only forecast link last. Historical-oracle comparison remains a separate non-publishing regression, never an ordinary-release admission condition.

4. [Narrow offline CI](2026-08-09-narrow-ci.md)

   Add CI only after the preceding contracts are stable. Pushes and pull requests run Ruff, the non-slow offline suite, and Plan 3's named deterministic miniature-release contract. Scheduled or manual runs provide unfiltered-suite early warning; they do not replace local release verification.

## Cross-plan interfaces

| Producer | Committed interface | Consumer |
|---|---|---|
| Plan 1 | `verify_run_bundle_at_source_revision` | Plans 1 and 3 historical bundle validation |
| Plan 1 | `replay_current_frozen_output` via `python -m ti26.frozen_output_oracle` | Plan 2 post-change proof; Plan 3 and Plan 4 completion-verification frozen regression |
| Plan 1 | `load_staged_frozen_output` | Plan 3 staged internal validation before `manifest.json` exists |
| Plan 1 | `registered_baseline_invocation`, `load_current_baseline`, `load_frozen_output`, `assert_matches_frozen_output` | internal to Plan 1's oracle module; later plans invoke them only through the two interfaces above |
| Plan 2 | `load_release_evidence`, `reconcile_release_evidence`, immutable selected evidence paths/digests, exact roster accounts, independently selected groups and Round-1 state | Plan 3 read-only preflight |
| Plan 3 | `test_miniature_release_is_deterministic_and_verifiable` | Plan 4 change-event CI |
| Plan 3 | manifest-bound bundle plus append-only published-forecast link | Near-lock runbook and later forecast registry work |

Plan 3 must use Plan 1's staged reader before `manifest.json` exists. It must use manifest-bound verification for the committed baseline, historical registry artifacts, and post-publication verification. Normal release must not call `assert_matches_frozen_output` or `replay_current_frozen_output`; the dedicated frozen-regression path owns that diagnostic. Plan 3 must not reimplement Plan 2 evidence loading or selection.

## Owner-supplied prerequisites

Implementation may begin with Plan 1 without external input. Plan 2's generic schemas, importer, and synthetic tests may also proceed, but its current-record task must stop until the owner supplies:

- the exact rendered Valve rules bytes already captured;
- evidence-backed source availability, observation, publication when known, and retrieval timestamps;
- the stable source-key registration approved for that rules subject.

Before the near-lock release, the owner must separately capture and register current participants, exact five-account rosters, groups publication state, and Round-1 publication state. `unpublished` requires captured negative-observation evidence current through the release cutoff. Lack of adequate evidence is `unknown`, and final shipping rejects it.

No plan may invent a URL authority, timestamp, roster account, participant, draw, rule, or source-availability claim from prose or memory.

**Recorded owner policy (2026-08-10) — Round 1 published without groups:** this
state is a hard release stop. Plan 2's release adapter already fails closed on a
published Round-1 tip without a published groups tip; that behavior is the
policy, not a gap to engineer around. No unconditioned forecast is issued while
knowingly discarding published Round-1 matchups, and Round-1-only conditioning
(for example, sampling group assignments consistent with the known pairs) is a
predictive-behavior change outside this slice's authority — it requires its own
reviewed amendment before anyone implements it. As of 2026-08-10 the project is
in exactly this state (see `docs/ti26/2026-08-10-ti2026-schedule-fetched.md`);
the resolution everyone should expect is the groups publishing before lock day,
since Rounds 2–4 cannot run without them.

**Owner decision (2026-08-11) resolving that state:** the owner has supplied the
group split by taking the broadcast time blocks, committed at
`data/ti2026_groups.yaml`. This resolves the stop by supplying groups, not by
weakening the rule: `load_group_draw` is unmodified, no Round-1-only
conditioning was implemented, and the release path still requires a complete
`groups:` mapping. The split is an owner inference from the schedule and is
recorded as such — it is not a published Valve draw, and no evidence record
claims it is. Under Plan 2's evidence contract a groups record still needs its
own capture, authorization, and attestation before it can satisfy the
`draws:ti2026:event-authority:groups` subject; the committed file is a release
input, not evidence.

**Recorded owner constraint (2026-08-10) — LGD roster standin:** external
reporting has Topson replacing the banned TaiLung
(`docs/ti26/2026-08-10-lgd-standin-topson.md`). Once Plan 3 is implemented and
exact-roster evidence is imported, an evidence-versus-snapshot roster mismatch
for LGD is a preflight failure that stops the release before any write — not a
closing-report limitation. Shipping despite it requires a recorded owner
decision (retain the stop and not publish, reauthorize a fallback, authorize a
cold-start predictive change, or defer Plan 3 enforcement); silently keeping the
banned player's roster because his account already exists is not an option any
plan authorizes.

## Frozen-behavior boundary

The isolated oracle replay is the required falsifier for accidental predictive change. Later plans may change only evidence, validation, orchestration, provenance, recovery, documentation, and CI behavior.

In particular:

- do not change ratings, calibration, strengths, map/series probabilities, simulation, optimizer behavior, gates, categories, or capacities;
- do not feed newly captured roster evidence into the predictor in this slice;
- if evidence roster accounts differ from the latest validated snapshot accounts used by the current card path, preflight stops before writes;
- do not weaken, rerun for a better result, or reinterpret a registered gate;
- keep diagnostics non-authoritative;
- live event evidence never gates or alters the frozen replay: the replay executes
  the baseline manifest's recorded predictive arguments, and Plan 3's
  `--frozen-replay` diagnostic route in `cli_release` (required by Plan 1's
  registered cross-plan obligation) performs no evidence loading, no release
  preflight, and no registry interaction, so a new roster or draw tip cannot
  block or change the regression verdict.

## Slice completion contract

Each plan owns its focused RED/GREEN checks and manual mutation observations. After Plan 4, run on the exact final tree:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

For a genuinely generated release, also run the existing provenance verifier against the exact bundle directory printed by that release. CI status alone is not release verification.

The slice is complete only when:

- all four plans are implemented and committed in order;
- the frozen-output oracle accepts a fresh isolated replay generated from its registered baseline invocation after each non-predictive implementation plan;
- evidence and preflight failures leave no store, bundle manifest, or registry link;
- a valid artifact-without-link retry first reproduces and byte-verifies expected output, then creates only the missing link;
- a complete retry reproduces output in verification staging, proves byte identity, and makes no durable change;
- exact unfiltered pytest and Ruff checks pass on the reported tree;
- the near-lock runbook reflects the evidence-import and preflight order.

Pushing a branch, opening a pull request, or relying on a GitHub workflow result requires separate owner authorization and execution. Until then, report CI runner behavior as externally unverified.
