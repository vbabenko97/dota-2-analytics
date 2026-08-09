# Three-plane longitudinal forecasting system design

**Date:** 2026-08-09

**Review state:**

```yaml
owner_review: changes_requested
architecture_direction: approved
implementation_plan_handoff: blocked
```

**Scope:** Batch release provenance, longitudinal evaluation, and model-promotion authority

## Purpose

Extend the existing TI 2026 batch forecast into a longitudinal forecasting
system without weakening the near-lock release discipline or changing the
registered TI 2026 model. The design separates immutable event evidence,
shipping authority, and research authority while retaining one implementation
of ratings, simulation, scoring, schemas, and validation.

The operational objective remains a complete fixed-capacity prediction card
issued before lock from information available by its declared cutoff. The
research objective is to measure probability quality, tournament-distribution
quality, and card-decision value across frozen events, then change the shipping
incumbent only through registered evidence and an explicit owner decision.

The owner who submits the card is the release authority. Future maintainers and
auditors are consumers of the provenance and evaluation artifacts. There is no
online user, API consumer, or serving operator.

This is an umbrella design with three implementation slices:

1. pre-TI release hardening;
2. post-TI evidence and evaluation infrastructure;
3. candidate research and explicit promotion.

Each slice receives its own implementation plan. The pre-TI slice is first and
contains no predictive-model change.

This specification complements rather than replaces the original forecast
design, the reproducible-forecast design, registered gate specifications, and
the near-lock runbook. Where this document defines future longitudinal
architecture, the immutable historical registrations retain authority over
their own runs.

## Non-negotiable constraints

- Keep the six card categories and capacities unchanged.
- Keep D2, D3, and D3b registrations, artifacts, criteria, and verdicts
  unchanged.
- Keep D4 and all current diagnostics unable to alter the shipping card.
- Make no change to strengths, calibration, series probabilities, uncertainty,
  simulation behavior, or assignment behavior before the TI 2026 lock.
- Keep all network access through `explorer_query`; tests remain offline.
- Preserve roster-based identity. Organisation identifiers and display names
  do not become team identity.
- Apply the repository's bind-every-number rule without narrowing it. Every
  number in a report, docstring, source or config comment, generated registry
  record, or commit message is either emitted by code from a
  manifest-identified input or removed. The only authored exception is a
  normative numeric choice in a digest-bound protocol, candidate, or decision
  field registered before measurement; it is labelled as a registered choice
  and never presented as an empirical result or repeated as numeric prose.
- Register future evaluation and promotion criteria before running the producer
  that measures them.
- Bind every post-migration candidate, fold forecast, evaluation, promotion,
  and shipping forecast to the content-addressed implementation actually
  executed. A clean checkout alone is not implementation identity.
- Treat an event outcome as development evidence for every candidate cycle
  designed after that outcome was exposed. Preregistration does not make an
  already viewed result unseen again.
- Never overwrite a complete evidence bundle, fixture, forecast, evaluation, or
  promotion record.

## Maturity statement

The repository does not have one meaningful maturity label. Current
documentation will use these dimensions:

```yaml
maturity:
  release_reproducibility: production
  provenance_enforcement: hardening
  longitudinal_evaluation: planned
  predictive_evidence: unproven
  online_serving: not_applicable
```

`release_reproducibility` describes deterministic batch generation and bundle
verification. It does not imply predictive value. `predictive_evidence` remains
unproven until registered rolling-origin evaluation supports a stronger claim.

## Architecture and authority

The system has three authority planes.

### Immutable evidence plane

The evidence plane owns facts and their provenance:

- raw data snapshots;
- event cutoffs and start times;
- participant fields;
- roster account sets;
- rules evidence and normalized rule facts;
- groups and Round 1 pairings;
- balance-patch calendars;
- post-event results and derived truth.

It does not own model choices, fitted parameters, promotion decisions, or the
active shipping model.

### Shipping plane

The shipping plane may:

- read one complete pre-cutoff knowledge bundle;
- read the active-model pointer or the existing frozen TI 2026 gate lineage;
- rebuild strengths from manifest-bound inputs;
- simulate, optimize, and emit a forecast;
- append a published-forecast registry entry.

It may not:

- accept an arbitrary candidate identifier;
- fit or select calibration;
- tune a parameter;
- compare candidates;
- read an outcome bundle;
- write a promotion record;
- change the active-model pointer.

### Research plane

The research plane may:

- register candidates and evaluation protocols;
- construct historical event fixtures;
- fit and calibrate candidates using training-side data;
- produce fold forecasts;
- score persisted forecasts after exposing the matching outcome;
- aggregate event-level evaluation reports;
- produce promotion proposals.

It may not:

- overwrite a published forecast or historical fixture;
- update the active-model pointer;
- write a promoted decision;
- alter a shipping run;
- use a target event's outcome during that event's forecast phase.

### Shared implementation

The planes share pure rating, roster, simulation, optimization, scoring,
schema, and validation functions. Plane separation concerns readable state and
mutation authority, not duplicated domain code. Existing modules remain in
place unless an implementation slice needs a narrow extraction; this design
does not authorize a broad package reorganization.

## Repository layout

Braces below denote identifier path components, not literal directory names.

```text
data/
  raw/
    {snapshot_id}/
      manifest.json
      ...
  evidence/
    rules/{evidence_id}/
      rendered.txt
      extracted.json
      manifest.json
    participants/{evidence_id}/...
    rosters/{evidence_id}/...
    draws/{evidence_id}/...
    patches/{calendar_id}/...
    source-availability/{evidence_id}/...
  events/{event_id}/
    knowledge/{cutoff_id}/
      event.yaml
      participants.yaml
      rosters.yaml
      rules.yaml
      draw.yaml
      training_rows.jsonl.gz
      inputs.json
      manifest.json
    outcomes/{outcome_id}/
      results.json
      standings.json
      card_truth.json
      manifest.json

reports/
  runs/{run_id}/...
  evaluations/{evaluation_id}/...

registry/
  implementations/{record_id}.json
  protocols/{record_id}.json
  candidates/{record_id}.json
  evaluations/{record_id}.json
  exposures/{record_id}.json
  proposals/{record_id}.json
  decisions/{record_id}.json
  promotions/{record_id}.json
  forecasts/{record_id}.json
  scores/{record_id}.json
  corrections/{record_id}.json

config/
  active_model.yaml
```

The current `data/raw` and `reports/runs` contracts remain. New evidence and
event directories use the same fail-closed principles: safe relative paths,
regular files, exact schema keys, canonical JSON manifests, SHA-256 payload
digests, and exclusive creation.

## Evidence records

An evidence record captures one externally sourced fact set. Its manifest has
these required fields:

