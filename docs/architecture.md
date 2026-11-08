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
- **Analytics:** `GET /analytics/overview/{project_id}` and
  `GET /analytics/documents/{project_id}`.
- **Dashboard:** `GET /dashboard/` and `GET /dashboard/insights`.
- **Assistant:** chat session and chat endpoints under `/chat`.

The project, document, analytics, and dashboard pages consume these live
endpoints. Sidebar navigation is configuration, not sample data. Dashboard
knowledge and health values are derived from document processing and embedding
counts; they are not test execution or production release measurements. Test
generation impact fields are currently returned as unavailable rather than
presenting formula-generated values as measured results.

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
currently records filename, source type, file type, chunk index, and any
recognizable page, sheet, or heading context.

## Embeddings, retrieval, and RAG

`EmbeddingService` uses the Sentence Transformers
`all-MiniLM-L6-v2` model and stores 384-dimensional vectors through pgvector.
Generation is scoped to a project and can be narrowed to selected documents or
chunks. Embedding activity snapshots feed the dashboard's processing trend.

`RetrievalService` first checks project ownership and optional document scope,
encodes the query, and orders the project's embedded chunks by cosine distance.
The default retrieval count is small and callers can set a bounded limit. There
is no calibrated relevance cutoff or retrieval benchmark in the current code.
`ContextBuilderService` assembles retrieved text up to an approximate budget
using a four-characters-per-token estimate; it does not use a model tokenizer.

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
records, and evidence links. Evaluation checks structure, linked evidence,
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
