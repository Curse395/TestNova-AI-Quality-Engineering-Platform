# Supabase test-case schema reconciliation

## Scope and safety

This manual repair targets the schema used by the project test-case and
generation-run endpoints. The known Supabase inventory is compared with the
current SQLAlchemy models and migrations. No database was queried from this
workspace; none of the SQL below has been executed.

The known schema is missing `test_cases.severity` and `test_cases.test_type`,
generation-run traceability/accounting columns, and the
`project_requirements` and `test_case_requirements` tables. The API also
selects document and chunk ORM columns while returning evidence. Its model
declares `document_chunks.source_metadata` as SQL `JSON`, while the confirmed
Supabase column is `JSONB NOT NULL DEFAULT '{}'::jsonb`.

The application model deliberately spells the project foreign-key column
`projects.organitzation_id`. Reconciliation and verification use that exact
spelling and target `organizations.id`; do not rename it as part of this repair.

## Model-derived schema checks

The final verification query checks the mapped columns, PostgreSQL types,
nullability, and server defaults for projects/organizations/users, documents
and chunks, test cases, generation runs, evidence, project requirements, test
case requirements, and workflow runs. It also checks their `id` primary keys,
model-declared unique keys, check constraints, foreign keys, and indexes.
Client-side SQLAlchemy `default=` values are not treated as database defaults;
only declared server defaults are expected.

`users.email` is declared with both `unique=True` and `index=True`; SQLAlchemy
maps this to the unique `ix_users_email` index rather than a separate
`UniqueConstraint`. Reconciliation and verification recognize an equivalent
existing unique btree key under another name to avoid adding a duplicate.

The script preserves the existing FK delete actions: `NO ACTION` unless the
model specifies `ON DELETE CASCADE`. It includes
`projects.organitzation_id -> organizations.id` and the organization-owner
relationship. Existing same-named incompatible checks or indexes, unexpected
column definitions, unvalidated constraints, and incompatible primary keys
require manual review rather than being silently accepted.

## Data safety and manual-review conditions

- The preflight is read-only. It reports check violations, duplicate unique
  keys, FK orphans, duplicate/null IDs, partial requirement-table columns, the
  historical generation counts, and the current `source_metadata` type,
  nullability, and default.
- For a populated partial requirement table, missing `classification` and
  `evidence_chunk_ids` columns can use the reconciliation's model-derived
  defaults (`explicit` and `[]`). Missing no-default required fields require
  manual review; the reconciliation does not invent their values.
- A populated requirement table missing `id` causes an explicit exception.
  IDs are not assigned to existing rows. The preflight reports missing IDs
  and primary-key duplicates/nulls before reconciliation.
- `source_metadata` converts only from `JSONB NOT NULL`, using
  `USING source_metadata::json`. The existing default is dropped and restored
  as `'{}'::json`; the existing values are cast, not replaced. This type
  conversion may rewrite/lock the table and require additional disk space.
  Review a backup and maintenance window. A nullable JSONB column, a missing
  column, or an unexpected type stops with a clear error. If it is already
  JSON, the reconciliation leaves it unchanged only when it is already
  `NOT NULL` with the expected `{}` server default; otherwise manual review is
  required.
- Adding checks, unique constraints, primary keys, and foreign keys can fail
  when the preflight reports existing violations. Do not resolve those
  findings by deleting or rewriting user data without a separately approved
  data-repair plan.
- There is no historical generation-count backfill. `generated_case_count`
  represents raw candidates and does not prove how many unique cases were
  persisted. `final_persisted_count` remains `INTEGER NOT NULL DEFAULT 0`;
  historical zero values remain zero.
- Alembic revision `20261111_01_phase4_traceability.py` contains a legacy
  update that copies raw candidate counts into `final_persisted_count`. Do
  **not** run this migration against the existing database as part of this
  reconciliation.

## Runbook

Use the Supabase SQL Editor only after reviewing a current backup/recovery
approach and confirming the target project/database. Run these files in order:

1. **Read-only preflight:**
   [20261111_preflight_phase4_schema.sql](./sql/20261111_preflight_phase4_schema.sql)
2. **Manual additive reconciliation:**
   [20261111_supabase_phase4_schema_reconciliation.sql](./sql/20261111_supabase_phase4_schema_reconciliation.sql)
3. **Read-only verification:**
   [20261111_verify_phase4_schema.sql](./sql/20261111_verify_phase4_schema.sql)

Stop for manual review if the preflight reports invalid values, duplicate
unique keys, FK orphans, duplicate/null IDs, missing no-default columns on
populated partial tables, nullable/unexpected `source_metadata`, or other
unexpected definitions. Reconciliation also raises on conflicting named
constraints/indexes and incompatible schema states. Do not run Alembic as a
substitute; its legacy data update is intentionally excluded.

Expected successful outcome: preflight reports no data violations and no
unresolved manual-review condition; reconciliation completes without an
exception; verification returns **zero rows**. A zero-row verification is
schema evidence only, not a live API test.

## API follow-up and limitations

The two GET routes use project-ownership checks. The frontend calls the
matching project-scoped endpoints and expects `{ success, data }`. Missing
mapped columns or traceability tables are consistent with the reported
`ProgrammingError` responses. If reconciliation succeeds and verification
returns zero rows, those known schema mismatches should be resolved. After
applying SQL, still call both endpoints in the intended environment and check
the application logs for any remaining schema or authorization errors.

No Supabase connection, SQL execution, migration, or production API test was
performed for this report. Production is not considered fixed until the user
has reviewed/applied the scripts, obtained a clean verification result, and
confirmed both API responses.
