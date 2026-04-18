"""Notion integration setup — interactive CLI flow for connecting Notion.

Used both during onboarding (Step 2b) and via /notion connect command.
"""
import logging
from typing import Optional

import httpx

from cli.api_client import APIClient, APIError
from cli.config import CLIConfig
from cli.display import (
    console,
    print_error,
    print_info,
    print_success,
    print_warning,
    spinner,
)

logger = logging.getLogger(__name__)

NOTION_INTRO = (
    "Would you like to connect Notion?\n"
    "\n"
    "Notion lets me:\n"
    "  \u2022 Read your pages and databases as knowledge source\n"
    "  \u2022 Maintain a shared workspace where I publish:\n"
    "    - Your commitment tracking board\n"
    "    - Daily briefings as pages\n"
    "    - Meeting prep summaries\n"
    "    - Weekly digests\n"
    "\n"
    "This is optional \u2014 you can enable it later with /notion connect\n"
    "\n"
    "  [y] Yes, connect Notion\n"
    "  [n] No, skip for now"
)

NOTION_TOKEN_INSTRUCTIONS = (
    "I need a Notion Integration Token.\n"
    "\n"
    "  1. Go to https://www.notion.so/my-integrations\n"
    "  2. Click \"New Integration\"\n"
    "  3. Name it \"secondBrain\"\n"
    "  4. Select your workspace\n"
    "  5. Copy the \"Internal Integration Token\"\n"
    "\n"
    "  Then share the pages you want me to read:\n"
    "  - Open each page/database in Notion\n"
    "  - Click \"...\" \u2192 \"Connect to\" \u2192 \"secondBrain\""
)

NOTION_READ_MODE_MENU = (
    "What should I read from your Notion?\n"
    "  [1] Everything I have access to (recommended)\n"
    "  [2] Let me choose specific pages later"
)


def _ask(prompt: str, password: bool = False) -> str:
    """Prompt user for input."""
    try:
        if password:
            import getpass
            return getpass.getpass(prompt + " ").strip()
        return console.input(prompt + " ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


class NotionSetup:
    """Interactive Notion setup flow."""

    def __init__(self, api: APIClient, config: CLIConfig) -> None:
        self._api = api
        self._config = config

    async def run_onboarding_step(self) -> bool:
        """Run as optional step in onboarding. Returns True to continue."""
        console.print(NOTION_INTRO)
        console.print()

        choice = _ask(">").lower()
        if choice != "y":
            print_info("Skipping Notion. You can enable it later with /notion connect.")
            return True

        return await self._connect_flow()

    async def connect(self) -> bool:
        """Run the connect flow (used by /notion connect)."""
        if self._config.notion and self._config.notion.get("enabled"):
            print_warning("Notion is already connected.")
            console.print("  Use /notion disconnect first, then reconnect.")
            return False

        return await self._connect_flow()

    def disconnect(self) -> None:
        """Disconnect Notion integration."""
        if not self._config.notion or not self._config.notion.get("enabled"):
            print_info("Notion is not connected.")
            return

        self._config.notion["enabled"] = False
        self._config.save()
        print_success("Notion disconnected.")

    async def _connect_flow(self) -> bool:
        """Full connection flow: token → validate → read mode → workspace setup."""
        console.print()
        console.print(NOTION_TOKEN_INSTRUCTIONS)
        console.print()

        # Get token
        token = _ask("Paste your integration token:\n>", password=True)
        if not token:
            print_info("Skipping Notion.")
            return True

        # Validate token
        with spinner("Validating..."):
            valid = await self._validate_notion_token(token)

        if not valid:
            print_error(
                "Could not connect to Notion. Check that:\n"
                "  - The token is correct\n"
                "  - The integration has access to your workspace"
            )
            return True  # Don't block onboarding

        print_success("Connected to Notion!")

        # Store token via API (as an integration)
        try:
            await self._api.create_integration(
                user_id=self._config.user_id or "",
                platform="notion",
                access_token=token,
            )
        except APIError as e:
            logger.warning("Failed to store Notion integration: %s", e.detail)
            print_warning("Could not save token to server: %s" % e.detail)
            return True

        # Ask read mode
        console.print()
        console.print(NOTION_READ_MODE_MENU)
        read_choice = _ask(">")
        read_mode = "selected" if read_choice == "2" else "all"

        # Setup workspace
        console.print()
        console.print("Setting up my workspace in your Notion...")

        notion_config = await self._setup_workspace(token)
        if notion_config is None:
            print_warning("Could not create workspace. Notion reading is still enabled.")
            self._config.notion = {
                "enabled": True,
                "read_mode": read_mode,
            }
            self._config.save()
            return True

        notion_config["read_mode"] = read_mode
        self._config.notion = notion_config
        self._config.save()

        # Add notion to platforms_connected for background sync
        if "notion" not in self._config.platforms_connected:
            self._config.platforms_connected.append("notion")
            self._config.save()

        console.print()
        print_success("Notion is ready!")
        root_url = notion_config.get("root_page_url", "")
        if root_url:
            print_info("My workspace: %s" % root_url)
        console.print()
        console.print("You can view and edit my workspace anytime in Notion.")

        return True

    async def _validate_notion_token(self, token: str) -> bool:
        """Validate a Notion integration token."""
        from app.services.connectors.notion import NotionConnector
        connector = NotionConnector()
        return await connector.validate_token(token)

    async def _setup_workspace(self, token: str) -> Optional[dict]:
        """Create the assistant's workspace in Notion."""
        from app.services.notion.publisher import NotionPublisher
        from app.services.notion.config import NotionWorkspaceConfig

        publisher = NotionPublisher(token, NotionWorkspaceConfig())
        try:
            config = await publisher.setup_workspace()
            return config.to_dict()
        except (httpx.HTTPError, RuntimeError) as e:
            logger.error("Notion workspace setup failed: %s", e)
            print_error("Workspace setup failed: %s" % str(e))
            return None
