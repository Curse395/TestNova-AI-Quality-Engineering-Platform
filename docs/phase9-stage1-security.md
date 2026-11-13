# Phase 9 — Stage 1: Authentication, Authorization, and Data Isolation

## Status

**Partial.** The current owner-based authentication and project isolation
boundaries were hardened and offline checks were added. Company membership and
multi-user workspace roles remain unsupported by the existing schema, so this
stage is not represented as full company-level isolation.

## Implemented

- Password storage uses Passlib `bcrypt_sha256` for new registrations and keeps
  verification support for existing bcrypt hashes. Unknown-account and
  incorrect-password login failures share a generic response.
- `JWT_SECRET_KEY` remains a required setting and is validated for minimum
  strength. Access tokens use an explicit HS256 algorithm, expiry and issue
  times, a numeric subject, and an access-token purpose claim.
- Authentication rejects missing, malformed, expired, invalid-signature,
  wrong-purpose, and structurally invalid tokens. The user record is reloaded
  for each request.
- Project and document authorization share owner-scoped query helpers.
  Project-scoped APIs continue to constrain child records by the authorized
  project. Unauthorized document processing no longer distinguishes a foreign
  document from a nonexistent one.
- Project updates/deletions and project dashboard retrieval query only
  owner-authorized projects.
- Offline security tests cover password handling, login behavior, JWT claims,
  configuration requirements, owner-scoped query construction, and ignored
  role-escalation fields.

## Existing authorization model and limitations

- The only supported role is the implicit owner in `Organization.owner_id`.
- The schema has no workspace membership, company, company membership, or
  persisted account-active field. Member/admin permissions, company-group
  isolation, and account deactivation therefore cannot be implemented or
  certified without schema work.
- Frontend route protection is a usability mechanism; only backend checks
  authorize requests. There is no role-based frontend navigation because no
  role claims or membership model exists.

## Verification

- Python source compilation: **passed** for all 20 changed backend Python files
  using in-memory `compile()` without generating bytecode.
- `pytest -q backend/tests/test_security_hardening.py`: **21 passed** using
  isolated fakes from a temporary working directory; no configured `.env` or
  database connection was used.
- Frontend lint: **passed**.
- Frontend tests: **15 passed**.
- Frontend production build: **passed** into a temporary output directory.
  Vite reported the existing large-chunk advisory.
- `git diff --check`: **passed**.

No database, external provider, migration, application server, or dependency
installation was used.
