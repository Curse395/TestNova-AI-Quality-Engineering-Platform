# Deployment configuration

See [phase9-security-reliability.md](./phase9-security-reliability.md) for the
current security/reliability status, rate-limit deployment requirements, and
backup/recovery runbook, including the supported local-upload archive tool and
the Supabase provider-managed database backup boundary.

The backend reads configuration through Pydantic Settings from the process
environment or `backend/.env`. Do not commit the real `.env` file.

Required settings:

- `DATABASE_URL`: SQLAlchemy connection string for the intended database.
- `GEMINI_API_KEY`: Gemini API credential.
- `JWT_SECRET_KEY`: at least 32 characters of cryptographically random secret
  material. Generate it with a secrets manager or
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

Optional settings:

- `GEMINI_MODEL` (defaults to the configured code default).
- `TEMPERATURE`, `MAX_OUTPUT_TOKENS`, `TOP_P`, `TOP_K`.
- `MAX_UPLOAD_SIZE_BYTES` (defaults to 10 MiB).
- `LLM_TIMEOUT_SECONDS` (defaults to 60 seconds; allowed range greater than
  zero and at most 300 seconds) applies as the provider request timeout.
- `TEST_EXECUTION_ALLOWED_HOSTS` is a comma-separated allowlist of public API
  hostnames for test execution. No targets are allowed when unset. Do not list
  private/internal infrastructure unless the deployment has an explicit,
  separately reviewed network policy.
- `RETRIEVAL_TOP_K` (defaults to 4), `RETRIEVAL_MAX_TOP_K` (defaults to 20),
  and `RETRIEVAL_MIN_SIMILARITY` (defaults to 0.0). Similarity is cosine
  similarity in the range [-1, 1]; calibrate the threshold on a representative
  retrieval evaluation set before increasing it.
- `CONTEXT_TOKEN_BUDGET` (defaults to 1000). Context construction estimates
  tokens at four characters per token; it does not use a model tokenizer.
- `WORKFLOW_MAX_CONCURRENT_TASKS` (defaults to 3; allowed range 1–8) limits
  independent synchronous agent tasks per backend process; individual workflow
  batches are bounded by the same value.
- `WORKFLOW_AGENT_TASK_TIMEOUT_SECONDS` (defaults to 300; allowed range
  1–1800) controls the parallel batch execution window. Python cannot safely
  force-stop a synchronous agent already running in a thread, so it is awaited
  and recorded as timed out when it returns.
- `CORS_ORIGINS`: JSON array of exact trusted browser origins, for example
  `["https://app.example.com"]`. Do not use wildcard origins with credentials.
- `AUTO_CREATE_SCHEMA`: defaults to `false`; set to `true` only for local
  disposable development databases. Production schema changes must use reviewed
  migrations.

The JWT secret must be kept stable across application instances. Changing it
invalidates all existing access tokens; coordinate a rotation during a planned
deployment and require users to sign in again. Never place the secret in source
control, logs, or client-side configuration.

## Backup deployment requirements

The application does not create database exports. Configure database backup
and any point-in-time recovery through authorized Supabase provider tooling;
features and retention vary by project plan. Separately schedule the
application-managed upload archive described in the Phase 9 runbook, with
document writes quiesced so file snapshots align with database recovery points.
Store archives in encrypted, access-controlled storage, verify checksums, and
rehearse a restore into an isolated target before relying on the proposed RPO
or RTO. The upload utility does not back up Supabase Storage objects.

## Database migrations

The repository has five additive Alembic revisions, but no baseline covering all
SQLAlchemy models:

- `20261104_01` adds document processing status/error, source type, uploader,
  and chunk source metadata. It expects existing `documents`,
  `document_chunks`, and `users` tables.
- `20261106_02` adds the nullable `test_cases.generation_run_id` foreign key
  and index when missing. It expects existing `test_cases` and
  `test_case_generation_runs` tables.
