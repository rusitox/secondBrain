"""Add owner column to commitments table

Revision ID: 007
Revises: 006
Create Date: 2026-08-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "commitments",
        sa.Column("owner", sa.Text(), server_default="unknown", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("commitments", "owner")
