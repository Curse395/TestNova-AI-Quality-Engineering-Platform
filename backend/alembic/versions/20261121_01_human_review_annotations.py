"""Add immutable project-scoped human review annotation revisions.

Revision ID: 20261121_01
Revises: 20261111_01
"""

from alembic import op
import sqlalchemy as sa

revision = "20261121_01"
down_revision = "20261111_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "human_review_annotations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_key", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), nullable=False),
        sa.Column("test_case_id", sa.Integer(), nullable=True),
        sa.Column("benchmark_run_id", sa.String(length=200)),
        sa.Column("benchmark_dataset_version", sa.String(length=50)),
        sa.Column("benchmark_example_id", sa.String(length=200)),
        sa.Column("candidate_reference", sa.String(length=200)),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("requirement_relevance", sa.Integer(), nullable=False),
        sa.Column("evidence_correctness", sa.Integer(), nullable=False),
        sa.Column("scenario_coverage", sa.Integer(), nullable=False),
        sa.Column("step_clarity", sa.Integer(), nullable=False),
        sa.Column("expected_result_specificity", sa.Integer(), nullable=False),
        sa.Column("execution_usefulness", sa.Integer(), nullable=False),
        sa.Column("comments", sa.Text()), sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("automated_metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"]),
        sa.UniqueConstraint("review_key", "version", name="uq_human_review_key_version"),
        sa.CheckConstraint("decision IN ('approved', 'rejected', 'needs_improvement', 'not_applicable')", name="ck_human_review_decision"),
        *[sa.CheckConstraint(f"{column} BETWEEN 1 AND 5", name=f"ck_human_review_{column}") for column in ("requirement_relevance", "evidence_correctness", "scenario_coverage", "step_clarity", "expected_result_specificity", "execution_usefulness")],
    )
    op.create_index("ix_human_review_project_created", "human_review_annotations", ["project_id", "created_at"])
    op.create_index("ix_human_review_test_case", "human_review_annotations", ["test_case_id"])


def downgrade() -> None:
    op.drop_index("ix_human_review_test_case", table_name="human_review_annotations")
    op.drop_index("ix_human_review_project_created", table_name="human_review_annotations")
    op.drop_table("human_review_annotations")