| Field | Contract |
|---|---|
| `schema` | Exact supported evidence-manifest schema identifier |
| `evidence_id` | Stable identifier unique within the evidence kind |
| `kind` | Registered evidence kind |
| `event_id` | Event to which the evidence applies, when event-specific |
| `subject_key` | Canonical identity of the externally observable fact slot: evidence kind, event scope, source namespace, and stable subject locator; it never includes the observed value |
| `source` | URL key, capture method, established availability time, optional claimed publication time, and retrieval time |
| `observation` | Exact-schema assertion of `present` or `absent`, observation time, supported-through time, and digest-bound source captures; an inadequate observation may be retained but proves neither assertion |
| `construction` | `contemporaneous`, `reconstructed_verified`, or `reconstructed_unknown` |
| `payloads` | Safe relative path and SHA-256 for every payload |
| `supersedes` | Digests of predecessor evidence records for the same `kind` and `subject_key`, possibly empty |
| `producer_revision` | Actual clean Git revision that produced the record |

`available_at_utc`, `published_at_utc`, and `retrieved_at_utc` are distinct.
`available_at_utc` is the earliest time supported by the evidence at which the
exact fact set was public. A contemporaneous retrieval at or before cutoff may
establish availability no later than its retrieval time even when the source
does not publish a timestamp. A later retrieval does not by itself establish
historical availability. `published_at_utc` records a source claim when one
exists; `retrieved_at_utc` records when the owner obtained the bound bytes.

Evidence construction quality is ordered from strongest to weakest as
`contemporaneous`, `reconstructed_verified`, then `reconstructed_unknown`.
When a knowledge bundle combines evidence classes, its `construction` equals
the weakest class it depends on, including the training-corpus availability
class defined below.

### Current-at-cutoff selection

Supersession is an acyclic graph within one `(kind, subject_key)`. A record
cannot supersede another subject. An import that would leave multiple current
tips must explicitly reconcile and supersede every current tip; a fork is not
resolved by choosing whichever record is convenient.

For a cutoff, a record is applicable only when its evidence-backed
`available_at_utc` is at or before the cutoff. Among applicable records,
knowledge construction selects the unique maximal record in the supersession
graph. A known descendant available by the cutoff makes its ancestor stale and
inadmissible. No applicable tip, multiple incomparable tips, a cycle, a missing
predecessor, a cross-subject edge, or contradictory concurrent records fails
closed. Reconciliation output identifies the selected tip and every rejected
record with its reason. A record first available after the cutoff never changes
which record was current at that cutoff.

A positive assertion requires captured bytes that show the subject was
published. A negative assertion requires captured bytes from every registered
authoritative source checked, plus `observed_at_utc` and
`supported_through_utc`; omission of a field from an unrelated payload is not
negative evidence. By default a point observation supports absence only at its
observation time. Extending that support requires a freshness policy registered
before the knowledge bundle is built. A negative observation is inadmissible
when the cutoff is later than its supported-through time.

### Rules evidence

Rules evidence contains:

- `rendered.txt`: the captured rendered page body or owner-supplied source text;
- `extracted.json`: normalized factual fields generated from the captured text;
- `manifest.json`: source metadata and both payload digests.

Each normalized field records the digest of the supporting text span. The
normalized factual set covers published format, ranking order, pairing
restrictions, Round 5 behavior, and elimination-selection order. It excludes
model choices such as opponent-choice policy and the duration distribution.

For TI 2026, release preflight compares the normalized factual set with the
factual subset of `config/ti2026_rules.yaml`. Assumptions in that configuration
remain explicitly tagged as assumptions. A disagreement is a hard preflight
failure.

Rules, participant, roster, and draw acquisition outside OpenDota is an owner
task. The repository does not fetch those sources. The owner supplies captured
bytes plus source metadata to an offline `cli_evidence_import` command. That
command performs no network access; it validates and exclusive-creates the
evidence record. Repeating a rendered rules capture means repeating this owner
task, then importing a new record.

The morning-state owner transcript remains committed with a superseded banner
and links to the later rendered evidence. Supersession does not delete or edit
its historical body.

### Patch evidence

A committed balance-patch calendar distinguishes base patches from letter
patches. Raw OpenDota patch values remain unchanged. A derived
`balance_patch` is assigned from match completion time and the calendar. This
evidence may be captured before TI 2026, but no patch-dependent model behavior
is introduced before lock.

## Knowledge bundles

A knowledge bundle is the complete fact set admissible to a forecast at one
cutoff. It has its own trust root and is independently usable when the entire
outcomes tree is absent.

Its manifest has these required fields:

| Field | Contract |
|---|---|
| `schema` | Exact supported knowledge-manifest schema identifier |
| `event_id` | Stable event identifier |
| `cutoff_utc` | Latest admissible information time |
| `event_start_utc` | Declared first event time and strictly after cutoff |
| `construction` | Derived from the weakest bound external-evidence class and the mapped training-corpus availability class |
| `payloads` | Digest-bound event, participant, roster, rules, draw-state, filtered training-row, and input files |
| `evidence` | Path and digest of every referenced evidence manifest |
| `source_snapshot` | Path and digest of the raw snapshot manifest from which training rows were derived |
| `training_corpus` | Path, digest, row-schema version, row count, cutoff, source-availability basis, availability-witness digest, and latest admissible row-availability time of the filtered training artifact |
| `producer_revision` | Actual clean Git revision that built the bundle |

The manifest schema does not permit an outcome path, outcome digest, observed
result, score, evaluation identifier, or promotion decision.

`draw.yaml` is always a local, digest-bound state payload. It represents groups
and Round 1 independently with one of these states:

- `published`: external draw fields and the current positive evidence-tip
  reference are required and must reconcile exactly;
- `unpublished`: external draw fields are forbidden, while the current negative
  evidence-tip reference is required and must support absence through the
  bundle cutoff;
- `unknown`: external draw fields are forbidden because no adequate current
  observation exists; attempted observations may be referenced, but this state
  makes no claim that the draw was unpublished.

`null` is not a valid publication state.

Rules, participant, and roster facts required by an event fixture cannot use
`unknown`. A final shipping bundle also rejects an `unknown` draw state. A
retrospective diagnostic may retain it only when the registered protocol
permits that construction class and the uncertainty is explicit.

The knowledge bundle does not bind the code revision later used to forecast.
That revision belongs to the forecast manifest so the same factual bundle can
be evaluated by multiple registered candidates. `producer_revision` identifies
only the code that validated and assembled the knowledge bundle.

### Cutoff-filtered training corpus

Knowledge construction materializes the admissible maps as
`training_rows.jsonl.gz`. Rows use the normalized `MapRow` schema, canonical
JSON serialization, deterministic ordering by `(start_time, match_id)`, and a
deterministic gzip header. The knowledge manifest binds the compressed bytes,
row-schema version, row count, cutoff, and source-snapshot manifest.

The knowledge loader returns a typed `TrainingCorpus`. Shipping and candidate
fitting APIs accept that type and do not accept a raw snapshot path, raw store,
or unfiltered row sequence. The source snapshot may physically contain later
maps, especially for reconstructed history; those rows never enter the
forecast-side artifact or API.

Every training corpus has one source-availability basis:

- `contemporaneous_snapshot`: the exact normalized row bytes occur in a
  snapshot retrieved at or before the forecast cutoff;
- `first_seen_verified`: an immutable history of snapshot manifests proves the
  first appearance of every exact normalized row at or before the cutoff;
