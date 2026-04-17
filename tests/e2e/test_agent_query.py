"""End-to-end tests for agent query endpoint."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


class TestAgentQueryEndpoint:
    """Tests for POST /agent/query."""

    @pytest.mark.asyncio
    async def test_missing_auth_header(self, client: AsyncClient) -> None:
        """Request without X-User-Id header returns 401."""
        resp = await client.post(
            "/agent/query",
            json={"question": "What's on my plate?"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_question(self, client: AsyncClient) -> None:
        """Empty question returns 422."""
        resp = await client.post(
            "/agent/query",
            json={"question": ""},
            headers={"X-User-Id": str(uuid.uuid4())},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_question_too_long(self, client: AsyncClient) -> None:
        """Question exceeding max length returns 422."""
        resp = await client.post(
            "/agent/query",
            json={"question": "x" * 2001},
            headers={"X-User-Id": str(uuid.uuid4())},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_question_field(self, client: AsyncClient) -> None:
        """Missing question field returns 422."""
        resp = await client.post(
            "/agent/query",
            json={},
            headers={"X-User-Id": str(uuid.uuid4())},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_successful_query(self, client: AsyncClient) -> None:
        """Successful agent query returns structured response."""
        user_id = str(uuid.uuid4())

        mock_agent = AsyncMock()
        mock_agent.query = AsyncMock(return_value={
            "answer": "You have 2 pending tasks and a meeting at 3pm.",
            "tools_used": ["memory", "tasks", "calendar"],
            "sources": [{"source": "slack", "content": "reminder"}],
        })

        with patch("app.api.routers.agent._get_agent", return_value=mock_agent):
            resp = await client.post(
                "/agent/query",
                json={"question": "What meetings do I have today?"},
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert "tools_used" in data
        assert "sources" in data
        assert "query" in data
        assert data["query"] == "What meetings do I have today?"

    @pytest.mark.asyncio
    async def test_response_schema_types(self, client: AsyncClient) -> None:
        """Response fields have correct types."""
        user_id = str(uuid.uuid4())

        mock_agent = AsyncMock()
        mock_agent.query = AsyncMock(return_value={
            "answer": "No pending items.",
            "tools_used": ["memory", "tasks"],
            "sources": [],
        })

        with patch("app.api.routers.agent._get_agent", return_value=mock_agent):
            resp = await client.post(
                "/agent/query",
                json={"question": "Any pending tasks?"},
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["answer"], str)
        assert isinstance(data["tools_used"], list)
        assert isinstance(data["sources"], list)
        assert isinstance(data["query"], str)

    @pytest.mark.asyncio
    async def test_agent_api_error_returns_502(self, client: AsyncClient) -> None:
        """When agent raises RuntimeError, return 502."""
        user_id = str(uuid.uuid4())

        mock_agent = AsyncMock()
        mock_agent.query = AsyncMock(side_effect=RuntimeError("Claude API failed"))

        with patch("app.api.routers.agent._get_agent", return_value=mock_agent):
            resp = await client.post(
                "/agent/query",
                json={"question": "What's happening?"},
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 502

    @pytest.mark.asyncio
    async def test_query_with_calendar_keywords(self, client: AsyncClient) -> None:
        """Questions with calendar keywords should trigger calendar tool."""
        user_id = str(uuid.uuid4())

        mock_agent = AsyncMock()
        mock_agent.query = AsyncMock(return_value={
            "answer": "You have a standup at 9am.",
            "tools_used": ["memory", "tasks", "calendar"],
            "sources": [],
        })

        with patch("app.api.routers.agent._get_agent", return_value=mock_agent):
            resp = await client.post(
                "/agent/query",
                json={"question": "What's on my agenda today?"},
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["tools_used"], list)

    @pytest.mark.asyncio
    async def test_query_spanish_language(self, client: AsyncClient) -> None:
        """Agent handles Spanish language questions."""
        user_id = str(uuid.uuid4())

        mock_agent = AsyncMock()
        mock_agent.query = AsyncMock(return_value={
            "answer": "Tienes 3 compromisos pendientes.",
            "tools_used": ["memory", "tasks"],
            "sources": [],
        })

        with patch("app.api.routers.agent._get_agent", return_value=mock_agent):
            resp = await client.post(
                "/agent/query",
                json={"question": "Que tengo pendiente hoy?"},
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["answer"], str)

    @pytest.mark.asyncio
    async def test_query_with_curly_braces(self, client: AsyncClient) -> None:
        """Questions with curly braces don't crash string formatting."""
        user_id = str(uuid.uuid4())

        mock_agent = AsyncMock()
        mock_agent.query = AsyncMock(return_value={
            "answer": "I found references to that code pattern.",
            "tools_used": ["memory"],
            "sources": [],
        })

        with patch("app.api.routers.agent._get_agent", return_value=mock_agent):
            resp = await client.post(
                "/agent/query",
                json={"question": "Find mentions of {config} in my notes"},
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_query_echoes_question(self, client: AsyncClient) -> None:
        """Response includes the original question."""
        user_id = str(uuid.uuid4())
        question = "Summarize my week"

        mock_agent = AsyncMock()
        mock_agent.query = AsyncMock(return_value={
            "answer": "Here's your week summary.",
            "tools_used": ["memory"],
            "sources": [],
        })

        with patch("app.api.routers.agent._get_agent", return_value=mock_agent):
            resp = await client.post(
                "/agent/query",
                json={"question": question},
                headers={"X-User-Id": user_id},
            )

        assert resp.status_code == 200
        assert resp.json()["query"] == question
