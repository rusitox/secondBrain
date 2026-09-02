"""Add user_token column to integrations table.

Used by the Slack connector to store a User Token (xoxp-) alongside the
Bot Token stored in access_token. A User Token grants access to the
authenticated user's personal DMs (im) and group DMs (mpim), which are
not accessible via a Bot Token.

Revision ID: 008
Revises: 007
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integrations",
        sa.Column("user_token", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("integrations", "user_token")
