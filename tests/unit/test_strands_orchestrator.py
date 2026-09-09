"""Unit tests for StrandsOrchestrator — the production agent orchestrator.

Covers session resolution/expiry, turn persistence, system prompt / style
formatting, Strands message conversion, the reasoning_effort guard for
reasoning models, and the streaming callback handler — none of which had
test coverage before this file (StrandsOrchestrator shipped without tests,
which is what let the SSE NameError and callback thread-safety bugs reach
review undetected).
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.agent_run import RunStatus
from app.services.agent.agent_config_service import EffectiveAgentConfig
from app.services.agent.strands_orchestrator import (
    StrandsOrchestrator,
    _StreamingCallbackHandler,
    _build_system_prompt,
    _extract_last_assistant_text,
    _format_style,
    _history_to_strands_messages,
)


def _make_empty_db():
    """Mock AsyncSession returning no rows for any select()."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    return db


def _make_turn(role: str, content: str, created_at: datetime) -> MagicMock:
    turn = MagicMock()
    turn.role = role
    turn.content = content
    turn.created_at = created_at
    return turn


# ---------------------------------------------------------------------------
# _resolve_session
# ---------------------------------------------------------------------------

class TestResolveSession:
    @pytest.mark.asyncio
    async def test_no_session_id_generates_new_one(self) -> None:
        orch = StrandsOrchestrator()
        sid, history = await orch._resolve_session(_make_empty_db(), uuid.uuid4(), None)
        assert uuid.UUID(sid)
        assert history == []

    @pytest.mark.asyncio
    async def test_invalid_uuid_generates_new_session(self) -> None:
        orch = StrandsOrchestrator()
        sid, history = await orch._resolve_session(_make_empty_db(), uuid.uuid4(), "not-a-uuid")
        assert uuid.UUID(sid)
        assert history == []

    @pytest.mark.asyncio
    async def test_valid_session_no_rows_is_echoed(self) -> None:
        orch = StrandsOrchestrator()
        provided = str(uuid.uuid4())
        sid, history = await orch._resolve_session(_make_empty_db(), uuid.uuid4(), provided)
        assert sid == provided
        assert history == []

    @pytest.mark.asyncio
    async def test_recent_session_returns_history_in_chronological_order(self) -> None:
        orch = StrandsOrchestrator()
        provided = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        rows = [
            _make_turn("assistant", "second", now - timedelta(minutes=1)),
            _make_turn("user", "first", now - timedelta(minutes=2)),
        ]
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = rows
        db.execute = AsyncMock(return_value=mock_result)

        sid, history = await orch._resolve_session(db, uuid.uuid4(), provided)

        assert sid == provided
        assert [h["content"] for h in history] == ["first", "second"]

    @pytest.mark.asyncio
    async def test_expired_session_naive_created_at_starts_fresh(self) -> None:
        """created_at older than 24h and naive (no tzinfo) — common with SQLite/Supabase."""
        orch = StrandsOrchestrator()
        provided = str(uuid.uuid4())
        stale_naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=25)
        rows = [_make_turn("assistant", "old", stale_naive)]
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = rows
        db.execute = AsyncMock(return_value=mock_result)

        sid, history = await orch._resolve_session(db, uuid.uuid4(), provided)

        assert sid != provided
        assert uuid.UUID(sid)
        assert history == []

    @pytest.mark.asyncio
    async def test_fresh_session_naive_created_at_keeps_history(self) -> None:
        """Regression guard: a naive created_at within the window must NOT be treated
        as expired just because it lacks tzinfo (this was the datetime bug fixed in
        the code review — comparing naive-local vs aware-UTC could misfire)."""
        orch = StrandsOrchestrator()
        provided = str(uuid.uuid4())
        fresh_naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
        rows = [_make_turn("assistant", "recent", fresh_naive)]
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = rows
        db.execute = AsyncMock(return_value=mock_result)

        sid, history = await orch._resolve_session(db, uuid.uuid4(), provided)

        assert sid == provided
        assert len(history) == 1


# ---------------------------------------------------------------------------
# _persist_turns
# ---------------------------------------------------------------------------

