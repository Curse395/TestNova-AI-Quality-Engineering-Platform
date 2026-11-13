-- Additive reconciliation reference for manual Supabase SQL Editor review.
-- Do not run until the target schema, data preflight, and backup/recovery plan
-- have been reviewed. This script has not been executed against any database.
-- It is scoped to the current test-case API models and the related document
-- metadata selected by GET /projects/{project_id}/test-cases.
--
-- Preconditions: the existing public tables projects, users, test_cases,
-- test_case_generation_runs, test_case_evidence, documents, document_chunks,
-- organizations, and workflow_runs exist. The script does not create/rebuild
-- those tables.
-- Constraint creation can fail if existing data violates a required
-- constraint; investigate such rows rather than deleting or silently changing
-- them.

ALTER TABLE public.test_cases
    ADD COLUMN IF NOT EXISTS severity VARCHAR(20) NOT NULL DEFAULT 'medium',
    ADD COLUMN IF NOT EXISTS test_type VARCHAR(60);

ALTER TABLE public.test_case_generation_runs
    ADD COLUMN IF NOT EXISTS requirement_keys JSON NOT NULL DEFAULT '[]'::json,
    ADD COLUMN IF NOT EXISTS duplicate_rejected_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS invalid_rejected_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS insufficient_evidence_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS final_persisted_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;

-- These metadata fields are read as part of the evidence query's ORM SELECT.
-- They are from migration 20261104_01; their current presence was not included
-- in the supplied schema inventory.
ALTER TABLE public.documents
    ADD COLUMN IF NOT EXISTS processing_status VARCHAR(20) NOT NULL DEFAULT 'uploaded',
    ADD COLUMN IF NOT EXISTS processing_error TEXT,
    ADD COLUMN IF NOT EXISTS source_type VARCHAR(30) NOT NULL DEFAULT 'document',
    ADD COLUMN IF NOT EXISTS uploaded_by_user_id INTEGER;

DO $source_metadata_type$
DECLARE
    source_metadata_type_oid OID;
    source_metadata_type_name TEXT;
    source_metadata_not_null BOOLEAN;
    source_metadata_default TEXT;
    normalized_source_metadata_default TEXT;
