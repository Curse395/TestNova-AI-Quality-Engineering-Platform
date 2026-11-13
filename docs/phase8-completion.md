# Phase 8 — Dashboard and Analytics Improvements

## Stage status

| Stage | Status | Implementation |
|---|---|---|
| 1 — Dashboard and analytics foundation | Complete | Corrected dashboard metric definitions, unavailable-value handling, chart labels, and synthetic chart fallback behavior. |
| 2 — Quality analytics | Complete | Added owner-scoped test-case statistics, requirement traceability, execution summaries, and UTC-bucketed execution trends. |
| 3 — Intelligence and monitoring | Complete | Added persisted risk evidence, bounded workflow snapshots, and explicitly requested evidence-validated AI quality summaries. |
| 4 — Release readiness and final verification | Complete | Added a deterministic project-level release assessment and a release-readiness dashboard that composes Stages 1–3 evidence. |

## Stage 4 implementation

`GET /analytics/release-readiness/{project_id}` returns the deterministic
assessment, test-case and requirement metrics, lifetime execution statistics,
recent execution activity and time range, daily execution trends, risk evidence,
workflow snapshots, outstanding concerns, and limitations. The route uses the
existing authenticated project ownership path and makes no schema changes.

Assessment states are `blocked`, `insufficient_evidence`,
`attention_required`, and `ready_for_review`. Failed/error execution runs are
observed blockers. Missing core data, no execution history, no determinate
passed/failed runs, no approved cases, or no explicit requirements produce
insufficient evidence unless a blocker takes precedence. Unresolved
approved-case traceability, unapproved cases, high/critical AI-assessed risks,
workflow failures, or indeterminate execution statuses require attention.
Ready for review means only that the configured review checks found no
blocker or medium/high concern; it is not release approval or production
readiness. The full rules and edge-case behavior are in
[architecture.md](./architecture.md).

The UI is exposed at `/release-readiness`. Its optional AI-generated context
uses the existing quality-summary endpoint, displays source evidence IDs and
limitations, and never changes the deterministic assessment.

## Verification boundaries

Stage 4 automated checks use offline unit tests and frontend static checks.
They do not access the configured database, apply migrations, start the
application, or make live provider calls. These checks do not certify
production behavior, database-schema parity, or semantic correctness of
provider-generated text. Consult the current implementation report for the
exact commands and results from the delivery environment.
