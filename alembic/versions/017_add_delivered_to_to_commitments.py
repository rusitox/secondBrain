"""Add delivered_to column to commitments table

Revision ID: 017
Revises: 016
Create Date: 2026-09-13

NOTE: numbered 017 (not 014) because feat/liquid-ui-redesign already added
014/015/016 (user_interactions, proposed_actions, external_account_id) and
those are already applied to the shared dev DB, even though that branch
hasn't merged to main yet — see the known Alembic revision collision this
repo is tracking. Whoever reconciles that merge needs to check this chains
correctly against whatever main's history looks like by then.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "commitments",
        sa.Column("delivered_to", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("commitments", "delivered_to")
