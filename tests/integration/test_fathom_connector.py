"""Integration tests for Fathom connector (HTTP mocked with respx)."""
import pytest
import respx
from httpx import Response

from app.services.connectors.fathom import FathomConnector, FATHOM_API_URL


@pytest.fixture
def connector() -> FathomConnector:
    return FathomConnector()


class TestFathomConnector:
    @respx.mock
    async def test_fetch_transcripts(self, connector: FathomConnector) -> None:
        respx.get(f"{FATHOM_API_URL}/recordings").mock(return_value=Response(
            200,
            json={
                "recordings": [
                    {
                        "id": "rec-001",
                        "title": "Sprint Review",
                        "created_at": "2024-01-15T10:00:00Z",
                        "duration": 3600,
                        "participants": ["Alice", "Bob"],
                    },
                ],
            },
        ))
        respx.get(f"{FATHOM_API_URL}/recordings/rec-001/transcript").mock(
            return_value=Response(200, json={"text": "We discussed the Q4 results."}),
        )

        items = await connector.fetch_items(access_token="test-token")
        assert len(items) == 1
        assert items[0].source_id == "rec-001"
        assert "Sprint Review" in items[0].content
        assert "Q4 results" in items[0].content
        assert items[0].metadata["type"] == "transcript"
        assert items[0].metadata["duration"] == 3600

    @respx.mock
    async def test_transcript_as_string(self, connector: FathomConnector) -> None:
        """Transcript endpoint may return plain text string."""
        respx.get(f"{FATHOM_API_URL}/recordings").mock(return_value=Response(
            200, json={"recordings": [
                {"id": "rec-002", "title": "Standup", "created_at": "2024-01-16T09:00:00Z"},
            ]},
        ))
        respx.get(f"{FATHOM_API_URL}/recordings/rec-002/transcript").mock(
            return_value=Response(200, json="Plain transcript text here."),
        )

        items = await connector.fetch_items(access_token="test-token")
        assert len(items) == 1
        assert "Plain transcript text here." in items[0].content

    @respx.mock
    async def test_transcript_fetch_failure_skips(self, connector: FathomConnector) -> None:
        """If transcript fetch fails, the recording should be skipped."""
        respx.get(f"{FATHOM_API_URL}/recordings").mock(return_value=Response(
            200, json={"recordings": [
                {"id": "rec-003", "title": "Failed", "created_at": "2024-01-17T10:00:00Z"},
            ]},
        ))
        respx.get(f"{FATHOM_API_URL}/recordings/rec-003/transcript").mock(
            return_value=Response(500),
        )

        items = await connector.fetch_items(access_token="test-token")
        assert len(items) == 0  # skipped due to transcript failure

    @respx.mock
    async def test_validate_token_valid(self, connector: FathomConnector) -> None:
        respx.get(f"{FATHOM_API_URL}/user").mock(return_value=Response(200, json={"id": "u1"}))
        assert await connector.validate_token("valid-token") is True

    @respx.mock
    async def test_validate_token_invalid(self, connector: FathomConnector) -> None:
        respx.get(f"{FATHOM_API_URL}/user").mock(return_value=Response(401))
        assert await connector.validate_token("bad-token") is False

    @respx.mock
    async def test_fetch_with_since_filter(self, connector: FathomConnector) -> None:
        from datetime import datetime, timezone
        since = datetime(2024, 1, 10, tzinfo=timezone.utc)

        route = respx.get(f"{FATHOM_API_URL}/recordings").mock(return_value=Response(
            200, json={"recordings": []},
        ))

        await connector.fetch_items(access_token="token", since=since)
        call = route.calls[0]
        assert "created_after" in str(call.request.url)
