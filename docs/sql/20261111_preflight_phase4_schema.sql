-- Read-only preflight for 20261111_supabase_phase4_schema_reconciliation.sql.
-- Run this before the reconciliation file. It performs catalog reads and
-- SELECTs only; findings are emitted as SQL Editor NOTICE messages. It does
-- not create temporary or persistent objects and does not change application
-- data.
--
-- Review all reported violations before applying constraints. The reconciliation
-- script intentionally fails rather than deleting or rewriting rows to make
-- CHECK, UNIQUE, PRIMARY KEY, or FOREIGN KEY constraints pass.
-- If a partially existing requirement table has rows but lacks a required
-- column with no safe model/migration default, the reconciliation's NOT NULL
-- ADD COLUMN will stop. This preflight reports those cases; do not invent
-- values to make the DDL proceed.
--
-- Historical generation-count review: report rows with raw generated
-- candidates and a zero final_persisted_count for manual inspection only.
-- generated_case_count does not establish how many unique cases were
-- persisted. Neither this read-only preflight nor the reconciliation performs
-- an automatic historical-count backfill.

DO $preflight_source_metadata_type$
DECLARE
    actual_type TEXT;
    actual_nullable TEXT;
    actual_default TEXT;
    conversion_status TEXT;
BEGIN
    IF to_regclass('public.document_chunks') IS NULL THEN
        RAISE NOTICE
            'SOURCE METADATA preflight: public.document_chunks is missing; reconciliation will stop for manual review';
        RETURN;
    END IF;

    SELECT c.data_type, c.is_nullable, c.column_default
    INTO actual_type, actual_nullable, actual_default
    FROM information_schema.columns AS c
    WHERE c.table_schema = 'public'
      AND c.table_name = 'document_chunks'
      AND c.column_name = 'source_metadata';

    IF NOT FOUND THEN
        RAISE NOTICE
            'SOURCE METADATA preflight: public.document_chunks.source_metadata is missing; reconciliation will stop for manual review';
        RETURN;
    END IF;

    conversion_status :=
        CASE actual_type
            WHEN 'jsonb' THEN
                CASE
                    WHEN actual_nullable = 'NO'
                        THEN 'required: JSONB will be cast to JSON'
                    ELSE 'manual review: JSONB is nullable; reconciliation stops'
                END
            WHEN 'json' THEN
                CASE
                    WHEN actual_nullable = 'NO'
                        AND regexp_replace(
                            regexp_replace(
                                lower(COALESCE(actual_default, '')),
                                '\s+',
                                '',
                                'g'
                            ),
                            '[()]',
                            '',
                            'g'
                        ) = '''{}''::json'
                        THEN 'not required: already JSON with required nullability/default'
                    ELSE 'manual review: JSON nullability/default differs from model'
                END
            ELSE 'unsupported type: reconciliation will stop for manual review'
        END;

    RAISE NOTICE
        'SOURCE METADATA preflight: current_type=% nullable=% default=% conversion=%',
        actual_type,
        actual_nullable,
        COALESCE(actual_default, '<none>'),
        conversion_status;
END;
$preflight_source_metadata_type$;

DO $preflight_checks$
DECLARE
    item RECORD;
    issue_count BIGINT;
    issue_samples JSONB;
    has_id BOOLEAN;
    row_identifier_expression TEXT;
BEGIN
    FOR item IN
        SELECT *
        FROM (VALUES
            ('test_cases', 'category', 'category IS NULL OR category NOT IN (''positive'', ''negative'', ''boundary'', ''edge'')'),
            ('test_cases', 'priority', 'priority IS NULL OR priority NOT IN (''low'', ''medium'', ''high'', ''critical'')'),
            ('test_cases', 'severity', 'severity IS NULL OR severity NOT IN (''low'', ''medium'', ''high'', ''critical'')'),
            ('test_cases', 'review_status', 'review_status IS NULL OR review_status NOT IN (''draft'', ''approved'', ''rejected'')'),
            ('test_case_generation_runs', 'workflow_attempt_number', 'workflow_attempt_number IS NOT NULL AND workflow_attempt_number <= 0'),
            ('workflow_runs', 'status', 'status IS NULL OR status NOT IN (''pending'', ''running'', ''completed'', ''partially_completed'', ''failed'')')
        ) AS check_items(table_name, column_name, violation_predicate)
    LOOP
        IF to_regclass(format('public.%I', item.table_name)) IS NULL
           OR NOT EXISTS (
               SELECT 1
               FROM information_schema.columns
               WHERE table_schema = 'public'
                 AND table_name = item.table_name
                 AND column_name = item.column_name
           ) THEN
            RAISE NOTICE
                'CHECK preflight skipped for %.%: table or column does not exist yet',
                item.table_name,
                item.column_name;
            CONTINUE;
        END IF;

        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = item.table_name
              AND column_name = 'id'
        )
        INTO has_id;
        row_identifier_expression :=
            CASE WHEN has_id THEN 'id' ELSE 'ctid::text' END;

        EXECUTE format(
            'SELECT count(*) FROM public.%I WHERE %s',
            item.table_name,
            item.violation_predicate
        )
        INTO issue_count;
        EXECUTE format(
            'SELECT COALESCE(jsonb_agg(to_jsonb(sample_rows)), ''[]''::jsonb)
             FROM (
                 SELECT %s AS row_identifier, %I AS invalid_value
                 FROM public.%I
                 WHERE %s
                 ORDER BY row_identifier
                 LIMIT 50
             ) AS sample_rows',
            row_identifier_expression,
            item.column_name,
            item.table_name,
            item.violation_predicate
        )
        INTO issue_samples;

        RAISE NOTICE
            'CHECK %.% violation_count=% sample_rows=%',
            item.table_name,
            item.column_name,
            issue_count,
            issue_samples;
    END LOOP;
END;
$preflight_checks$;

DO $preflight_partial_tables$
DECLARE
    item RECORD;
    row_count BIGINT;
    safety_classification TEXT;
    safety_reason TEXT;
BEGIN
    FOR item IN
        SELECT *
        FROM (VALUES
            ('project_requirements', 'id'),
            ('project_requirements', 'project_id'),
            ('project_requirements', 'requirement_key'),
            ('project_requirements', 'description'),
            ('project_requirements', 'classification'),
            ('project_requirements', 'evidence_chunk_ids'),
            ('project_requirements', 'created_at'),
            ('project_requirements', 'updated_at'),
            ('test_case_requirements', 'id'),
            ('test_case_requirements', 'test_case_id'),
            ('test_case_requirements', 'requirement_id'),
            ('test_case_requirements', 'created_at')
        ) AS required_columns(table_name, column_name)
    LOOP
        IF to_regclass(format('public.%I', item.table_name)) IS NULL
           OR EXISTS (
               SELECT 1
               FROM information_schema.columns
               WHERE table_schema = 'public'
                 AND table_name = item.table_name
                 AND column_name = item.column_name
           ) THEN
            CONTINUE;
        END IF;

        EXECUTE format(
            'SELECT count(*) FROM public.%I',
            item.table_name
        ) INTO row_count;

        IF item.column_name IN ('classification', 'evidence_chunk_ids') THEN
            safety_classification := 'SAFE DEFAULT';
            safety_reason :=
                CASE item.column_name
                    WHEN 'classification'
                        THEN 'reconciliation adds NOT NULL with DEFAULT explicit'
                    ELSE 'reconciliation adds NOT NULL with DEFAULT []::json'
                END;
        ELSIF item.column_name = 'id' AND row_count > 0 THEN
            safety_classification := 'MANUAL REVIEW';
            safety_reason :=
                'reconciliation explicitly raises when a populated table lacks id; it will not assign IDs';
        ELSIF row_count > 0 THEN
            safety_classification := 'MANUAL REVIEW';
            safety_reason :=
                'reconciliation adds this NOT NULL column without a default and will not invent values for existing rows';
        ELSE
            safety_classification := 'SAFE ON EMPTY TABLE';
            safety_reason :=
                'table has no existing rows; reconciliation can add the column without fabricating historical values';
        END IF;

        RAISE NOTICE
            'PARTIAL TABLE COLUMN: table=public.% missing_column=% safety=% reason=% existing_rows=%',
            item.table_name,
            item.column_name,
            safety_classification,
            safety_reason,
            row_count;
    END LOOP;
END;
$preflight_partial_tables$;

DO $preflight_unique$
DECLARE
    item RECORD;
    missing_column TEXT;
    nonnull_predicate TEXT;
    issue_count BIGINT;
    issue_samples JSONB;
BEGIN
    FOR item IN
        SELECT *
        FROM (VALUES
            ('users', 'email'),
            ('test_case_generation_runs', 'workflow_run_id,workflow_attempt_number'),
            ('test_case_evidence', 'test_case_id,chunk_id'),
            ('project_requirements', 'project_id,requirement_key'),
            ('test_case_requirements', 'test_case_id,requirement_id')
        ) AS unique_keys(table_name, columns_csv)
    LOOP
        IF to_regclass(format('public.%I', item.table_name)) IS NULL THEN
            RAISE NOTICE
                'UNIQUE preflight skipped for %: table does not exist; no existing rows can violate this key',
                item.table_name;
            CONTINUE;
        END IF;

        SELECT column_name
        INTO missing_column
        FROM unnest(string_to_array(item.columns_csv, ',')) AS expected_column(column_name)
        WHERE NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = item.table_name
              AND column_name = expected_column.column_name
        )
        LIMIT 1;
        IF missing_column IS NOT NULL THEN
            RAISE NOTICE
                'UNIQUE preflight skipped for %(%): column % does not exist yet',
                item.table_name,
                item.columns_csv,
                missing_column;
            CONTINUE;
        END IF;

        SELECT string_agg(format('%I IS NOT NULL', column_name), ' AND ')
        INTO nonnull_predicate
        FROM unnest(string_to_array(item.columns_csv, ',')) AS key_column(column_name);

        EXECUTE format(
            'SELECT
                 (SELECT count(*) FROM (
                     SELECT %s
                     FROM public.%I
                     WHERE %s
                     GROUP BY %s
                     HAVING count(*) > 1
                 ) AS duplicate_keys),
                 COALESCE((
                     SELECT jsonb_agg(to_jsonb(sample_keys))
                     FROM (
                         SELECT %s, count(*) AS duplicate_count
                         FROM public.%I
                         WHERE %s
                         GROUP BY %s
                         HAVING count(*) > 1
                         ORDER BY %s
                         LIMIT 50
                     ) AS sample_keys
                 ), ''[]''::jsonb)',
            item.columns_csv,
            item.table_name,
            nonnull_predicate,
            item.columns_csv,
            item.columns_csv,
            item.table_name,
            nonnull_predicate,
            item.columns_csv,
            item.columns_csv
        )
        INTO issue_count, issue_samples;

        RAISE NOTICE
            'UNIQUE %.% duplicate_key_count=% sample_keys=%',
            item.table_name,
            item.columns_csv,
            issue_count,
            issue_samples;
    END LOOP;
END;
$preflight_unique$;

DO $preflight_foreign_keys$
DECLARE
    item RECORD;
    missing_column TEXT;
    issue_count BIGINT;
    issue_samples JSONB;
BEGIN
    FOR item IN
        SELECT *
        FROM (VALUES
            ('test_cases', 'project_id', 'projects', 'id'),
            ('test_cases', 'created_by_user_id', 'users', 'id'),
            ('test_cases', 'generation_run_id', 'test_case_generation_runs', 'id'),
            ('test_case_generation_runs', 'project_id', 'projects', 'id'),
            ('test_case_generation_runs', 'created_by_user_id', 'users', 'id'),
            ('test_case_generation_runs', 'workflow_run_id', 'workflow_runs', 'id'),
            ('test_case_evidence', 'test_case_id', 'test_cases', 'id'),
            ('test_case_evidence', 'document_id', 'documents', 'id'),
            ('test_case_evidence', 'chunk_id', 'document_chunks', 'id'),
            ('documents', 'project_id', 'projects', 'id'),
            ('documents', 'uploaded_by_user_id', 'users', 'id'),
            ('document_chunks', 'document_id', 'documents', 'id'),
            ('projects', 'organitzation_id', 'organizations', 'id'),
            ('organizations', 'owner_id', 'users', 'id'),
            ('workflow_runs', 'project_id', 'projects', 'id'),
            ('workflow_runs', 'initiated_by', 'users', 'id'),
            ('project_requirements', 'project_id', 'projects', 'id'),
            ('test_case_requirements', 'test_case_id', 'test_cases', 'id'),
            ('test_case_requirements', 'requirement_id', 'project_requirements', 'id')
        ) AS foreign_keys(child_table, child_column, parent_table, parent_column)
    LOOP
        IF to_regclass(format('public.%I', item.child_table)) IS NULL
           OR to_regclass(format('public.%I', item.parent_table)) IS NULL THEN
            RAISE NOTICE
                'FOREIGN KEY preflight skipped for %.% -> %.%: child or parent table does not exist yet',
                item.child_table,
                item.child_column,
                item.parent_table,
                item.parent_column;
            CONTINUE;
        END IF;

        SELECT expected.column_name
        INTO missing_column
        FROM (VALUES
            (item.child_table, item.child_column),
            (item.parent_table, item.parent_column)
        ) AS expected(table_name, column_name)
        WHERE NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = expected.table_name
              AND column_name = expected.column_name
        )
        LIMIT 1;
        IF missing_column IS NOT NULL THEN
            RAISE NOTICE
                'FOREIGN KEY preflight skipped for %.% -> %.%: column % does not exist yet',
                item.child_table,
                item.child_column,
                item.parent_table,
                item.parent_column,
                missing_column;
            CONTINUE;
        END IF;

        IF (
            SELECT child_column.udt_name
            FROM information_schema.columns AS child_column
            WHERE child_column.table_schema = 'public'
              AND child_column.table_name = item.child_table
              AND child_column.column_name = item.child_column
        ) IS DISTINCT FROM (
            SELECT parent_column.udt_name
            FROM information_schema.columns AS parent_column
            WHERE parent_column.table_schema = 'public'
              AND parent_column.table_name = item.parent_table
              AND parent_column.column_name = item.parent_column
        ) THEN
            RAISE NOTICE
                'FOREIGN KEY preflight manual review for %.% -> %.%: child and parent column types differ',
                item.child_table,
                item.child_column,
                item.parent_table,
                item.parent_column;
            CONTINUE;
        END IF;

        EXECUTE format(
            'SELECT
                 (SELECT count(*)
                  FROM public.%I AS child
                  LEFT JOIN public.%I AS parent
                    ON parent.%I = child.%I
                  WHERE child.%I IS NOT NULL
                    AND parent.%I IS NULL),
                 COALESCE((
                     SELECT jsonb_agg(to_jsonb(sample_rows))
                     FROM (
                         SELECT child.%I AS orphan_value
                         FROM public.%I AS child
                         LEFT JOIN public.%I AS parent
                           ON parent.%I = child.%I
                         WHERE child.%I IS NOT NULL
                           AND parent.%I IS NULL
                         ORDER BY child.%I
                         LIMIT 50
                     ) AS sample_rows
                 ), ''[]''::jsonb)',
            item.child_table,
            item.parent_table,
            item.parent_column,
            item.child_column,
            item.child_column,
            item.parent_column,
            item.child_column,
            item.child_table,
            item.parent_table,
            item.parent_column,
            item.child_column,
            item.child_column,
            item.parent_column,
            item.child_column
        )
        INTO issue_count, issue_samples;

        RAISE NOTICE
            'FOREIGN KEY %.% -> %.% orphan_count=% sample_rows=%',
            item.child_table,
            item.child_column,
            item.parent_table,
            item.parent_column,
            issue_count,
            issue_samples;
    END LOOP;
END;
$preflight_foreign_keys$;

DO $preflight_primary_keys$
DECLARE
    target_table TEXT;
    issue_count BIGINT;
    null_count BIGINT;
    issue_samples JSONB;
BEGIN
    FOREACH target_table IN ARRAY ARRAY[
        'test_cases',
        'test_case_generation_runs',
        'test_case_evidence',
        'projects',
        'organizations',
        'users',
        'documents',
        'document_chunks',
        'project_requirements',
        'test_case_requirements',
        'workflow_runs'
    ]
    LOOP
        IF to_regclass(format('public.%I', target_table)) IS NULL THEN
            RAISE NOTICE
                'PRIMARY KEY preflight skipped for public.%: table does not exist yet',
                target_table;
            CONTINUE;
        END IF;

        IF NOT EXISTS (
               SELECT 1
               FROM information_schema.columns
               WHERE table_schema = 'public'
                 AND table_name = target_table
                 AND column_name = 'id'
           ) THEN
            RAISE NOTICE
                'PRIMARY KEY manual review required for public.%: id column is missing; reconciliation will not invent IDs',
                target_table;
            CONTINUE;
        END IF;

        EXECUTE format(
            'SELECT
                 (SELECT count(*) FROM (
                     SELECT id FROM public.%I
                     WHERE id IS NOT NULL
                     GROUP BY id
                     HAVING count(*) > 1
                 ) AS duplicate_ids),
                 (SELECT count(*) FROM public.%I WHERE id IS NULL),
                 COALESCE((
                     SELECT jsonb_agg(to_jsonb(sample_ids))
                     FROM (
                         SELECT id, count(*) AS duplicate_count
                         FROM public.%I
                         WHERE id IS NOT NULL
                         GROUP BY id
                         HAVING count(*) > 1
                         ORDER BY id
                         LIMIT 50
                     ) AS sample_ids
                 ), ''[]''::jsonb)',
            target_table,
            target_table,
            target_table
        )
        INTO issue_count, null_count, issue_samples;

        RAISE NOTICE
            'PRIMARY KEY public.%(id) duplicate_id_count=% null_id_count=% sample_duplicates=%',
            target_table,
            issue_count,
            null_count,
            issue_samples;
    END LOOP;
END;
$preflight_primary_keys$;

DO $preflight_historical_counts$
DECLARE
    historical_count BIGINT;
    historical_rows JSONB;
    has_final_count BOOLEAN;
    historical_predicate TEXT;
BEGIN
    IF to_regclass('public.test_case_generation_runs') IS NULL
       OR NOT EXISTS (
           SELECT 1
           FROM information_schema.columns
           WHERE table_schema = 'public'
             AND table_name = 'test_case_generation_runs'
             AND column_name = 'generated_case_count'
       ) THEN
        RAISE NOTICE
            'Historical-count report unavailable: generation-run table or generated_case_count is missing';
        RETURN;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'test_case_generation_runs'
          AND column_name = 'id'
    ) THEN
        RAISE NOTICE
            'Historical-count report unavailable: generation-run id column is missing';
        RETURN;
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'test_case_generation_runs'
          AND column_name = 'final_persisted_count'
    )
    INTO has_final_count;

    historical_predicate :=
        CASE
            WHEN has_final_count
                THEN 'final_persisted_count = 0 AND generated_case_count > 0'
            ELSE 'generated_case_count > 0'
        END;

    EXECUTE format(
        'SELECT
             (SELECT count(*) FROM public.test_case_generation_runs WHERE %s),
             COALESCE((
                 SELECT jsonb_agg(to_jsonb(sample_rows))
                 FROM (
                     SELECT id,
                            generated_case_count
                            %s
                     FROM public.test_case_generation_runs
                     WHERE %s
                     ORDER BY id
                     LIMIT 100
                 ) AS sample_rows
             ), ''[]''::jsonb)',
        historical_predicate,
        CASE
            WHEN has_final_count THEN ', final_persisted_count'
            ELSE ''
        END,
        historical_predicate
    )
    INTO historical_count, historical_rows;

    RAISE NOTICE
        'Historical generation-run rows with generated candidates and no recorded final count: % row(s); no automatic backfill is performed; sample rows=%',
        historical_count,
        historical_rows;
END;
$preflight_historical_counts$;
