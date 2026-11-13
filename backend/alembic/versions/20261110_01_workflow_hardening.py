"""Add workflow attempt integrity and lifetime generation accounting.

Revision ID: 20261110_01
Revises: 20261109_01
"""

from alembic import op
import sqlalchemy as sa

revision = "20261110_01"
down_revision = "20261109_01"
branch_labels = None
depends_on = None


def _reject_duplicate_keys(table: str, columns: tuple[str, ...]) -> None:
    if op.get_context().as_sql:
        return
    grouped_columns = ", ".join(columns)
    duplicates = op.get_bind().execute(
        sa.text(
            f"SELECT {grouped_columns} FROM {table} "
            f"WHERE " + " AND ".join(f"{column} IS NOT NULL" for column in columns)
            + f" GROUP BY {grouped_columns} HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicates is not None:
        raise RuntimeError(
            f"Cannot add unique constraint to {table}({grouped_columns}); "
            f"duplicate key found: {duplicates!r}. Resolve duplicates in a "
            "separately reviewed, data-preserving operation before retrying."
        )


def _constraint_exists(table: str, constraint_name: str, constraint_type: str) -> bool:
    connection = op.get_bind()
    if connection is None:
        return False
    inspector = sa.inspect(connection)
    if constraint_type == "unique":
        existing = inspector.get_unique_constraints(table)
    elif constraint_type == "check":
        existing = inspector.get_check_constraints(table)
    else:
        raise ValueError(f"Unsupported constraint type: {constraint_type!r}")
    return any(item.get("name") == constraint_name for item in existing)


def upgrade() -> None:
    if op.get_context().as_sql:
        op.add_column(
            "workflow_runs",
            sa.Column(
                "generation_attempt_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
        with op.batch_alter_table("workflow_task_attempts") as batch_op:
            batch_op.create_unique_constraint(
                "uq_workflow_task_attempt_number",
                ["workflow_task_id", "attempt_number"],
            )
            batch_op.create_check_constraint(
                "ck_workflow_task_attempt_positive_number",
                "attempt_number > 0",
            )
            batch_op.create_check_constraint(
                "ck_workflow_task_attempt_status",
                "status IN ('running', 'interrupted', 'completed', 'partial', 'skipped', "
                "'retrying', 'failed')",
            )
        with op.batch_alter_table("test_case_generation_runs") as batch_op:
            batch_op.create_unique_constraint(
                "uq_generation_runs_workflow_attempt",
                ["workflow_run_id", "workflow_attempt_number"],
            )
            batch_op.create_check_constraint(
                "ck_generation_runs_workflow_attempt_positive",
                "workflow_attempt_number IS NULL OR workflow_attempt_number > 0",
            )
        return

    _reject_duplicate_keys(
        "workflow_task_attempts",
        ("workflow_task_id", "attempt_number"),
    )
    _reject_duplicate_keys(
        "test_case_generation_runs",
        ("workflow_run_id", "workflow_attempt_number"),
    )

    column_names = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("workflow_runs")
    }
    if "generation_attempt_count" not in column_names:
        op.add_column(
            "workflow_runs",
            sa.Column(
                "generation_attempt_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )

    if op.get_context().dialect.name == "sqlite":
        with op.batch_alter_table("workflow_task_attempts") as batch_op:
            if not _constraint_exists(
                "workflow_task_attempts",
                "uq_workflow_task_attempt_number",
                "unique",
            ):
                batch_op.create_unique_constraint(
                    "uq_workflow_task_attempt_number",
                    ["workflow_task_id", "attempt_number"],
                )
            if not _constraint_exists(
                "workflow_task_attempts",
                "ck_workflow_task_attempt_positive_number",
                "check",
            ):
                batch_op.create_check_constraint(
                    "ck_workflow_task_attempt_positive_number",
                    "attempt_number > 0",
                )
            if not _constraint_exists(
                "workflow_task_attempts",
                "ck_workflow_task_attempt_status",
                "check",
            ):
                batch_op.create_check_constraint(
                    "ck_workflow_task_attempt_status",
                    "status IN ('running', 'interrupted', 'completed', 'partial', 'skipped', "
                    "'retrying', 'failed')",
                )
        with op.batch_alter_table("test_case_generation_runs") as batch_op:
            if not _constraint_exists(
                "test_case_generation_runs",
                "uq_generation_runs_workflow_attempt",
                "unique",
            ):
                batch_op.create_unique_constraint(
                    "uq_generation_runs_workflow_attempt",
                    ["workflow_run_id", "workflow_attempt_number"],
                )
            if not _constraint_exists(
                "test_case_generation_runs",
                "ck_generation_runs_workflow_attempt_positive",
                "check",
            ):
                batch_op.create_check_constraint(
                    "ck_generation_runs_workflow_attempt_positive",
                    "workflow_attempt_number IS NULL OR workflow_attempt_number > 0",
                )
        return

    for constraint_name, table_name, columns in (
        (
            "uq_workflow_task_attempt_number",
            "workflow_task_attempts",
            ["workflow_task_id", "attempt_number"],
        ),
        (
            "uq_generation_runs_workflow_attempt",
            "test_case_generation_runs",
            ["workflow_run_id", "workflow_attempt_number"],
        ),
    ):
        if not _constraint_exists(table_name, constraint_name, "unique"):
            op.create_unique_constraint(
                constraint_name,
                table_name,
                columns,
            )

    for constraint_name, table_name, sql_expression in (
        (
            "ck_workflow_task_attempt_positive_number",
            "workflow_task_attempts",
            "attempt_number > 0",
        ),
        (
            "ck_workflow_task_attempt_status",
            "workflow_task_attempts",
            "status IN ('running', 'interrupted', 'completed', 'partial', 'skipped', "
            "'retrying', 'failed')",
        ),
        (
            "ck_generation_runs_workflow_attempt_positive",
            "test_case_generation_runs",
            "workflow_attempt_number IS NULL OR workflow_attempt_number > 0",
        ),
    ):
        if not _constraint_exists(table_name, constraint_name, "check"):
            op.create_check_constraint(
                constraint_name,
                table_name,
                sql_expression,
            )


def downgrade() -> None:
    raise RuntimeError(
        "This migration is intentionally forward-only. Preserve workflow "
        "attempt and generation history; use a reviewed forward correction."
    )
