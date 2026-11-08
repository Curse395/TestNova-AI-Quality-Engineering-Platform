"""Add persistent document processing and source metadata.

Revision ID: 20261104_01
Revises:
Create Date: 2026-11-04
"""

from alembic import op
import sqlalchemy as sa

revision = "20261104_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "processing_status",
            sa.String(length=20),
            nullable=False,
            server_default="uploaded",
        ),
    )
    op.add_column(
        "documents",
        sa.Column("processing_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "source_type",
            sa.String(length=30),
            nullable=False,
            server_default="document",
        ),
    )
    if op.get_context().dialect.name == "sqlite":
        op.execute(
            "ALTER TABLE documents ADD COLUMN uploaded_by_user_id "
            "INTEGER REFERENCES users (id)"
        )
    else:
        op.add_column(
            "documents",
            sa.Column(
                "uploaded_by_user_id",
                sa.Integer(),
                sa.ForeignKey(
                    "users.id",
                    name="fk_documents_uploaded_by_user_id_users",
                ),
                nullable=True,
            ),
        )
    op.add_column(
        "document_chunks",
        sa.Column(
            "source_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    raise RuntimeError(
        "This migration is intentionally forward-only to avoid deleting "
        "persisted processing status. Restore the prior application version "
        "without dropping these columns, or prepare a reviewed forward migration."
    )
