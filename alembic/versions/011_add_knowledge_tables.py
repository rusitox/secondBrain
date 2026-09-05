"""Add multi-agent knowledge tables (entities, entity_claims, entity_links, pending_questions).

Revision ID: 011
Revises: 010
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None

ENTITY_TYPE_VALUES = ("person", "project", "initiative", "topic", "organization")
CLAIM_STATUS_VALUES = ("active", "superseded", "disputed", "confirmed_by_user")
LINK_RESOLVED_BY_VALUES = ("deterministic", "swarm", "user")
QUESTION_TARGET_VALUES = ("peer_agents", "human")
QUESTION_STATUS_VALUES = ("open", "answered", "dismissed")
RESOLVED_BY_VALUES = ("knowledge_base", "peer_swarm", "human")


def upgrade() -> None:
    entity_type_enum = postgresql.ENUM(*ENTITY_TYPE_VALUES, name="entity_type_enum", create_type=False)
    claim_status_enum = postgresql.ENUM(*CLAIM_STATUS_VALUES, name="claim_status_enum", create_type=False)
    link_resolved_by_enum = postgresql.ENUM(
        *LINK_RESOLVED_BY_VALUES, name="link_resolved_by_enum", create_type=False
    )
    question_target_enum = postgresql.ENUM(
        *QUESTION_TARGET_VALUES, name="question_target_enum", create_type=False
    )
    question_status_enum = postgresql.ENUM(
        *QUESTION_STATUS_VALUES, name="question_status_enum", create_type=False
    )
    resolved_by_enum = postgresql.ENUM(*RESOLVED_BY_VALUES, name="resolved_by_enum", create_type=False)

    bind = op.get_bind()
    entity_type_enum.create(bind, checkfirst=True)
    claim_status_enum.create(bind, checkfirst=True)
    link_resolved_by_enum.create(bind, checkfirst=True)
    question_target_enum.create(bind, checkfirst=True)
    question_status_enum.create(bind, checkfirst=True)
    resolved_by_enum.create(bind, checkfirst=True)

    op.create_table(
        "entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", entity_type_enum, nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("aliases", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("attributes", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_entities_user_id", "entities", ["user_id"])
    op.create_index("ix_entities_user_type", "entities", ["user_id", "entity_type"])

    op.create_table(
        "entity_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("status", claim_status_enum, nullable=False, server_default="active"),
        sa.Column("asserted_by_agent", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_entity_claims_entity_id", "entity_claims", ["entity_id"])
    op.create_index("ix_entity_claims_user_id", "entity_claims", ["user_id"])

    op.create_table(
        "entity_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entity_id_a",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entity_id_b",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("resolved_by", link_resolved_by_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_entity_links_user_id", "entity_links", ["user_id"])
    op.create_index("ix_entity_links_entity_id_a", "entity_links", ["entity_id_a"])
    op.create_index("ix_entity_links_entity_id_b", "entity_links", ["entity_id_b"])

    op.create_table(
        "pending_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raised_by_agent", sa.Text(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("context", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("target", question_target_enum, nullable=False, server_default="peer_agents"),
        sa.Column("candidate_answer", sa.Text(), nullable=True),
        sa.Column("candidate_confidence", sa.Float(), nullable=True),
        sa.Column("status", question_status_enum, nullable=False, server_default="open"),
        sa.Column("resolved_by", resolved_by_enum, nullable=True),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_pending_questions_user_id", "pending_questions", ["user_id"])
    op.create_index("ix_pending_questions_user_status", "pending_questions", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_pending_questions_user_status", table_name="pending_questions")
    op.drop_index("ix_pending_questions_user_id", table_name="pending_questions")
    op.drop_table("pending_questions")

    op.drop_index("ix_entity_links_entity_id_b", table_name="entity_links")
    op.drop_index("ix_entity_links_entity_id_a", table_name="entity_links")
    op.drop_index("ix_entity_links_user_id", table_name="entity_links")
    op.drop_table("entity_links")

    op.drop_index("ix_entity_claims_user_id", table_name="entity_claims")
    op.drop_index("ix_entity_claims_entity_id", table_name="entity_claims")
    op.drop_table("entity_claims")

    op.drop_index("ix_entities_user_type", table_name="entities")
    op.drop_index("ix_entities_user_id", table_name="entities")
    op.drop_table("entities")

    op.execute("DROP TYPE IF EXISTS resolved_by_enum")
    op.execute("DROP TYPE IF EXISTS question_status_enum")
    op.execute("DROP TYPE IF EXISTS question_target_enum")
    op.execute("DROP TYPE IF EXISTS link_resolved_by_enum")
    op.execute("DROP TYPE IF EXISTS claim_status_enum")
    op.execute("DROP TYPE IF EXISTS entity_type_enum")
