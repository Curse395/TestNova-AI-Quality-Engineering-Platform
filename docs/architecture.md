# TestNova AI architecture

## System overview

TestNova is a browser-based quality-engineering application. A React single-page
app communicates over HTTP with a FastAPI service. The service uses synchronous
SQLAlchemy sessions to read and write a PostgreSQL-compatible database, including
pgvector for document embeddings. Uploaded files are stored on the backend
filesystem; they are not stored in the database or an object-storage service.

The backend is organized into API routers, Pydantic schemas, services, agents,
SQLAlchemy models, and shared configuration/security modules:

- `frontend/src/pages/` contains the routed dashboard, projects, upload,
  analytics, assistant, workflow, and authentication views. `frontend/src/api/` contains
  Axios calls to the backend.
- `backend/app/api/` defines HTTP endpoints and translates service outcomes
  into HTTP responses.
- `backend/app/schemas/` validates request payloads and selected response data.
- `backend/app/services/` implements database workflows, ingestion, retrieval,
  analytics, generation, evaluation, and execution.
- `backend/app/agents/` contains agent implementations and a small in-process
  task router.
- `backend/app/models/` defines the SQLAlchemy tables and relationships.

## Frontend and API integration

The frontend uses React, React Router, Axios, and Vite. Its API base URL is
`VITE_API_BASE_URL`, falling back to `http://localhost:8000`. The Axios request
interceptor adds the locally stored access token; a 401 removes the token and
dispatches an application event that returns protected routes to sign-in.
`RequireAuth` checks token presence in the browser, while backend endpoints
perform the actual authentication and authorization checks.

The main routed workflows are:

- **Authentication:** `POST /auth/register` and `POST /auth/login`.
- **Projects:** `GET/POST /projects/`, and `DELETE /projects/{project_id}`.
- **Upload:** `POST /uploads/`, `GET /uploads/project/{project_id}`,
  `POST /documents/{document_id}/process`, and
  `POST /embeddings/regenerate`.
- **Analytics:** `GET /analytics/overview/{project_id}`,
  `GET /analytics/documents/{project_id}`,
  `GET /analytics/test-cases/{project_id}`,
  `GET /analytics/coverage/{project_id}`,
  `GET /analytics/executions/{project_id}`, and
  `GET /analytics/execution-trends/{project_id}`,
  `GET /analytics/risks/{project_id}`,
  `GET /analytics/workflows/{project_id}`,
  `POST /analytics/quality-summary/{project_id}`, and
  `GET /analytics/release-readiness/{project_id}`.
- **Dashboard:** `GET /dashboard/` and `GET /dashboard/insights`.
- **Assistant:** chat session and chat endpoints under `/chat`.
- **QA workflows:** workflow start, history, task detail, and resume endpoints
  under `/projects/{project_id}/workflows`.

The project, document, analytics, and dashboard pages consume these live
endpoints. Sidebar navigation is configuration, not sample data. Dashboard
metrics report document, chunk, and embedding counts and their separate
coverage ratios; they are not test-execution or production-release
measurements. Coverage is unavailable when its denominator is empty. Test
generation impact fields are currently returned as unavailable rather than
presenting formula-generated values as measured results.

Quality analytics aggregate persisted test cases, requirement links, and
execution runs for an owner-authorized project. Test-case distributions keep
unexpected, missing, and blank values separate. Requirement links measure
traceability, not completeness of testing; the primary traceability rate counts
explicit requirements linked to at least one approved case, while the
secondary rate includes links to any case. Execution summaries count runs
(including retries/repeats), classify missing/blank/unknown statuses separately,
and report duration statistics only for finite, non-negative values. Execution
trend queries use UTC timestamps and half-open `[from, to)` ranges. Trends
default to the trailing 30 days with daily buckets; supported buckets are day,
Monday-start week, and calendar month. Explicit ranges are limited to 366 days.

Stage 3 project risk analytics reuse persisted change-risk workflow-task outputs
and persisted execution runs. Change-impact risks are explicitly marked
AI-inferred and use the persisted agent severity label without exposing its
heuristic risk score; failed/error execution totals are observed facts with
unclassified severity. The risk endpoint reads at most the latest 100 change
risk tasks and attaches at most 20 failed/error run references. The risk-task
window can be incomplete when older records are omitted. The endpoint returns
at most 100 prioritized risk records while distribution totals cover all
findings in the queried task window. AI summaries include at most 30 of those
findings to bound provider input size.