- `completion_time_only`: map completion is known, but source availability at
  the historical cutoff is not.

The training-corpus manifest binds the source snapshot retrieval time, the
first-seen index digest when used, a deterministic row-to-availability-witness
mapping, and `latest_admissible_row_available_at_utc`. A later correction to a
row is a different byte sequence and cannot inherit the earlier row's
availability witness.

`contemporaneous_snapshot` maps to `contemporaneous` construction and
`first_seen_verified` maps to `reconstructed_verified` unless weaker external
evidence determines the bundle class. `completion_time_only` maps to
`reconstructed_unknown`; it is diagnostic-only and ineligible for promotion
evidence unless a protocol registered before evaluation explicitly permits and
justifies it. The bundle's overall construction class includes this mapping.

## Outcome bundles

An outcome bundle is created only after the event facts it represents are
available. It has a separate manifest and does not reference a knowledge
bundle, forecast, candidate, or promotion.

Its manifest has these required fields:

| Field | Contract |
|---|---|
| `schema` | Exact supported outcome-manifest schema identifier |
| `event_id` | Stable event identifier |
| `available_at_utc` | Time after which the outcome was admissible to scoring |
| `payloads` | Digest-bound raw result reference and derived truth files |
| `evidence` | Path and digest of source evidence supporting availability and event identity |
| `derivation` | Registered derivation schema and producer revision |
| `producer_revision` | Actual clean Git revision that built the bundle |

`results.json` identifies the manifest-bound result snapshot and event window.
`standings.json` and `card_truth.json` are producer outputs, not hand-maintained
copies. The existing TI 2025 dual-source check is preserved: derived truth must
equal its frozen registered truth, and disagreement fails.

A correction never overwrites an outcome bundle. It creates another outcome
identifier and a correction record explaining the supersession.

## Time and availability semantics

All timestamps use RFC 3339 UTC form. The following comparisons are normative:

- A source fact is admissible only when it belongs to the unique current
  evidence tip for its subject and its evidence-backed `available_at_utc` is at
  or before `cutoff_utc`. A negative fact must additionally support absence
  through the cutoff.
- A training map is admissible only when it belongs to the materialized bound
  training corpus, `start_time + duration` is at or before `cutoff_utc`, and its
  source availability satisfies that corpus's registered basis.
- `cutoff_utc` is strictly before `event_start_utc`.
- An outcome is admissible to scoring only when `available_at_utc` is strictly
  after the forecast's cutoff.
- A shipping forecast is created before `event_start_utc`.

The new longitudinal evaluator uses match completion time. Existing frozen
gates and their historical cutoff semantics are not modified.

A retrospectively retrieved external source may support a reconstructed
fixture only when its fact availability is established by evidence. A later
training snapshot may support historical rows only through
`first_seen_verified`; filtering that snapshot by match completion alone is
`completion_time_only`, not point-in-time reconstruction. If pre-cutoff fact or
row availability cannot be established, construction is
`reconstructed_unknown`. Such a fixture may support diagnostics but is
ineligible for promotion evidence unless a future registered protocol
explicitly permits and justifies that evidence class.

Promotion eligibility is derived by validators from manifests and the
registered evaluation protocol. It is not an author-controlled fixture flag.

## Cryptographic lineage

Manifests form a directed lineage:

```text
candidate -> implementation + evaluation protocol
forecast -> knowledge + implementation
score -> forecast + outcome
evaluation -> fold forecasts + fold scores + candidate + implementation
              + evaluation protocol + exposure records
decision -> proposal + candidate + implementation + evaluation + incumbent
promotion -> committed decision + implementation + approval revision
active model -> promoted promotion record + implementation
```

Knowledge never references outcomes. Outcomes never reference knowledge.
Scoring is the first artifact allowed to bind the two trust roots.

Content hashes and Git history make accidental or partial changes detectable.
They do not provide externally anchored immutability against a coordinated
rewrite of every local artifact and Git reference. Documentation must not claim
otherwise.

## Forecast and evaluation artifacts

### Shipping forecast

A shipping forecast manifest binds:

- the knowledge-manifest path and digest;
- actual `HEAD` at generation time;
- a clean tracked and untracked worktree precondition;
- the implementation record executed and a successful implementation
  preflight certificate;
- the active-model pointer and promotion digest, or the frozen TI 2026 gate
  artifact during the migration period;
- every configuration and raw-snapshot input;
- seeds, simulation plans, commands, runtime, and outputs.

Ignored files are outside the clean-worktree claim. Any ignored file that can
affect output must instead be an explicitly hashed input.

### Research fold forecast

A research fold forecast binds the same factual inputs but references a
registered candidate and its implementation rather than the active-model
pointer. It lives under an evaluation bundle and cannot be appended to the
published-forecast registry. Its manifest declares
`forecast_kind: research_fold`; a published forecast declares
`forecast_kind: published`.

### Score artifact

A score manifest binds one immutable forecast and one outcome manifest. Its
producer verifies event identity, cutoff ordering, field reconciliation, and
both upstream manifests before loading outcome content. It never modifies the
forecast.

Two thin command boundaries call the same pure scorer. `cli_score_forecast`
accepts only `forecast_kind: published` and appends a published score registry
entry. `cli_score_fold` accepts only `forecast_kind: research_fold` and writes
inside its evaluation bundle. Before the fold scorer can load any outcome
payload, it requires an `opened` exposure record that binds the fold, candidate,
implementation, protocol, event, and exact outcome-manifest digest. It has no
authority to create that opening. The exposure guard may read and hash the
outcome manifest to create or validate the opening, but it does not return any
outcome payload until the record is durably published. Each scorer rejects the
other forecast kind.

### Rolling-origin evaluation

Fixtures are ordered by event start. For target event `t`, the runner:

1. loads outcomes only from events earlier than `t`;
2. loads the target event's knowledge bundle;
3. fits all candidate parameters and calibration on the training side;
4. emits and persists the target fold forecast;
5. closes the forecast phase;
6. records the exposure transition before loading the target outcome through
   the scoring boundary;
7. emits the fold score;
8. moves to the next event.

Candidate registration and the authoritative evaluation protocol are fixed
before the first fold runs. Calibration is part of the candidate pipeline. No
criterion asks an uncalibrated rating-to-logit mapping to prove value on an
arbitrary scale.

Cross-event conclusions report every event delta and an event-level aggregate.
Map or series rows within one event are not represented as independent events.

## Evaluation exposure and promotion evidence

Point-in-time folds prevent target leakage inside one evaluation. They do not
make an outcome reusable as fresh promotion evidence after its results have
influenced later candidate design. An append-only exposure ledger therefore
classifies each event for each registered candidate cycle:

- `development`: the result was already visible to the candidate author or was
  previously used for model, feature, search-space, protocol, or diagnostic
  design; it remains reportable but cannot satisfy that cycle's promotion
  criteria;
- `promotion_lockbox`: the outcome is held behind an access boundary until a
  protocol and either one candidate or a finite candidate family have been
  registered for a one-time opening;
