"""Initial schema — users, identities, integrations, documents, commitments

Revision ID: 001
Revises: None
Create Date: 2026-04-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create enum types
    platform_enum = postgresql.ENUM(
        "slack", "outlook", "teams", "fathom", name="platform_enum", create_type=False
    )
    platform_enum.create(op.get_bind(), checkfirst=True)

    status_enum = postgresql.ENUM(
        "pending", "completed", "cancelled", name="commitment_status_enum", create_type=False
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    # Users
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("timezone", sa.String(50), server_default="UTC"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Identities
    op.create_table(
        "identities",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("persona_description", sa.Text(), server_default=""),
        sa.Column("tone_guidelines", sa.Text(), server_default=""),
        sa.Column("heuristics", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Integrations
    op.create_table(
        "integrations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", platform_enum, nullable=False),
        sa.Column("access_token", sa.Text(), server_default=""),
        sa.Column("refresh_token", sa.Text(), server_default=""),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Documents
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536)),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("source_id", sa.String(255), server_default=""),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Unique index for deduplication
    op.create_index(
        "ix_documents_user_source",
        "documents",
        ["user_id", "source", "source_id"],
        unique=True,
    )

    # HNSW index for vector search
    op.execute(
        "CREATE INDEX ix_documents_embedding_hnsw ON documents "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # Commitments
    op.create_table(
        "commitments",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.UUID(), sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("commitment_text", sa.Text(), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", status_enum, server_default="pending"),
        sa.Column("priority", sa.Integer(), server_default="3"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("commitments")
    op.execute("DROP INDEX IF EXISTS ix_documents_embedding_hnsw")
    op.drop_index("ix_documents_user_source", table_name="documents")
    op.drop_table("documents")
    op.drop_table("integrations")
    op.drop_table("identities")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS commitment_status_enum")
    op.execute("DROP TYPE IF EXISTS platform_enum")
    op.execute("DROP EXTENSION IF EXISTS vector")
