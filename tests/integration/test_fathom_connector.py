"""Integration tests for FathomConnector.

Fathom has no public REST API (api.fathom.video is NXDOMAIN).
These tests verify the connector correctly refuses all operations so that
the server-side scheduler never accidentally calls it.
"""
import pytest
from datetime import datetime, timezone

from app.services.connectors.fathom import FathomConnector


@pytest.fixture
def connector() -> FathomConnector:
    return FathomConnector()


class TestFathomConnectorPlatform:
    def test_platform_name(self, connector: FathomConnector) -> None:
        assert connector.platform == "fathom"


class TestFathomConnectorFetchItems:
    @pytest.mark.asyncio
    async def test_fetch_items_raises_not_implemented(
        self, connector: FathomConnector
    ) -> None:
        """fetch_items must raise NotImplementedError — no public REST API exists."""
        with pytest.raises(NotImplementedError) as exc_info:
            await connector.fetch_items(access_token="any-token")
        msg = str(exc_info.value).lower()
        assert "no public rest api" in msg or "mcp" in msg

    @pytest.mark.asyncio
    async def test_fetch_items_raises_with_since_param(
        self, connector: FathomConnector
    ) -> None:
        """NotImplementedError raised regardless of since parameter."""
        with pytest.raises(NotImplementedError):
            await connector.fetch_items(
                access_token="token",
                since=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

    @pytest.mark.asyncio
    async def test_fetch_items_error_message_mentions_script(
        self, connector: FathomConnector
    ) -> None:
        """Error message must direct users to the incremental sync script."""
        with pytest.raises(NotImplementedError) as exc_info:
            await connector.fetch_items(access_token="tok")
        assert "sync_fathom_incremental" in str(exc_info.value)


class TestFathomConnectorValidateToken:
    @pytest.mark.asyncio
    async def test_validate_token_raises_not_implemented(
        self, connector: FathomConnector
    ) -> None:
        """validate_token must raise NotImplementedError — no REST API."""
        with pytest.raises(NotImplementedError):
            await connector.validate_token("any-token")

    @pytest.mark.asyncio
    async def test_validate_token_error_message_helpful(
        self, connector: FathomConnector
    ) -> None:
        """Error message explains why and how to proceed."""
        with pytest.raises(NotImplementedError) as exc_info:
            await connector.validate_token("tok")
        msg = str(exc_info.value).lower()
        assert "no public rest api" in msg or "fathom" in msg