- `prospective`: candidate, implementation, protocol, knowledge cutoff, and
  forecast were registered before the outcome became available.

Exposure roles only weaken. A record cannot upgrade `development` to a
promotion-eligible role. A prospective result may support the exact frozen
candidate and protocol for which it was reserved; after opening, it is
development evidence for every candidate cycle authored later. Existing event
results already visible in repository history migrate as `development`.
Development outcomes may remain on the training side of later folds and in
diagnostic reports; the restriction is that their target-event scores cannot
serve as fresh promotion evidence for an adaptively designed candidate.

Exposure records form a predecessor chain with the states `reserved`, `opened`,
`consumed`, and `invalidated`. A reservation binds the event, candidate or
finite candidate family, implementation IDs, protocol, intended evidence role,
knowledge digest, and registered query or comparison budget. Immediately before
any outcome loader can return content, the evaluator exclusive-creates the
`opened` record binding the actual outcome digest. A crash after that write
conservatively counts as exposure. Completion appends `consumed`; a provenance
or access violation appends `invalidated`. Missing predecessors, parallel tips,
budget overruns, opening before reservation, and opening an already consumed
lockbox fail closed.

An exact retry may resume the already opened evaluation for the same fixed
candidate family, implementation set, protocol, and output identities without
spending another query. It may not change a metric, candidate, output path, or
query after opening. The opened event is already consumed for every later
candidate cycle whether that retry succeeds or fails.

The default promotion path is prospective evidence. Optional alternatives must
be fixed in the evaluation protocol before any outcome is opened:

- a previously sealed lockbox behind an access boundary separate from the
  research checkout;
- a finite candidate family registered before one atomic lockbox opening, with
  its multiplicity treatment;
- a registered reusable-holdout or sequential-testing method with its explicit
  query budget and validity calculation.

Running another command against the same outcome is not a reusable-holdout
method. `cli_promote` derives eligibility from the exposure chain and refuses a
proposal whose required evidence is development-only, consumed outside its
registered family, over budget, or missing a valid reservation and opening.

## Evaluation domains and readiness

The system exposes three evaluation domains and four metric sets.

| Domain | Metric set | Required readiness |
|---|---|---|
| Predictive model | Map probabilities | Valid knowledge, outcome, and cutoff reconciliation |
| Predictive model | Series probabilities | Map readiness plus strict series integrity |
| Tournament distribution | Records, categories, advancement, elimination | Series readiness plus simulation convergence |
| Card decision | Card hits, ladder comparison, and assignment stability | Tournament readiness plus valid fixed-capacity assignment |

Reports have explicit readiness state. A completed diagnostic states
`shipping_effect: none`. A blocked report contains stable blocker codes and no
numeric results. Malformed reports, blocked reports containing results, and
unknown readiness states are invalid rather than diagnostic.

Scoreboard interfaces may exist before their prerequisites, but series,
tournament, and card results cannot become authoritative or promotion evidence
until their corresponding readiness checks pass.

### Metrics and baselines

Map and series probability reports use mean log loss as the primary proper
score. They also emit Brier score, calibration intercept and slope, a registered
discrimination or resolution measure, coverage and exclusions, and event-level
score deltas. Target-tier and non-target-tier results remain separate.

Tournament-distribution reports score realized team categories as multiclass
probabilities and advancement or elimination as binary probabilities. They also
report distributional coverage and simulation readiness. No simulated expected
card objective is presented as observed evaluation.

Card-decision reports emit realized hits, the paired difference from the naive
strength ladder, assignment stability, and whether simulation changed any
ladder assignment. They do not emit realized regret under ordinary hit-count
loss because, with fixed category capacities, that value is only a restatement
of realized hits. A future nonredundant regret field requires a different loss
or comparator registered before evaluation.

Registered comparisons include:

- constant map and series probability baselines;
- the current complete calibrated incumbent;
- the naive strength ladder at the card-decision layer;
- the registered random-card reference where the historical specification
  requires it.

Promotion thresholds and catastrophic-regression limits are not invented in
this architecture document. They must be registered in a future evaluation
protocol before its producer runs. With few events, reports retain every event
delta alongside any pooled summary.

## Series integrity contract

One immutable evaluation protocol owns the series-integrity plan. That plan
fixes the permitted format source hierarchy, terminal-win rules, maximum
inter-map gap in seconds, timestamp ordering and tolerance, reconstructed-ID
algorithm, exclusion reason codes, permitted exclusion bounds, and the effect
of each exclusion on promotion eligibility.

Absent an explicitly registered exclusion rule, any violation blocks the
event's series report and emits no series metrics. Permitted exclusions are
retained row by row in the report and still obey the plan's registered count
and effect. The validator applies those deterministic rules to:

- null or zero source series identifiers;
- one source identifier reused across different leagues or team pairs;
- a series containing anything other than two teams;
- noncontiguous map order or an inter-map gap beyond the registered maximum;
- duplicate map identifiers or map sequence;
- an impossible number of completed maps for the declared format;
- a tie after the expected terminal state;
- maps recorded after either team has already won the series;
- source and reconstructed identities that disagree.

The source identifier and any reconstructed identifier are retained separately.
Series scoring consumes verified source rows by default and reports every
exclusion. It never turns a missing identifier into a silent one-map series.

## Simulation convergence contract

Candidate comparisons use common random numbers for draw, pairing, map, and
choice-policy streams whenever both mechanisms admit the same candidate-neutral
coupling. The coupling specification and stream identifiers are manifest-bound;
candidate-specific thresholds or stopping choices are not inputs to its random
keys.

Simulation runs in independent batches. A registered plan fixes:

- estimands for category marginals, card objectives, objective gaps, and
  boundary-team differences;
- independent-batch construction and the estimator for each estimand or paired
  candidate difference;
- one stopping-valid sequential uncertainty method and its assumptions;
- the simultaneous-coverage family across estimands, teams, cards, candidates,
  and checkpoint looks, plus its registered error budget;
- batch size, checkpoint schedule, consecutive-stability requirement, and
  maximum work;
- every threshold with its unit and inclusive or exclusive comparison;
- the exact Boolean conjunction defining convergence;
- the stream-key derivation algorithm and inputs for draw, pairing, map, and
  choice-policy randomness;
- tie behavior and near-optimal-card tolerance.

Every uncertainty statement used by the stopping condition must retain its
registered coverage under the checkpoint schedule and the stopping rule. The
plan permits exactly these method classes:

- a time-uniform confidence sequence valid at arbitrary registered stopping
  times;
- alpha spending or another familywise-valid correction over a finite,
  preregistered checkpoint schedule;
- an independent two-stage design in which a pilot chooses the final fixed
  simulation count and a fresh final run supplies the authoritative estimate.

Ordinary fixed-sample confidence intervals recomputed at repeated checkpoints
are invalid for adaptive stopping. A convergence artifact records the method,
formula or algorithm version, assumptions, checkpoint history, simultaneous
coverage scope, spent error budget where applicable, exact decision trace, and
final bounds so a verifier can reproduce the Boolean result.

