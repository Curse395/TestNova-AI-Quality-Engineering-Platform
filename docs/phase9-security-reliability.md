# Phase 9 — Security, Reliability, and Production Readiness

## Overall status: Partially complete

The repository now has additional offline-verifiable owner-based authorization,
upload validation, per-endpoint throttles, bounded LLM provider timeouts,
request-correlated JSON logs, safer database error handling, and an isolated
backup/restore utility for locally stored uploads. This is not a
production-readiness certification. Company/workspace RBAC is not representable
by the current schema, rate limits and workflow state are process-local, and
provider-managed database backups and production recovery remain deployment
responsibilities.

Status meanings:

- **Implemented and verified:** code and the named offline checks ran in this
  environment.
- **Implemented; verification incomplete:** code exists, but an environment
  limitation or missing test prevents end-to-end verification.
- **Deployment-dependent:** the repository documents the control; cloud or
  operational configuration is still needed.
- **Blocked:** the current schema or product policy does not provide enough
  information to implement the requirement safely.

## Checklist

| # | Requirement | Status | Evidence and remaining work |
|---|---|---|---|
| 1 | Initial inspection and preservation | Implemented and verified | Branch, worktree, checkpoint, and scoped diffs were inspected. No existing changes were staged or reverted. |
| 2 | Authentication and JWT security | Implemented; verification incomplete | `bcrypt_sha256` for new passwords, legacy bcrypt verification, generic login errors, required strong JWT key, pinned HS256, access-purpose and time claims, 24-hour access tokens, and database user reload are in place. Login and registration are throttled. There is no refresh or revocation mechanism; a stolen token remains valid until expiry. |
| 3 | RBAC and data isolation | Blocked for shared roles; owner isolation implemented | Shared owner-scoped project/document queries back the existing project architecture. Tests cover token and owner query behavior. There are no membership, company, role, or account-deactivation tables/fields; no admin/member permissions are claimed. |
| 4 | Secure uploads | Implemented; verification incomplete | Project ownership, sanitized display names, UUID storage names, bounded streaming, extension/MIME allowlists, server-selected MIME values, content signature/format checks, Office ZIP size/ratio bounds, storage path confinement, and processing/deletion conflict checks are implemented. Malware scanning and parser sandboxing are not available. |
| 5 | API credential protection | Implemented; verification incomplete | Provider credentials remain settings-only; provider calls do not log prompts or raw exception messages. Frontend source uses only the API base URL and access token. The frontend source credential-pattern scan returned no matches; production/deployment secret scanning remains an operational control. |
| 6 | API rate limiting | Implemented; deployment-dependent | Endpoint-specific, thread-safe sliding-window limits return HTTP 429 and `Retry-After`. Counters are bounded and process-local, keyed by direct peer IP; they are not shared across workers or machines and proxy forwarding headers are intentionally not trusted. Use a shared gateway/store before horizontal scaling. |
| 7 | LLM timeout and provider failures | Implemented; verification incomplete | Gemini and Groq receive explicit configurable timeouts. SDK retries are disabled; the existing router makes at most one configured fallback attempt for eligible transient failures. No unbounded retry loop exists. The Groq SDK is missing in this environment, so provider-wide import/runtime tests were not run. |
| 8 | Database error handling | Implemented; verification incomplete | Request-scoped sessions roll back when request processing raises and always close; pool pre-ping is enabled. SQLAlchemy and unhandled errors have safe response messages and log only path/type metadata. Existing multi-operation service transactions were not exhaustively audited or integration-tested. |
| 9 | Structured application logging | Implemented; verification incomplete | JSON formatter, generated request ID context, `X-Request-ID` response header, method/path/status/duration logging, and credential-pattern redaction are implemented. Request bodies and query strings are not logged. Environment-specific log shipping, retention, and access controls remain operational work. |
| 10 | Backup and recovery | Implemented and offline verified; production deployment-dependent | `backend/scripts/backup_uploads.py` creates, verifies, and restores checksummed archives of local uploaded documents without database access. Supabase database backups remain provider-managed. Production scheduling, encryption, retention, and recovery rehearsal are not configured or verified here. |
| 11 | Concurrent request handling | Implemented; verification incomplete | Rate-limit updates are synchronized across threads in one process. Upload paths are unique; document processing uses an atomic status claim, and deletion locks/checks processing state. These controls do not coordinate multiple workers. Workflow recovery remains subject to the existing single-process `BackgroundTasks` limitation. |
| 12 | Failure/recovery testing | Implemented and offline verified; production verification incomplete | Offline tests exercise bounded provider failures, generation rejection/rollback boundaries, preservation of existing upload files, upload validation, rate limits, JWT checks, and DB session rollback/close. No live DB, provider, malware scanner, or multi-worker environment is used. |
| 13 | Frontend security and error handling | Implemented; verification incomplete | Protected routes, token removal and login redirect after 401, explicit logout, safe backend error display, and 403/429 fallback text are present. Access tokens remain in `localStorage`; no refresh-token flow or browser XSS defense is introduced here. |
| 14 | Documentation | Implemented | This checklist, architecture notes, deployment configuration, and backup/recovery runbook distinguish code evidence from deployment requirements and blockers. |
| 15 | Verification | Implemented; verification incomplete | This pass ran 66 focused offline backend tests, compiled five changed backend Python files in memory, and passed 17 frontend tests plus lint. The earlier frontend build passed in the prior Phase 9 verification; the broad backend suite is not safe to claim as passed. |
| 16 | Preservation and safety rules | Implemented and verified | No `.env` content was read, no external LLM call or database connection was made, and no migration, schema creation, application startup, dependency installation, staging, commit, or push occurred. |
| 17 | Phase completion decision | Partially complete | Owner-only isolation is the strongest safe model supported by the schema; shared RBAC, distributed throttling, malware scanning, provider backup configuration, and production recovery rehearsal need infrastructure or product/schema work. |

