"""Add sync scheduling columns to integrations table.

Revision ID: 005
Revises: 004
Create Date: 2026-04-19
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integrations",
        sa.Column("sync_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "integrations",
        sa.Column("sync_interval_minutes", sa.Integer(), nullable=False, server_default="30"),
    )
    op.add_column(
        "integrations",
        sa.Column("last_sync_status", sa.String(20), nullable=True),
    )
    op.add_column(
        "integrations",
        sa.Column("last_sync_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("integrations", "last_sync_error")
    op.drop_column("integrations", "last_sync_status")
    op.drop_column("integrations", "sync_interval_minutes")
    op.drop_column("integrations", "sync_enabled")