The workflow monitoring endpoint returns at most 100 owner-scoped persisted
workflow snapshots (20 by default), including ordered task and attempt status,
timestamps, durations, retry counts, and sanitized diagnostics. It does not
provide a live event stream or progress percentage. Inputs, prompts, model
outputs, and credentials are not included in this monitoring response.
Plan order follows task creation; observed execution order follows persisted
start timestamps, and concurrently running tasks may overlap.

The AI quality-summary endpoint is an explicit POST operation. It aggregates
existing quality analytics and persisted risk evidence, sends only those
aggregates to the provider-neutral LLM service, and validates the JSON against
a Pydantic schema with evidence-reference checks. Valid summaries are cached
in a bounded process-local LRU by evidence fingerprint; cache state is not
shared between workers and is lost on restart. The summary distinguishes
observations from interpretation and cannot make release-readiness claims.
Its execution trend input covers the last 30 complete UTC days to keep the
evidence fingerprint stable within a day.
Schema and evidence-ID validation do not guarantee that each generated
statement is semantically entailed by its cited evidence; human review remains
appropriate before relying on generated interpretations.

The project-level release-readiness endpoint composes Stage 2 quality metrics
and Stage 3 risk and workflow evidence; it does not duplicate their aggregation
rules. Its response includes test-case distributions, explicit/inferred
requirement traceability, lifetime execution summaries, a trailing 30-day UTC
execution trend, up to 10 recent execution runs, risk findings, and up to 20
recent persisted workflow snapshots. Execution time bounds are derived from
persisted run timestamps. Workflow counts describe only the bounded snapshot.
Missing metric fields remain unavailable and are not converted to zero.

The deterministic release assessment follows these ordered rules:

1. **Blocked:** at least one persisted execution run is classified as failed
   or error. This rule takes precedence even if other evidence is missing.
2. **Insufficient evidence:** a required analytics source or required metric is
   unavailable; there are no execution runs; runs exist but none have a
   recognized passed/failed status; there are no approved test cases; or there
   are no explicit requirements. Missing evidence is not a successful result.
3. **Attention required:** no higher-priority state applies, but a relevant
   concern remains, including explicit requirements without approved-case
   links, draft/rejected cases, high/critical AI-assessed risks, bounded risk
   history, unavailable persisted risk evidence, failed/partial recent
   workflows, or skipped/unknown/missing/blank execution statuses.
4. **Ready for review:** the required evidence exists and no blocker or
   medium/high attention condition is present. This is a review handoff, not a
   release approval, production-readiness claim, probability, or score.

Observed failed/error execution outcomes are blockers. Risk severity is shown
as an AI-assessed category and never translated into a numerical probability.
Workflow failures are operational concerns, not test-execution failures.
Requirement traceability uses explicit requirements as its denominator;
inferred requirements are shown separately, and links do not establish that a
requirement is fully or adequately tested. Pass rate is
`passed / (passed + failed)` and remains unavailable when that denominator is
zero. Duration statistics use only valid persisted values, preserving
unavailable counts separately. Concern records include source, evidence IDs
where available, explanation, attention level, and a suggested next action.

The optional AI-generated quality context reuses the existing explicit
quality-summary operation. It retains its evidence references and limitations
and cannot override the deterministic assessment. Both the deterministic
assessment and the AI text require human review; no live-provider behavior is
certified by offline tests.

## API, service, and persistence layers

FastAPI routers are assembled in `backend/app/main.py`; exception handlers
provide a common error envelope for HTTP, validation, database, and unexpected
errors. Routers call services, which query or update models through a request-
scoped SQLAlchemy `Session` from `app.database.connection`.

The principal model relationships are:

- A `User` owns one or more `Organization` records; an organization has
  projects; a project has documents and project-activity records.
- A `Document` has `DocumentChunk` rows; each chunk may have one
  `DocumentEmbedding` vector.