For a paired comparison, batch summaries include paired differences produced by
the same coupling digest and streams. The candidate plans may differ elsewhere;
requiring their entire plan digests to match would incorrectly forbid the
comparison. If mechanisms cannot share the registered coupling, the protocol
must preregister a valid unpaired comparison rather than silently falling back.

The simulator stops only when the registered stopping-valid condition holds or
maximum work is reached. Reaching maximum work first emits the valid state
`not_converged_max_work`; dependent tournament and card reports are blocked
with stable reason codes and no numeric results. Invalid uncertainty schemas,
stream mismatches, or runtime faults are operational failures and do not emit a
partial convergence result. A fixed simulation count is not itself evidence of
convergence.

Evaluation artifacts retain batch summaries, assignment stability, boundary
teams, every card inside the registered near-optimal tolerance, and the complete
convergence certificate.

## Candidate and promotion registry

Registry records are canonical, content-addressed JSON written with exclusive
creation. They use this envelope:

```json
{
  "schema": "ti26.registry-record.v1",
  "record_id": "sha256 digest",
  "payload": {}
}
```

`record_id` is SHA-256 of the repository's existing canonical JSON encoding of
exactly `{"schema": "ti26.registry-record.v1", "payload": payload}`. The
identifier field is absent from those hashed bytes. The filename is
`registry/{kind}/{record_id}.json`. A registry reference is the record ID;
non-registry artifact references remain safe relative path plus SHA-256.
Verification recomputes the ID, checks the filename, validates the payload's
kind-specific exact schema, and then validates predecessor or artifact
references. Records may point to predecessor record IDs to form an auditable
chain; no mutable registry database is introduced.

### Implementation registration

An implementation record identifies the executable behavior separately from
the candidate's authored statistical specification. Its registry record ID is
the `implementation_id` and its exact-schema payload binds:

- the clean source revision at registration;
- an executable entry point such as a candidate factory module and callable;
- a canonical source closure containing every tracked file under `src/ti26`,
  plus `pyproject.toml` and `uv.lock`, represented by sorted path, file mode,
  byte digest, and one digest of the complete list;
- the exact dependency-lock path and byte digest;
- a canonical runtime closure containing the exact Python executable, standard
  library, installed distribution files, extension modules, and native
  libraries available to the process, represented by sorted logical path, file
  mode, byte digest, and one digest of the complete list; an immutable archive
  or image digest may additionally bind how that closure is materialized, but
  package names and versions alone are never authoritative;
- the Python implementation, version, ABI, normalized installed distribution
  set, and exact host platform constraints used by the authoritative run;
- a scrubbed process-environment contract covering executable path, import
  path, locale, timezone, hash seed, numerical-library thread settings, and
  every environment value permitted to affect output;
- a digest-bound deterministic conformance fixture and the expected output
  digest produced through the registered entry point.

Repository-local executable code outside the sealed source closure and runtime
bytes outside the sealed runtime closure are forbidden. Non-code files may
affect output only as explicit digest-bound forecast inputs. The process must
execute the registered Python bytes and starts from the registered scrubbed
environment. It rejects an undeclared repository-local import, dynamic code
load, executable child, runtime library, input-file access, or output-affecting
environment read. This enforcement lets a documentation-only commit change
`HEAD` without changing implementation identity while preventing an unsealed
helper module, package, interpreter, or native library from changing behavior.

The source closure is the executable artifact because this repository currently
runs the editable source tree with `.venv/bin/python`. Building a wheel and then
executing different source bytes would certify the wrong artifact. If shipping
later executes an installed wheel, a new implementation schema must bind that
exact wheel and shipping must execute it; the record never substitutes an
unused build artifact for the code actually run.

`cli_implementation_register` requires a clean checkout, computes the source
and runtime-closure fingerprints, captures the environment contract, runs the
conformance fixture, and exclusive-creates the implementation record.
Conformance is a drift detector, not a substitute for source, lock, and runtime
identity.

Each authoritative evaluation record contains exactly one candidate and one
implementation ID, and every fold forecast and fold score repeats that binding.
An incumbent comparison is a reference to a separate immutable evaluation
record. When a lockbox or prospective cohort compares a finite candidate
family, all candidate fold forecasts are persisted before the cohort outcome is
opened; scoring then creates one evaluation record per implementation. The
proposal pairs those records rather than allowing one evaluation identity to
hide multiple executable versions.

Research and shipping implementation preflight recompute the source closure,
lock digest, runtime closure, host constraints, scrubbed-environment
fingerprints, import and file-access boundary, and conformance output before the
registered entry point is invoked or any final bundle is written. The current
clean `HEAD` is recorded and may differ from the implementation's registration
revision only when the sealed executable closure is byte-identical. Any source,
dependency, interpreter, installed-file, native-library, host, environment,
entry-point, access-boundary, or conformance mismatch fails closed. Candidate
registration applies the same identity check. A later shared-code or runtime
change therefore cannot change evaluated or shipping behavior without a newly
registered and evaluated implementation, decision, promotion, and active
pointer.

### Evaluation protocol registration

One protocol record is authoritative for required folds and fixture evidence
classes; metrics and aggregation; promotion thresholds; the catastrophic-
regression rule; exposure roles, allowed reuse method, comparison or query
budget, and multiplicity treatment; and the series-integrity and
simulation-convergence plans. It is registered before candidate evaluation.
Candidates reference its record ID and cannot repeat or override protocol-owned
criteria.

A reusable-holdout or sequential-testing method is not a free-text claim. Its
protocol field references a supported, versioned method schema and validator
that fixes assumptions, permitted queries, budget accounting, multiplicity or
sequential correction, and the eligibility calculation. Protocol registration
rejects an unsupported method or an unverifiable validity condition; evaluation
emits a machine-checkable budget certificate, and promotion independently
recomputes it. Until such a method is implemented and registered, adaptive
reuse is development-only and the only promotion-eligible paths are prospective
evidence or a finite family fixed before a one-time valid lockbox opening.

Protocol, candidate, and decision registration commands read an authored file
tracked at a clean `HEAD`. The resulting record binds that authoring path,
SHA-256, and source revision before embedding its exact-schema payload.
Normative numeric fields declare `value_origin: registered_choice`. Evaluation
and proposal records instead accept measured values only from manifest-bound
producer artifacts. Registration therefore preserves deliberate numeric
thresholds without turning them into retrospective measurements or unbound
numeric prose.

### Candidate registration

A candidate record fixes before evaluation:

- implementation record ID;
- model components and feature set;
- training and temporal protocol;
- calibration procedure;
- hyperparameter search space or fixed values;
- simulation mechanism when it differs from the incumbent;
- authoritative evaluation-protocol record ID.

An evaluation runner rejects an unregistered candidate or a candidate whose
digest differs from its registration. It also rejects candidate fields that
duplicate protocol-owned criteria.

### Promotion proposal

Research emits a proposal that binds the candidate, implementation, incumbent,
single-implementation evaluation records, exposure records, event fixtures,
and measured reports. It has no shipping authority and cannot update
`active_model.yaml`.

### Promotion transaction

