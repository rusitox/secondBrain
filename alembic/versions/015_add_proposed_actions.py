"""Add proposed_actions and action_audit_log tables (agent action gate).

Revision ID: 015
Revises: 014

Renumbered from 014 (down_revision=013) to 015 (down_revision=014) as part
of resolving the 013 revision-id collision with main's own migration
chain — see 014_add_user_interactions.py's docstring and
[[project-alembic-revision-collision]] in memory.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None

ACTION_STATUS_VALUES = ("proposed", "approved", "executing", "executed", "failed", "rejected", "expired")


def upgrade() -> None:
    action_status_enum = postgresql.ENUM(
        *ACTION_STATUS_VALUES, name="action_status_enum", create_type=False
    )
    bind = op.get_bind()
    action_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "proposed_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "interaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_interactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.Text(), nullable=False),
        sa.Column("artifact", postgresql.JSONB(), nullable=False),
        sa.Column("risk", sa.Text(), nullable=False),
        sa.Column("status", action_status_enum, nullable=False, server_default="proposed"),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("executor_version", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_proposed_actions_idempotency_key"),
    )
    op.create_index("ix_proposed_actions_user_status", "proposed_actions", ["user_id", "status"])

    op.create_table(
        "action_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("proposed_actions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_action_audit_log_action_id", "action_audit_log", ["action_id"])


def downgrade() -> None:
    op.drop_index("ix_action_audit_log_action_id", table_name="action_audit_log")
    op.drop_table("action_audit_log")

    op.drop_index("ix_proposed_actions_user_status", table_name="proposed_actions")
    op.drop_table("proposed_actions")

    op.execute("DROP TYPE IF EXISTS action_status_enum")