class TestPersistTurns:
    @pytest.mark.asyncio
    async def test_persists_user_and_assistant_turns_with_no_tool_calls(self) -> None:
        orch = StrandsOrchestrator()
        db = AsyncMock()
        sid = str(uuid.uuid4())
        user_id = uuid.uuid4()

        await orch._persist_turns(db, user_id, sid, "hola", "che, como andas")

        assert db.add.call_count == 2
        added = [call.args[0] for call in db.add.call_args_list]
        roles = {row.role: row for row in added}
        assert roles["user"].content == "hola"
        assert roles["assistant"].content == "che, como andas"
        # Strands manages its own tool history — we never persist tool_calls
        assert roles["user"].tool_calls is None
        assert roles["assistant"].tool_calls is None
        db.flush.assert_awaited_once()


class TestQueryBuildAgentFailure:
    """tracing.start_run now runs before _build_agent (so run_id can thread
    into make_agent_tools as parent_run_id) — a regression this reorder could
    introduce is a _build_agent failure leaving that AgentRun row permanently
    RUNNING, since before the reorder no row existed yet at that point."""

    @pytest.mark.asyncio
    async def test_build_agent_failure_finishes_the_run_as_failed(self) -> None:
        orch = StrandsOrchestrator()
        db = _make_empty_db()
        user_id = uuid.uuid4()
        run_id = uuid.uuid4()
        config = EffectiveAgentConfig(
            enabled=True, model_id=None, system_prompt="x", enabled_tools=None,
        )
        settings = MagicMock()
        settings.llm_model = "openai/gpt-4o-mini"

        with patch(
            "app.services.agent.strands_orchestrator.agent_config_service.get_effective_config",
            AsyncMock(return_value=config),
        ), patch(
            "app.services.agent.strands_orchestrator.tracing.start_run",
            AsyncMock(return_value=run_id),
        ) as mock_start_run, patch(
            "app.services.agent.strands_orchestrator.tracing.finish_run", AsyncMock(),
        ) as mock_finish_run, patch(
            "app.core.config.get_settings", return_value=settings,
        ), patch.object(
            StrandsOrchestrator, "_build_agent", side_effect=RuntimeError("boom"),
        ) as mock_build_agent:
            with pytest.raises(RuntimeError, match="boom"):
                await orch.query(db, user_id, "hola")

        mock_start_run.assert_awaited_once()
        # The run_id start_run returned is the one _build_agent (and therefore
        # make_agent_tools' parent_run_id) actually received.
        assert mock_build_agent.call_args.kwargs["run_id"] == run_id
        mock_finish_run.assert_awaited_once_with(run_id, RunStatus.FAILED, error="boom")


# ---------------------------------------------------------------------------
# _build_agent — reasoning_effort guard
# ---------------------------------------------------------------------------

class TestBuildAgentReasoningGuard:
    def _run_build(self, llm_model: str):
        orch = StrandsOrchestrator(embedder=MagicMock())
        settings = MagicMock()
        settings.llm_model = llm_model
        settings.llm_api_key = "sk-test"

        with patch("strands.Agent") as mock_agent_cls, \
             patch("strands.models.openai.OpenAIModel") as mock_model_cls, \
             patch("app.core.config.get_settings", return_value=settings), \
             patch("app.services.agent.strands_tools.make_agent_tools", return_value=[]):
            orch._build_agent(
                db=MagicMock(),
                user_id=uuid.uuid4(),
                user_tz="UTC",
                system_prompt="sys",
                history=[],
                stream_callback=None,
            )
        return mock_model_cls

    def test_reasoning_model_gets_reasoning_effort_none(self) -> None:
        mock_model_cls = self._run_build("openai/gpt-5.6-luna")
        _, kwargs = mock_model_cls.call_args
        assert kwargs["params"] == {"reasoning_effort": "none"}
        assert kwargs["model_id"] == "gpt-5.6-luna"

    @pytest.mark.parametrize("model_id", ["o1", "o1-mini", "o3", "o3-mini", "o4-mini"])
    def test_o_series_models_get_reasoning_effort_none(self, model_id: str) -> None:
        mock_model_cls = self._run_build(model_id)
        _, kwargs = mock_model_cls.call_args
        assert kwargs["params"] == {"reasoning_effort": "none"}

    def test_non_reasoning_model_gets_no_params(self) -> None:
        mock_model_cls = self._run_build("openai/gpt-4o-mini")
        _, kwargs = mock_model_cls.call_args
        assert kwargs["params"] is None
        assert kwargs["model_id"] == "gpt-4o-mini"


