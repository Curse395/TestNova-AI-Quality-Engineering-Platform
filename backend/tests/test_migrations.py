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


def test_forward_only_migrations_refuse_to_drop_columns():
    for filename in (
        "20261104_01_document_processing_state.py",
        "20261106_02_test_case_generation_run_link.py",
    ):
        migration = load_migration(filename)
        with pytest.raises(RuntimeError, match="forward-only"):
            migration.downgrade()