- A project has generated `TestCase` records and `TestCaseGenerationRun`
  history. A test case can link to evidence rows that reference a document and
  chunk.
- `TestExecutionRun` records API execution results and references a project,
  test case, and executing user.
- `WorkflowRun` stores project-scoped workflow inputs, status and final output;
  `WorkflowTask` stores agent task states, and `WorkflowTaskAttempt` records
  preserve execution history. Active attempt records are updated as work
  proceeds; interrupted work may reuse the same attempt record for idempotent
  recovery. Generation runs reference a workflow and generation attempt number.
- `ChatSession` groups `ChatHistory` messages for a user and project.
- `SemanticCache` is defined in metadata but has no active service or request
  path in the current application.

The model metadata currently defines tables for users, organizations, projects,
documents, document chunks, document embeddings, project activity, test cases,
test-case generation runs, test-case evidence, test execution runs, chat
sessions, chat history, semantic cache, workflow runs, workflow tasks, and task
attempt history. Important uniqueness/check rules
include unique user email, one embedding per chunk, unique test-case evidence
per case/chunk, and test-case category, priority, and review-status checks.
Model-declared indexes also cover commonly queried project, run, and timestamp
columns. These are model facts, not proof that every deployed database contains
the corresponding tables, indexes, or constraints.

Security/reliability implementation status, rate-limit policy, and backup/
recovery procedures are documented in
[phase9-security-reliability.md](./phase9-security-reliability.md).

Several project-scoped services verify that the authenticated user owns the
project's organization before returning data. This is an owner-based access
model; organization membership, team roles, and shared-project grants are not
implemented.

## Authentication and authorization

Registration hashes passwords with Passlib's `bcrypt_sha256` scheme; existing
`bcrypt` hashes remain verifiable. Passwords are never returned or included in
tokens. Login uses the same generic invalid-credentials response for unknown
accounts and incorrect passwords. `UserCreate` accepts no role or owner fields.

Login issues a 24-hour HS256 access token signed with the required
`JWT_SECRET_KEY` setting. Configuration requires at least 32 characters and
rejects low-character-variety keys; the key value must be provided through the
existing settings mechanism.
The verifier pins the accepted algorithm to HS256 and requires `sub`, `user_id`,
`iat`, `exp`, and `token_use=access`. The subject and numeric user ID must agree,
timestamps are validated, and the user is reloaded from the database for every
request. Missing, malformed, expired, wrong-purpose, or invalid-signature
tokens receive a 401 response with a Bearer challenge. Tokens issued before the
required access-token claims were added must be refreshed by signing in again.

`get_current_user` is the centralized authentication dependency. Project and
document authorization uses the shared `get_owned_project` and
`get_owned_document` queries, which scope through
`Project.organitzation_id -> Organization.id` and
`Organization.owner_id -> User.id`. Project creation, listing, updates, and
deletion are likewise limited to organizations owned by the authenticated
user. Child records such as documents, test cases, executions, workflows,
requirements, analytics, and retrieval are queried within that authorized
project. Foreign project and document IDs are returned as not found rather
than disclosing their existence. Quality-summary cache fingerprints include
the project ID, and retrieval is constrained to the authorized project.

The only currently supported role is the implicit workspace owner represented
by `Organization.owner_id`. Owners can create and manage projects and use
project-scoped features in their own organization. There are no membership,
invitation, guest, administrator, or role-assignment models/endpoints; those
roles are denied by absence of a grant rather than inferred from request data.
Registration cannot assign an owner or role. The frontend has no role-based
permissions to enforce: its route guard and static navigation are usability
features only, while backend authentication and owner-scoped queries are the
security boundary. HTTP 401 responses clear the stored access token and route
to login; ordinary 403 responses remain API errors for the caller to display.
Auth and resource-intensive endpoints also use bounded per-process rate
limits. Each HTTP response includes a generated `X-Request-ID`; application
request logs use JSON and omit request bodies and query strings.

Known limitations: the data model has no `Company` entity or company
membership relation. An organization currently acts as a single-user workspace,
so owner-scoped isolation is enforced, but company-wide group boundaries and
shared-workspace membership cannot be represented or verified without a
schema change. The `User` model also has no active/disabled field, so account
deactivation cannot be persisted; authentication rejects an inactive user if
such a field is added later. These limits are not filled with inferred roles or
company relationships.

