# Deployment configuration

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
- `RETRIEVAL_TOP_K` (defaults to 4), `RETRIEVAL_MAX_TOP_K` (defaults to 20),
  and `RETRIEVAL_MIN_SIMILARITY` (defaults to 0.0). Similarity is cosine
  similarity in the range [-1, 1]; calibrate the threshold on a representative
  retrieval evaluation set before increasing it.
- `CONTEXT_TOKEN_BUDGET` (defaults to 1000). Context construction estimates
  tokens at four characters per token; it does not use a model tokenizer.
- `CORS_ORIGINS`: JSON array of exact trusted browser origins, for example
  `["https://app.example.com"]`. Do not use wildcard origins with credentials.
- `AUTO_CREATE_SCHEMA`: defaults to `false`; set to `true` only for local
  disposable development databases. Production schema changes must use reviewed
  migrations.

The JWT secret must be kept stable across application instances. Changing it
invalidates all existing access tokens; coordinate a rotation during a planned
deployment and require users to sign in again. Never place the secret in source
control, logs, or client-side configuration.

## Database migrations

The repository has two additive Alembic revisions, but no baseline covering all
SQLAlchemy models:

- `20261104_01` adds document processing status/error, source type, uploader,
  and chunk source metadata. It expects existing `documents`,
  `document_chunks`, and `users` tables.
- `20261106_02` adds the nullable `test_cases.generation_run_id` foreign key
  and index when missing. It expects existing `test_cases` and
  `test_case_generation_runs` tables.

Before any controlled deployment:

1. Obtain explicit deployment approval and a verified backup/restore plan.
2. Read-only inspect the deployed table/column/index/constraint definitions
   and `alembic_version`; compare them with the current model metadata and both
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

The `generation_run_id` revision checks for an existing column/index during an
online run, but does not make the incomplete migration history a fresh-install
baseline. Both revisions intentionally refuse downgrade rather than dropping
columns. Use a reviewed forward correction if needed; preserve data written to
these fields. No live database was inspected or modified for this work.

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
