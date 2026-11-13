"""Add test-case severity, requirement traceability, and generation accounting.

Revision ID: 20261111_01
Revises: 20261110_02
"""

from alembic import op
import sqlalchemy as sa

revision = "20261111_01"
down_revision = "20261110_02"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def upgrade() -> None:
    if "severity" not in _column_names("test_cases"):
        op.add_column(
            "test_cases",
            sa.Column(
                "severity",
                sa.String(length=20),
                nullable=False,
                server_default="medium",
            ),
        )
    existing_severity_checks = {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(
            "test_cases"
        )
    }
    if "ck_test_cases_severity" not in existing_severity_checks:
        if not op.get_context().as_sql:
            invalid_severity = op.get_bind().execute(
                sa.text(
                    "SELECT id, severity FROM test_cases "
                    "WHERE severity NOT IN ('low', 'medium', 'high', 'critical') "
                    "LIMIT 1"
                )
            ).first()
            if invalid_severity is not None:
                raise RuntimeError(
                    "Cannot add the test-case severity constraint; an invalid "
                    f"severity value exists on test case {invalid_severity[0]!r}. "
                    "Review the data and prepare a separately approved correction."
                )
        if op.get_context().dialect.name == "sqlite":
            with op.batch_alter_table("test_cases") as batch_op:
                batch_op.create_check_constraint(
                    "ck_test_cases_severity",
                    "severity IN ('low', 'medium', 'high', 'critical')",
                )
        else:
            op.create_check_constraint(
                "ck_test_cases_severity",
                "test_cases",
                "severity IN ('low', 'medium', 'high', 'critical')",
            )
    existing_run_columns = _column_names("test_case_generation_runs")
    if "requirement_keys" not in existing_run_columns:
        op.add_column(
            "test_case_generation_runs",
            sa.Column(
                "requirement_keys",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )
    for column_name in (
        "duplicate_rejected_count",
        "invalid_rejected_count",
        "insufficient_evidence_count",
        "final_persisted_count",
        "retry_count",
    ):
        if column_name not in existing_run_columns:
            op.add_column(
                "test_case_generation_runs",
                sa.Column(
                    column_name,
                    sa.Integer(),
                    nullable=False,
                    server_default=sa.text("0"),
                ),
            )

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "project_requirements" not in tables:
        op.create_table(
            "project_requirements",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("requirement_key", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column(
                "classification",
                sa.String(length=20),
                nullable=False,
                server_default="explicit",
            ),
            sa.Column(
                "evidence_chunk_ids",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.UniqueConstraint(
                "project_id",
                "requirement_key",
                name="uq_project_requirements_project_key",
            ),
        )
    if "ix_project_requirements_project_id" not in {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes("project_requirements")
    }:
        op.create_index(
            "ix_project_requirements_project_id",
            "project_requirements",
            ["project_id"],
        )

    if "test_case_requirements" not in tables:
        op.create_table(
            "test_case_requirements",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("test_case_id", sa.Integer(), nullable=False),
            sa.Column("requirement_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["test_case_id"],
                ["test_cases.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["requirement_id"],
                ["project_requirements.id"],
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint(
                "test_case_id",
                "requirement_id",
                name="uq_test_case_requirements_case_requirement",
            ),
        )

    if not op.get_context().as_sql:
        op.get_bind().execute(
            sa.text(
                "UPDATE test_case_generation_runs "
                "SET final_persisted_count = generated_case_count "
                "WHERE final_persisted_count = 0 AND generated_case_count > 0"
            )
        )


def downgrade() -> None:
    raise RuntimeError(
        "This migration is forward-only. Preserve generated test cases and "
        "requirement traceability; use a reviewed forward correction."
    )
