"""Add external_account_id column to integrations table.

The connected account's own id on the external platform (e.g. Slack's
"user_id" from auth.test) — needed to tell "a message that mentions me"
from "a message that mentions someone else". Populated lazily by the sync
scheduler, not backfilled by this migration.

Revision ID: 016
Revises: 015
Create Date: 2026-09-11
"""
from alembic import op
import sqlalchemy as sa

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integrations",
        sa.Column("external_account_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("integrations", "external_account_id")
