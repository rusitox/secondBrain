"""Integration tests for POST /agent/query.

Covers the full HTTP stack: auth, validation, orchestrator wiring,
session_id propagation, and ConversationTurn persistence.

LLM calls are mocked — these tests do NOT hit OpenAI/Anthropic.
"""
import json
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm.claude_client import ToolCall, ToolUseResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_user_and_api_key(client: AsyncClient) -> tuple:
    """Create a user and return (user_id, api_key_str, auth_headers)."""
    resp = await client.post("/users/", json={
        "email": f"agent_{uuid.uuid4().hex[:8]}@test.com",
        "full_name": "Agent Test User",
    })
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["id"]

    resp = await client.post(
        "/auth/api-keys",
        json={"name": "test-key"},
        headers={"X-User-Id": user_id},
    )
    assert resp.status_code == 201, resp.text
    api_key = resp.json()["key"]
    return user_id, api_key, {"Authorization": f"Bearer {api_key}"}


def _mock_tool_result(answer: str = "Test answer.", tool_calls=None) -> ToolUseResult:
    return ToolUseResult(
        final_answer=answer,
        tool_calls=tool_calls or [],
        iterations=1,
        stop_reason="end_turn",
    )


def _make_mock_orchestrator(answer: str = "Test answer.") -> MagicMock:
    """Return a mock AgentOrchestrator whose query() returns a fixed result."""
    orch = MagicMock()
    orch.query = AsyncMock(return_value={
        "answer": answer,
        "tools_used": ["get_user_style"],
        "sources": [],
        "session_id": str(uuid.uuid4()),
        "iterations": 1,
    })
    return orch


# ---------------------------------------------------------------------------
# Auth and validation
# ---------------------------------------------------------------------------