- `20261109_01` creates workflow run, task, and task-attempt history
  tables, and adds nullable workflow/attempt linkage to
  `test_case_generation_runs`. It expects the referenced project, user, and
  generation-run tables to exist.
- `20261110_01` adds workflow-lifetime generation-attempt accounting, unique
  attempt keys, and attempt-number/status checks. Before creating unique
  constraints, an online upgrade checks for duplicate non-null keys and stops
  with an error if any exist. Offline SQL rendering cannot perform that data
  preflight; verify the target data separately before deployment.
- `20261110_02` adds nullable `test_cases.test_type` so testing discipline is
  separate from scenario `category`; existing cases remain valid with a null
  test type. This migration has not been executed.

Before any controlled deployment:

1. Obtain explicit deployment approval and a verified backup/restore plan.
2. Read-only inspect the deployed table/column/index/constraint definitions
   and `alembic_version`; compare them with the current model metadata and all
   revisions. Do not rely on SQLite test results as evidence of production
   schema compatibility.
3. If Alembic has no recorded revision, determine the correct existing-schema
   baseline/stamp in a staging environment; do not assume upgrading from base
   is valid. These revisions do not create the rest of the model tables.
4. Rehearse on a disposable PostgreSQL database with the deployed schema and
   representative data. Confirm constraints, defaults, index creation,
   duration/locking, application reads/writes, and the existing
   `generation_run_id` column case.
5. Schedule and execute only the reviewed forward migrations in the approved
   deployment environment, then perform read-only schema and application
   health checks. Never apply the SQLite rehearsal database or generated SQL
   directly to production.

   For environments that cannot use Alembic, the reviewed additive reference
   script is [20261110_02_add_test_type.sql](./sql/20261110_02_add_test_type.sql).
   It is not a substitute for checking the deployed schema and has not been run.

The `generation_run_id` revision checks for an existing column/index during an
online run, but does not make the incomplete migration history a fresh-install
baseline. Workflow revision `20261109_01` is additive and has a forward-only
downgrade guard; it does not drop tables or generation history. Use a reviewed
forward correction if needed; preserve data written to these fields. No live
database was inspected or modified and no migration was executed for this work.

## QA workflow worker

The initial workflow runner uses FastAPI `BackgroundTasks` and assumes one
backend worker. It persists the workflow and initial tasks in one transaction,
tracks each agent attempt, and keeps generation feedback and retry budgets across
resumes. FastAPI background tasks are not durable queue guarantees: process
termination can interrupt active execution or occur after commit and before
scheduling. On a subsequent authorized workflow API request, stale pending runs
are marked failed and stale running runs are marked partially completed; an
owner can explicitly resume them. This is request-driven reconciliation, not an
automatic startup dispatcher, so recovery waits until the application receives
another relevant API request. Do not deploy multiple workers for workflow
execution without durable queueing and distributed run coordination. No Redis,
Celery, or external queue is required or included in this MVP. The bounded
thread pool only parallelizes independent tasks inside one workflow; it does
not make multiple FastAPI workers safe.

Workflow migration `20261110_01` is forward-only. It validates duplicate keys
before adding unique constraints; resolve any preflight failure through a
separately reviewed, data-preserving operation. Do not assume a downgrade can
remove these constraints or the persisted attempt records.

## Ingestion and retrieval limits

Uploads can be tagged as general documents, requirements, bug reports, test
logs, or technical documentation. These tags and extracted PDF page, workbook
sheet, and document heading markers are retained as chunk metadata and surfaced
with retrieval evidence. This is classification and traceability, not
source-specific schema validation or normalization.

There is not yet a document replacement/deletion workflow that preserves saved
test-case citations. Avoid removing or replacing files whose chunks are cited
by saved test cases. Retrieval ranks embedded chunks, but the project has no
calibrated relevance threshold or benchmark evaluation set yet.

## Tests

Backend tests set `DATABASE_URL` to a per-process SQLite file in the operating
system temporary directory before importing the application. Existing test
fixtures reset tables in that isolated database. Do not remove this override or
run the suite with a deployment database URL.
