"""Add knowledge-system backoffice tables (agent_runs, agent_run_events, agent_configs, mcp_servers).

Revision ID: 013
Revises: 012
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None

RUN_TYPE_VALUES = ("domain_agent", "rd_agent", "reconciliation", "negotiation", "chat")
RUN_TRIGGER_VALUES = ("scheduler", "manual", "api")
RUN_STATUS_VALUES = ("running", "completed", "failed")
RUN_EVENT_TYPE_VALUES = ("assistant_text", "tool_call", "tool_result", "handoff", "verdict", "error")


def upgrade() -> None:
    run_type_enum = postgresql.ENUM(*RUN_TYPE_VALUES, name="run_type_enum", create_type=False)
    run_trigger_enum = postgresql.ENUM(*RUN_TRIGGER_VALUES, name="run_trigger_enum", create_type=False)
    run_status_enum = postgresql.ENUM(*RUN_STATUS_VALUES, name="run_status_enum", create_type=False)
    run_event_type_enum = postgresql.ENUM(
        *RUN_EVENT_TYPE_VALUES, name="run_event_type_enum", create_type=False
    )

    bind = op.get_bind()
    run_type_enum.create(bind, checkfirst=True)
    run_trigger_enum.create(bind, checkfirst=True)
    run_status_enum.create(bind, checkfirst=True)
    run_event_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_key", sa.Text(), nullable=False),
        sa.Column("run_type", run_type_enum, nullable=False),
        sa.Column("trigger", run_trigger_enum, nullable=False),
        sa.Column("status", run_status_enum, nullable=False, server_default="running"),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("stats", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "parent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_index("ix_agent_runs_user_agent", "agent_runs", ["user_id", "agent_key"])
    op.create_index("ix_agent_runs_user_started", "agent_runs", ["user_id", "started_at"])
    op.create_index("ix_agent_runs_parent_run_id", "agent_runs", ["parent_run_id"])

    op.create_table(
        "agent_run_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", run_event_type_enum, nullable=False),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_run_events_run_id", "agent_run_events", ["run_id"])
    op.create_index("ix_agent_run_events_run_seq", "agent_run_events", ["run_id", "seq"])

    op.create_table(
        "agent_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_key", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("enabled_tools", postgresql.JSONB(), nullable=True),
        sa.Column("mcp_server_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_agent_configs_user_id", "agent_configs", ["user_id"])
    op.create_index(
        "ix_agent_configs_user_agent", "agent_configs", ["user_id", "agent_key"], unique=True
    )

    op.create_table(
        "mcp_servers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("auth_header", sa.Text(), nullable=False, server_default="Authorization"),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("allowed_tools", postgresql.JSONB(), nullable=True),
        sa.Column("rejected_tools", postgresql.JSONB(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.Text(), nullable=True),
        sa.Column("discovered_tools", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_mcp_servers_user_id", "mcp_servers", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_servers_user_id", table_name="mcp_servers")
    op.drop_table("mcp_servers")

    op.drop_index("ix_agent_configs_user_agent", table_name="agent_configs")
    op.drop_index("ix_agent_configs_user_id", table_name="agent_configs")
    op.drop_table("agent_configs")

    op.drop_index("ix_agent_run_events_run_seq", table_name="agent_run_events")
    op.drop_index("ix_agent_run_events_run_id", table_name="agent_run_events")
    op.drop_table("agent_run_events")

    op.drop_index("ix_agent_runs_parent_run_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_started", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_agent", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    op.drop_table("agent_runs")

    op.execute("DROP TYPE IF EXISTS run_event_type_enum")
    op.execute("DROP TYPE IF EXISTS run_status_enum")
    op.execute("DROP TYPE IF EXISTS run_trigger_enum")
    op.execute("DROP TYPE IF EXISTS run_type_enum")
