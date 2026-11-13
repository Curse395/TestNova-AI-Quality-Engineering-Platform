# TestNova AI Phase 6 — Workflow UI/API Integration

## Status

**Phase 6: PARTIAL.** The workflow UI/API contracts, result presentation, and
project-context navigation are implemented and covered by isolated automated
tests plus a browser smoke test against a temporary mocked HTTP API. A
successful browser-to-real-backend workflow using PostgreSQL/pgvector remains
unverified; Supabase and configured external databases were not accessed.

## Four target checklist

| # | Target | Status | Evidence and limitation |
|---:|---|---|---|
| 1 | Workflow runs and statuses | **COMPLETE** | Workflow list/detail uses the existing project-scoped API; run creation/start/completion/update timestamps are shown; known backend run/task/attempt statuses are mapped without inventing `cancelled`; active statuses drive polling; project-scoped stale-response guards remain in place. Unit tests cover active/terminal status rules and project guards; isolated backend tests cover run/list/detail contracts; mocked-browser smoke verified run timestamps and switching to a second project without retaining the first project's results. |
| 2 | Task results, failures, and diagnostics | **COMPLETE** | Task/dependency/attempt order, timestamps, retry attempts, outputs, validation/reviewer findings, and safe failure diagnostics are rendered from the existing payload. Stack details and common secret/token forms are withheld or redacted in displayed diagnostic/output JSON. Focused API test verifies stable task/attempt order and persisted result payload. Frontend tests cover status, diagnostic redaction, and task-result data; browser smoke exercised an attempt history and task output. |
| 3 | Generated test cases and evidence | **COMPLETE** | Workflow results display title, description, category, priority, severity, preconditions, steps, expected result, review status, linked requirement definitions/keys, cited document name/type/chunk, available source location, and cited excerpt. Chunk-ID-only data is explicitly identified as lacking source metadata. Browser smoke verified these fields and the link to Test Cases. The existing Test Cases API remains the source of saved cases and full evidence. |
| 4 | Complete frontend-to-backend workflow integration | **PARTIAL** | Frontend methods use the existing routes and standard authenticated API client; existing project ownership checks remain unchanged. The actual frontend was exercised against a temporary mocked API and backend API/authorization contracts ran against per-test SQLite fixtures. No successful live browser-to-backend workflow was run: SQLite cannot execute pgvector's `<=>`, and this machine has no accessible local PostgreSQL/pgvector server. No Supabase or external database verification is claimed. |

## Existing implementation reused

- `backend/app/api/workflows.py` and `backend/app/services/workflow_service.py`
  provide project-scoped run creation, history/detail/task/resume endpoints,
  persisted task attempts, orchestration, and final outputs.
- `backend/app/schemas/workflow_schema.py` defines workflow request validation.
- `backend/app/models/workflow_run.py`,
  `backend/app/models/workflow_task.py`, and
  `backend/app/models/workflow_task_attempt.py` define the persisted status and
  timestamp contracts.
- `frontend/src/api/workflows.js` already calls the workflow routes through the
  shared authenticated API client.
- `backend/app/api/test_cases.py` already serializes saved cases with
  requirement links and project-scoped evidence source metadata/excerpts.
- Routes and sidebar links already connect Projects, Test Cases, Workflows, and
  Dashboard.

## Confirmed gaps fixed

- Run rows showed creation time only despite the API returning start,
  completion, and update times.
- Unknown statuses visually fell back to the pending style, which could
  misrepresent an API value; only statuses supported by backend contracts now
  receive known labels/styles. `cancelled` is not a backend workflow status.
- Task ordering and attempt ordering in detail responses depended on ORM
  relationship order.
- Task output and attempt output were rendered as raw JSON, and error objects
  could fall back to raw JSON text. Displayed diagnostics now redact common
  credential forms and withhold stack/technical trace details.
- Workflow-generated case cards omitted severity, preconditions, steps,
  expected result, linked requirements, and full citation context.