## Authentication and authorization

Registration and login use the existing authentication service. New passwords
use Passlib `bcrypt_sha256`; legacy bcrypt hashes remain verifiable. Login
failures use one generic response for unknown users and invalid passwords.
Access tokens are signed with HS256, require a configured high-entropy
`JWT_SECRET_KEY`, and contain `sub`, `user_id`, `iat`, `exp`, and
`token_use=access`. Access-token lifetime is 24 hours.

There are no refresh tokens, token revocation list, or persisted user-active
field. Signing out clears the browser's token but cannot invalidate a copied
token server-side. Require re-authentication after the access token expires;
rotation of the signing key invalidates all existing tokens.

Project/document ownership is user -> `Organization.owner_id` -> project ->
project-scoped records. `get_owned_project` and `get_owned_document` are the
shared query helpers. The schema contains no workspace/company memberships or
role assignments. Adding member/admin roles requires an approved role policy,
membership model, migration/backfill, endpoint updates, and migration rehearsal;
this stage does not invent role semantics or make owner access weaker.

## Upload controls

Uploads are streamed in bounded chunks and rejected above
`MAX_UPLOAD_SIZE_BYTES` (10 MiB default). The API normalizes filenames for
display, stores content under a random server filename, canonicalizes MIME
values from the extension, and validates text encoding/JSON syntax, PDF
signatures, and Office ZIP members with uncompressed-size and compression-ratio
limits. Document processing and deletion are owner-scoped; storage paths must
resolve beneath the configured project upload directory. A processing
validation failure returns a generic error and persists no parser exception
text for display.

These controls do not replace antivirus/content-disarm scanning or process
isolation. Production deployments should run parsers with least privilege and
resource limits, monitor disk capacity, and add an approved malware-scanning
service if the threat model requires it.

## Rate-limit policy

| Operation | Limit |
|---|---:|
| Registration | 5 requests / 60 seconds |
| Login | 10 requests / 60 seconds |
| Document upload | 10 requests / 60 seconds |
| Document processing | 5 requests / 60 seconds |
| Embedding regeneration | 3 requests / 60 seconds |
| Test-case generation | 3 requests / 60 seconds |
| Test-case evaluation and generation-run evaluation | 10 requests / 60 seconds each |
| Change-risk, review, test-analysis, and quality-insight generation | 5 requests / 60 seconds each |
| API execution | 10 requests / 60 seconds |
| Chat generation | 20 requests / 60 seconds |
| Knowledge index/search | 5 / 60 seconds and 30 / 60 seconds respectively |
| Workflow start/resume | 5 requests / 60 seconds each |
| Execution/trend analytics | 30 requests / 60 seconds each |
| Risk, workflow-monitoring, and release-readiness analytics | 20 / 60 seconds for risks; 30 / 60 seconds for workflow/readiness |
| AI quality summary | 5 requests / 60 seconds |

The in-process limiter uses a lock and bounded per-scope/per-peer-IP sliding
windows. It returns 429 with `Retry-After`. It does not trust
`X-Forwarded-For`, because that header is unsafe without trusted-proxy
configuration. On multiple instances, each process has independent counters;
configure a trusted API gateway or shared rate-limit backend before scaling.
The current fallback is abuse friction, not a distributed quota guarantee.

## LLM and database failure handling

`LLM_TIMEOUT_SECONDS` defaults to 60 seconds and is capped at 300 seconds.
Gemini receives a timeout in SDK milliseconds; Groq receives seconds. Provider
SDK retries are disabled. The existing router may make one fallback call only
for configured, eligible transient failures; fallback is disabled by default.
Failures are represented by safe categories/stages; user-facing chat failures
do not include provider exception details. Prompts, document content,
credentials, and provider payloads are not included in the structured request
log.

