"""Add persistent QA workflow runs and task attempts.

Revision ID: 20261109_01
Revises: 20261106_02
"""

from alembic import op
import sqlalchemy as sa

revision = "20261109_01"
down_revision = "20261106_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("initiated_by", sa.Integer(), nullable=False),
        sa.Column("workflow_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("input_data", sa.JSON(), nullable=False),
        sa.Column("final_output", sa.JSON(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', "
            "'partially_completed', 'failed')",
            name="ck_workflow_runs_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["initiated_by"], ["users.id"]),
    )
    op.create_index("ix_workflow_runs_id", "workflow_runs", ["id"])
    op.create_index(
        "ix_workflow_runs_project_created",
        "workflow_runs",
        ["project_id", "created_at"],
    )
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])

    op.create_table(
        "workflow_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_run_id", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(length=100), nullable=False),
        sa.Column("task_type", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("depends_on_task_ids", sa.JSON(), nullable=False),
        sa.Column("input_data", sa.JSON(), nullable=False),
        sa.Column("output_data", sa.JSON(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_details", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial', 'skipped', "
            "'retrying', 'failed')",
            name="ck_workflow_tasks_status",
        ),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"]),
    )
    op.create_index("ix_workflow_tasks_id", "workflow_tasks", ["id"])
    op.create_index(
        "ix_workflow_tasks_workflow_created",
        "workflow_tasks",
        ["workflow_run_id", "created_at"],
    )
    op.create_index("ix_workflow_tasks_status", "workflow_tasks", ["status"])

    op.create_table(
        "workflow_task_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_task_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("output_data", sa.JSON(), nullable=True),
        sa.Column("error_details", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workflow_task_id"], ["workflow_tasks.id"]),
    )
    op.create_index(
        "ix_workflow_task_attempts_id",
        "workflow_task_attempts",
        ["id"],
    )
    op.create_index(
        "ix_workflow_task_attempts_task_created",
        "workflow_task_attempts",
        ["workflow_task_id", "created_at"],
    )

    if op.get_context().dialect.name == "sqlite":
        op.execute(
            "ALTER TABLE test_case_generation_runs ADD COLUMN "
            "workflow_run_id INTEGER REFERENCES workflow_runs (id)"
        )
    else:
        op.add_column(
            "test_case_generation_runs",
            sa.Column("workflow_run_id", sa.Integer(), nullable=True),
        )
    op.add_column(
        "test_case_generation_runs",
        sa.Column("workflow_attempt_number", sa.Integer(), nullable=True),
    )
    if op.get_context().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_generation_runs_workflow_run",
            "test_case_generation_runs",
            "workflow_runs",
            ["workflow_run_id"],
            ["id"],
        )
    op.create_index(
        "ix_generation_runs_workflow_attempt",
        "test_case_generation_runs",
        ["workflow_run_id", "workflow_attempt_number"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "This migration is intentionally forward-only. Preserve workflow "
        "history and prepare a reviewed forward migration instead of dropping it."
    )
