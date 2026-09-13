"""Add user_interactions and agent_session_states tables (generative UI protocol).

Revision ID: 014
Revises: 013

Numbered 014 (not 013) because this branch's migration chain and main's
own 013_add_backoffice_tables.py both forked independently off 012 —
see [[project-alembic-revision-collision]] in memory for the full story.
This file used to be 013_add_user_interactions.py with down_revision=012;
renumbered so the two branches' migration histories are linear once
merged, instead of two different files claiming revision id "013".
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None

INTERACTION_STATUS_VALUES = ("open", "answered", "cancelled", "expired")


def upgrade() -> None:
    interaction_status_enum = postgresql.ENUM(
        *INTERACTION_STATUS_VALUES, name="interaction_status_enum", create_type=False
    )
    bind = op.get_bind()
    interaction_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "user_interactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "turn_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversation_turns.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("interrupt_id", sa.Text(), nullable=False),
        sa.Column("tool_use_id", sa.Text(), nullable=False),
        sa.Column("spec", postgresql.JSONB(), nullable=False),
        sa.Column("answer", postgresql.JSONB(), nullable=True),
        sa.Column("status", interaction_status_enum, nullable=False, server_default="open"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_via", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("session_id", "interrupt_id", name="uq_user_interactions_session_interrupt"),
    )
    op.create_index("ix_user_interactions_user_status", "user_interactions", ["user_id", "status"])
    op.create_index("ix_user_interactions_session", "user_interactions", ["session_id"])

    op.create_table(
        "agent_session_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("strands_version", sa.Text(), nullable=False),
        sa.Column("awaiting_input", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("session_id", name="uq_agent_session_states_session_id"),
    )


def downgrade() -> None:
    op.drop_table("agent_session_states")

    op.drop_index("ix_user_interactions_session", table_name="user_interactions")
    op.drop_index("ix_user_interactions_user_status", table_name="user_interactions")
    op.drop_table("user_interactions")

    op.execute("DROP TYPE IF EXISTS interaction_status_enum")