`get_db` rolls back on request exceptions and closes the session in all cases.
The engine uses `pool_pre_ping`; SQLAlchemy exceptions return a generic
database error without connection strings or SQL text. This does not certify
every service transaction or the health of an unavailable production database.

API test execution is additionally restricted to HTTPS on the standard port,
an explicitly configured `TEST_EXECUTION_ALLOWED_HOSTS` hostname allowlist, and
hostnames resolving only to globally routable addresses. Configure this list
only for intended test targets. Deployment DNS/network controls are still
required to mitigate DNS changes between validation and connection.

## Structured logging

The application configures JSON logs with UTC timestamps, severity, logger,
message, and request ID. HTTP logs include method, path (not query string),
status, and duration, never request bodies. A generated `X-Request-ID` is
returned on each HTTP response and is not accepted from an untrusted client.
Credential-shaped key/value strings are redacted by the formatter. Deployment
must still restrict log access and define retention/export policies.

## Backup and recovery runbook

### Supported backup boundaries

The configured `DATABASE_URL` is a SQLAlchemy PostgreSQL-compatible connection
string; the application does not include a Supabase backup API client or a
provider-independent database export format. Use the authorized Supabase
dashboard/provider tooling for database snapshots or point-in-time recovery.
Availability, retention, and PITR depend on the selected Supabase project plan
and its current provider settings. Confirm them in the provider console; do not
assume PITR is enabled.

The application-managed utility
[`backend/scripts/backup_uploads.py`](../backend/scripts/backup_uploads.py)
handles only local files under `backend/app/uploads/<project_id>/`. It never
connects to a database, emits SQL, or includes database rows, Supabase Storage
objects, settings, credentials, or telemetry. The archive necessarily contains
uploaded document contents, which may themselves be sensitive application
data. It is not encrypted by the script and must be placed on an encrypted
volume or in an encrypted, access-controlled backup store.

The utility rejects symlinks, unexpected directory layouts, and in-progress
upload temporary files. It writes timestamped ZIP archives without overwriting,
records per-file size/SHA-256 in a manifest, writes an archive SHA-256 sidecar,
and verifies the completed archive before reporting success. On POSIX, the
backup directory and files are restricted to owner permissions (0700/0600).
On Windows, apply and verify restrictive NTFS ACLs on the destination; Python's
portable standard library does not set a private Windows ACL. Checksums detect
accidental corruption but do not authenticate an archive against a malicious
replacement.

From the `backend` directory, the operator commands are:

```text
python scripts/backup_uploads.py backup --destination-dir <protected-backup-dir>
python scripts/backup_uploads.py verify --archive <protected-backup-dir>/<timestamped-archive>.zip
python scripts/backup_uploads.py restore --archive <protected-backup-dir>/<timestamped-archive>.zip --destination-dir <new-empty-restore-dir>
```

The restore destination must not already exist. Restore validates the checksum,
manifest, archive member set, file sizes, and content hashes before and during
extraction. The restore tool recovers files only; it does not restore database
records, switch application paths, or reconcile database references.

### Operational targets (proposed, not verified)

- **Schedule:** daily provider-managed database backup/snapshot and a coordinated
  daily local-upload archive after writes are quiesced. Alert on missed or
  failed jobs and verify each archive before retention.
- **Retention:** proposed 35 daily copies and 12 weekly copies, subject to
  privacy, legal, and cost review. Keep an encrypted copy in a separate
  account/region with restricted operator access.
- **RPO:** 24 hours proposed; only achievable if both database and uploads are
  backed up at that interval and the job is monitored.
- **RTO:** 4 hours proposed; not measured and must be tested by the operations
  owner.
- **Consistency:** stop or quiesce document writes, capture the provider DB
  recovery point and upload archive as one documented window, then resume
  writes. Database rows contain paths to local files; the two snapshots must
  represent the same recovery point. Supabase Storage objects, if added later,
  require their own provider object-storage backup/versioning plan.
- **Protection:** encrypt in transit and at rest, restrict backup/restore
  identities, audit access, and never put credentials in scripts, source
  control, archive manifests, or logs.

### Recovery checklist

1. Declare the incident, preserve evidence, and record the selected UTC
   recovery point and operator.
2. Obtain an authorized Supabase provider restore into an isolated project or
   approved recovery target. Provider-managed database restoration cannot be
   performed by this utility.
3. Verify the provider database recovery point and schema revision without
   applying unreviewed migrations.
4. Verify the matching upload archive with the `verify` command, then restore
   it to a new isolated directory. Do not overwrite the live upload directory.
