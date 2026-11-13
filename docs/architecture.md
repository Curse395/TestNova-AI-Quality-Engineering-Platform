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
  analytics, assistant, and authentication views. `frontend/src/api/` contains
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

The project, document, analytics, and dashboard pages consume these live
endpoints. Sidebar navigation is configuration, not sample data. Dashboard
metrics report document, chunk, and embedding counts and their separate
coverage ratios; they are not test-execution or production-release
measurements. Coverage is unavailable when its denominator is empty. Test
generation impact fields are currently returned as unavailable rather than
presenting formula-generated values as measured results.

## API, service, and persistence layers

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
- `ChatSession` groups `ChatHistory` messages for a user and project.
- `SemanticCache` is defined in metadata but has no active service or request
  path in the current application.

The model metadata currently defines tables for users, organizations, projects,
documents, document chunks, document embeddings, project activity, test cases,
test-case generation runs, test-case evidence, test execution runs, chat
sessions, chat history, and semantic cache. Important uniqueness/check rules
include unique user email, one embedding per chunk, unique test-case evidence
per case/chunk, and test-case category, priority, and review-status checks.
Model-declared indexes also cover commonly queried project, run, and timestamp
columns. These are model facts, not proof that every deployed database contains
the corresponding tables, indexes, or constraints.

Several project-scoped services verify that the authenticated user owns the
project's organization before returning data. This is an owner-based access
model; organization membership, team roles, and shared-project grants are not
implemented.

## Authentication and authorization

Passwords are hashed with Passlib/Bcrypt. Login issues an HS256 JWT with a
24-hour expiration, signed using the required `JWT_SECRET_KEY`. The
`get_current_user` dependency validates the signature and expiry, then resolves
the user from the database. Protected API routes use that dependency.

Authorization is generally enforced by joining projects to their organization
and comparing `Organization.owner_id` with the current user. Chat sessions,
retrieval, embeddings, analytics, test-case operations, and API test execution
also scope records to their project. The frontend route guard is a navigation
convenience only and is not an authorization boundary.

## Document upload and processing

The upload endpoint requires a project ID and multipart file. It checks project
ownership, supported extension and MIME type, nonempty content, and the
configured byte limit. The file is streamed to a temporary file and moved to a
UUID-named path beneath `backend/app/uploads/{project_id}`; the sanitized
original name is retained for display. A `Document` row records its category,
uploader, processing status, content type, and storage path.

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
by `PromptBuilderService`, then calls the configured Gemini model. Responses
include source document/chunk identifiers and are persisted in chat history
when generation succeeds.

## Agents and test lifecycle

`Orchestrator` routes a task to agents registered by the caller. The API builds
the applicable agents for each request; it is not a background worker or
durable orchestration queue. Current agents cover test generation, knowledge
search, change-risk analysis, test-case review, test analysis, and quality
insights.

Test generation retrieves project evidence, asks Gemini for structured cases,
validates categories and evidence chunk IDs, then saves cases, generation-run
records, and evidence links. The generation response and saved-case listing
include document/chunk identifiers, source metadata, and the source excerpt
derived from the persisted chunk; no excerpt is copied into a separate
historical snapshot. The Upload Center displays document source/format/time,
and the Test Cases view exposes linked evidence. Evaluation checks structure, linked evidence,
duplicates, and—when verified evidence is available—uses Gemini for semantic
assessment. Review is advisory and does not automatically approve a case.

API execution accepts an explicit request configuration for an approved test
case. Targets must use HTTPS and match `TEST_EXECUTION_ALLOWED_HOSTS`; private
or reserved IPs and nonstandard ports are rejected. Redirects and environment
proxy use are disabled. Execution history stores a sanitized request snapshot,
assertions, status, and timing; it does not infer runnable API calls from
natural-language test steps.

## External services and configuration

- **PostgreSQL and pgvector:** connection comes from `DATABASE_URL`.
- **Gemini:** `google-genai` client uses `GEMINI_API_KEY`, `GEMINI_MODEL`, and
  generation settings.
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

- Alembic currently has two additive revisions, starting from
  `20261104_01` with `down_revision = None`; this is not a baseline for all
  existing models. The document-processing revision expects pre-existing
  `documents`, `document_chunks`, and `users` tables. A fresh database cannot
  be initialized from this history alone.
- `20261104_01` adds document processing status/error, source type, uploader,
  and chunk source metadata. `20261106_02` adds the nullable
  `test_cases.generation_run_id` foreign key and index if missing. The latter
  requires `test_cases` and `test_case_generation_runs` to exist. Both
  downgrades deliberately refuse to drop persisted columns.
- The test-only raw-DDL schema helper was removed after its only test was
  covered by the dedicated migration rehearsal; Alembic is the maintained
  schema-change path.
- The model metadata contains many tables, indexes, foreign keys, and checks
  not created by these two additive revisions. Whether those objects already
  exist in a deployment, and which Alembic revision it records, cannot be
  established from this repository. A controlled, read-only schema and
  `alembic_version` comparison is required before deployment; no live schema
  was inspected and neither revision was applied to Supabase.
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
- Dashboard readiness and estimated-after-fix values are heuristic summaries
  of ingestion and embedding completeness, not calibrated release predictions.
  Test-generation coverage uplift, flake reduction, and time saved are not
  measured by persisted execution data.
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
