"""Chat session — main interactive loop for daily use.

Handles natural language queries via the agent API and /slash commands
via the CommandRouter. Uses prompt_toolkit for input with history and
autocompletion.
"""
import logging
from pathlib import Path
from typing import Optional

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
        """Send a natural language query to the agent API."""
        with spinner("Thinking..."):
            try:
                result = await self._api.agent_query(question)
            except APIError as e:
                if e.status_code == 503:
                    print_warning("Agent service unavailable. Is the backend running?")
                else:
                    print_error("Query failed: %s" % e.detail)
                return

        # Display answer
        answer = result.get("answer", "")
        if answer:
            print_panel(answer, title="Answer", style="green")
        else:
            print_info("No answer returned.")

        # Show metadata
        tools = result.get("tools_used", [])
        sources = result.get("sources", [])
        meta_parts = []
        if tools:
            meta_parts.append("tools: %s" % ", ".join(tools))
        if sources:
            meta_parts.append("sources: %d documents" % len(sources))
        if meta_parts:
            print_muted("  " + " | ".join(meta_parts))

    async def _show_welcome(self) -> None:
        """Show welcome banner with status summary."""
        name = self._config.user_name or "there"

        # Try to fetch stats
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

        console.print()
        print_panel("\n".join(lines), title="secondBrain", style="blue")
        console.print()
