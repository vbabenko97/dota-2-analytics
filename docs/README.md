# Documentation index

## Current guides

[Overview](../README.md), [reproduction](reproduce.md), [data rights](data-sources.md), [contributing](../CONTRIBUTING.md), [release checklist](release-checklist.md), and [release notes](release-notes.md).

The [public release plan](public-release-plan.md) is the approved implementation scope; its original review status is historical. The [ML scorecard](../mlsd-scorecard-ti26.md) grades design, not publication clearance.

## Research evidence

[Known weaknesses](ti26/2026-08-08-known-weaknesses.md) describes historical validation limits. [Strengthening plan](ti26/2026-08-08-strengthening-plan.md) proposes future research. [Fetched rules](ti26/2026-08-08-ti2026-rules-fetched.md) and [format provenance](ti26/2026-08-08-published-format-rules.md) distinguish evidence from assumptions. The [near-lock runbook](ti26/near-lock-runbook.md) is historical guidance, not a request to rerun frozen decisions.

The [audit archive](audits/) and [correction register](audits/2026-08-04-correction-register.md) retain corrections. Historical references to ignored `gpt-pro-output.md` identify unavailable local review context; that private file is not public evidence. The [external audit](audits/2026-08-04-external-audit-of-d0221dc.md) is verbatim; its absolute local-path links do not resolve outside the author's machine.

## Specifications

| Document | Status |
|---|---|
| [Forecast design](superpowers/specs/2026-08-01-ti2026-forecast-design.md) | Historical; core forecasting implemented. |
| [Reproducible forecast](superpowers/specs/2026-08-04-ti26-reproducible-forecast-design.md) | Historical; bounded provenance helpers implemented. |
| [Three-plane system](superpowers/specs/2026-08-09-three-plane-forecasting-system-design.md) | Planned architecture; evidence import and oracle partially realize it. Full registry/preflight remains absent. |
| [Group postmortem](superpowers/specs/2026-08-16-group-card-postmortem.md) | Implemented historical diagnostic registration. |
| [Playoff forecast](superpowers/specs/2026-08-16-ti2026-playoff-bracket-prediction.md) | Implemented historical forecast; recorded registration deviations preserved. |
| [Playoff comparison](superpowers/specs/2026-08-17-playoff-card-comparison.md) | Implemented historical diagnostic. |
| [Playoff postmortem](superpowers/specs/2026-08-23-playoff-card-postmortem.md) | Implemented historical diagnostic registration. |

## Implementation plans

The [plan archive](superpowers/plans/) records intent, not acceptance evidence. Forecast generation, ingestion/ratings, gates/D4, stable identity, and provenance describe implemented foundations. Evidence import and the frozen-output oracle have implementations. The pre-TI hardening index remains partial; release preflight/orchestration remains planned. The old narrow-CI proposal was not implemented as written; this release's [offline CI](../.github/workflows/offline-ci.yml) uses existing coverage.