BEGIN
    IF to_regclass('public.document_chunks') IS NULL THEN
        RAISE EXCEPTION
            'Required table public.document_chunks is missing; manual review is required';
    END IF;

    SELECT
        attribute.atttypid,
        format_type(attribute.atttypid, attribute.atttypmod),
        attribute.attnotnull,
        pg_get_expr(default_expression.adbin, default_expression.adrelid)
    INTO source_metadata_type_oid, source_metadata_type_name,
         source_metadata_not_null, source_metadata_default
    FROM pg_attribute AS attribute
    LEFT JOIN pg_attrdef AS default_expression
      ON default_expression.adrelid = attribute.attrelid
     AND default_expression.adnum = attribute.attnum
    WHERE attribute.attrelid = 'public.document_chunks'::regclass
      AND attribute.attname = 'source_metadata'
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Required column public.document_chunks.source_metadata is missing; manual review is required';
    END IF;

    IF source_metadata_type_oid = 'jsonb'::regtype THEN
        IF NOT source_metadata_not_null THEN
            RAISE EXCEPTION
                'Column public.document_chunks.source_metadata is JSONB but nullable; manual review is required before conversion';
        END IF;

        ALTER TABLE public.document_chunks
            ALTER COLUMN source_metadata DROP DEFAULT;
        ALTER TABLE public.document_chunks
            ALTER COLUMN source_metadata TYPE JSON
            USING source_metadata::json;
        ALTER TABLE public.document_chunks
            ALTER COLUMN source_metadata SET DEFAULT '{}'::json;
        ALTER TABLE public.document_chunks
            ALTER COLUMN source_metadata SET NOT NULL;
    ELSIF source_metadata_type_oid = 'json'::regtype THEN
        normalized_source_metadata_default := regexp_replace(
            regexp_replace(
                lower(COALESCE(source_metadata_default, '')),
                '\s+',
                '',
                'g'
            ),
            '[()]',
            '',
            'g'
        );
        IF NOT source_metadata_not_null
           OR normalized_source_metadata_default <> '''{}''::json' THEN
            RAISE EXCEPTION
                'Column public.document_chunks.source_metadata is already JSON but does not match NOT NULL DEFAULT ''{}''::json (nullable=%, default=%); manual review is required',
                NOT source_metadata_not_null,
                COALESCE(source_metadata_default, '<none>');
        END IF;
    ELSE
        RAISE EXCEPTION
            'Column public.document_chunks.source_metadata has unexpected type %; expected JSONB (convertible) or JSON; manual review is required',
            source_metadata_type_name;
    END IF;
END;
$source_metadata_type$;

CREATE TABLE IF NOT EXISTS public.project_requirements (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL,
    requirement_key VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    classification VARCHAR(20) NOT NULL DEFAULT 'explicit',
    evidence_chunk_ids JSON NOT NULL DEFAULT '[]'::json,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    CONSTRAINT uq_project_requirements_project_key
        UNIQUE (project_id, requirement_key)
);

CREATE TABLE IF NOT EXISTS public.test_case_requirements (
    id SERIAL PRIMARY KEY,
    test_case_id INTEGER NOT NULL,
    requirement_id INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL,
    CONSTRAINT uq_test_case_requirements_case_requirement
        UNIQUE (test_case_id, requirement_id)
);

-- Repair partially existing requirement tables as well as creating absent
-- ones. Adding a missing NOT NULL column without a server default will fail
-- when the existing table has rows; review/backfill those rows first rather
-- than inventing requirement keys, descriptions, or timestamps.
DO $requirement_id_preflight$
DECLARE
    target_table TEXT;
    existing_rows BIGINT;
BEGIN
    FOREACH target_table IN ARRAY ARRAY[
        'project_requirements',
        'test_case_requirements'
    ]
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE information_schema.columns.table_schema = 'public'
              AND information_schema.columns.table_name = target_table
              AND column_name = 'id'
        ) THEN
            EXECUTE format('SELECT count(*) FROM public.%I', target_table)
                INTO existing_rows;
            IF existing_rows > 0 THEN
                RAISE EXCEPTION
                    'Table public.% has % existing row(s) but lacks id; manual review must assign/validate IDs before reconciliation. No existing IDs will be invented',
                    target_table,
                    existing_rows;
            END IF;
        END IF;
    END LOOP;
END;
$requirement_id_preflight$;

ALTER TABLE public.project_requirements
    ADD COLUMN IF NOT EXISTS id SERIAL,
    ADD COLUMN IF NOT EXISTS project_id INTEGER NOT NULL,
    ADD COLUMN IF NOT EXISTS requirement_key VARCHAR(200) NOT NULL,
    ADD COLUMN IF NOT EXISTS description TEXT NOT NULL,
    ADD COLUMN IF NOT EXISTS classification VARCHAR(20) NOT NULL DEFAULT 'explicit',
    ADD COLUMN IF NOT EXISTS evidence_chunk_ids JSON NOT NULL DEFAULT '[]'::json,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL;

ALTER TABLE public.test_case_requirements
    ADD COLUMN IF NOT EXISTS id SERIAL,
    ADD COLUMN IF NOT EXISTS test_case_id INTEGER NOT NULL,
    ADD COLUMN IF NOT EXISTS requirement_id INTEGER NOT NULL,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL;

-- Add missing primary keys for pre-existing tables only. Normally each is
-- already present; this does not rewrite table data.
DO $$
DECLARE
    item RECORD;
BEGIN
    FOR item IN
        SELECT *
        FROM (VALUES
            ('projects'),
            ('organizations'),
            ('users'),
            ('documents'),
            ('document_chunks'),
            ('test_cases'),
            ('test_case_generation_runs'),
            ('test_case_evidence'),
            ('project_requirements'),
            ('test_case_requirements'),
            ('workflow_runs')
        ) AS expected(table_name)
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = item.table_name
              AND column_name = 'id'
        ) THEN
            RAISE EXCEPTION
                'Required id column is missing from public.%; manual review is required and reconciliation will not invent IDs',
                item.table_name;
        END IF;

        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint AS c
            JOIN pg_attribute AS a
              ON a.attrelid = c.conrelid
             AND a.attnum = c.conkey[1]
            WHERE c.conrelid = format('public.%I', item.table_name)::regclass
              AND c.contype = 'p'
              AND cardinality(c.conkey) = 1
              AND a.attname = 'id'
        ) THEN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = format('public.%I', item.table_name)::regclass
                  AND contype = 'p'
            ) THEN
                RAISE EXCEPTION
                    'Table % already has a primary key that is not its single id column; manual review is required',
                    item.table_name;
            END IF;

            EXECUTE format(
                'ALTER TABLE public.%I ADD CONSTRAINT %I PRIMARY KEY (id)',
                item.table_name,
                item.table_name || '_pkey'
            );
        END IF;
    END LOOP;
END;
$$;

-- Add model-declared checks if missing. Existing values must satisfy them.
DO $$
DECLARE
    item RECORD;
    existing_constraint RECORD;
    normalized_actual TEXT;
    normalized_expected TEXT;
BEGIN
    FOR item IN
        SELECT *
        FROM (VALUES
            ('test_cases', 'ck_test_case_category', 'CHECK (((category)::text = ANY ((ARRAY[''positive''::character varying, ''negative''::character varying, ''boundary''::character varying, ''edge''::character varying])::text[])))'),
            ('test_cases', 'ck_test_cases_priority', 'CHECK (((priority)::text = ANY ((ARRAY[''low''::character varying, ''medium''::character varying, ''high''::character varying, ''critical''::character varying])::text[])))'),
            ('test_cases', 'ck_test_cases_severity', 'CHECK (((severity)::text = ANY ((ARRAY[''low''::character varying, ''medium''::character varying, ''high''::character varying, ''critical''::character varying])::text[])))'),
            ('test_cases', 'ck_test_cases_review_status', 'CHECK (((review_status)::text = ANY ((ARRAY[''draft''::character varying, ''approved''::character varying, ''rejected''::character varying])::text[])))'),
            ('test_case_generation_runs', 'ck_generation_runs_workflow_attempt_positive', 'CHECK (((workflow_attempt_number IS NULL) OR (workflow_attempt_number > 0)))'),
            ('workflow_runs', 'ck_workflow_runs_status', 'CHECK (((status)::text = ANY ((ARRAY[''pending''::character varying, ''running''::character varying, ''completed''::character varying, ''partially_completed''::character varying, ''failed''::character varying])::text[])))')
        ) AS expected(table_name, constraint_name, expected_definition)
    LOOP
        SELECT
            c.oid,
            c.contype,
            c.convalidated,
            pg_get_constraintdef(c.oid, false) AS definition
        INTO existing_constraint
        FROM pg_constraint AS c
        WHERE c.conrelid = format('public.%I', item.table_name)::regclass
          AND c.conname = item.constraint_name;

        normalized_expected := regexp_replace(
            lower(item.expected_definition),
            '\s+',
            '',
            'g'
        );

        IF FOUND THEN
            IF existing_constraint.contype <> 'c' THEN
                RAISE EXCEPTION
                    'Constraint name % on public.% is not a CHECK constraint; manual review is required',
                    item.constraint_name,
                    item.table_name;
            END IF;

            normalized_actual := regexp_replace(
                lower(existing_constraint.definition),
                '\s+',
                '',
                'g'
            );
            IF normalized_actual <> normalized_expected THEN
                RAISE EXCEPTION
                    'CHECK constraint public.% (%): existing definition % differs from expected %; manual review is required',
                    item.table_name,
                    item.constraint_name,
                    existing_constraint.definition,
                    item.expected_definition;
            END IF;
            IF NOT existing_constraint.convalidated THEN
                RAISE EXCEPTION
                    'CHECK constraint public.% (%) has the expected definition but is NOT VALID; manual review is required',
                    item.table_name,
                    item.constraint_name;
            END IF;
        ELSE
            IF item.constraint_name = 'ck_test_case_category' THEN
                ALTER TABLE public.test_cases
                    ADD CONSTRAINT ck_test_case_category
                    CHECK (category IN ('positive', 'negative', 'boundary', 'edge'));
            ELSIF item.constraint_name = 'ck_test_cases_priority' THEN
                ALTER TABLE public.test_cases
                    ADD CONSTRAINT ck_test_cases_priority
                    CHECK (priority IN ('low', 'medium', 'high', 'critical'));
            ELSIF item.constraint_name = 'ck_test_cases_severity' THEN
                ALTER TABLE public.test_cases
                    ADD CONSTRAINT ck_test_cases_severity
                    CHECK (severity IN ('low', 'medium', 'high', 'critical'));
            ELSIF item.constraint_name = 'ck_test_cases_review_status' THEN
                ALTER TABLE public.test_cases
                    ADD CONSTRAINT ck_test_cases_review_status
                    CHECK (review_status IN ('draft', 'approved', 'rejected'));
            ELSIF item.constraint_name = 'ck_generation_runs_workflow_attempt_positive' THEN
                ALTER TABLE public.test_case_generation_runs
                    ADD CONSTRAINT ck_generation_runs_workflow_attempt_positive
                    CHECK (
                        workflow_attempt_number IS NULL
                        OR workflow_attempt_number > 0
                    );
            ELSE
                ALTER TABLE public.workflow_runs
                    ADD CONSTRAINT ck_workflow_runs_status
                    CHECK (
                        status IN (
                            'pending',
                            'running',
                            'completed',
                            'partially_completed',
                            'failed'
                        )
                    );
            END IF;
        END IF;
    END LOOP;
END;
$$;

-- Detect equivalent unique btree definitions by their key columns, regardless
-- of constraint/index name. Partial, expression, invalid, non-btree, or
-- NULLS-NOT-DISTINCT indexes do not match SQLAlchemy's ordinary UniqueConstraint.
DO $$
DECLARE
    item RECORD;
BEGIN
    FOR item IN
        SELECT *
        FROM (VALUES
            ('test_case_generation_runs', 'workflow_run_id,workflow_attempt_number', 'uq_generation_runs_workflow_attempt'),
            ('test_case_evidence', 'test_case_id,chunk_id', 'uq_test_case_evidence_case_chunk'),
            ('project_requirements', 'project_id,requirement_key', 'uq_project_requirements_project_key'),
            ('test_case_requirements', 'test_case_id,requirement_id', 'uq_test_case_requirements_case_requirement')
        ) AS expected(table_name, columns_csv, constraint_name)
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_index AS i
            JOIN pg_class AS index_relation ON index_relation.oid = i.indexrelid
            JOIN pg_am AS access_method ON access_method.oid = index_relation.relam
            WHERE i.indrelid = format('public.%I', item.table_name)::regclass
              AND i.indisunique
              AND NOT i.indisprimary
              AND i.indisvalid
              AND i.indisready
              AND i.indimmediate
              AND i.indpred IS NULL
              AND i.indexprs IS NULL
              AND i.indnkeyatts = cardinality(string_to_array(item.columns_csv, ','))
              AND access_method.amname = 'btree'
              AND NOT i.indnullsnotdistinct
              AND (
                  SELECT array_agg(attribute.attname ORDER BY attribute.attname)
                  FROM unnest(i.indkey) WITH ORDINALITY AS key_column(attnum, ordinal)
                  JOIN pg_attribute AS attribute
                    ON attribute.attrelid = i.indrelid
                   AND attribute.attnum = key_column.attnum
                  WHERE key_column.ordinal <= i.indnkeyatts
              ) = (
                  SELECT array_agg(column_name::name ORDER BY column_name::name)
                  FROM unnest(string_to_array(item.columns_csv, ',')) AS expected_column(column_name)
              )
        ) THEN
            IF EXISTS (
                SELECT 1
                FROM pg_class AS existing_relation
                WHERE existing_relation.relnamespace = 'public'::regnamespace
                  AND existing_relation.relname = item.constraint_name
            ) THEN
                RAISE EXCEPTION
                    'Relation name public.% already exists but does not provide the required unique key on public.% (%); manual review is required',
                    item.constraint_name,
                    item.table_name,
                    item.columns_csv;
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = format('public.%I', item.table_name)::regclass
                  AND conname = item.constraint_name
            ) THEN
                RAISE EXCEPTION
                    'Constraint name % already exists on %, but its unique definition does not match the required columns (%)',
                    item.constraint_name,
                    item.table_name,
                    item.columns_csv;
            END IF;

            EXECUTE format(
                'ALTER TABLE public.%I ADD CONSTRAINT %I UNIQUE (%s)',
                item.table_name,
                item.constraint_name,
                item.columns_csv
            );
        END IF;
    END LOOP;
END;
$$;

-- Add a missing FK by the expected child/parent columns and delete action,
-- regardless of the name of an already-existing equivalent FK.
DO $$
DECLARE
    item RECORD;
BEGIN
    FOR item IN
        SELECT *
        FROM (VALUES
            ('test_cases', 'project_id', 'projects', 'id', 'a', 'fk_test_cases_project_id_projects'),
            ('test_cases', 'created_by_user_id', 'users', 'id', 'a', 'fk_test_cases_created_by_user_id_users'),
            ('test_cases', 'generation_run_id', 'test_case_generation_runs', 'id', 'a', 'fk_test_cases_generation_run_id_test_case_generation_runs'),
            ('test_case_generation_runs', 'project_id', 'projects', 'id', 'a', 'fk_generation_runs_project_id_projects'),
            ('test_case_generation_runs', 'created_by_user_id', 'users', 'id', 'a', 'fk_generation_runs_created_by_user_id_users'),
            ('test_case_generation_runs', 'workflow_run_id', 'workflow_runs', 'id', 'a', 'fk_generation_runs_workflow_run'),
            ('test_case_evidence', 'test_case_id', 'test_cases', 'id', 'c', 'fk_test_case_evidence_test_case_id_test_cases'),
            ('test_case_evidence', 'document_id', 'documents', 'id', 'a', 'fk_test_case_evidence_document_id_documents'),
            ('test_case_evidence', 'chunk_id', 'document_chunks', 'id', 'a', 'fk_test_case_evidence_chunk_id_document_chunks'),
            ('documents', 'project_id', 'projects', 'id', 'a', 'fk_documents_project_id_projects'),
            ('documents', 'uploaded_by_user_id', 'users', 'id', 'a', 'fk_documents_uploaded_by_user_id_users'),
            ('document_chunks', 'document_id', 'documents', 'id', 'a', 'fk_document_chunks_document_id_documents'),
            ('projects', 'organitzation_id', 'organizations', 'id', 'a', 'fk_projects_organitzation_id_organizations'),
            ('organizations', 'owner_id', 'users', 'id', 'a', 'fk_organizations_owner_id_users'),
            ('workflow_runs', 'project_id', 'projects', 'id', 'a', 'fk_workflow_runs_project_id_projects'),
            ('workflow_runs', 'initiated_by', 'users', 'id', 'a', 'fk_workflow_runs_initiated_by_users'),
            ('project_requirements', 'project_id', 'projects', 'id', 'a', 'fk_project_requirements_project_id_projects'),
            ('test_case_requirements', 'test_case_id', 'test_cases', 'id', 'c', 'fk_test_case_requirements_test_case_id_test_cases'),
            ('test_case_requirements', 'requirement_id', 'project_requirements', 'id', 'c', 'fk_test_case_requirements_requirement_id_project_requirements')
        ) AS expected(child_table, child_column, parent_table, parent_column, delete_action, constraint_name)
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint AS c
            JOIN pg_attribute AS child_attribute
              ON child_attribute.attrelid = c.conrelid
             AND child_attribute.attnum = c.conkey[1]
            JOIN pg_attribute AS parent_attribute
              ON parent_attribute.attrelid = c.confrelid
             AND parent_attribute.attnum = c.confkey[1]
            WHERE c.contype = 'f'
              AND c.conrelid = format('public.%I', item.child_table)::regclass
              AND c.confrelid = format('public.%I', item.parent_table)::regclass
              AND cardinality(c.conkey) = 1
              AND cardinality(c.confkey) = 1
              AND child_attribute.attname = item.child_column
              AND parent_attribute.attname = item.parent_column
              AND c.confdeltype::text = item.delete_action
              AND c.confupdtype::text = 'a'
              AND c.confmatchtype::text = 's'
              AND NOT c.condeferrable
              AND NOT c.condeferred
              AND c.convalidated
        ) THEN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint AS c
                JOIN pg_attribute AS child_attribute
                  ON child_attribute.attrelid = c.conrelid
                 AND child_attribute.attnum = c.conkey[1]
                JOIN pg_attribute AS parent_attribute
                  ON parent_attribute.attrelid = c.confrelid
                 AND parent_attribute.attnum = c.confkey[1]
                WHERE c.contype = 'f'
                  AND c.conrelid = format('public.%I', item.child_table)::regclass
                  AND c.confrelid = format('public.%I', item.parent_table)::regclass
                  AND cardinality(c.conkey) = 1
                  AND cardinality(c.confkey) = 1
                  AND child_attribute.attname = item.child_column
                  AND parent_attribute.attname = item.parent_column
            ) THEN
                RAISE EXCEPTION
                    'Foreign key public.%.% -> public.%.% exists with a definition differing from the expected delete/validation behavior; manual review is required',
                    item.child_table,
                    item.child_column,
                    item.parent_table,
                    item.parent_column;
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_constraint AS existing_constraint
                WHERE existing_constraint.conrelid =
                          format('public.%I', item.child_table)::regclass
                  AND existing_constraint.conname = item.constraint_name
            ) THEN
                RAISE EXCEPTION
                    'Constraint name % already exists on public.% but is not the expected foreign key; manual review is required',
                    item.constraint_name,
                    item.child_table;
            END IF;

            EXECUTE format(
                'ALTER TABLE public.%I ADD CONSTRAINT %I FOREIGN KEY (%I) REFERENCES public.%I (%I)%s',
                item.child_table,
                item.constraint_name,
                item.child_column,
                item.parent_table,
                item.parent_column,
                CASE WHEN item.delete_action = 'c'
                     THEN ' ON DELETE CASCADE'
                     ELSE ''
                END
            );
        END IF;
    END LOOP;
END;
$$;

-- Validate named indexes before accepting them. Column order,
-- table, btree method, validity/readiness, uniqueness, predicate, expression,
-- and INCLUDE-column count must match the model-derived definition.
DO $$
DECLARE
    item RECORD;
    existing_index RECORD;
    expected_columns TEXT[];
    actual_columns TEXT[];
BEGIN
    FOR item IN
        SELECT *
        FROM (VALUES
            ('ix_test_cases_id', 'test_cases', 'id', FALSE),
            ('ix_test_cases_project_id', 'test_cases', 'project_id', FALSE),
            ('ix_test_cases_generation_run_id', 'test_cases', 'generation_run_id', FALSE),
            ('ix_test_case_generation_runs_id', 'test_case_generation_runs', 'id', FALSE),
            ('ix_generation_runs_project_id', 'test_case_generation_runs', 'project_id', FALSE),
            ('ix_generation_runs_created_at', 'test_case_generation_runs', 'created_at', FALSE),
            ('ix_generation_runs_workflow_attempt', 'test_case_generation_runs', 'workflow_run_id,workflow_attempt_number', FALSE),
            ('ix_test_case_evidence_id', 'test_case_evidence', 'id', FALSE),
            ('ix_test_case_evidence_test_case_id', 'test_case_evidence', 'test_case_id', FALSE),
            ('ix_project_requirements_id', 'project_requirements', 'id', FALSE),
            ('ix_project_requirements_project_id', 'project_requirements', 'project_id', FALSE),
            ('ix_projects_id', 'projects', 'id', FALSE),
            ('ix_organizations_id', 'organizations', 'id', FALSE),
            ('ix_users_id', 'users', 'id', FALSE),
            ('ix_users_email', 'users', 'email', TRUE),
            ('ix_workflow_runs_id', 'workflow_runs', 'id', FALSE),
            ('ix_workflow_runs_project_created', 'workflow_runs', 'project_id,created_at', FALSE),
            ('ix_workflow_runs_status', 'workflow_runs', 'status', FALSE),
            ('ix_documents_id', 'documents', 'id', FALSE),
            ('ix_document_chunks_id', 'document_chunks', 'id', FALSE)
        ) AS expected(index_name, table_name, columns_csv, is_unique)
    LOOP
        expected_columns := string_to_array(item.columns_csv, ',');
        SELECT
            i.indexrelid,
            i.indrelid,
            i.indisvalid,
            i.indisready,
            i.indisunique,
            i.indnullsnotdistinct,
            i.indpred IS NULL AS has_no_predicate,
            i.indexprs IS NULL AS has_no_expressions,
            i.indnkeyatts,
            i.indnatts,
            access_method.amname AS access_method,
            index_relation.relnamespace = 'public'::regnamespace
                AND index_relation.relname = item.index_name AS name_is_public,
            pg_get_indexdef(i.indexrelid) AS definition,
            ARRAY(
                SELECT attribute.attname::TEXT
                FROM unnest(i.indkey) WITH ORDINALITY AS key_column(attnum, ordinal)
                JOIN pg_attribute AS attribute
                  ON attribute.attrelid = i.indrelid
                 AND attribute.attnum = key_column.attnum
                WHERE key_column.ordinal <= i.indnkeyatts
                ORDER BY key_column.ordinal
            ) AS key_columns
        INTO existing_index
        FROM pg_class AS index_relation
        LEFT JOIN pg_index AS i
          ON i.indexrelid = index_relation.oid
        LEFT JOIN pg_am AS access_method
          ON access_method.oid = index_relation.relam
        WHERE index_relation.relname = item.index_name
          AND index_relation.relnamespace = 'public'::regnamespace;

        IF FOUND THEN
            actual_columns := existing_index.key_columns;
            IF existing_index.indexrelid IS NULL
               OR NOT existing_index.name_is_public
               OR existing_index.indrelid <> format('public.%I', item.table_name)::regclass
               OR existing_index.access_method <> 'btree'
               OR NOT existing_index.indisvalid
               OR NOT existing_index.indisready
               OR existing_index.indisunique <> item.is_unique
               OR existing_index.indnullsnotdistinct
               OR NOT existing_index.has_no_predicate
               OR NOT existing_index.has_no_expressions
               OR existing_index.indnkeyatts <> cardinality(expected_columns)
               OR existing_index.indnatts <> cardinality(expected_columns)
               OR actual_columns <> expected_columns THEN
                RAISE EXCEPTION
                    'Index name public.% exists with an unexpected definition: %. Expected btree index on public.% (%), ordered as listed, unique=%, valid/ready, without predicate, expressions, or INCLUDE columns; manual review is required',
                    item.index_name,
                    existing_index.definition,
                    item.table_name,
                    item.columns_csv,
                    item.is_unique;
            END IF;
        ELSE
            IF NOT item.is_unique OR NOT EXISTS (
                SELECT 1
                FROM pg_index AS i
                JOIN pg_class AS index_relation ON index_relation.oid = i.indexrelid
                JOIN pg_am AS access_method ON access_method.oid = index_relation.relam
                WHERE i.indrelid = format('public.%I', item.table_name)::regclass
                  AND i.indisunique
                  AND NOT i.indisprimary
                  AND i.indisvalid
                  AND i.indisready
                  AND i.indimmediate
                  AND i.indpred IS NULL
                  AND i.indexprs IS NULL
                  AND i.indnkeyatts = cardinality(expected_columns)
                  AND i.indnatts = cardinality(expected_columns)
                  AND access_method.amname = 'btree'
                  AND NOT i.indnullsnotdistinct
                  AND ARRAY(
                      SELECT attribute.attname::TEXT
                      FROM unnest(i.indkey) WITH ORDINALITY AS key_column(attnum, ordinal)
                      JOIN pg_attribute AS attribute
                        ON attribute.attrelid = i.indrelid
                       AND attribute.attnum = key_column.attnum
                      WHERE key_column.ordinal <= i.indnkeyatts
                      ORDER BY key_column.ordinal
                  ) = expected_columns
            ) THEN
                EXECUTE format(
                    'CREATE %sINDEX %I ON public.%I USING btree (%s)',
                    CASE WHEN item.is_unique THEN 'UNIQUE ' ELSE '' END,
                    item.index_name,
                    item.table_name,
                    item.columns_csv
                );
            END IF;
        END IF;
    END LOOP;
END;
$$;