class TestBuildAgentWithConfig:
    """Phase 2 — config overrides model/tools for the orchestrator, but never
    system_prompt (see _build_agent's own docstring for why)."""

    def _run_build(self, config: EffectiveAgentConfig, tools=None):
        orch = StrandsOrchestrator(embedder=MagicMock())
        settings = MagicMock()
        settings.llm_model = "openai/gpt-4o-mini"
        settings.llm_api_key = "sk-test"

        with patch("strands.Agent") as mock_agent_cls, \
             patch("strands.models.openai.OpenAIModel") as mock_model_cls, \
             patch("app.core.config.get_settings", return_value=settings), \
             patch(
                 "app.services.agent.strands_tools.make_agent_tools",
                 return_value=tools if tools is not None else [],
             ):
            orch._build_agent(
                db=MagicMock(), user_id=uuid.uuid4(), user_tz="UTC",
                system_prompt="dynamic per-request prompt", history=[], stream_callback=None,
                config=config,
            )
        return mock_model_cls, mock_agent_cls

    def test_model_id_override_reaches_build_openai_model(self) -> None:
        config = EffectiveAgentConfig(
            enabled=True, model_id="openai/gpt-4o", system_prompt="ignored", enabled_tools=None,
        )
        mock_model_cls, _ = self._run_build(config)
        assert mock_model_cls.call_args.kwargs["model_id"] == "gpt-4o"

    def test_enabled_tools_filters_orchestrator_tools(self) -> None:
        def _fake_tool(name: str):
            t = MagicMock()
            t.tool_name = name
            return t

        config = EffectiveAgentConfig(
            enabled=True, model_id=None, system_prompt="ignored", enabled_tools=["search_memory"],
        )
        _, mock_agent_cls = self._run_build(
            config, tools=[_fake_tool("search_memory"), _fake_tool("web_search")],
        )
        tool_names = {t.tool_name for t in mock_agent_cls.call_args.kwargs["tools"]}
        assert tool_names == {"search_memory"}

    def test_system_prompt_is_never_overridden_by_config(self) -> None:
        """The dynamic per-request prompt (identity/style/date) always wins —
        config.system_prompt is intentionally not wired for the orchestrator."""
        config = EffectiveAgentConfig(
            enabled=True, model_id=None, system_prompt="a config override", enabled_tools=None,
        )
        _, mock_agent_cls = self._run_build(config)
        assert mock_agent_cls.call_args.kwargs["system_prompt"] == "dynamic per-request prompt"

    def test_disabled_config_does_not_stop_the_orchestrator(self) -> None:
        """Deliberate carve-out (see _build_agent's docstring): unlike
        run_domain_agent/run_rd_domain_agent, the orchestrator ignores
        config.enabled — disabling the whole chat interface via a stray
        config row would be a worse failure mode than a no-op knowledge
        agent. This test pins that choice down, not just the docstring."""
        config = EffectiveAgentConfig(
            enabled=False, model_id=None, system_prompt="ignored", enabled_tools=None,
        )
        _, mock_agent_cls = self._run_build(config)
        mock_agent_cls.assert_called_once()


# ---------------------------------------------------------------------------
# _StreamingCallbackHandler
# ---------------------------------------------------------------------------