Login and registration return generic credential errors and are throttled
separately. There is no refresh-token or revocation mechanism: clearing the
browser token on logout does not invalidate a copied token before its 24-hour
expiry. The in-process limiter uses peer IP, returns 429 with `Retry-After`,
and is not a shared quota across workers or machines. It ignores forwarded-IP
headers unless a trusted proxy integration is explicitly deployed.

The application installs request-ID middleware and JSON logging. Logs include
request method/path/status/duration and safe error types, not request bodies,
prompts, document content, or query strings. Database exceptions return
generic client errors; request-scoped sessions roll back on exceptions and
close in all cases. These controls do not replace deployment log-retention
policies, shared rate-limit infrastructure, or provider monitoring.

## Document upload and processing

The upload endpoint requires a project ID and multipart file. It checks project
ownership, supported extension and compatible MIME type, nonempty content, and
the configured byte limit. It validates UTF-8/JSON content, a PDF signature,
and Office ZIP members with uncompressed-size/compression-ratio bounds. The
server selects the persisted MIME value from the extension. The file is
streamed to a temporary file and moved to a UUID-named path beneath
`backend/app/uploads/{project_id}`; the sanitized original name is retained
for display. Storage paths are resolved beneath the project upload directory
before processing or deletion. A `Document` row records its category, uploader,
processing status, content type, and storage path.

The frontend calls upload, processing, and embedding endpoints in sequence.
Processing claims the document as `processing`, extracts text, replaces chunks
in a database transaction, and records `completed` or `failed` status. Supported
extractors cover TXT, CSV, JSON, PDF text, DOCX text/tables, and XLSX workbook
sheets. PDF pages and workbook sheets are labeled in extracted text; DOCX
heading paragraphs retain heading markers. The uploader can classify a source
as a general document, requirements, bug report, test log, or technical
document. This is a label, not a source-specific parser or validation schema.

Chunking normalizes whitespace while retaining line boundaries, then groups
words using `CHUNK_SIZE_WORDS` and `CHUNK_OVERLAP_WORDS`. Chunk metadata
records filename, source type, file type, chunk index, parser/format details,
and any recognizable page, sheet, or heading context. Unavailable locations
are omitted rather than inferred.

## Embeddings, retrieval, and RAG

`EmbeddingService` uses the Sentence Transformers
`all-MiniLM-L6-v2` model and stores 384-dimensional vectors through pgvector.
Generation is scoped to a project and can be narrowed to selected documents or
chunks. Count-change snapshots feed the dashboard's knowledge-index history;
they are sparse activity records, not execution-performance measurements.

`RetrievalService` first checks project ownership and optional document/source
type scope, encodes the query with the same configured model used for document
vectors, and orders the project's matching-model embeddings by cosine distance.
The response preserves `score` as cosine distance for compatibility and also
returns explicit `distance` and `similarity` (`1 - distance`) fields.
`RETRIEVAL_TOP_K`, `RETRIEVAL_MAX_TOP_K`, and `RETRIEVAL_MIN_SIMILARITY`
control the result count and minimum similarity; the default threshold is
permissive and is not empirically calibrated. `retrieval_evaluation.py`
provides repeatable Precision@K, Recall@K, MRR, and source-attribution
calculations, but a representative labeled benchmark has not yet demonstrated
quality improvements. `ContextBuilderService` deduplicates chunks, retains
source identifiers, and assembles context under `CONTEXT_TOKEN_BUDGET` using a
four-characters-per-token estimate; it does not use a model tokenizer.