class TestAgentQueryAuth:
    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post("/agent/query", json={"question": "hello"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_api_key_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/agent/query",
            json={"question": "hello"},
            headers={"Authorization": "Bearer sb_invalid_key"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_question_returns_422(self, client: AsyncClient) -> None:
        _, _, headers = await _create_user_and_api_key(client)
        resp = await client.post(
            "/agent/query",
            json={"question": ""},
            headers=headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_question_returns_422(self, client: AsyncClient) -> None:
        _, _, headers = await _create_user_and_api_key(client)
        resp = await client.post("/agent/query", json={}, headers=headers)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_question_too_long_returns_422(self, client: AsyncClient) -> None:
        _, _, headers = await _create_user_and_api_key(client)
        resp = await client.post(
            "/agent/query",
            json={"question": "x" * 2001},
            headers=headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

class TestAgentQueryResponse:
    @pytest.mark.asyncio
    async def test_successful_query_returns_expected_fields(
        self, client: AsyncClient
    ) -> None:
        _, _, headers = await _create_user_and_api_key(client)

        with patch("app.api.routers.agent._get_agent", return_value=_make_mock_orchestrator()):
            resp = await client.post(
                "/agent/query",
                json={"question": "¿qué tengo pendiente?"},
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == "Test answer."
        assert isinstance(data["tools_used"], list)
        assert isinstance(data["sources"], list)
        assert data["query"] == "¿qué tengo pendiente?"
        assert "session_id" in data
        assert isinstance(data["iterations"], int)

    @pytest.mark.asyncio
    async def test_session_id_is_valid_uuid(self, client: AsyncClient) -> None:
        _, _, headers = await _create_user_and_api_key(client)

        with patch("app.api.routers.agent._get_agent", return_value=_make_mock_orchestrator()):
            resp = await client.post(
                "/agent/query",
                json={"question": "hola"},
                headers=headers,
            )

        assert resp.status_code == 200
        session_id = resp.json()["session_id"]
        uuid.UUID(session_id)  # raises if not a valid UUID

    @pytest.mark.asyncio
    async def test_session_id_echoed_when_provided(self, client: AsyncClient) -> None:
        _, _, headers = await _create_user_and_api_key(client)
        provided_session = str(uuid.uuid4())

        orch = MagicMock()
        orch.query = AsyncMock(return_value={
            "answer": "ok",
            "tools_used": [],
            "sources": [],
            "session_id": provided_session,   # orchestrator echoes it
            "iterations": 1,
        })

        with patch("app.api.routers.agent._get_agent", return_value=orch):
            resp = await client.post(
                "/agent/query",
                json={"question": "hola", "session_id": provided_session},
                headers=headers,
            )

        assert resp.status_code == 200
        assert resp.json()["session_id"] == provided_session

    @pytest.mark.asyncio
    async def test_session_id_forwarded_to_orchestrator(
        self, client: AsyncClient
    ) -> None:
        """The session_id from the request body must reach orchestrator.query()."""
        _, _, headers = await _create_user_and_api_key(client)
        provided_session = str(uuid.uuid4())

        orch = _make_mock_orchestrator()

        with patch("app.api.routers.agent._get_agent", return_value=orch):
            await client.post(
                "/agent/query",
                json={"question": "test", "session_id": provided_session},
                headers=headers,
            )

        call_kwargs = orch.query.call_args[1]
        assert call_kwargs.get("session_id") == provided_session

    @pytest.mark.asyncio
    async def test_llm_failure_returns_502(self, client: AsyncClient) -> None:
        _, _, headers = await _create_user_and_api_key(client)

        orch = MagicMock()
        orch.query = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        with patch("app.api.routers.agent._get_agent", return_value=orch):
            resp = await client.post(
                "/agent/query",
                json={"question": "test"},
                headers=headers,
            )

        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# ConversationTurn persistence
# ---------------------------------------------------------------------------

class TestConversationTurnPersistence:
    @pytest.mark.asyncio
    async def test_query_persists_user_and_assistant_turns(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """After a query, two ConversationTurn rows must exist in the DB."""
        _, _, headers = await _create_user_and_api_key(client)
        session_id = str(uuid.uuid4())

        # Use a real orchestrator with a mocked LLM so persistence code runs.
        from app.services.agent.agent import AgentOrchestrator
        from app.services.ingestion.embedder import Embedder

        mock_llm = MagicMock()
        mock_llm.generate_with_tools = AsyncMock(
            return_value=ToolUseResult(
                final_answer="Aquí está tu respuesta.",
                tool_calls=[],
                iterations=1,
                stop_reason="end_turn",
            )
        )
        mock_llm.generate = AsyncMock(return_value="Aquí está tu respuesta.")
        orch = AgentOrchestrator(
            claude_client=mock_llm,
            embedder=MagicMock(spec=Embedder),
        )

        with patch("app.api.routers.agent._get_agent", return_value=orch):
            resp = await client.post(
                "/agent/query",
                json={"question": "¿quién soy?", "session_id": session_id},
                headers=headers,
            )

        assert resp.status_code == 200

        # Verify two rows were written to conversation_turns.
        result = await db_session.execute(
            text("SELECT role, content FROM conversation_turns WHERE session_id = :sid ORDER BY created_at"),
            {"sid": uuid.UUID(session_id).hex},
        )
        rows = result.fetchall()
        assert len(rows) == 2
        roles = [r[0] for r in rows]
        assert "user" in roles
        assert "assistant" in roles

        user_row = next(r for r in rows if r[0] == "user")
        assert user_row[1] == "¿quién soy?"

        assistant_row = next(r for r in rows if r[0] == "assistant")
        assert assistant_row[1] == "Aquí está tu respuesta."

    @pytest.mark.asyncio
    async def test_tool_calls_serialized_in_assistant_turn(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Tool calls must be serialized to JSON in the assistant turn."""
        _, _, headers = await _create_user_and_api_key(client)
        session_id = str(uuid.uuid4())

        from app.services.agent.agent import AgentOrchestrator
        from app.services.ingestion.embedder import Embedder

        mock_llm = MagicMock()
        mock_llm.generate_with_tools = AsyncMock(
            return_value=ToolUseResult(
                final_answer="Listo.",
                tool_calls=[
                    ToolCall(
                        tool_name="get_user_style",
                        tool_input={},
                        tool_result='{"persona_description": ""}',
                    )
                ],
                iterations=2,
                stop_reason="end_turn",
            )
        )
        mock_llm.generate = AsyncMock(return_value="Listo.")
        orch = AgentOrchestrator(
            claude_client=mock_llm,
            embedder=MagicMock(spec=Embedder),
        )

        with patch("app.api.routers.agent._get_agent", return_value=orch):
            resp = await client.post(
                "/agent/query",
                json={"question": "dame mi estilo", "session_id": session_id},
                headers=headers,
            )

        assert resp.status_code == 200

        result = await db_session.execute(
            text("SELECT tool_calls FROM conversation_turns WHERE session_id = :sid AND role = 'assistant'"),
            {"sid": uuid.UUID(session_id).hex},
        )
        row = result.first()
        assert row is not None
        tool_calls_raw = row[0]
        assert tool_calls_raw is not None
        parsed = json.loads(tool_calls_raw)
        assert isinstance(parsed, list)
        assert parsed[0]["tool_name"] == "get_user_style"

    @pytest.mark.asyncio
    async def test_second_query_same_session_appends_turns(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Two queries on the same session_id accumulate 4 turns total."""
        _, _, headers = await _create_user_and_api_key(client)
        session_id = str(uuid.uuid4())

        from app.services.agent.agent import AgentOrchestrator
        from app.services.ingestion.embedder import Embedder

        def _make_orch(answer: str) -> AgentOrchestrator:
            mock_llm = MagicMock()
            mock_llm.generate_with_tools = AsyncMock(
                return_value=ToolUseResult(
                    final_answer=answer,
                    tool_calls=[],
                    iterations=1,
                    stop_reason="end_turn",
                )
            )
            mock_llm.generate = AsyncMock(return_value=answer)
            return AgentOrchestrator(
                claude_client=mock_llm,
                embedder=MagicMock(spec=Embedder),
            )

        with patch("app.api.routers.agent._get_agent", return_value=_make_orch("Primera respuesta.")):
            await client.post(
                "/agent/query",
                json={"question": "primera pregunta", "session_id": session_id},
                headers=headers,
            )

        with patch("app.api.routers.agent._get_agent", return_value=_make_orch("Segunda respuesta.")):
            resp = await client.post(
                "/agent/query",
                json={"question": "segunda pregunta", "session_id": session_id},
                headers=headers,
            )

        assert resp.status_code == 200

        result = await db_session.execute(
            text("SELECT COUNT(*) FROM conversation_turns WHERE session_id = :sid"),
            {"sid": uuid.UUID(session_id).hex},
        )
        count = result.scalar()
        assert count == 4  # 2 turns per query


# ---------------------------------------------------------------------------
# Smoke: question forwarded to orchestrator
# ---------------------------------------------------------------------------

class TestAgentQueryForwarding:
    @pytest.mark.asyncio
    async def test_question_forwarded_to_orchestrator(
        self, client: AsyncClient
    ) -> None:
        _, _, headers = await _create_user_and_api_key(client)
        orch = _make_mock_orchestrator()

        with patch("app.api.routers.agent._get_agent", return_value=orch):
            await client.post(
                "/agent/query",
                json={"question": "¿qué tengo hoy?"},
                headers=headers,
            )

        orch.query.assert_awaited_once()
        call_kwargs = orch.query.call_args[1]
        assert call_kwargs["question"] == "¿qué tengo hoy?"

    @pytest.mark.asyncio
    async def test_user_id_forwarded_to_orchestrator(
        self, client: AsyncClient
    ) -> None:
        user_id, _, headers = await _create_user_and_api_key(client)
        orch = _make_mock_orchestrator()

        with patch("app.api.routers.agent._get_agent", return_value=orch):
            await client.post(
                "/agent/query",
                json={"question": "test"},
                headers=headers,
            )

        call_kwargs = orch.query.call_args[1]
        assert str(call_kwargs["user_id"]) == user_id
