"""Separate test discipline from scenario category.

Revision ID: 20261110_02
Revises: 20261110_01
"""

from alembic import op
import sqlalchemy as sa

revision = "20261110_02"
down_revision = "20261110_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("test_cases")
    }
    if "test_type" not in columns:
        op.add_column(
            "test_cases",
            sa.Column("test_type", sa.String(length=60), nullable=True),
        )


def downgrade() -> None:
    raise RuntimeError(
        "This migration is forward-only. Preserve existing test-case records."
    )
