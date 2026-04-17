"""Chat session — main interactive loop for daily use.

Full implementation in Phase 7C.
"""
import logging

from cli.api_client import APIClient
from cli.config import CLIConfig
from cli.display import console, print_info, print_welcome

logger = logging.getLogger(__name__)


class ChatSession:
    """Interactive chat session."""

    def __init__(self, api: APIClient, config: CLIConfig) -> None:
        self._api = api
        self._config = config

    async def run(self) -> None:
        """Run the chat loop."""
        name = self._config.user_name or "there"
        print_welcome(
            f"secondBrain — Hey {name}!",
            "Chat session will be available in Phase 7C.\n"
            "Type /quit to exit.",
        )

        while True:
            try:
                user_input = console.input("[bold]you>[/bold] ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue
            if user_input in ("/quit", "/exit", "/q"):
                break

            print_info("Chat not yet implemented. Use the API directly for now.")

        console.print("[muted]Goodbye![/muted]")