Promotion uses two Git-visible transitions. First, the owner creates a decision
record containing the candidate, `promoted` or `rejected`, the reason, and the
first effective event, then commits it. That clean commit is the approval
revision. A rejected decision is terminal: `cli_promote` refuses it without
writing. For a `promoted` decision, `cli_promote` creates a promotion record and
changes the active pointer. The promotion record binds the decision record and
approval revision and verifies:

- current `HEAD` equals the approval revision;
- an explicitly `promoted` committed decision;
- candidate, proposal, decision, and evaluation records binding the same
  implementation ID;
- source closure, dependency lock, runtime, scrubbed environment, access
  boundary, entry point, and conformance output matching that implementation
  record;
- candidate registration before evaluation;
- exact evaluation-protocol identity and digest;
- complete eligible fold set;
- ready prerequisite reports;
- promotion-eligible exposure chains and an unexceeded registered query or
  comparison budget;
- criteria from the bound evaluation protocol;
- absence of diagnostic or blocked evidence;
- an effective event after every evaluated event.

Before writing, the command deterministically derives the expected promotion
record path and bytes, final pointer bytes, and fixed transaction-temp path from
the committed decision and approval revision. It accepts exactly two starting
states:

- `fresh`: the index and worktree are clean at the approval revision, the
  expected promotion record is absent, the active pointer equals its `HEAD`
  version or is absent in both places, and no transaction-temp file exists;
- `resumable`: there are no staged changes; the only changed or untracked paths
  are the expected promotion record, active pointer, and optional fixed temp
  path; the promotion record exactly equals the expected bytes; and either the
  pointer still equals its `HEAD` version with an absent or exact temp file, or
  the pointer equals the expected final bytes with no temp file.

Every other dirty state, byte mismatch, unexpected path, impossible transition,
or different `HEAD` fails for owner recovery. From an accepted state, the
command exclusive-creates a missing promotion record, writes and validates the
temporary pointer, and atomically replaces `config/active_model.yaml`. A
matching completed `resumable` state is an idempotent success.

On successful completion, the command asserts that the diff from the approval
revision contains exactly the expected promotion record and pointer bytes and
no temp file. Those two files are then committed together in a separate
activation commit. Shipping accepts them only when both exact files are tracked
at the current clean `HEAD`. Until that commit exists, the dirty tree is
non-shippable. The command never rewrites an existing promotion record.

`active_model.yaml` binds the candidate record ID, implementation record ID,
promotion record ID, and first effective event. Record IDs are already content
digests; no parallel mutable alias or duplicate digest field exists. Shipping
rejects a pointer whose promotion is missing, malformed, not yet effective, or
does not bind the same implementation through candidate, evaluation, decision,
and promotion.

The existing frozen TI 2026 gate lineage remains the explicit migration
exception. It is not retrospectively relabelled as an implementation record,
and no future candidate may use that exception.

Current D2, D3, D3b, D4, optimiser objectives, blocked diagnostics, and
unregistered reports cannot independently satisfy this future promotion
protocol.

## CLI authority boundaries

| Command | Reads | Writes | Forbidden capability |
|---|---|---|---|
| `cli_evidence_import` | Owner-supplied local capture and metadata | New evidence record | Network access |
| `cli_fixture_knowledge` | Current-at-cutoff evidence tips, source snapshot manifest, and availability witnesses | New knowledge bundle | Reading outcomes or exposing unfiltered or availability-unknown rows as promotion-eligible |
| `cli_fixture_outcome` | Post-event result snapshot plus availability and event-identity evidence | New outcome bundle | Mutating knowledge |
| `cli_implementation_register` | Clean executable source closure, lock, scrubbed runtime environment, access policy, and conformance fixture | New implementation record | Reading candidate measurements or outcomes |
| `cli_release` | Knowledge, active model and implementation, or frozen TI 2026 lineage | Run bundle and published forecast entry | Accepting arbitrary candidates or outcomes |
| `cli_score_forecast` | Published forecast and outcome | New score entry | Rewriting forecast |
| `cli_score_fold` | Research fold forecast, opened exposure record, and bound outcome | Fold score inside evaluation | Publishing forecast or score; creating an opening or loading outcome payload before one exists |
| `cli_protocol_register` | Authored protocol | New protocol record | Reading candidate measurements |
| `cli_candidate_register` | Authored registered specification and implementation record | New candidate record | Reading measured candidate results |
| `cli_exposure_register` | Authored event role, candidate family, protocol, and budget | New exposure reservation | Reading outcome content or digest |
| `cli_evaluate` | Candidate, implementation, protocol, exposure reservation, and chronological fixtures | Exposure transitions, evaluation bundle, and proposal | Writing promotion or active pointer; loading an outcome before recording its opening |
| `cli_series_integrity` | Event result maps | Integrity report | Inferring unregistered series identities |
| `cli_simulation_convergence` | Registered simulation plan | Convergence report | Changing shipping card |
| `cli_decision_register` | Owner-authored decision, proposal, and evaluation | New decision record | Updating active model |
| `cli_promote` | Committed decision, implementation, exposure chain, and registered evaluation evidence | Promotion record and active pointer | Fitting, scoring, choosing metrics, or choosing the decision |

The implementation enforces authority through narrow function signatures,
separate loaders for knowledge and outcomes, and import-boundary tests. It does
not rely on command documentation alone.

## Pre-TI release hardening

The pre-TI slice contains only operational corrections.

It is implemented as four dependency-ordered plans rather than one refactor:

1. freeze a manifest-bound oracle for current gate verdicts, card assignments,
   and card machine-readable output;
2. add offline evidence import, schemas, and pure reconciliation;
3. add side-effect-free checkout and declared-input preflight, then reorder
   release orchestration while proving the frozen output oracle is unchanged;
4. add CI after the preceding contracts are stable.

Each plan is independently reviewable and leaves the predictive output oracle
unchanged.

The second plan also audits empirical numbers in current config comments and
other touched prose. In particular, numeric annotations under the duration
model and tiebreak provenance either become exact references to manifest-owned
producer artifacts or lose the numeric prose. YAML values, registered gates,
and predictive behavior remain unchanged.

### Rules supersession and binding

- Add a superseded banner to the morning-state rules transcript.
- Convert the current rendered rules capture into a manifest-bound evidence
  record.
- Generate normalized factual fields from the captured text.
- Reconcile those fields with the shipping rules configuration.
- Ask the owner to repeat the rendered capture during near-lock verification,
  import the supplied local bytes offline, and stop on changed content.

### Checkout preflight

Keep `--source-revision` temporarily for runbook compatibility but require it to
equal resolved `HEAD`. Require no tracked or untracked worktree changes before
generation. Git preflight belongs to release orchestration, not the offline
historical bundle verifier.

### Fail-before-write ordering

Before creating a persistent processed store or run directory, release must:

1. resolve and validate the checkout;
2. validate evidence manifests and referenced digests;
3. reconcile rules, participants, roster identities, and draw state;
4. validate the raw snapshot manifest;
5. construct the complete declared-input set.

The processed store may then be rebuilt. Run output remains incomplete until
its manifest is written last, preserving the current interrupted-run contract.

