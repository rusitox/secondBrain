"""Add oauth_client_id and token_expires_at columns to integrations table.

Fathom's MCP server requires OAuth 2.1 (authorization_code + PKCE, via
dynamic client registration) rather than a static API key. oauth_client_id
is the id issued by Fathom's registration endpoint during the one-time
interactive setup (scripts/connect_fathom_oauth.py) — needed to request a
refresh_token grant later (app/services/token_refresh.py). token_expires_at
tracks when the current access_token needs refreshing, mirroring how MSAL's
JWT access tokens carry their own `exp` claim, except Fathom's access token
isn't a JWT we can decode, so the expiry is tracked out-of-band instead.

Revision ID: 018
Revises: 017
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integrations",
        sa.Column("oauth_client_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "integrations",
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("integrations", "token_expires_at")
    op.drop_column("integrations", "oauth_client_id")
