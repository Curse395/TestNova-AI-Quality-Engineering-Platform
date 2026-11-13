-- Run after manually reviewing/applying
-- 20261111_supabase_phase4_schema_reconciliation.sql.
-- Returns only absent/mismatched expected objects; zero rows means the
-- enumerated presence checks passed. Check expressions are checked by name and
-- validation state; confirm their displayed pg_get_constraintdef definitions
-- separately if the database had constraints with pre-existing names.
WITH expected_columns(
    table_name,
    column_name,
    expected_type,
    expected_nullable,
    expected_default
) AS (
    VALUES
        ('projects', 'id', 'integer', 'NO', 'SERIAL'),
        ('projects', 'name', 'character varying', 'NO', NULL),
        ('projects', 'description', 'character varying', 'YES', NULL),
        ('projects', 'organitzation_id', 'integer', 'YES', NULL),
        ('projects', 'created_at', 'timestamp without time zone', 'YES', NULL),
        ('organizations', 'id', 'integer', 'NO', 'SERIAL'),
        ('organizations', 'name', 'character varying', 'NO', NULL),
        ('organizations', 'owner_id', 'integer', 'YES', NULL),
        ('organizations', 'created_at', 'timestamp without time zone', 'YES', NULL),
        ('users', 'id', 'integer', 'NO', 'SERIAL'),
        ('users', 'name', 'character varying', 'YES', NULL),
        ('users', 'email', 'character varying', 'NO', NULL),
        ('users', 'password_hash', 'character varying', 'NO', NULL),
        ('users', 'created_at', 'timestamp without time zone', 'YES', NULL),
        ('documents', 'id', 'integer', 'NO', 'SERIAL'),
        ('documents', 'filename', 'character varying', 'NO', NULL),
        ('documents', 'content_type', 'character varying', 'NO', NULL),
        ('documents', 'storage_path', 'character varying', 'NO', NULL),
        ('documents', 'project_id', 'integer', 'NO', NULL),
        ('documents', 'uploaded_at', 'timestamp without time zone', 'YES', NULL),
        ('documents', 'processing_status', 'character varying(20)', 'NO', '''uploaded'''),
        ('documents', 'processing_error', 'text', 'YES', NULL),
        ('documents', 'source_type', 'character varying(30)', 'NO', '''document'''),
        ('documents', 'uploaded_by_user_id', 'integer', 'YES', NULL),
        ('document_chunks', 'id', 'integer', 'NO', 'SERIAL'),
        ('document_chunks', 'document_id', 'integer', 'NO', NULL),
        ('document_chunks', 'chunk_index', 'integer', 'NO', NULL),
        ('document_chunks', 'content', 'text', 'NO', NULL),
        ('document_chunks', 'created_at', 'timestamp without time zone', 'YES', NULL),
        ('document_chunks', 'source_metadata', 'json', 'NO', '''{}'''),
        ('test_cases', 'id', 'integer', 'NO', 'SERIAL'),
        ('test_cases', 'project_id', 'integer', 'NO', NULL),
        ('test_cases', 'created_by_user_id', 'integer', 'NO', NULL),
        ('test_cases', 'title', 'character varying(200)', 'NO', NULL),
        ('test_cases', 'description', 'text', 'NO', NULL),
        ('test_cases', 'test_type', 'character varying(60)', 'YES', NULL),
        ('test_cases', 'category', 'character varying(20)', 'NO', NULL),
        ('test_cases', 'priority', 'character varying(20)', 'NO', NULL),
        ('test_cases', 'severity', 'character varying(20)', 'NO', '''medium'''),
        ('test_cases', 'preconditions', 'text', 'YES', NULL),
        ('test_cases', 'steps', 'json', 'NO', NULL),
        ('test_cases', 'expected_result', 'text', 'NO', NULL),
        ('test_cases', 'review_status', 'character varying(20)', 'NO', NULL),
        ('test_cases', 'created_at', 'timestamp without time zone', 'NO', NULL),
        ('test_cases', 'updated_at', 'timestamp without time zone', 'NO', NULL),
        ('test_cases', 'generation_run_id', 'integer', 'YES', NULL),
        ('test_case_generation_runs', 'id', 'integer', 'NO', 'SERIAL'),
        ('test_case_generation_runs', 'project_id', 'integer', 'NO', NULL),
        ('test_case_generation_runs', 'created_by_user_id', 'integer', 'NO', NULL),
        ('test_case_generation_runs', 'requirements_prompt', 'text', 'NO', NULL),
        ('test_case_generation_runs', 'requested_categories', 'json', 'NO', NULL),
        ('test_case_generation_runs', 'requirement_keys', 'json', 'NO', '''[]'''),
        ('test_case_generation_runs', 'max_cases', 'integer', 'NO', NULL),
        ('test_case_generation_runs', 'status', 'character varying(20)', 'NO', NULL),
        ('test_case_generation_runs', 'generated_case_count', 'integer', 'NO', NULL),
        ('test_case_generation_runs', 'duplicate_rejected_count', 'integer', 'NO', '0'),
        ('test_case_generation_runs', 'invalid_rejected_count', 'integer', 'NO', '0'),
        ('test_case_generation_runs', 'insufficient_evidence_count', 'integer', 'NO', '0'),
        ('test_case_generation_runs', 'final_persisted_count', 'integer', 'NO', '0'),
        ('test_case_generation_runs', 'retry_count', 'integer', 'NO', '0'),
        ('test_case_generation_runs', 'created_at', 'timestamp without time zone', 'NO', NULL),
        ('test_case_generation_runs', 'workflow_run_id', 'integer', 'YES', NULL),
        ('test_case_generation_runs', 'workflow_attempt_number', 'integer', 'YES', NULL),
        ('test_case_evidence', 'id', 'integer', 'NO', 'SERIAL'),
        ('test_case_evidence', 'test_case_id', 'integer', 'NO', NULL),
        ('test_case_evidence', 'document_id', 'integer', 'NO', NULL),
        ('test_case_evidence', 'chunk_id', 'integer', 'NO', NULL),
        ('test_case_evidence', 'created_at', 'timestamp without time zone', 'NO', NULL),
        ('workflow_runs', 'id', 'integer', 'NO', 'SERIAL'),
        ('workflow_runs', 'project_id', 'integer', 'NO', NULL),
        ('workflow_runs', 'initiated_by', 'integer', 'NO', NULL),
        ('workflow_runs', 'workflow_type', 'character varying(40)', 'NO', NULL),
        ('workflow_runs', 'status', 'character varying(30)', 'NO', NULL),
        ('workflow_runs', 'input_data', 'json', 'NO', NULL),
        ('workflow_runs', 'final_output', 'json', 'YES', NULL),
        ('workflow_runs', 'error_summary', 'text', 'YES', NULL),
        ('workflow_runs', 'generation_attempt_count', 'integer', 'NO', '0'),
        ('workflow_runs', 'created_at', 'timestamp without time zone', 'NO', NULL),
        ('workflow_runs', 'started_at', 'timestamp without time zone', 'YES', NULL),
        ('workflow_runs', 'completed_at', 'timestamp without time zone', 'YES', NULL),
        ('workflow_runs', 'updated_at', 'timestamp without time zone', 'NO', NULL),
        ('project_requirements', 'id', 'integer', 'NO', 'SERIAL'),
        ('project_requirements', 'project_id', 'integer', 'NO', NULL),
        ('project_requirements', 'requirement_key', 'character varying(200)', 'NO', NULL),
        ('project_requirements', 'description', 'text', 'NO', NULL),
        ('project_requirements', 'classification', 'character varying(20)', 'NO', '''explicit'''),
        ('project_requirements', 'evidence_chunk_ids', 'json', 'NO', '''[]'''),
        ('project_requirements', 'created_at', 'timestamp without time zone', 'NO', NULL),
        ('project_requirements', 'updated_at', 'timestamp without time zone', 'NO', NULL),
        ('test_case_requirements', 'id', 'integer', 'NO', 'SERIAL'),
        ('test_case_requirements', 'test_case_id', 'integer', 'NO', NULL),
        ('test_case_requirements', 'requirement_id', 'integer', 'NO', NULL),
        ('test_case_requirements', 'created_at', 'timestamp without time zone', 'NO', NULL)
),
column_actual AS (
    SELECT
        e.*,
        c.data_type,
        c.character_maximum_length,
        c.is_nullable,
        c.column_default,
        CASE
            WHEN c.character_maximum_length IS NOT NULL
                THEN format('character varying(%s)', c.character_maximum_length)
            WHEN c.data_type = 'USER-DEFINED'
                THEN c.udt_name
            ELSE c.data_type
        END AS actual_type,
        CASE
            WHEN c.column_default IS NULL THEN NULL
            ELSE regexp_replace(
                c.column_default,
                '::[[:alnum:]_ ]+$',
                ''
            )
        END AS normalized_default
    FROM expected_columns AS e
    LEFT JOIN information_schema.columns AS c
      ON c.table_schema = 'public'
     AND c.table_name = e.table_name
     AND c.column_name = e.column_name
),
missing_columns AS (
    SELECT
        'column' AS object_type,
        format('public.%I.%I', table_name, column_name) AS object_name
    FROM column_actual
    WHERE data_type IS NULL
),
mismatched_columns AS (
    SELECT
        'column definition' AS object_type,
        format(
            'public.%I.%I expected type=%s nullable=%s default=%s; actual type=%s nullable=%s default=%s',
            table_name,
            column_name,
            expected_type,
            expected_nullable,
            COALESCE(expected_default, '<none>'),
            COALESCE(actual_type, '<missing>'),
            COALESCE(is_nullable, '<missing>'),
            COALESCE(normalized_default, '<none>')
        ) AS object_name
    FROM column_actual
    WHERE data_type IS NOT NULL
      AND (
          actual_type <> expected_type
          OR is_nullable <> expected_nullable
          OR (
              expected_default = 'SERIAL'
              AND pg_get_serial_sequence(
                  format('public.%I', table_name),
                  column_name
              ) IS NULL
          )
          OR (
              expected_default IS DISTINCT FROM 'SERIAL'
              AND normalized_default IS DISTINCT FROM expected_default
          )
      )
),
expected_tables(table_name) AS (
    VALUES ('project_requirements'), ('test_case_requirements')
),
missing_tables(object_type, object_name) AS (
    SELECT 'table', format('public.%I', e.table_name)
    FROM expected_tables AS e
    WHERE to_regclass(format('public.%I', e.table_name)) IS NULL
),
expected_indexes(index_name, table_name, columns_csv, is_unique) AS (
    VALUES
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
),
missing_indexes AS (
    SELECT
        'index missing' AS object_type,
        format('public.%I ON %I(%s)', e.index_name, e.table_name, e.columns_csv) AS object_name
    FROM expected_indexes AS e
    WHERE NOT EXISTS (
        SELECT 1
        FROM pg_class AS index_relation
        WHERE index_relation.relnamespace = 'public'::regnamespace
          AND index_relation.relname = e.index_name
    )
      AND NOT (
          e.is_unique
          AND EXISTS (
              SELECT 1
              FROM pg_index AS i
              JOIN pg_class AS index_relation ON index_relation.oid = i.indexrelid
              JOIN pg_am AS access_method ON access_method.oid = index_relation.relam
              WHERE i.indrelid = to_regclass(format('public.%I', e.table_name))
                AND i.indisunique
                AND NOT i.indisprimary
                AND i.indisvalid
                AND i.indisready
                AND i.indimmediate
                AND i.indpred IS NULL
                AND i.indexprs IS NULL
                AND i.indnkeyatts = cardinality(string_to_array(e.columns_csv, ','))
                AND i.indnatts = cardinality(string_to_array(e.columns_csv, ','))
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
                ) = string_to_array(e.columns_csv, ',')
          )
      )
),
index_mismatches AS (
    SELECT
        'index mismatch' AS object_type,
        format(
            'public.%I expected table=public.%I columns=(%s) method=btree valid/ready unique=%s no-predicate no-expressions no-INCLUDE; actual=%s',
            e.index_name,
            e.table_name,
            e.columns_csv,
            e.is_unique,
            CASE
                WHEN i.indexrelid IS NULL THEN '<not an index>'
                ELSE pg_get_indexdef(i.indexrelid)
            END
        ) AS object_name
    FROM expected_indexes AS e
    JOIN pg_class AS index_relation
      ON index_relation.relnamespace = 'public'::regnamespace
     AND index_relation.relname = e.index_name
    LEFT JOIN pg_index AS i ON i.indexrelid = index_relation.oid
    LEFT JOIN pg_am AS access_method ON access_method.oid = index_relation.relam
    WHERE i.indexrelid IS NULL
       OR i.indrelid <> to_regclass(format('public.%I', e.table_name))
       OR access_method.amname <> 'btree'
       OR NOT i.indisvalid
       OR NOT i.indisready
       OR i.indisunique IS DISTINCT FROM e.is_unique
       OR i.indnullsnotdistinct
       OR i.indpred IS NOT NULL
       OR i.indexprs IS NOT NULL
       OR i.indnkeyatts <> cardinality(string_to_array(e.columns_csv, ','))
       OR i.indnatts <> cardinality(string_to_array(e.columns_csv, ','))
       OR ARRAY(
              SELECT attribute.attname::TEXT
              FROM unnest(i.indkey) WITH ORDINALITY AS key_column(attnum, ordinal)
              JOIN pg_attribute AS attribute
                ON attribute.attrelid = i.indrelid
               AND attribute.attnum = key_column.attnum
              WHERE key_column.ordinal <= i.indnkeyatts
              ORDER BY key_column.ordinal
          ) <> string_to_array(e.columns_csv, ',')
),
expected_constraints(table_name, constraint_name, expected_definition) AS (
    VALUES
        ('test_cases', 'ck_test_case_category', 'CHECK (((category)::text = ANY ((ARRAY[''positive''::character varying, ''negative''::character varying, ''boundary''::character varying, ''edge''::character varying])::text[])))'),
        ('test_cases', 'ck_test_cases_priority', 'CHECK (((priority)::text = ANY ((ARRAY[''low''::character varying, ''medium''::character varying, ''high''::character varying, ''critical''::character varying])::text[])))'),
        ('test_cases', 'ck_test_cases_severity', 'CHECK (((severity)::text = ANY ((ARRAY[''low''::character varying, ''medium''::character varying, ''high''::character varying, ''critical''::character varying])::text[])))'),
        ('test_cases', 'ck_test_cases_review_status', 'CHECK (((review_status)::text = ANY ((ARRAY[''draft''::character varying, ''approved''::character varying, ''rejected''::character varying])::text[])))'),
        ('test_case_generation_runs', 'ck_generation_runs_workflow_attempt_positive', 'CHECK (((workflow_attempt_number IS NULL) OR (workflow_attempt_number > 0)))'),
        ('workflow_runs', 'ck_workflow_runs_status', 'CHECK (((status)::text = ANY ((ARRAY[''pending''::character varying, ''running''::character varying, ''completed''::character varying, ''partially_completed''::character varying, ''failed''::character varying])::text[])))')
),
missing_constraints AS (
    SELECT
        'check constraint' AS object_type,
        format(
            'public.%I.%I status=%s expected=%s actual=%s',
            e.table_name,
            e.constraint_name,
            CASE
                WHEN c.oid IS NULL THEN 'missing'
                WHEN c.contype <> 'c' THEN 'wrong constraint type'
                WHEN NOT c.convalidated THEN 'unvalidated'
                ELSE 'incorrect expression'
            END,
            e.expected_definition,
            COALESCE(pg_get_constraintdef(c.oid, false), '<missing>')
        ) AS object_name
    FROM expected_constraints AS e
    LEFT JOIN pg_constraint AS c
      ON c.conrelid = to_regclass(format('public.%I', e.table_name))
     AND c.conname = e.constraint_name
    WHERE c.oid IS NULL
       OR c.contype <> 'c'
       OR NOT c.convalidated
       OR regexp_replace(
              lower(COALESCE(pg_get_constraintdef(c.oid, false), '')),
              '\s+',
              '',
              'g'
          ) <> regexp_replace(lower(e.expected_definition), '\s+', '', 'g')
),
expected_unique_keys(table_name, columns_csv) AS (
    VALUES
        ('users', 'email'),
        ('test_case_generation_runs', 'workflow_run_id,workflow_attempt_number'),
        ('test_case_evidence', 'test_case_id,chunk_id'),
        ('project_requirements', 'project_id,requirement_key'),
        ('test_case_requirements', 'test_case_id,requirement_id')
),
missing_unique_keys AS (
    SELECT
        'unique constraint' AS object_type,
        format('public.%I UNIQUE (%s)', e.table_name, e.columns_csv) AS object_name
    FROM expected_unique_keys AS e
    WHERE NOT EXISTS (
        SELECT 1
        FROM pg_index AS i
        JOIN pg_class AS index_relation ON index_relation.oid = i.indexrelid
        JOIN pg_am AS access_method ON access_method.oid = index_relation.relam
        WHERE i.indrelid = to_regclass(format('public.%I', e.table_name))
          AND i.indisunique
          AND NOT i.indisprimary
          AND i.indisvalid
          AND i.indisready
          AND i.indimmediate
          AND i.indpred IS NULL
          AND i.indexprs IS NULL
          AND i.indnkeyatts = cardinality(string_to_array(e.columns_csv, ','))
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
              FROM unnest(string_to_array(e.columns_csv, ',')) AS expected_column(column_name)
          )
    )
),
expected_primary_keys(table_name, column_name) AS (
    VALUES
        ('test_cases', 'id'),
        ('test_case_generation_runs', 'id'),
        ('test_case_evidence', 'id'),
        ('projects', 'id'),
        ('organizations', 'id'),
        ('users', 'id'),
        ('documents', 'id'),
        ('document_chunks', 'id'),
        ('project_requirements', 'id'),
        ('test_case_requirements', 'id'),
        ('workflow_runs', 'id')
),
missing_primary_keys AS (
    SELECT
        'primary key' AS object_type,
        format('public.%I(%I)', e.table_name, e.column_name) AS object_name
    FROM expected_primary_keys AS e
    WHERE NOT EXISTS (
        SELECT 1
        FROM pg_constraint AS c
        JOIN pg_attribute AS a
          ON a.attrelid = c.conrelid
         AND a.attnum = c.conkey[1]
        WHERE c.contype = 'p'
          AND c.conrelid = to_regclass(format('public.%I', e.table_name))
          AND cardinality(c.conkey) = 1
          AND a.attname = e.column_name
    )
),
expected_foreign_keys(
    child_table, child_column, parent_table, parent_column, delete_action
) AS (
    VALUES
        ('test_cases', 'project_id', 'projects', 'id', 'a'),
        ('test_cases', 'created_by_user_id', 'users', 'id', 'a'),
        ('test_cases', 'generation_run_id', 'test_case_generation_runs', 'id', 'a'),
        ('test_case_generation_runs', 'project_id', 'projects', 'id', 'a'),
        ('test_case_generation_runs', 'created_by_user_id', 'users', 'id', 'a'),
        ('test_case_generation_runs', 'workflow_run_id', 'workflow_runs', 'id', 'a'),
        ('test_case_evidence', 'test_case_id', 'test_cases', 'id', 'c'),
        ('test_case_evidence', 'document_id', 'documents', 'id', 'a'),
        ('test_case_evidence', 'chunk_id', 'document_chunks', 'id', 'a'),
        ('documents', 'project_id', 'projects', 'id', 'a'),
        ('documents', 'uploaded_by_user_id', 'users', 'id', 'a'),
        ('document_chunks', 'document_id', 'documents', 'id', 'a'),
        ('projects', 'organitzation_id', 'organizations', 'id', 'a'),
        ('organizations', 'owner_id', 'users', 'id', 'a'),
        ('workflow_runs', 'project_id', 'projects', 'id', 'a'),
        ('workflow_runs', 'initiated_by', 'users', 'id', 'a'),
        ('project_requirements', 'project_id', 'projects', 'id', 'a'),
        ('test_case_requirements', 'test_case_id', 'test_cases', 'id', 'c'),
        ('test_case_requirements', 'requirement_id', 'project_requirements', 'id', 'c')
),
missing_foreign_keys AS (
    SELECT
        'foreign key' AS object_type,
        format(
            'public.%I(%I) -> public.%I(%I), delete_action=%s',
            e.child_table,
            e.child_column,
            e.parent_table,
            e.parent_column,
            e.delete_action
        ) AS object_name
    FROM expected_foreign_keys AS e
    WHERE NOT EXISTS (
        SELECT 1
        FROM pg_constraint AS c
        JOIN pg_attribute AS child_attribute
          ON child_attribute.attrelid = c.conrelid
         AND child_attribute.attnum = c.conkey[1]
        JOIN pg_attribute AS parent_attribute
          ON parent_attribute.attrelid = c.confrelid
         AND parent_attribute.attnum = c.confkey[1]
        WHERE c.contype = 'f'
          AND c.convalidated
          AND c.conrelid = to_regclass(format('public.%I', e.child_table))
          AND c.confrelid = to_regclass(format('public.%I', e.parent_table))
          AND cardinality(c.conkey) = 1
          AND cardinality(c.confkey) = 1
          AND child_attribute.attname = e.child_column
          AND parent_attribute.attname = e.parent_column
          AND c.confdeltype::text = e.delete_action
          AND c.confupdtype::text = 'a'
          AND c.confmatchtype::text = 's'
          AND NOT c.condeferrable
          AND NOT c.condeferred
    )
)
SELECT object_type, object_name FROM missing_columns
UNION ALL
SELECT object_type, object_name FROM mismatched_columns
UNION ALL
SELECT object_type, object_name FROM missing_tables
UNION ALL
SELECT object_type, object_name FROM missing_indexes
UNION ALL
SELECT object_type, object_name FROM index_mismatches
UNION ALL
SELECT object_type, object_name FROM missing_constraints
UNION ALL
SELECT object_type, object_name FROM missing_unique_keys
UNION ALL
SELECT object_type, object_name FROM missing_primary_keys
UNION ALL
SELECT object_type, object_name FROM missing_foreign_keys
ORDER BY object_type, object_name;
