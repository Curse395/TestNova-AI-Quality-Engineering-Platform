import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def load_migration(filename: str):
    spec = importlib.util.spec_from_file_location(
        filename.removesuffix(".py"),
        MIGRATION_DIR / filename,
    )
    assert spec is not None
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    return migration


def create_legacy_tables(connection) -> None:
    connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    connection.exec_driver_sql(
        "CREATE TABLE documents (id INTEGER PRIMARY KEY)"
    )
    connection.exec_driver_sql(
        "CREATE TABLE document_chunks (id INTEGER PRIMARY KEY)"
    )
    connection.exec_driver_sql(
        "CREATE TABLE test_case_generation_runs (id INTEGER PRIMARY KEY)"
    )
    connection.exec_driver_sql(
        "CREATE TABLE test_cases (id INTEGER PRIMARY KEY)"
    )


def run_migration(connection, migration, operation: str) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration, operation)()


def test_additive_migrations_upgrade_on_disposable_sqlite():
    engine = sa.create_engine("sqlite://")
    document_migration = load_migration(
        "20261104_01_document_processing_state.py"
    )
    generation_migration = load_migration(
        "20261106_02_test_case_generation_run_link.py"
    )

    with engine.begin() as connection:
        create_legacy_tables(connection)
        run_migration(connection, document_migration, "upgrade")
        run_migration(connection, generation_migration, "upgrade")
        run_migration(connection, generation_migration, "upgrade")

        inspector = sa.inspect(connection)
        document_columns = {
            column["name"] for column in inspector.get_columns("documents")
        }
        chunk_columns = {
            column["name"] for column in inspector.get_columns("document_chunks")
        }
        test_case_columns = {
            column["name"] for column in inspector.get_columns("test_cases")
        }

        assert {
            "processing_status",
            "processing_error",
            "source_type",
            "uploaded_by_user_id",
        } <= document_columns
        assert "source_metadata" in chunk_columns
        assert "generation_run_id" in test_case_columns
        assert "ix_test_cases_generation_run_id" in {
            index["name"] for index in inspector.get_indexes("test_cases")
        }
        assert {
            foreign_key["referred_table"]
            for foreign_key in inspector.get_foreign_keys("documents")
        } == {"users"}
        assert {
            foreign_key["referred_table"]
            for foreign_key in inspector.get_foreign_keys("test_cases")
        } == {"test_case_generation_runs"}


def test_generation_run_migration_is_safe_when_column_already_exists():
    engine = sa.create_engine("sqlite://")
    migration = load_migration(
        "20261106_02_test_case_generation_run_link.py"
    )

    with engine.begin() as connection:
        create_legacy_tables(connection)
        connection.exec_driver_sql(
            "ALTER TABLE test_cases "
            "ADD COLUMN generation_run_id INTEGER "
            "REFERENCES test_case_generation_runs(id)"
        )
        run_migration(connection, migration, "upgrade")

        indexes = {
            index["name"] for index in sa.inspect(connection).get_indexes("test_cases")
        }
        assert "ix_test_cases_generation_run_id" in indexes


def test_workflow_hardening_migration_is_idempotent():
    engine = sa.create_engine("sqlite://")
    migration = load_migration("20261110_01_workflow_hardening.py")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE workflow_runs (id INTEGER PRIMARY KEY, "
            "project_id INTEGER, initiated_by INTEGER, workflow_type TEXT, "
            "status TEXT, input_data TEXT, final_output TEXT, "
            "error_summary TEXT, created_at TEXT, started_at TEXT, "
            "completed_at TEXT, updated_at TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE workflow_tasks (id INTEGER PRIMARY KEY, "
            "workflow_run_id INTEGER, agent_name TEXT, task_type TEXT, "
            "status TEXT, depends_on_task_ids TEXT, input_data TEXT, "
            "output_data TEXT, attempt_count INTEGER, error_details TEXT, "
            "started_at TEXT, completed_at TEXT, created_at TEXT, "
            "updated_at TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE workflow_task_attempts (id INTEGER PRIMARY KEY, "
            "workflow_task_id INTEGER, attempt_number INTEGER, status TEXT, "
            "output_data TEXT, error_details TEXT, started_at TEXT, "
            "completed_at TEXT, created_at TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE test_case_generation_runs (id INTEGER PRIMARY KEY, "
            "workflow_run_id INTEGER, workflow_attempt_number INTEGER)"
        )

        run_migration(connection, migration, "upgrade")
        run_migration(connection, migration, "upgrade")

        workflow_run_columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns("workflow_runs")
        }
        unique_constraints = {
            constraint["name"]
            for constraint in sa.inspect(connection).get_unique_constraints(
                "workflow_task_attempts"
            )
        }
        check_constraints = {
            constraint["name"]
            for constraint in sa.inspect(connection).get_check_constraints(
                "workflow_task_attempts"
            )
        }

        assert "generation_attempt_count" in workflow_run_columns
        assert "uq_workflow_task_attempt_number" in unique_constraints
        assert "ck_workflow_task_attempt_status" in check_constraints


