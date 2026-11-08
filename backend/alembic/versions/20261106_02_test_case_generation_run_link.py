"""Add the generated test-case run link.

Revision ID: 20261106_02
Revises: 20261104_01
"""

from alembic import op
import sqlalchemy as sa

revision = "20261106_02"
down_revision = "20261104_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().as_sql:
        if op.get_context().dialect.name == "sqlite":
            op.execute(
                "ALTER TABLE test_cases ADD COLUMN generation_run_id "
                "INTEGER REFERENCES test_case_generation_runs (id)"
            )
        else:
            op.add_column(
                "test_cases",
                sa.Column(
                    "generation_run_id",
                    sa.Integer(),
                    sa.ForeignKey(
                        "test_case_generation_runs.id",
                        name=(
                            "fk_test_cases_generation_run_id_"
                            "test_case_generation_runs"
                        ),
                    ),
                    nullable=True,
                ),
            )
        op.create_index(
            "ix_test_cases_generation_run_id",
            "test_cases",
            ["generation_run_id"],
        )
        return

    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if not inspector.has_table("test_cases"):
        raise RuntimeError(
            "The test_cases table must exist before adding generation_run_id."
        )
    if not inspector.has_table("test_case_generation_runs"):
        raise RuntimeError(
            "The test_case_generation_runs table must exist before adding "
            "generation_run_id."
        )

    columns = {column["name"] for column in inspector.get_columns("test_cases")}
    if "generation_run_id" not in columns:
        if connection.dialect.name == "sqlite":
            op.execute(
                "ALTER TABLE test_cases ADD COLUMN generation_run_id "
                "INTEGER REFERENCES test_case_generation_runs (id)"
            )
        else:
            op.add_column(
                "test_cases",
                sa.Column(
                    "generation_run_id",
                    sa.Integer(),
                    sa.ForeignKey(
                        "test_case_generation_runs.id",
                        name=(
                            "fk_test_cases_generation_run_id_"
                            "test_case_generation_runs"
                        ),
                    ),
                    nullable=True,
                ),
            )

    indexes = {index["name"] for index in inspector.get_indexes("test_cases")}
    if "ix_test_cases_generation_run_id" not in indexes:
        op.create_index(
            "ix_test_cases_generation_run_id",
            "test_cases",
            ["generation_run_id"],
        )


def downgrade() -> None:
    raise RuntimeError(
        "This migration is intentionally forward-only. Preserve generation "
        "history and prepare a reviewed forward migration instead of dropping "
        "the link."
    )