class TestStreamingCallbackHandler:
    def test_tracks_unique_tool_calls_and_increments_iterations(self) -> None:
        handler = _StreamingCallbackHandler(stream_callback=None)
        handler(current_tool_use={"name": "search_memory"})
        handler(current_tool_use={"name": "search_memory"})  # duplicate, ignored
        handler(current_tool_use={"name": "list_tasks"})

        assert handler.tools_used == ["search_memory", "list_tasks"]
        assert handler.iterations == 2

    def test_ignores_tool_use_with_no_name(self) -> None:
        handler = _StreamingCallbackHandler(stream_callback=None)
        handler(current_tool_use={})
        assert handler.tools_used == []
        assert handler.iterations == 0

    @pytest.mark.asyncio
    async def test_forwards_text_tokens_to_stream_callback(self) -> None:
        received: list = []

        async def on_token(text: str) -> None:
            received.append(text)

        handler = _StreamingCallbackHandler(stream_callback=on_token)
        handler(data="hola ")
        handler(data="mundo")
        # The handler schedules tasks on the running loop — let them run.
        await asyncio.sleep(0)

        assert received == ["hola ", "mundo"]

    def test_no_stream_callback_does_not_raise(self) -> None:
        handler = _StreamingCallbackHandler(stream_callback=None)
        handler(data="token")  # must be a no-op, not an error

    def test_callback_outside_event_loop_logs_and_does_not_raise(self) -> None:
        """Regression guard for the thread-safety issue flagged in code review:
        if Strands fires the callback off the event loop, tokens are dropped
        but the handler must not crash the agent run."""
        async def on_token(text: str) -> None:
            pass

        handler = _StreamingCallbackHandler(stream_callback=on_token)
        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no running loop")):
            handler(data="token")  # should swallow and log, not raise


# ---------------------------------------------------------------------------
# Prompt / message helpers
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    def test_includes_identity_when_user_known(self) -> None:
        prompt = _build_system_prompt(
            today_str="2026-09-04",
            user_name="Mariano Ortega",
            user_email="mariano@example.com",
            user_timezone="America/Argentina/Buenos_Aires",
            style_text="Persona: directo",
        )
        assert "Mariano Ortega" in prompt
        assert "mariano@example.com" in prompt
        assert "2026-09-04" in prompt

    def test_falls_back_to_timezone_only_when_no_user(self) -> None:
        prompt = _build_system_prompt(
            today_str="2026-09-04",
            user_name=None,
            user_email=None,
            user_timezone="UTC",
            style_text="No style profile available.",
        )
        assert "Timezone: UTC" in prompt
        assert "Usuario:" not in prompt


class TestFormatStyle:
    def test_no_style_info_returns_fallback(self) -> None:
        assert _format_style({}) == "No style profile available."

    def test_persona_and_tone_joined(self) -> None:
        result = _format_style({
            "persona_description": "Directo",
            "tone_guidelines": "Conciso",
        })
        assert result == "Persona: Directo | Tone: Conciso"

    def test_persona_only(self) -> None:
        result = _format_style({"persona_description": "Directo", "tone_guidelines": ""})
        assert result == "Persona: Directo"


class TestHistoryToStrandsMessages:
    def test_converts_role_and_content(self) -> None:
        history = [
            {"role": "user", "content": "hola"},
            {"role": "assistant", "content": "che como andas"},
        ]
        messages = _history_to_strands_messages(history)
        assert messages == [
            {"role": "user", "content": [{"text": "hola"}]},
            {"role": "assistant", "content": [{"text": "che como andas"}]},
        ]

    def test_empty_history_returns_empty_list(self) -> None:
        assert _history_to_strands_messages([]) == []


class TestExtractLastAssistantText:
    def test_returns_last_assistant_message_text(self) -> None:
        messages = [
            {"role": "user", "content": [{"text": "hola"}]},
            {"role": "assistant", "content": [{"text": "primera"}]},
            {"role": "user", "content": [{"text": "y despues?"}]},
            {"role": "assistant", "content": [{"text": "segunda"}]},
        ]
        assert _extract_last_assistant_text(messages) == "segunda"

    def test_joins_multiple_text_blocks(self) -> None:
        messages = [
            {"role": "assistant", "content": [{"text": "parte uno"}, {"text": "parte dos"}]},
        ]
        assert _extract_last_assistant_text(messages) == "parte uno parte dos"

    def test_no_assistant_message_returns_empty_string(self) -> None:
        messages = [{"role": "user", "content": [{"text": "hola"}]}]
        assert _extract_last_assistant_text(messages) == ""

    def test_empty_messages_returns_empty_string(self) -> None:
        assert _extract_last_assistant_text([]) == ""
