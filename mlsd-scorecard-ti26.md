*Reviewed with [ml-system-design-review](https://github.com/ML-SystemDesign/MLSystemDesign/tree/main/skills) · [ML System Design](https://arseny.info/ml_design_book) by Kravchenko and Babushkin*

## ML System Design Scorecard: ti26

**Verdict:** approve (avg 3.01) · retrospective research release, tournament forecasting, low direct decision stakes with material risk of overstating scientific evidence

**Critical findings:** none under the design-review scope; the unresolved third-party rights hold (see Top fix) is a release blocker, not a design defect.

**Author verdict:** Through Valerii and Arseny's rubric, this is a disciplined, auditable research pipeline whose temporal validation, candid postmortems, and now-versioned replay tooling exceed its evidence for repeat-event predictive performance.

| Dimension | Grade | Why |
|---|---|---|
| Problem framing, goals & antigoals | A- | The rewritten README and release plan now carry the retrospective scope, antigoals, and a tradeoffs/MVP-target framing the prior review found missing. |
| Cost of mistakes & risk | B+ | A recorded asymmetric-cost publication decision names its second-order consequence (no per-file hold under full-history publication) and pairs it with a concrete takedown/incident mitigation path. |
| Prior work, build/buy & baselines | A- | Meaningful constant, rating, random-card, naive, and external-card comparisons; unchanged since no baseline code or report moved. |
| Metrics, loss & measurement | B- | Unchanged: the series-score caveat is now stated more visibly, but the measurement design behind it — splits, clustering treatment, CI/MDE reporting — did not change. |
| Data, labels & features | C- | Strong source lineage and roster identity; limited target-tier coverage and uneven roster evidence; unchanged. |
| Validation & leakage | B+ | Hard temporal cutoffs and in-fold calibration; target-population generalization remains weak; unchanged. |
| Error analysis | B | Group and playoff diagnostics characterize realized errors within the same tournament while refusing to infer repeat-event skill; unchanged. |
| Training pipeline & reproducibility | B+ | A new, tested one-command postmortem replay binds `uv.lock` and producer/tooling bytes; CI still checks the bindings only, not the replay itself. |
| Serving, integration & release | B- | Pinned, network-isolated hosted CI is independently confirmed green on an ancestor commit (re-observation on the merge commit pending); a merge-method constraint and a post-publication incident plan now exist, but the version tag and flip settings are still open. |
| Monitoring, ownership & maintenance | B- | A named owner, support scope, two escalation channels, and a minimal incident runbook now exist; there is still no threshold or proactive detection, only an external-report trigger. |

**Top fix:** Close the third-party rights hold before publication ([data sources, publication decision](docs/data-sources.md#publication-decision), deadline 2026-10-11) — OpenDota permission is still pending, and the owner must approve both analyses in `predictions-from-llms/` (or switch to a fresh-history repository) before the deadline, because full-history publication leaves no per-file hold.

**Takeaway:** Reproducibility makes a forecast inspectable; repeated independent evaluation is still needed to establish predictive skill.

Evidence mode: docs and repository, including later TI postmortems, a full git diff of every rubric-relevant path across the two reviewed revisions, one independently re-executed mutation check, and one read-only hosted-CI status query. External LLM cards are frozen inputs, so a live LLM/RAG/agent-system row is inapplicable. Grades are reviewer judgments, not empirical measurements; their arithmetic, reviewed revision, file hashes, checks, and limits are recorded in the [re-review evidence](docs/audits/2026-09-27-release-design-rereview.json), which supersedes the [prior review evidence](docs/audits/2026-09-26-public-release-review.json) (reviewed an earlier revision, before the public-release documentation existed). Findings and the staged remedy are in the [release proposal](docs/public-release-plan.md) and the [completion plan](docs/superpowers/plans/2026-09-27-public-release-completion.md). No implementation or publication approval is implied.