### CI

Add a narrow CI workflow for Ruff, fast unit tests, provenance contracts, and a
deterministic miniature release. Run the complete unfiltered suite in the
required pre-release job and before every completion claim. A scheduled full
job may provide earlier warning but does not replace release verification.

## Post-TI dependency graph

Implementation order is:

```text
implementation, protocol, and exposure schemas
                         |
        register future evaluation and promotion protocol
                         |
                 fixture schemas
                  /            \
       historical ingest    integrity and convergence contracts
                  \            /
              rolling-origin evaluator
                         |
       map, series, tournament, and card reports
                         |
              registered candidate cycles
                         |
               explicit future promotion
```

Integrity and convergence contracts may be implemented against miniature
fixtures while historical ingestion runs. Historical ingest and the relevant
readiness contract must both complete before a dependent held-out report can
support promotion.

The first post-TI cycle builds the evaluation spine. The next candidate cycle
tests player-level partial pooling before hero features, then tier handling,
subpatch-aware temporal behavior, and marginal rating-uncertainty propagation.
Series-mechanism comparison follows only after series integrity is trustworthy.
Joint uncertainty and low-dimensional hero features come later.

### Error-analysis loop

Each event score emits drill-downs by team, forecast bucket, target tier,
fixture construction class, balance patch, roster evidence volume, rating
uncertainty, and assignment boundary where the data supports that grouping.
Small cells are shown rather than interpreted as stable effects.

An error-analysis finding cannot change an existing candidate. It becomes an
authored hypothesis in a new candidate registration. Every event whose outcome
informed that hypothesis is `development` for the new cycle, even when the new
candidate references an unchanged protocol. Those events remain in diagnostic
reports but cannot satisfy the new candidate's promotion threshold. A changed
temporal protocol or promotion criterion requires a new protocol record before
the candidate is evaluated. Forecast, outcome, score, exposure, and decision
records remain unchanged. This is the only path from an observed failure to a
model change; fresh promotion evidence follows the exposure policy above.

## Statistical corrections carried into the roadmap

### Calibration

The complete predictive candidate includes rating method, rating-to-logit
mapping, calibration procedure, and temporal fitting protocol. Calibration is
fit inside training data for each outer fold. Promotion compares complete
pipelines using held-out proper scores; it does not require an arbitrary raw
rating scale to beat a constant forecast without calibration.

### Series mechanisms

For an independent-map best-of-three, the series probability is
`3p^2 - 2p^3`. A positive shared series condition naturally moves the result
toward the underlying map probability rather than necessarily making it more
extreme. The roadmap therefore removes the claim that positive within-series
correlation explains an underconfident series model.

Registered candidates compare distinct mechanisms:

- symmetric direct series recalibration;
- a shared series-level condition;
- previous-map adaptation;
- side, selection-priority, and map-order effects;
- positive or negative residual dependence.

No flexible combined model is treated as proof of one mechanism.

### Roster cold start

The first roster-generalization candidate uses regularized player effects plus
an exact-roster residual. It preserves exact-five-player roster identity while
sharing evidence across transfers. Organisation effects, roles, coaches, hero
interactions, and richer synergy terms remain out of the first candidate.

### Rating uncertainty

The first uncertainty candidate draws one latent strength per team per simulated
tournament from marginal rating uncertainty and labels the independence
assumption. Later candidates may use history bootstrap refits or a joint dynamic
posterior. Point estimates and rating uncertainty remain distinct in reports.

## Failure behavior

Schema errors, unsafe paths, digest mismatches, factual reconciliation errors,
cutoff violations, authority violations, and attempts to overwrite complete
artifacts fail non-zero. They do not emit partial numeric results.

A valid diagnostic may deliberately emit `blocked` when a registered
prerequisite is unavailable. That report exits successfully only when the
blocked state itself is well-formed, contains stable reason codes, has
`shipping_effect: none`, and contains no results. Operational faults never
masquerade as blocked diagnostics.

An incomplete run directory remains identifiable by missing `manifest.json`.
Retry may replace that incomplete directory under the existing release
contract. Complete artifacts are never replaced.

## Operations and recovery

This is a single-maintainer local batch system. Compute, storage, and release
work remain repository-local; no service uptime or request-latency objective
applies. The operational deadline is the external prediction lock.

Near lock, any changed rules source, participant field, roster account set,
draw, checkout state, snapshot digest, or manifest digest triggers the runbook's
stop path. The owner resolves external ambiguity; the pipeline does not infer a
convenient replacement.

After an event, the exact published forecast is frozen before outcomes are
inspected. Outcome creation and scoring append new artifacts. A bad derivation
or source correction creates a new bundle and correction record; it never edits
the prior result.

### Multi-artifact transaction contract

Every command that publishes both a durable artifact and a registry or lineage
record implements one deterministic, idempotent transaction. From immutable
inputs it derives the final artifact identifier, final path, canonical manifest
bytes, link-record identifier and bytes, and fixed temporary path before
publishing either durable object. Its verifier recognizes only these states:

- `fresh`: neither final object nor temporary object exists;
- `prepared`: only the exact expected temporary artifact exists;
- `artifact_published`: the complete artifact and final manifest match expected
  bytes, while the link record is absent;
- `complete`: artifact and link record both match expected bytes and no
  temporary object remains.

The command validates all temporary and final bytes before transition,
publishes the complete artifact first, and exclusive-creates the link record
last. Retry resumes `prepared` or `artifact_published` and treats `complete` as
idempotent success. A link without its artifact, unexpected path, extra partial
file, duplicate registry tip, or any byte mismatch is a conflict requiring
owner recovery; the command neither overwrites nor guesses which object wins.
An artifact directory becomes published only when its manifest is written last
or it is atomically renamed from the fixed temporary path.

This contract applies at least to:

- release run bundle plus published-forecast registry entry;
- published score artifact plus score registry entry;
- single-implementation evaluation bundle plus proposal record;
- replacement outcome bundle plus its correction or supersession record.

The promotion transaction retains its stricter Git-visible state machine. The
generic contract does not make an uncommitted active-pointer change shippable.

Git and committed raw/evidence payloads are the backup and recovery boundary.
An incomplete generated run can be regenerated from its manifest-owned inputs.
Loss of an uncommitted external capture cannot be reconstructed honestly and
requires a new capture with a new retrieval time.

