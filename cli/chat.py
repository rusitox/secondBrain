"""Chat session — main interactive loop for daily use.

Handles natural language queries via the agent API and /slash commands
via the CommandRouter. Uses prompt_toolkit for input with history and
autocompletion.
"""
import logging
import uuid
from pathlib import Path
from typing import Any, List, Optional

import httpx

from cli.alerts import AlertManager
from cli.api_client import APIClient, APIError
from cli.background import BackgroundSync
from cli.commands import CommandRouter
from cli.config import CLIConfig, DEFAULT_CONFIG_DIR
from cli.display import (
    console,
    print_error,
    print_info,
    print_markdown,
    print_muted,
    print_panel,
    print_stats,
    print_warning,
    spinner,
)

logger = logging.getLogger(__name__)

HISTORY_FILE = DEFAULT_CONFIG_DIR / "history"

# Prompt sent to the agent as the first turn of every session.
# Instructs it to build a genuinely personalised, context-aware greeting
# using everything it knows and can look up — not a generic template.
_WELCOME_PROMPT = """
Inicio de jornada. Hacé solo esto:
1. list_tasks → cantidad de pendientes detectados
2. get_calendar → reuniones de hoy que no empezaron

Respondé en máximo 4 líneas:
- Saludo breve y cálido (una frase).
- Reuniones de hoy (solo hora y título, sin descripción).
- Si hay pendientes: "Encontré X items por verificar — ¿arrancamos por ahí?"
- Una pregunta o acción concreta para empezar.

Sin listas largas. Sin análisis. Sin repetir contexto. Solo lo esencial.
Respondé en el idioma del usuario.
"""


def _create_prompt_session():
    """Create a prompt_toolkit session with history and autocompletion.

    Returns None if prompt_toolkit is not available (fallback to console.input).
    """
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import WordCompleter
        from prompt_toolkit.history import FileHistory

        commands = [
            "/briefing", "/commitments", "/overdue", "/sync",
            "/connect", "/disconnect", "/status", "/identity",
            "/settings", "/setup", "/help", "/quit",
        ]
        completer = WordCompleter(commands, sentence=True)

        # Ensure history dir exists
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

        return PromptSession(
            history=FileHistory(str(HISTORY_FILE)),
            completer=completer,
        )
    except ImportError:
        logger.debug("prompt_toolkit not available, using basic input")
        return None