Chat combines retrieved context with recent session history and a prompt built
by `PromptBuilderService`, then calls the configured model through the central
`LLMService`. Provider adapters implement the shared `LLMProvider` contract:
Gemini uses the Google GenAI SDK, and Groq uses the Groq chat-completions SDK.
The provider factory centrally resolves provider names, configured models, and
provider credentials; Gemini remains the default. `LLMGenerationRequest`
validates provider/model identity, prompts, generation parameters, optional
structured-output MIME type, metadata, and a correlation ID. `LLMResponse`
carries generated text, finish reason, optional usage counts, provider metadata,
and a typed `LLMError` with a safe category and stage. Both adapters map their
provider-specific usage and error types into these common contracts. Groq maps
temperature, top-p, and maximum completion tokens (not Gemini's top-k); its
JSON mode is supported only for `application/json`.

Fallback is disabled by default. When `LLM_FALLBACK_ENABLED` is true, the
fallback provider must be explicitly configured with `LLM_FALLBACK_PROVIDER`;
`LLM_FALLBACK_MODEL` is optional and otherwise that provider's configured model
is used. A request makes at most one primary and one fallback attempt, with SDK
retries disabled for both providers. Rate limits and timeouts may fall back;
provider API errors fall back only when the adapter identifies them as transient.
Authentication, configuration, invalid-request, and successful-but-invalid
structured responses do not trigger fallback. When both attempts fail, the
primary failure stage is retained and both safe failure categories/stages are
recorded without provider payloads or credentials.
Both provider SDKs also receive `LLM_TIMEOUT_SECONDS` (60 seconds by default,
maximum 300); SDK retries remain disabled so configured fallback is bounded.

`validate_structured_output()` parses JSON and validates it against a supplied
Pydantic model without repairing invalid output; parse and schema failures use
the standardized error categories. Existing agents and services continue using
`generate_content()`, which translates the typed response to the legacy
dictionary shape at the compatibility boundary. Chat responses include source
document/chunk identifiers and are persisted in chat history when generation
succeeds.

### LLM telemetry and performance monitoring

The central `LLMRouter` records one telemetry event for each provider attempt,
including failed attempts before fallback. Events contain provider/model
attribution, UTC request/completion timestamps, monotonic-clock latency,
optional token usage, safe error category, correlation ID, and primary/final
provider and model. The same request-level fallback outcome is attached to each
attempt, while monitoring counts fallback requests once from the primary
attempt. Provider prompts, generated content, credentials, and raw provider
payloads are not included.

`JsonlLLMTelemetryService` preserves the in-memory service API and appends one
versioned JSONL event per request to `LLM_TELEMETRY_PATH` (default
`backend/data/llm_telemetry.jsonl`). Events contain only the existing safe
attempt contract and pricing metadata: no prompts, generated content, API keys,
authorization headers, or provider payloads. A fresh service reloads retained
active/rotated files, skips malformed or incomplete lines, and exposes the
read-only `get_persisted_telemetry_summary()` summary function. `get_summary()`
continues to provide request/attempt totals, success rates, average and median
latency, provider/model counts, fallback frequency/success, observed token
totals, and cost coverage. Missing observations remain `null`, distinct from
observed zero.

Writes are serialized between threads and service instances in one process,
and are appended as complete JSONL request events. Rotation is bounded by
`LLM_TELEMETRY_MAX_BYTES` (default 10 MiB) and
`LLM_TELEMETRY_BACKUP_COUNT` (default five files). POSIX files are created with
owner-only permissions where supported; Windows uses the parent directory's
ACL. This is local single-process persistence, not a distributed store:
multiple worker processes or machines do not share a lock or coordinate
rotation. Keep the supported deployment single-process, or use a separately
approved shared telemetry service before scaling workers. Retention means old
records are eventually discarded.

Telemetry collection and file-write failures are logged by exception type
only, isolated from generation, and never expose provider error details.

Pricing is optional and configured in `LLM_PRICING`, keyed by provider and
model, with a matching three-letter `LLM_PRICING_CURRENCY`. Each entry supplies
`input_per_million_tokens` and `output_per_million_tokens` rates in the
configured currency. Optionally set `LLM_PRICING_VERSION` to an administrator-
maintained verified price-sheet/version identifier. Every recorded attempt
stores the resolved rates, currency, version, and a deterministic SHA-256
fingerprint of the rates/currency (unless an explicit version label is set),
so the calculation can be reproduced later. The estimate is
`(input_tokens * input_rate + output_tokens * output_rate) / 1,000,000`;
there are no built-in prices. A per-attempt estimate is `null` unless both rates
and both token counts are available, and every returned cost is explicitly an
estimate. Aggregate cost reports coverage and whether it is partial; mixed
currencies are summarized separately rather than added together. Configure
prices only from an administrator-verified provider price sheet; no current
rates are assumed. To apply newly verified pricing to a historical benchmark,
the `benchmark_cli cost` command writes a separate sidecar with the source
report digest and exact rates/version; it never edits original measurements.
Primary and fallback usage are recorded as separate attempts and are not copied
onto an additional request-level usage record.

Telemetry is process-local and is not persistent or shared between workers.
Existing workflow task-attempt JSON fields record agent task output/errors, not
reliable per-provider call metrics, so they are not reused. Durable monitoring
would require an approved telemetry table (or equivalent external telemetry
store); this stage makes no schema changes and does not claim persistent
monitoring.

### LLM model evaluation and benchmarking

The provider-neutral benchmark harness lives in `backend/app/evaluation/` and
uses the versioned synthetic dataset at
`backend/evaluation_datasets/test_case_generation_v1.json`. It compares
explicitly selected provider/model pairs using identical prompt templates,
requirements, and evidence. The runner calls the central `LLMService` with
fallback disabled so a result is attributed to the selected model. The CLI
requires an explicit `--live` flag before it can make provider requests;
benchmark outputs are local JSON and Markdown files, not database records.

Evaluation reuses the production `GeneratedTestCase` Pydantic schema and
`validate_structured_output()` without repairing malformed model output.
Deterministic metrics cover schema validity, evidence-ID validity, annotated
evidence citation precision/recall, exact-match unsupported-behavior phrases,
lexical overlap between case text and cited evidence, requirement/category
coverage, and a usefulness proxy based on action/result
length, testable step structure, evidence-token overlap, coverage, and
redundancy similarity. These lexical metrics do not prove semantic entailment.
Subjective relevance, realism, clarity, and semantic support require human
review and are not represented as automated scores.

Per-attempt latency and available token usage are taken from the Stage 4
telemetry sink; end-to-end request latency is measured by the runner. Cost is
estimated only from explicit model-specific input/output prices and an explicit
currency configuration. Missing token or pricing data remains unknown.
Mocked runs are marked as such and do not report latency or cost as measured
provider metrics. Comparison reports require the same dataset content/version,
selected example IDs, prompt hashes, and generation settings; they do not
automatically select a winner. The synthetic
dataset, rubric, CLI examples, offline tests, and known measurement limitations
are described in [the LLM evaluation guide](./llm-evaluation.md).

## Agents and test lifecycle

`Orchestrator` routes individual tasks and provides deterministic workflow
classification/templates. Workflow runs execute through FastAPI background
tasks and are persisted in `WorkflowRun`, `WorkflowTask`, and attempt-history
`WorkflowTaskAttempt` records. The full-workflow dependency graph has these
parallel groups:

1. Requirements analysis, Change Risk (when a change summary exists), and Test
   Analysis have no prerequisites and may run concurrently.
2. Bug Analysis waits for Requirements Analysis; Quality Insights waits for
   Test Analysis. Those two tasks can run concurrently.
3. Test Generation waits for Requirements and Bug Analysis. Its narrow
   conditional dependency permits Bug Analysis to be skipped only when no
   reports or failed execution records exist.
4. Deterministic validation and Reviewer run serially after generation;
   aggregation waits until all tasks are terminal.

Existing agents are synchronous, so independent tasks use a bounded thread
pool. `WORKFLOW_MAX_CONCURRENT_TASKS` configures the per-process execution
limit and each workflow batch's worker count (default 3, range 1–8). Each task
has its own SQLAlchemy session and deep-copied
agent context. The coordinator persists results serially and deterministically
by task identity, regardless of completion order.
`WORKFLOW_AGENT_TASK_TIMEOUT_SECONDS` (default 300) sets a batch execution
window. Pending work is cancelled where possible. Python cannot safely
force-stop synchronous work already running in a thread, so running calls are
awaited and recorded as timed out once they return; a stalled external call can
therefore delay the workflow.

Requirements analysis retrieves and extracts evidence-backed requirements; bug analysis is skipped when neither bug
reports nor failed executions are available. Test generation reuses the
existing generation service, then deterministic schema, duplicate, project
ownership, and evidence checks run before the advisory `ReviewAgent`. Up to two
regenerations are permitted across the workflow lifetime (three total generation
attempts), with validation and reviewer feedback persisted for later attempts.
Change-risk analysis is skipped unless a change summary was supplied; quality
insights depend on test analysis.

Deterministic validation blocks missing or placeholder expected outcomes,
invalid categories/priorities/steps, duplicate cases, and evidence references
outside the project. Reviewer findings at critical, high, or medium severity
request revision; low-severity findings remain informational. An unavailable
semantic provider produces `evaluation_unavailable` and manual review, never a
claim of semantic support. Final approval is a separate owner action that
re-runs deterministic validation and the reviewer policy.

The workflow router is project-owner scoped and supports start, history,
inspection, and resume. Completed tasks are not re-run during resume, except
that a persisted generation result may be reused to finish validation/review for
that exact interrupted attempt. New attempts use monotonically increasing
workflow-lifetime attempt numbers. Reviewer outcomes remain advisory, but the
human approval endpoint independently requires deterministic validation and no
blocking reviewer findings. If semantic evaluation is unavailable, an explicit
owner approval may proceed only as a human decision; the stored result remains
`evaluation_unavailable` and never implies semantic support.

BackgroundTasks are an in-process single-worker MVP, not a durable queue. A
process loss can interrupt work, including after the workflow/task transaction
commits but before scheduling. On a subsequent owner-authorized workflow API
request, stale pending runs become failed and stale running runs become
partially completed; owners can explicitly resume them. This is request-driven
reconciliation, not automatic startup dispatch. Multi-worker deployment
requires a durable queue and distributed execution coordination.
The thread pool parallelizes tasks only within one workflow runner; it does not
make multiple backend workers safe. Keep the single-worker deployment until
durable dispatch and cross-process claiming are implemented.

Test generation retrieves project evidence, asks Gemini for structured cases,
validates categories and evidence chunk IDs, then saves cases, generation-run
records, and evidence links. The generation response and saved-case listing
include document/chunk identifiers, source metadata, and the source excerpt
derived from the persisted chunk; no excerpt is copied into a separate
historical snapshot. The Upload Center displays document source/format/time,
and the Test Cases view exposes linked evidence. Evaluation checks structure,
linked evidence, duplicates, and—when verified evidence is available—uses
Gemini for semantic assessment. Semantic support, evidence relevance,
classification, step actionability, and requirement coverage are evaluated
separately from evidence reference ownership. Test `category` records the
scenario (positive, negative, boundary, edge); nullable `test_type` records
the testing discipline (such as security or functional). Existing rows remain
valid with `test_type = NULL`. Review is advisory and does not automatically
approve a case.

The Workflows page starts runs for selected projects, refreshes active runs,
and stops polling terminal runs. Its progress count is the fraction of persisted
task records in a terminal state (completed, partial, skipped, failed, or
blocked), not an estimate of remaining work. Expanded details show concurrent
agents, timestamps, durations, dependencies, attempt history, safe input
summaries, persisted outputs, evidence references, errors, final results, and
resume eligibility from the owner-scoped API.

API execution accepts an explicit request configuration for an approved test
case. Targets must use HTTPS and match `TEST_EXECUTION_ALLOWED_HOSTS`; private
or reserved IPs and nonstandard ports are rejected. Redirects and environment
proxy use are disabled. Execution history stores a sanitized request snapshot,
assertions, status, and timing; it does not infer runnable API calls from
natural-language test steps.

## External services and configuration

- **PostgreSQL and pgvector:** connection comes from `DATABASE_URL`.
- **LLM generation:** `LLM_PROVIDER` defaults to `gemini`; the Gemini adapter
  uses `GEMINI_API_KEY` and `GEMINI_MODEL`; Groq is selected with
  `LLM_PROVIDER=groq` and uses optional `GROQ_API_KEY` plus `GROQ_MODEL`.
  Optional fallback uses `LLM_FALLBACK_ENABLED`, `LLM_FALLBACK_PROVIDER`, and
  `LLM_FALLBACK_MODEL`; it is disabled by default. The provider-neutral service
  preserves the legacy `generate_content()` call interface used by agents and
  services.
- **Sentence Transformers:** loads `all-MiniLM-L6-v2` through
  `sentence-transformers`; model availability/download is required for
  embedding and retrieval operations.
- **Local filesystem:** uploaded documents are stored beneath the backend
  application directory.
- **Browser configuration:** frontend API origin comes from
  `VITE_API_BASE_URL`; backend CORS allows configured `CORS_ORIGINS`.

Runtime schema creation is guarded by `AUTO_CREATE_SCHEMA`, which defaults to
false. When enabled, SQLAlchemy `create_all()` may create missing tables at
startup; it does not upgrade existing table definitions.

## Current limitations and migration risks

- Alembic currently has five additive revisions, starting from
  `20261104_01` with `down_revision = None`; this is not a baseline for all
  existing models. The document-processing revision expects pre-existing
  `documents`, `document_chunks`, and `users` tables. A fresh database cannot
  be initialized from this history alone.
- `20261104_01` adds document processing status/error, source type, uploader,
  and chunk source metadata. `20261106_02` adds the nullable
  `test_cases.generation_run_id` foreign key and index if missing.
  `20261109_01` creates workflow run/task/attempt tables and adds nullable
  workflow linkage to test-case generation runs. These revisions expect the
  referenced pre-existing project, user, and generation-run tables. Their
  downgrades deliberately refuse to drop persisted data.
  `20261110_01` adds lifetime generation-attempt accounting and unique/check
  constraints for task and generation attempt keys. Online upgrade preflights
  duplicate keys; offline rendering cannot verify deployed data.
  `20261110_02` adds nullable `test_cases.test_type` without rewriting existing
  records. No schema migration was applied as part of this work.
- The test-only raw-DDL schema helper was removed after its only test was
  covered by the dedicated migration rehearsal; Alembic is the maintained
  schema-change path.
- The model metadata contains many tables, indexes, foreign keys, and checks
  not created by these additive revisions. Whether those objects already
  exist in a deployment, and which Alembic revision it records, cannot be
  established from this repository. A controlled, read-only schema and
  `alembic_version` comparison is required before deployment; no live schema
  was inspected and no migration was applied to Supabase.
- SQLite migration rehearsals validate basic DDL behavior, not PostgreSQL,
  pgvector, production data compatibility, lock behavior, or deployed schema
  state. The first revision's SQLite foreign-key addition has been changed
  from batch table recreation to a direct additive column operation so its
  SQL can also be rendered offline.
- Alembic's environment imports application settings and model metadata.
  Migration commands therefore need the app's required configuration even
  though the migration itself does not call Gemini. Do not use this repository's
  migration command against production without confirming the existing schema,
  reviewing a backup, and rehearsing against a disposable database.
- Upload storage is local disk and has no retention, malware scanning, object
  storage, or cross-instance coordination. MIME checks do not prove file
  signatures. Extractors do not OCR image-only PDFs.
- Reprocessing a document whose chunks are referenced by saved test-case
  evidence may be rejected by database foreign keys. A replacement/deletion
  lifecycle that preserves citations is not implemented.
- `TestCaseEvidence` stores document and chunk foreign keys separately; the
  database does not have a composite constraint enforcing that both references
  belong together. Application generation/evaluation code performs checks.
- The dashboard reports ingestion and embedding coverage only. It does not
  calculate release readiness or an estimated-after-fix score. Test-generation
  coverage uplift, flake reduction, and time saved are not measured by
  persisted execution data.
- Retrieval has no relevance threshold, evaluation set, or multi-tenant
  membership model. `SemanticCache` is currently dormant.
- Execution-history redaction covers common credential-like key names. It
  cannot identify arbitrary secrets embedded in values under innocuously named
  fields; callers should avoid submitting secrets in test payloads unless
  required.
- Document API responses omit the backend's filesystem path; the path remains
  an internal persistence detail.

Backend tests set a unique temporary SQLite database URL in `backend/conftest.py`
before importing the application. Test fixtures may reset tables in that
disposable database; they must not inherit a deployment database URL.
