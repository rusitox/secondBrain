"""Unit tests for FathomConnector.

Fathom has no public REST API. The connector raises NotImplementedError
for all operations to prevent accidental use via the server-side scheduler.
"""
import pytest

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
        """fetch_items must raise NotImplementedError — no public REST API."""
        with pytest.raises(NotImplementedError) as exc_info:
            await connector.fetch_items(access_token="any-token")
        assert "no public REST API" in str(exc_info.value).lower() or "mcp" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_fetch_items_raises_with_since_param(
        self, connector: FathomConnector
    ) -> None:
        """NotImplementedError regardless of since parameter."""
        from datetime import datetime, timezone
        with pytest.raises(NotImplementedError):
            await connector.fetch_items(
                access_token="token",
                since=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )


class TestFathomConnectorValidateToken:
    @pytest.mark.asyncio
    async def test_validate_token_raises_not_implemented(
        self, connector: FathomConnector
    ) -> None:
        """validate_token must raise NotImplementedError — no REST API."""
        with pytest.raises(NotImplementedError):
            await connector.validate_token("any-token")
