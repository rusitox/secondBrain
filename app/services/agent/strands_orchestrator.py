"""Strands-based agent orchestrator — single-agent replacement for MultiAgentOrchestrator.

Uses AWS Strands Agents with an OpenAI-compatible model backend. All tools are
injected via ``make_agent_tools`` closures so the Strands Agent receives a
flat list of ready-to-call tool functions — no sub-agent parallelism required.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import (
    TYPE_CHECKING, Any, Awaitable, Callable, Coroutine, Dict, List, Optional, Tuple, cast,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation_turn import ConversationTurn

if TYPE_CHECKING:
    from strands.types.content import Message

logger = logging.getLogger(__name__)

CONVERSATION_WINDOW = 20
SESSION_EXPIRY_HOURS = 24


# ---------------------------------------------------------------------------
# Streaming callback handler
# ---------------------------------------------------------------------------

class _StreamingCallbackHandler:
    """Strands callback handler that forwards text tokens and tracks tool calls.

    Strands calls this as a plain callable with ``**kwargs``.  The relevant
    keys we care about are:

    - ``data`` (str): Incremental text chunk from the LLM.
    - ``complete`` (bool): True on the last chunk of a response turn.
    - ``current_tool_use`` (dict): Present when a tool-use block is streaming;
      contains at minimum ``{"name": "<tool_name>", ...}``.
    """

    def __init__(
        self,
        stream_callback: Optional[Callable[[str], Awaitable[None]]],
    ) -> None:
        self._stream_callback = stream_callback
        self.tools_used: List[str] = []
        self._seen_tools: set = set()
        self.iterations: int = 0

    def __call__(self, **kwargs: Any) -> None:
        """Receive a Strands event and act on it synchronously.

        Strands fires this from an async context but the handler itself must
        be a regular (sync) callable.  We schedule coroutines back onto the
        running loop with ``asyncio.ensure_future``.
        """
        # Track tool calls — fires once per tool block with its name
        current_tool_use: Optional[Dict[str, Any]] = kwargs.get("current_tool_use")
        if current_tool_use:
            tool_name: str = current_tool_use.get("name", "")
            if tool_name and tool_name not in self._seen_tools:
                self.tools_used.append(tool_name)
                self._seen_tools.add(tool_name)
                self.iterations += 1
                logger.debug("StrandsOrchestrator: tool called=%s", tool_name)

        # Forward text tokens to the SSE stream_callback
        data: str = kwargs.get("data", "")
        if data and self._stream_callback is not None:
            try:
                loop = asyncio.get_running_loop()
                coro = self._stream_callback(data)
                loop.create_task(coro)  # type: ignore[arg-type]
            except RuntimeError:
                # Strands called this callback from a thread without a running loop.
                # Tokens are lost in this path — log so it's visible if it happens.
                logger.warning(
                    "StrandsOrchestrator: stream callback fired outside event loop — token discarded"
                )


# ---------------------------------------------------------------------------
# StrandsOrchestrator
# ---------------------------------------------------------------------------

class StrandsOrchestrator:
    """Single Strands Agent orchestrator with conversation persistence.

    Drop-in async replacement for ``MultiAgentOrchestrator``.  Builds a
    Strands ``Agent`` per request (stateless) so there are no concurrency
    issues with shared agent state.
    """

    def __init__(self, embedder: Optional[Any] = None) -> None:
        self._embedder = embedder

    async def query(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        question: str,
        session_id: Optional[str] = None,
        stream_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """Run a query through the Strands agent.

        Steps:
        1. Resolve/load conversation session from DB.
        2. Fetch user identity and communication style.
        3. Build system prompt incorporating identity, style, and date.
        4. Instantiate a Strands Agent with all tools.
        5. Run the agent (streaming if ``stream_callback`` is provided).
        6. Persist conversation turns.
        7. Return structured result dict.

        Args:
            db: Async SQLAlchemy session for the current request.
            user_id: Authenticated user's UUID.
            question: Raw user question text.
            session_id: Existing session UUID string, or None to start fresh.
            stream_callback: Async callable that receives incremental text
                tokens for SSE streaming.  Pass None for non-streaming queries.

        Returns:
            Dict with keys: answer, tools_used, sources, session_id, iterations.
        """
        # 1. Resolve session and load history
        resolved_session_id, history = await self._resolve_session(db, user_id, session_id)

        # 2. Fetch user identity and style
        user_name, user_email, user_tz = await self._fetch_user_identity(db, user_id)
        style_info = await self._fetch_user_style(db, user_id)
        style_text = _format_style(style_info)

        # 3. Build system prompt
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        system_prompt = _build_system_prompt(
            today_str=today_str,
            user_name=user_name,
            user_email=user_email,
            user_timezone=user_tz,
            style_text=style_text,
        )

        # Keep the question clean — identity context lives in system_prompt only
        identity_prefix = ""
        augmented_question = identity_prefix + question

        logger.info(
            "StrandsOrchestrator: starting query user=%s session=%s question=%r",
            user_id,
            resolved_session_id,
            question[:80],
        )

        # 4. Build Strands Agent
        agent = self._build_agent(
            db=db,
            user_id=user_id,
            user_tz=user_tz,
            system_prompt=system_prompt,
            history=history,
            stream_callback=stream_callback,
        )

        # 5. Run agent
        handler: _StreamingCallbackHandler = agent.callback_handler  # type: ignore[assignment]
        try:
            if stream_callback is not None:
                # stream_async yields events; we consume them all so tokens
                # flow through the callback handler to the SSE endpoint.
                async for _event in agent.stream_async(augmented_question):
                    pass  # tokens already forwarded inside _StreamingCallbackHandler
                # After exhausting the iterator the agent result is in agent.messages
                answer = _extract_last_assistant_text(agent.messages)
            else:
                await agent.invoke_async(augmented_question)
                answer = _extract_last_assistant_text(agent.messages)
        except Exception:
            logger.exception(
                "StrandsOrchestrator: agent failed for user=%s question=%r",
                user_id,
                question[:80],
            )
            raise

        tools_used = handler.tools_used
        iterations = handler.iterations + 1  # +1 for the LLM synthesis turn

        logger.info(
            "StrandsOrchestrator: completed user=%s tools=%s iterations=%d",
            user_id,
            tools_used,
            iterations,
        )

        # 6. Persist turns
        await self._persist_turns(db, user_id, resolved_session_id, question, answer)

        # 7. Return result
        return {
            "answer": answer,
            "tools_used": tools_used,
            "sources": [],   # Strands tools return results directly to the LLM; no separate source list
            "session_id": resolved_session_id,
            "iterations": iterations,
        }

    # ------------------------------------------------------------------
    # Agent construction
    # ------------------------------------------------------------------

    def _build_agent(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        user_tz: str,
        system_prompt: str,
        history: List[Dict[str, Any]],
        stream_callback: Optional[Callable[[str], Awaitable[None]]],
    ) -> Any:
        """Instantiate a Strands Agent for a single request.

        A new agent is created per request so there is no shared mutable
        state between concurrent queries.

        Uses SequentialToolExecutor: Strands runs multiple tool calls from one
        LLM turn concurrently by default, but every tool in make_agent_tools
        closes over this same AsyncSession, which is not safe for concurrent
        use from more than one task at a time (same reasoning as
        app/services/agent/knowledge/domain_agent.py's make_domain_agent).
        """
        from strands import Agent
        from strands.tools.executors import SequentialToolExecutor

        from app.services.agent.strands_model import build_openai_model
        from app.services.agent.strands_tools import make_agent_tools

        model = build_openai_model()

        tools = make_agent_tools(
            db=db,
            user_id=user_id,
            user_timezone=user_tz,
            embedder=self._embedder,
        )

        callback_handler = _StreamingCallbackHandler(stream_callback)

        # Pre-load conversation history as Strands messages if available
        initial_messages = _history_to_strands_messages(history) if history else []

        agent = Agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            callback_handler=callback_handler,
            messages=initial_messages,
            tool_executor=SequentialToolExecutor(),
        )

        return agent

    # ------------------------------------------------------------------
    # Session management (mirrored from MultiAgentOrchestrator)
    # ------------------------------------------------------------------

    async def _resolve_session(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        session_id: Optional[str],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Return (resolved_session_id, history_messages).

        Starts a new session if session_id is None, an invalid UUID, or
        the most recent turn exceeds SESSION_EXPIRY_HOURS.
        """
        if session_id is None:
            return str(uuid.uuid4()), []

        try:
            uuid.UUID(session_id)
        except ValueError:
            return str(uuid.uuid4()), []

        stmt = (
            select(ConversationTurn)
            .where(
                ConversationTurn.user_id == user_id,
                ConversationTurn.session_id == uuid.UUID(session_id),
            )
            .order_by(ConversationTurn.created_at.desc())
            .limit(CONVERSATION_WINDOW)
        )
        rows = (await db.execute(stmt)).scalars().all()

        if not rows:
            return session_id, []

        most_recent = rows[0]
        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(hours=SESSION_EXPIRY_HOURS)
        created = most_recent.created_at
        if created is not None:
            # Normalize to aware UTC for consistent comparison regardless of DB driver tz handling
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        if created is not None and created < cutoff:
            return str(uuid.uuid4()), []

        history = [
            {"role": turn.role, "content": turn.content}
            for turn in reversed(rows)
        ]
        return session_id, history

    async def _persist_turns(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        sid: str,
        question: str,
        answer: str,
    ) -> None:
        """Write user + assistant ConversationTurn rows to the database."""
        session_uuid = uuid.UUID(sid)

        db.add(ConversationTurn(
            user_id=user_id,
            session_id=session_uuid,
            role="user",
            content=question,
            tool_calls=None,
        ))

        db.add(ConversationTurn(
            user_id=user_id,
            session_id=session_uuid,
            role="assistant",
            content=answer,
            tool_calls=None,  # Strands manages tool history internally
        ))

        await db.flush()

    # ------------------------------------------------------------------
    # User identity + style
    # ------------------------------------------------------------------

    async def _fetch_user_identity(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> Tuple[Optional[str], Optional[str], str]:
        """Return (full_name, email, timezone) for user_id.

        Falls back to (None, None, "UTC") if the user record is not found.
        """
        from app.models.user import User

        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is not None:
            tz = user.timezone if user.timezone else "UTC"
            return user.full_name, user.email, tz
        return None, None, "UTC"

    async def _fetch_user_style(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """Return the user's style/persona dict from StyleAnalyzerTool."""
        from app.services.agent.tools.style_analyzer import StyleAnalyzerTool

        return await StyleAnalyzerTool().get_style(db, user_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_system_prompt(
    today_str: str,
    user_name: Optional[str],
    user_email: Optional[str],
    user_timezone: str,
    style_text: str,
) -> str:
    """Compose the agent system prompt."""
    identity_line = (
        f"Usuario: {user_name} <{user_email}> | Timezone: {user_timezone}"
        if user_name
        else f"Timezone: {user_timezone}"
    )
    return f"""Sos un AI Chief of Staff personal.

Fecha de hoy: {today_str}
{identity_line}

Estilo de comunicación del usuario:
{style_text}

Workflow obligatorio:
1. Llamá get_current_datetime si necesitás confirmar la fecha
2. Si la pregunta es sobre una persona, proyecto o tema específico, probá primero \
query_knowledge — es la vista consolidada y con proveniencia que arman los agentes \
de dominio, y trae su propio nivel de confianza. Si no encontrás nada ahí, o \
necesitás más contexto crudo, usá search_memory y search_learnings.
3. Al empezar la conversación (o cuando sea natural), llamá get_pending_questions — \
son dudas que los agentes de dominio no pudieron resolver solos y te piden que se \
las confirmes al humano. Si hay alguna relevante, planteala con naturalidad, no la \
fuerces en cada respuesta. Si el usuario confirma o corrige, llamá \
confirm_pending_answer para cerrar el loop — esa respuesta pasa a ser conocimiento \
de alta confianza.
4. Llamá otras tools según lo requiera la pregunta
5. Sintetizá una respuesta clara y accionable

Respondé siempre en el idioma del usuario."""


def _format_style(style_info: Dict[str, Any]) -> str:
    """Convert StyleAnalyzerTool output to a compact string for the prompt."""
    parts: List[str] = []
    persona = style_info.get("persona_description", "")
    tone = style_info.get("tone_guidelines", "")
    if persona:
        parts.append(f"Persona: {persona}")
    if tone:
        parts.append(f"Tone: {tone}")
    return " | ".join(parts) if parts else "No style profile available."


def _history_to_strands_messages(
    history: List[Dict[str, Any]],
) -> "List[Message]":
    """Convert our DB history format to Strands message format.

    Strands messages are dicts with ``role`` and ``content`` where content
    is a list of content blocks: ``[{"text": "..."}]``.
    """
    messages: List[Dict[str, Any]] = []
    for turn in history:
        role = turn.get("role", "user")
        content_str = turn.get("content", "")
        messages.append({
            "role": role,
            "content": [{"text": content_str}],
        })
    return cast("List[Message]", messages)


def _extract_last_assistant_text(messages: List[Any]) -> str:
    """Extract the last assistant message text from Strands agent messages list.

    Used after ``stream_async`` completes to retrieve the full answer since
    streaming does not return an ``AgentResult`` directly.
    """
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        text_parts: List[str] = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        if text_parts:
            return " ".join(text_parts).strip()
    return ""
