"""Add notion_page_id column to commitments table.

Revision ID: 003
Revises: 002
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "commitments",
        sa.Column("notion_page_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_commitments_notion_page_id",
        "commitments",
        ["notion_page_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_commitments_notion_page_id", table_name="commitments")
    op.drop_column("commitments", "notion_page_id")