def test_workflow_hardening_migration_rejects_duplicate_keys():
    engine = sa.create_engine("sqlite://")
    migration = load_migration("20261110_01_workflow_hardening.py")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE workflow_runs (id INTEGER PRIMARY KEY, "
            "project_id INTEGER, initiated_by INTEGER, workflow_type TEXT, "
            "status TEXT, input_data TEXT, final_output TEXT, "
            "error_summary TEXT, created_at TEXT, started_at TEXT, "
            "completed_at TEXT, updated_at TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE workflow_task_attempts (id INTEGER PRIMARY KEY, "
            "workflow_task_id INTEGER, attempt_number INTEGER, status TEXT, "
            "output_data TEXT, error_details TEXT, started_at TEXT, "
            "completed_at TEXT, created_at TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE test_case_generation_runs (id INTEGER PRIMARY KEY, "
            "workflow_run_id INTEGER, workflow_attempt_number INTEGER)"
        )
        connection.exec_driver_sql(
            "INSERT INTO workflow_task_attempts "
            "(workflow_task_id, attempt_number, status, started_at, created_at) "
            "VALUES (1, 1, 'running', '2026-01-01', '2026-01-01'), "
            "(1, 1, 'failed', '2026-01-02', '2026-01-02')"
        )

        with pytest.raises(RuntimeError, match="duplicate key found"):
            run_migration(connection, migration, "upgrade")


def test_forward_only_migrations_refuse_to_drop_columns():
    for filename in (
        "20261104_01_document_processing_state.py",
        "20261106_02_test_case_generation_run_link.py",
        "20261110_02_test_type_dimension.py",
        "20261111_01_phase4_traceability.py",
    ):
        migration = load_migration(filename)
        with pytest.raises(RuntimeError, match="forward-only"):
            migration.downgrade()


def test_test_type_migration_is_additive_and_idempotent():
    engine = sa.create_engine("sqlite://")
    migration = load_migration("20261110_02_test_type_dimension.py")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE test_cases (id INTEGER PRIMARY KEY)"
        )
        run_migration(connection, migration, "upgrade")
        run_migration(connection, migration, "upgrade")

        column = next(
            column
            for column in sa.inspect(connection).get_columns("test_cases")
            if column["name"] == "test_type"
        )
        assert column["nullable"] is True
        assert isinstance(column["type"], sa.String)
        assert column["type"].length == 60


def test_phase4_traceability_migration_adds_accounting_and_severity_check():
    engine = sa.create_engine("sqlite://")
    migration = load_migration("20261111_01_phase4_traceability.py")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE test_cases (id INTEGER PRIMARY KEY, severity TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE test_case_generation_runs ("
            "id INTEGER PRIMARY KEY, generated_case_count INTEGER NOT NULL DEFAULT 0)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE projects (id INTEGER PRIMARY KEY)"
        )
        run_migration(connection, migration, "upgrade")
        run_migration(connection, migration, "upgrade")

        inspector = sa.inspect(connection)
        run_columns = {
            column["name"]
            for column in inspector.get_columns("test_case_generation_runs")
        }
        case_checks = {
            item["name"] for item in inspector.get_check_constraints("test_cases")
        }
        assert {
            "requirement_keys",
            "duplicate_rejected_count",
            "invalid_rejected_count",
            "insufficient_evidence_count",
            "final_persisted_count",
            "retry_count",
        } <= run_columns
        assert "ck_test_cases_severity" in case_checks
        assert {"project_requirements", "test_case_requirements"} <= set(
            inspector.get_table_names()
        )