class ChatSession:
    """Interactive chat session with query routing and slash commands."""

    def __init__(self, api: APIClient, config: CLIConfig) -> None:
        self._api = api
        self._config = config
        self._router = CommandRouter(api=api, config=config)
        self._alerts = AlertManager()
        self._background = BackgroundSync(
            api=api, config=config, on_sync_result=self._alerts.on_sync_result,
        )
        self._prompt_session = _create_prompt_session()
        self._session_id: Optional[str] = str(uuid.uuid4())
        self._session_shown: bool = False

    async def run(self) -> None:
        """Run the chat loop with background sync."""
        try:
            await self._show_welcome()

            # Start background sync if platforms are connected
            if self._config.platforms_connected:
                await self._background.start()

            while True:
                # Show any pending alerts from background sync
                self._alerts.show_pending()

                try:
                    user_input = await self._get_input()
                except (EOFError, KeyboardInterrupt):
                    break

                if user_input is None:
                    break

                user_input = user_input.strip()
                if not user_input:
                    continue

                if user_input.startswith("/"):
                    await self._router.dispatch(user_input)
                    if self._router.should_quit:
                        break
                else:
                    await self._handle_query(user_input)
        finally:
            await self._background.stop()
            await self._api.close()
            console.print("[muted]Goodbye![/muted]")

    async def _get_input(self) -> Optional[str]:
        """Get user input with prompt_toolkit or fallback."""
        try:
            if self._prompt_session is not None:
                return await self._prompt_session.prompt_async("you> ")
            else:
                return console.input("[bold]you>[/bold] ")
        except (EOFError, KeyboardInterrupt):
            return None

    async def _handle_query(self, question: str) -> None:
        """Send a natural language query to the agent API, streaming the response."""
        import sys

        tools_announced: List[str] = []
        answer_started = False
        tools_used: List[Any] = []

        print_muted("Pensando...")

        try:
            async for event, data in self._api.agent_query_stream(
                question, session_id=self._session_id
            ):
                if event == "tool_call":
                    tool = data.get("tool", "")
                    if tool not in tools_announced:
                        print_muted("  * %s" % tool)
                        tools_announced.append(tool)
                elif event == "token":
                    if not answer_started:
                        console.print()
                        console.rule("[bold green]Respuesta[/bold green]")
                        answer_started = True
                    sys.stdout.write(data.get("text", ""))
                    sys.stdout.flush()
                elif event == "done":
                    if answer_started:
                        console.print()
                        console.rule()
                    tools_used = data.get("tools_used", [])
                    session_from_event = data.get("session_id", "")
                    if session_from_event and not self._session_shown:
                        console.print("[dim]session: %s...[/dim]" % session_from_event[:8])
                        self._session_shown = True
                elif event == "error":
                    print_error("Query failed: %s" % data.get("detail", "Unknown error"))
                    return
        except httpx.TimeoutException:
            print_warning("Query timed out — the server may still be processing.")
            return
        except APIError as e:
            if e.status_code == 503:
                print_warning("Agent service unavailable.")
            else:
                print_error("Query failed: %s" % e.detail)
            return

        if not answer_started:
            print_info("No answer returned.")
            return

        if tools_used:
            print_muted("  tools: %s" % ", ".join(tools_used))

    async def _show_welcome(self) -> None:
        """Show a proactive, personalised welcome generated by the agent.

        The agent runs the full tool-use loop (style, learnings, memory, tasks,
        calendar) to build a context-aware greeting. Falls back to the static
        stats panel if the agent call fails or times out.
        """
        console.print()
        if not self._config.user_id:
            await self._show_static_welcome()
            return

        print_muted("Preparando tu bienvenida...")
        try:
            with spinner(""):
                result = await self._api.agent_query(
                    _WELCOME_PROMPT, session_id=self._session_id
                )
            answer = result.get("answer", "").strip()
            if answer:
                name = self._config.user_name or ""
                title = "secondBrain — %s" % name if name else "secondBrain"
                print_panel(answer, title=title, style="blue")
                self._session_shown = True
                console.print()
                return
        except (httpx.TimeoutException, APIError, Exception) as exc:
            logger.debug("Proactive welcome failed, falling back to static: %s", exc)

        await self._show_static_welcome()

    async def _show_static_welcome(self) -> None:
        """Fallback welcome: static stats panel (original behaviour)."""
        name = self._config.user_name or "there"

        stats_line = ""
        if self._config.user_id:
            try:
                stats = await self._api.get_user_stats(self._config.user_id)
                docs = stats.get("documents_total", 0)
                pending = stats.get("commitments_pending", 0)
                overdue = stats.get("commitments_overdue", 0)
                parts = ["Documents: %d" % docs, "Commitments: %d pending" % pending]
                if overdue:
                    parts.append("%d overdue" % overdue)
                stats_line = "  " + " | ".join(parts)
            except APIError:
                stats_line = ""

        platforms = self._config.platforms_connected
        platform_line = ""
        if platforms:
            names = [p.capitalize() for p in platforms]
            platform_line = "  Connected: %s" % ", ".join(names)

        lines = ["Hey %s!" % name]
        if platform_line:
            lines.append(platform_line)
        if stats_line:
            lines.append(stats_line)
        lines.append("")
        lines.append("  Type a question or /help for commands.")

        print_panel("\n".join(lines), title="secondBrain", style="blue")
        console.print()
