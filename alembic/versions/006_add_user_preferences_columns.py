"""Add onboarding and preferences columns to users table.

Revision ID: 006
Revises: 005
Create Date: 2026-04-19
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("onboarding_completed", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("onboarding_step", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("preferences_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("notion_config_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "notion_config_json")
    op.drop_column("users", "preferences_json")
    op.drop_column("users", "onboarding_step")
    op.drop_column("users", "onboarding_completed")