Data drift monitoring remains batch-oriented: roster continuity, evidence
volume, target tier, balance subpatch, source schema, series integrity, and
post-event score deltas. Alerts are release-blocking failures or committed
diagnostic reports, not a new notification service.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Rules or draw source changes near lock | Fresh rendered capture, supersession chain, exact reconciliation, and stop-before-write release behavior |
| Retrospective fixture silently uses later or stale knowledge | Unique current-at-cutoff evidence tips, evidence-backed negative observations, row source-availability classes, target-outcome isolation, and promotion eligibility derived from protocol |
| Few premium events create false certainty | Event-level deltas, event-level aggregation, explicit evidence class, and no automatic promotion |
| Repeated candidate cycles overfit visible events | Append-only exposure ledger; visible outcomes become development evidence; prospective evidence is the default promotion path |
| Bad source series identifiers contaminate series claims | Strict integrity report before scoring; inferred identifiers remain separate and opt-in |
| Adaptive Monte Carlo stopping understates uncertainty | Stopping-valid sequential uncertainty, registered simultaneous-coverage family, common random numbers, and blocked downstream reports |
| Shared-code change bypasses promotion | Content-addressed source closure, dependency and runtime identity, conformance output, and end-to-end implementation binding |
| Research result changes shipping state | Dedicated promotion command, exposure and import boundaries, exclusive records, and active-pointer byte-invariance tests |
| Crash leaves an artifact without its registry link | Deterministic multi-artifact states and idempotent artifact-first repair |
| Local Git history is rewritten | State the limitation; do not claim externally anchored immutability |
| Deadline pressure invites a model change | Pre-TI slice forbids predictive changes and preserves frozen gate lineage |

## Test evidence

Every added or changed test has a docstring naming one implementation mutation
it rejects. During implementation, that mutation is applied temporarily, the
focused test is observed failing for the intended reason, the mutation is
restored, and the test is observed passing. This applies to every changed test,
not only tests labelled critical.

Required fail-closed coverage includes:

- dirty checkout and supplied-revision mismatch before ingest or bundle writes;
- rules, field, roster, or draw mismatch before persistent writes;
- stale, forked, cyclic, cross-subject, or contradictory supersession graphs;
- `unpublished` draw claims without negative evidence valid through cutoff;
- knowledge schemas rejecting outcome paths and outcome-shaped fields;
- forecasting with the outcomes tree physically absent;
- training rows completing after cutoff;
- training rows lacking the witness required by their source-availability basis,
  and corrected bytes attempting to inherit an earlier witness;
- target-outcome access during forecast construction;
- fold-local candidate fitting and calibration;
- implementation changes to source closure, dependency lock, entry point,
  interpreter bytes, installed files, native libraries, host constraints,
  scrubbed environment, access boundary, or conformance output without a new
  implementation record;
- an undeclared repository-local import, dynamic code load, executable child,
  file input, or output-affecting environment read;
- fold, evaluation, proposal, decision, promotion, and active-pointer
  implementation-ID disagreement;
- outcome loading before an exposure opening is persisted;
- a viewed event being upgraded from development evidence or reused outside its
  candidate family or registered query budget;
- an unsupported or unverifiable reusable-holdout method being treated as
  promotion-eligible;
- interruption after exposure opening remaining conservatively exposed;
- outcome availability and event-identity mismatch;
- malformed, reused, null, tied, or overlong series;
- common-random-number coupling or stream mismatch;
- an ordinary repeatedly inspected fixed-sample interval being rejected as an
  adaptive stopping method;
- a malformed sequential certificate or convergence failure blocking
  tournament and card results;
- blocked reports containing no numeric results;
- diagnostic evidence being rejected by promotion;
- research evaluation leaving the active pointer byte-identical;
- scoring leaving the published forecast byte-identical;
- registry overwrite attempts;
- retry and conflict behavior for every registered multi-artifact transaction
  state, including artifact-without-link repair and link-without-artifact
  rejection;
- interrupted promotion resuming only from each exact registered state;
- promotion recovery rejecting staged, unrelated, or byte-mismatched changes;
- active pointers to missing, malformed, or future promotions, or to a
  promotion whose committed decision is absent or not `promoted`;
- existing frozen TI 2026 gate and card behavior remaining unchanged.

Final verification for every implementation slice is:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

The pre-TI release additionally verifies the generated bundle with
`ti26.cli_provenance verify-run`.

## Honest claim boundary

After the pre-TI slice, the project may claim stronger rules and checkout
provenance. It may not claim stronger prediction quality.

After the evaluation-spine slice, it may claim that candidates are compared by
a manifest-bound rolling-origin procedure, qualified by each fixture's evidence
and source-availability classes, exposure role, and the number of independent
events. It may not claim a candidate is better merely because a pooled average
is favorable or because a repeatedly reused development event crosses a
threshold.

After an explicit promotion, it may claim that the shipping incumbent changed
through the registered, auditable transaction and executes the same sealed
implementation that earned promotion. Research output alone never changes that
claim.

The naive strength ladder remains the card-decision incumbent until registered
held-out evidence shows a promoted simulation pipeline improves that decision
layer. Simulation may still provide distributions and sensitivity diagnostics
without receiving decision-value credit.

## Glossary

- **Evidence record:** manifest-bound capture of externally sourced facts.
- **Current evidence tip:** unique maximal applicable record for one subject at
  a cutoff after validating the full supersession graph.
- **Knowledge bundle:** complete input facts admissible at one forecast cutoff.
- **Outcome bundle:** post-event results and producer-derived truth with its own
  manifest.
- **Candidate:** preregistered complete predictive pipeline, including
  calibration and temporal fitting.
- **Implementation record:** content-addressed identity of executable source,
  dependency lock, runtime, entry point, and conformance output.
- **Exposure record:** append-only reservation, opening, consumption, or
  invalidation of an event outcome for a registered candidate cycle.
- **Incumbent:** model version currently authorized for future shipping runs.
- **Promotion proposal:** research output with no shipping authority.
- **Decision record:** explicit owner decision binding a proposal and its
  registered evaluation evidence.
- **Promotion record:** activation evidence binding one committed approved
  decision and its approval revision.
- **Active-model pointer:** versioned shipping reference to one promoted record.
- **Diagnostic:** valid measurement with `shipping_effect: none`.
- **Blocked report:** valid declaration that a registered prerequisite was not
  satisfied; it contains no numeric results.
- **Convergence certificate:** reproducible evidence that a stopping-valid
  sequential uncertainty method satisfied or failed its registered rule.

## Design references

These references motivate the boundary contracts; they do not introduce their
platforms as repository dependencies.

- [SLSA build provenance](https://slsa.dev/spec/v1.2/build-provenance) for
  binding source identity, resolved dependencies, and the produced artifact.
- [uv project lockfile](https://docs.astral.sh/uv/concepts/projects/layout/)
  for the repository's existing exact, cross-platform dependency resolution.
- [The reusable holdout](https://doi.org/10.1126/science.aaa9375) for the risk of
  adaptive reuse of measured holdout outcomes.
- [Feast point-in-time joins](https://docs.feast.dev/getting-started/concepts/point-in-time-joins)
  for distinguishing event time from source availability in historical data.
- [Time-uniform confidence sequences](https://doi.org/10.1214/20-AOS1991) for
  uncertainty guarantees that remain valid under repeated inspection and
  stopping.

## Related repository documents

- `docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md`
- `docs/superpowers/specs/2026-08-04-ti26-reproducible-forecast-design.md`
- `docs/ti26/near-lock-runbook.md`
- `docs/ti26/2026-08-08-known-weaknesses.md`
- `docs/ti26/2026-08-08-strengthening-plan.md`
- `docs/ti26/2026-08-08-ti2025-series-scoring-spec.md`