5. In the isolated recovery environment, check document-row storage paths,
   missing/orphan file counts, sampled file hashes, document/chunk relations,
   and access controls. Validate representative application reads only after
   the recovery environment is approved.
6. Record data loss window, integrity outcomes, restore duration, and
   discrepancies. Obtain the service owner's approval before switching traffic.
7. Preserve the failed system and backup evidence according to incident and
   retention policy; do not clean up until the incident owner authorizes it.

No Supabase backup, provider restore, real file backup, production connection,
or production recovery was performed for this implementation. Schedules,
encryption/ACLs, monitoring, retention, authorized provider tooling, and
restore rehearsal remain deployment prerequisites. The proposed RPO/RTO are
not service guarantees.

### Requested completion-point status

- **Point 12 — Backup and Recovery: PARTIAL.** The app-managed local-upload
  archive and isolated file restore are implemented and covered by offline
  integrity tests. Provider-managed database backup scheduling and an isolated
  database restore have not been configured or verified.
- **Point 14 — Failure and Recovery Scenarios: PARTIAL.** Applicable local
  controls and offline fake-based failure tests are implemented. Production
  provider/database failures and restart recovery were not induced; persisted
  database continuity remains deployment-verifiable only.

## Failure and recovery scenarios

| Scenario | Implemented behavior | Offline evidence / remaining boundary |
|---|---|---|
| Gemini timeout | SDK request timeout is bounded; SDK retries are disabled; router may make one configured eligible fallback attempt; errors omit prompts/provider payloads. | Provider/config and router tests use fakes; no external provider call. |
| Database unavailable | Request-scoped session rolls back on errors and always closes; SQLAlchemy failures return a generic response and log error type/path only. | Fake-session rollback/close test; no database failure was induced. |
| Invalid/oversized upload | Type, signature and size checks reject invalid files; failed temporary writes are removed without deleting a pre-existing target. | Temporary-file and existing-file preservation tests; no parser sandbox or malware scanner. |
| Expired/invalid JWT | Invalid claims/signatures/expiry are rejected with 401 before protected data is returned. | Offline signed-token and fake-query tests; no live endpoint was started. |
| Rate limit exceeded | Per-process sliding-window limits return 429 and `Retry-After`. | Deterministic fake-clock and concurrency tests; counters reset on restart and are not distributed. |
| Process restart | Database records and uploaded files are external to process memory; workflow execution and rate-limit counters are process-local. | Archive restore is verified in temporary directories. No application restart or database persistence test was performed; active background tasks can be interrupted. |
| Failed generation | Invalid JSON/schema/evidence is rejected; generation attempts are bounded; transactions roll back on persistence errors and no incomplete test cases are committed. | Isolated fake-session tests; existing SQL-backed generation tests were not run because they create a SQLite schema. |
| Network interruption | Provider errors are standardized; provider timeout and fallback attempts are bounded; generation is not blindly retried beyond its configured attempt count. | Offline provider/router fakes; no network or external API call. |

Temporary upload files created during normal request handling are cleaned up
when the request fails. An abrupt process termination may leave a temporary
`.upload` file; the backup utility fails closed while such a file exists, so an
operator must quiesce uploads and review stale temporary files before backup.
It does not delete files automatically.

## Verification instructions and limits

Run backend tests only with a temporary working directory and explicitly
non-production dummy settings. Never run tests that load the configured
deployment database. Compile changed Python source in memory to avoid
bytecode artifacts. Frontend lint/tests do not start the application; if a
build is needed, direct its output to a temporary directory.

Verification performed for the backup/failure-recovery work:

- Backend command (run from a temporary working directory, with
  `--rootdir <repo>\backend`):
  `python -m pytest --rootdir <repo>\backend -p no:cacheprovider <repo>\backend\tests\test_upload_backup.py <repo>\backend\tests\test_phase9_failure_recovery_offline.py <repo>\backend\tests\test_phase9_reliability_controls.py <repo>\backend\tests\test_security_hardening.py -q`
  — **66 passed**. The two new test files use temporary filesystem fixtures
  and fake sessions/providers; the existing selected suites use fake database
  queries and do not connect to their configured database.
- Frontend command from `frontend`:
  `npm test` — **17 passed**, including the 401 token-clear/event test.
- Frontend lint from `frontend`: `npm run lint` — **passed**.
- In-memory Python syntax compilation — **5 changed backend Python files passed**.
- `git diff --check` — **passed**.

The existing SQL-backed `test_test_case_generation_service.py` was not run:
its fixture creates a SQLite schema, which this task explicitly prohibits.
Groq SDK tests were not run because the `groq` package is absent; no dependency
was installed. No build was needed for the focused frontend change.

No Phase 9 migration was created. The missing membership/role schema cannot be
added safely until role semantics, invitation/ownership transfer, existing
organization backfill, and downgrade/data-retention policy are approved.
