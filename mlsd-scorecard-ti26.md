*Reviewed with [ml-system-design-review](https://github.com/ML-SystemDesign/MLSystemDesign/tree/main/skills) · [ML System Design](https://arseny.info/ml_design_book) by Kravchenko and Babushkin*

## ML System Design Scorecard: ti26

**Verdict:** approve with concerns (avg 2.77) · retrospective research release, tournament forecasting, low direct decision stakes with material risk of overstating scientific evidence

**Critical findings:** none for the stated retrospective scope; public release still requires the rights, documentation, provenance, and CI work in the [release proposal](docs/public-release-plan.md).

**Author verdict:** Through Valerii and Arseny's rubric, this is a disciplined, auditable research pipeline whose temporal validation and candid postmortems exceed its evidence for repeat-event predictive performance.

| Dimension | Grade | Why |
|---|---|---|
| Problem framing, goals & antigoals | B+ | Fixed decision artifact and clear constraints; public narrative needs the completed retrospective scope. |
| Cost of mistakes & risk | B | Low direct stakes and strong internal safeguards; target-population and claim risks need prominent treatment. |
| Prior work, build/buy & baselines | A- | Meaningful constant, rating, random-card, naive, and external-card comparisons. |
| Metrics, loss & measurement | B- | Proper scores and clustered inference; headline series inference and conditional marginals need qualification. |
| Data, labels & features | C- | Strong source lineage and roster identity; limited target-tier coverage and uneven roster evidence. |
| Validation & leakage | B+ | Hard temporal cutoffs and in-fold calibration; target-population generalization remains weak. |
| Error analysis | B | Group and playoff diagnostics characterize realized errors within the same tournament while refusing to infer repeat-event skill. |
| Training pipeline & reproducibility | B- | Frozen bundles verify and post-group replay succeeds; public recipes and lock/postmortem bindings remain incomplete. |
| Serving, integration & release | C | Offline artifacts fit the purpose; public CI and release packaging are incomplete. Online serving is inapplicable. |
| Monitoring, ownership & maintenance | C+ | Strong historical audit trail; public ownership, support policy, and automated checks are thin. |

**Top fix:** Publish an artifact index with a verified snapshot-to-store-to-report recipe and explicit limits on what each verification step proves.

**Takeaway:** Reproducibility makes a forecast inspectable; repeated independent evaluation is still needed to establish predictive skill.

Evidence mode: docs and repository, including later TI postmortems. External LLM cards are frozen inputs, so a live LLM/RAG/agent-system row is inapplicable. Grades are reviewer judgments, not empirical measurements; their arithmetic, reviewed revision, file hashes, checks, and limits are recorded in the [review evidence](docs/audits/2026-09-26-public-release-review.json). Findings and the staged remedy are in the [release proposal](docs/public-release-plan.md). No implementation or publication approval is implied.