- The workflow page had no direct Test Cases link; the Test Cases page ignored
  a requested project ID. The link now carries `project_id`, and the page
  selects that project only if it is in the user's fetched project list.
- Loading details, project-load failures, and workflow-history failures now
  have distinct visible states; requests and errors from a previously selected
  project are ignored.
- Workflow result rendering now falls back to persisted generation-task output
  when the final-output convenience result is absent.

## Changes in this pass

- `backend/app/api/workflows.py`: return tasks in ID/execution order and task
  attempts in attempt-number order for detail and task-history payloads.
- `backend/tests/test_workflow_orchestration.py`: verify run timestamps,
  deterministic task/attempt ordering, and case/requirement/evidence payload
  serialization using the isolated fixture.
- `frontend/src/pages/WorkflowsPage.jsx`: show all available run dates; expose
  loading/error states for projects, history, and details; preserve project
  scoping during asynchronous operations; render complete generated test-case
  details and citations; add project-preserving navigation; avoid raw
  diagnostic/output exposure.
- `frontend/src/pages/workflowPresentation.js`: centralize backend status
  mapping, active/terminal rules, generated-case/evidence extraction, project
  response guards, project-selection validation, and safe diagnostic/output
  formatting.
- `frontend/src/pages/TestCasesPage.jsx`: honor and maintain a validated
  `project_id` query parameter.
- `frontend/tests/workflowPresentation.test.js`,
  `frontend/tests/errorMessage.test.js`, and `frontend/package.json`: add
  built-in Node regression tests for project context and API error messages,
  plus an `npm test` command.
- `docs/phase6-completion.md`: record current status and verification.

## Verification

Focused checks run for this pass:

- `python -m pytest -q tests/test_workflow_orchestration.py tests/test_workflow_review_regeneration_e2e.py`
  — **67 passed, 2 warnings**. `backend/conftest.py` overrides
  `DATABASE_URL` with a unique temporary SQLite file before application imports;
  workflow fixtures also create their own temporary SQLite databases. The
  review/regeneration tests stub retrieval and mock LLM calls. These tests did
  not connect to Supabase or another configured database.
- `npm test` — **10 passed, 0 failed**.
- `npm run lint` — **passed**.
- `npm run build` — **passed**; Vite emitted its non-blocking advisory for a
  JavaScript bundle over 500 kB.
- `python -m compileall -q app tests` — **passed**.
- `git diff --check` — **passed**; Git printed line-ending warnings for
  `frontend/package.json` and `frontend/src/App.jsx`.
- Browser smoke (not a committed browser-test suite): the frontend used its
  real API client against a temporary local mocked HTTP API. It rendered run
  timestamps, attempt history, generated case severity/preconditions/steps,
  requirement traceability, cited document/source location/excerpt, and
  navigated to `/test-cases?project_id=12`. Switching to project 13 preserved
  the query context and showed empty Test Cases and Workflow history states.
  The smoke test did not execute a backend workflow or contact an AI provider.

The full backend suite was not rerun in this pass; only the focused, verified
isolated workflow suites above were run. Real-provider tests and live database
tests were not run.

## Remaining limitations and safety

- A previous interactive run against isolated SQLite failed in
  `RetrievalService` because pgvector's PostgreSQL-only `<=>` operator is not
  supported by SQLite. Retrieval semantics were not changed.
- A prior environment inspection found no PostgreSQL client/server executable,
  PostgreSQL service/process, or listener on port 5432; Docker was installed
  but its local engine was unavailable. Consequently, a separate local
  PostgreSQL/pgvector database and a successful real backend workflow could not
  be verified.
- The browser smoke uses mocked API responses and does not prove that a
  successful workflow executes on Supabase or any PostgreSQL deployment.
- Workflow background execution remains in-process FastAPI background work;
  durable distributed queue behavior is outside this integration pass.
- No Supabase/external database connection, migration, schema initialization,
  or database cleanup was performed. `.env` was not inspected or modified. No
  changes were staged, committed, or pushed.
