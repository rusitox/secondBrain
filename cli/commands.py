"""Command router — dispatches /slash commands in the chat session."""
import logging
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from cli.api_client import APIClient, APIError
from cli.config import CLIConfig
from cli.display import (
    console,
    print_error,
    print_info,
    print_markdown,
    print_muted,
    print_panel,
    print_stats,
    print_success,
    print_table,
    print_warning,
    spinner,
)
from cli.prompts import PLATFORM_NAMES

if TYPE_CHECKING:
    from cli.onboarding import OnboardingFlow

logger = logging.getLogger(__name__)

# Type for command handlers
CommandHandler = Callable[["CommandRouter", List[str]], Any]


class CommandRouter:
    """Routes /slash commands to handler methods."""

    COMMANDS: Dict[str, str] = {
        "/briefing": "Show your daily briefing",
        "/commitments": "List pending commitments",
        "/overdue": "List overdue commitments",
        "/sync": "Sync platforms (optionally: /sync slack)",
        "/connect": "Connect a new platform",
        "/disconnect": "Disconnect a platform (/disconnect slack)",
        "/status": "Show connection status and stats",
        "/identity": "View or edit your profile",
        "/settings": "View or edit preferences",
        "/setup": "Re-run onboarding wizard",
        "/notion": "Notion integration (connect|disconnect|status|sync|workspace)",
        "/digest": "Generate and publish weekly digest",
        "/prep": "Generate meeting prep (/prep Meeting Name)",
        "/server": "Server management (start|stop|restart|status|logs)",
        "/help": "Show available commands",
        "/quit": "Exit secondBrain",
    }

    def __init__(self, api: APIClient, config: CLIConfig) -> None:
        self._api = api
        self._config = config
        self._should_quit = False

    @property
    def should_quit(self) -> bool:
        return self._should_quit

    def get_command_names(self) -> List[str]:
        """Return list of command names for autocompletion."""
        return list(self.COMMANDS.keys())

    async def dispatch(self, raw_input: str) -> None:
        """Parse and dispatch a /command."""
        parts = raw_input.strip().split()
        if not parts:
            return
        cmd = parts[0].lower()
        args = parts[1:]

        handler = self._get_handler(cmd)
        if handler is None:
            print_warning("Unknown command: %s. Type /help for available commands." % cmd)
            return

        try:
            await handler(args)
        except APIError as e:
            print_error("API error: %s" % e.detail)
        except Exception as e:
            logger.exception("Command %s failed", cmd)
            print_error("Command failed: %s" % str(e))

    def _get_handler(self, cmd: str) -> Optional[Callable]:
        """Map command name to handler method."""
        handlers = {
            "/briefing": self._cmd_briefing,
            "/commitments": self._cmd_commitments,
            "/overdue": self._cmd_overdue,
            "/sync": self._cmd_sync,
            "/connect": self._cmd_connect,
            "/disconnect": self._cmd_disconnect,
            "/status": self._cmd_status,
            "/identity": self._cmd_identity,
            "/settings": self._cmd_settings,
            "/setup": self._cmd_setup,
            "/notion": self._cmd_notion,
            "/digest": self._cmd_digest,
            "/prep": self._cmd_prep,
            "/server": self._cmd_server,
            "/help": self._cmd_help,
            "/quit": self._cmd_quit,
            "/exit": self._cmd_quit,
            "/q": self._cmd_quit,
        }
        return handlers.get(cmd)

    # ── Command Handlers ──────────────────────────────────────────

    async def _cmd_briefing(self, args: List[str]) -> None:
        """Show daily briefing."""
        user_id = self._config.user_id
        if not user_id:
            print_error("No user configured. Run /setup first.")
            return

        with spinner("Generating briefing..."):
            result = await self._api.get_briefing(user_id)

        # Publish to Notion if enabled
        await self._publish_briefing_to_notion(result)

        # Format briefing sections
        briefing = result.get("briefing", result)
        if isinstance(briefing, dict):
            sections = []
            if briefing.get("agenda"):
                sections.append("## Agenda\n" + briefing["agenda"])
            if briefing.get("pending_commitments"):
                sections.append("## Pending Commitments\n" + briefing["pending_commitments"])
            if briefing.get("contextual_alerts"):
                sections.append("## Alerts\n" + briefing["contextual_alerts"])
            if sections:
                print_markdown("\n\n".join(sections))
            else:
                print_info("No briefing content available.")
        elif isinstance(briefing, str):
            print_markdown(briefing)
        else:
            print_info("No briefing content available.")

    async def _publish_briefing_to_notion(
        self, briefing_result: Dict[str, Any],
    ) -> None:
        """Publish a briefing to Notion if enabled. Non-blocking on failure."""
        notion_cfg = self._config.notion
        if not notion_cfg or not notion_cfg.get("enabled"):
            return
        if not notion_cfg.get("briefings_db_id"):
            return

        # Extract briefing text from result
        briefing_text = ""
        briefing = briefing_result.get("briefing", briefing_result)
        if isinstance(briefing, dict):
            briefing_text = briefing.get("briefing_text", "")
        elif isinstance(briefing, str):
            briefing_text = briefing
        if not briefing_text:
            return

        try:
            from datetime import datetime, timezone
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            result = await self._api.publish_briefing_to_notion(
                workspace_config=notion_cfg,
                briefing_text=briefing_text,
                date=date_str,
            )
            url = result.get("url", "")
            if url:
                print_muted("Published to Notion: %s" % url)
        except APIError as e:
            logger.warning("Failed to publish briefing to Notion: %s", e.detail)

    async def _cmd_commitments(self, args: List[str]) -> None:
        """List pending commitments."""
        with spinner("Loading commitments..."):
            commitments = await self._api.list_commitments("pending")

        if not commitments:
            print_info("No pending commitments.")
            return

        rows = []
        for c in commitments:
            rows.append([
                c.get("description", "")[:60],
                c.get("priority", "—"),
                c.get("due_date", "—"),
                c.get("status", "—"),
            ])
        print_table(
            "Pending Commitments",
            columns=["Description", "Priority", "Due", "Status"],
            rows=rows,
        )

    async def _cmd_overdue(self, args: List[str]) -> None:
        """List overdue commitments."""
        with spinner("Loading overdue commitments..."):
            commitments = await self._api.list_commitments("overdue")

        if not commitments:
            print_success("No overdue commitments!")
            return

        rows = []
        for c in commitments:
            rows.append([
                c.get("description", "")[:60],
                c.get("priority", "—"),
                c.get("due_date", "—"),
            ])
        print_table(
            "Overdue Commitments",
            columns=["Description", "Priority", "Due"],
            rows=rows,
            styles=["red", "", "red"],
        )

    async def _cmd_sync(self, args: List[str]) -> None:
        """Sync one or all platforms."""
        if args:
            platforms = [args[0].lower()]
        else:
            platforms = self._config.platforms_connected

        if not platforms:
            print_info("No platforms connected. Use /connect to add one.")
            return

        for platform in platforms:
            name = PLATFORM_NAMES.get(platform, platform)
            with spinner("Syncing %s..." % name):
                try:
                    result = await self._api.sync_platform(platform)
                    docs = result.get("documents_created", 0)
                    updated = result.get("documents_updated", 0)
                    commits = result.get("commitments_detected", 0)
                    print_success(
                        "%s: %d new, %d updated, %d commitments"
                        % (name, docs, updated, commits)
                    )
                except APIError as e:
                    print_error("%s sync failed: %s" % (name, e.detail))

    async def _cmd_connect(self, args: List[str]) -> None:
        """Connect a new platform.

        Usage:
          /connect                           — guided platform setup
          /connect slack user-token          — add User Token to existing Slack integration
        """
        # Special case: /connect slack user-token
        if len(args) >= 2 and args[0].lower() == "slack" and args[1].lower() == "user-token":
            await self._cmd_connect_slack_user_token()
            return

        from cli.onboarding import OnboardingFlow
        flow = OnboardingFlow(api=self._api, config=self._config)
        await flow._step_platforms()
        self._config.save()

    async def _cmd_connect_slack_user_token(self) -> None:
        """Store a Slack User Token (xoxp-) to enable personal DM sync."""
        from cli.validators import validate_token as _validate_token
        from cli.display import print_info, print_success, print_error, print_warning

        print_info(
            "A Slack User Token (xoxp-...) allows syncing your personal DMs.\n"
            "Required scopes: channels:history channels:read groups:history groups:read\n"
            "                 im:history im:read mpim:history mpim:read users:read\n"
            "Get one at: api.slack.com → your app → OAuth & Permissions → User Token Scopes"
        )

        integrations = await self._api.list_integrations("slack")
        if not integrations:
            print_error("No Slack integration found. Run /connect first to add a Bot Token.")
            return

        integration_id = integrations[0]["id"]

        import asyncio
        import getpass
        loop = asyncio.get_event_loop()
        user_token = (
            await loop.run_in_executor(None, getpass.getpass, "Paste your User Token (xoxp-...): ")
        ).strip()
        if not user_token:
            print_warning("No token entered. Cancelled.")
            return
        if not user_token.startswith("xoxp-"):
            print_warning("Warning: token does not start with 'xoxp-'. Make sure this is a User Token.")

        with spinner("Saving User Token..."):
            try:
                await self._api.set_integration_user_token(integration_id, user_token)
                print_success("User Token saved. DMs will be included in the next /sync slack.")
            except APIError as e:
                print_error("Failed to save User Token: %s" % e.detail)

    async def _cmd_disconnect(self, args: List[str]) -> None:
        """Disconnect a platform."""
        if not args:
            print_warning("Usage: /disconnect <platform>")
            print_info("Connected: %s" % ", ".join(self._config.platforms_connected))
            return

        platform = args[0].lower()
        if platform not in self._config.platforms_connected:
            print_warning("%s is not connected." % platform)
            return

        # Find and delete the integration
        with spinner("Disconnecting %s..." % platform):
            try:
                integrations = await self._api.list_integrations(platform)
                for integ in integrations:
                    await self._api.delete_integration(integ["id"])
                self._config.platforms_connected.remove(platform)
                self._config.save()
                print_success("Disconnected %s." % PLATFORM_NAMES.get(platform, platform))
            except APIError as e:
                print_error("Failed to disconnect: %s" % e.detail)

    async def _cmd_status(self, args: List[str]) -> None:
        """Show connection status and stats."""
        user_id = self._config.user_id
        if not user_id:
            print_error("No user configured.")
            return

        with spinner("Loading status..."):
            stats = await self._api.get_user_stats(user_id)

        print_stats(stats)

        # Show connected platforms
        if self._config.platforms_connected:
            rows = []
            for p in self._config.platforms_connected:
                rows.append([PLATFORM_NAMES.get(p, p), "Connected"])
            print_table("Platforms", columns=["Platform", "Status"], rows=rows)
        else:
            print_muted("No platforms connected.")

    async def _cmd_identity(self, args: List[str]) -> None:
        """View or edit identity profile."""
        user_id = self._config.user_id
        if not user_id:
            print_error("No user configured.")
            return

        with spinner("Loading profile..."):
            identity = await self._api.get_identity(user_id)

        if identity is None:
            print_info("No identity configured. Creating one now...")
            from cli.onboarding import OnboardingFlow
            flow = OnboardingFlow(api=self._api, config=self._config)
            await flow._step_identity()
            return

        lines = [
            "  Role: %s" % identity.get("persona_description", "—"),
            "  Tone: %s" % identity.get("tone_guidelines", "—"),
        ]
        heuristics = identity.get("heuristics", {})
        if heuristics:
            lines.append("  Rules:")
            for key, val in heuristics.items():
                lines.append("    - %s" % val)
        print_panel("\n".join(lines), title="Your Profile", style="cyan")

        console.print()
        try:
            edit = console.input("Edit profile? [y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if edit == "y":
            from cli.onboarding import OnboardingFlow
            flow = OnboardingFlow(api=self._api, config=self._config)
            await flow._step_identity()

    async def _cmd_settings(self, args: List[str]) -> None:
        """View or edit preferences."""
        prefs = self._config.preferences
        lines = [
            "  Briefing: %02d:%02d" % (
                prefs.get("briefing_hour", 7),
                prefs.get("briefing_minute", 0),
            ),
            "  Alert mode: %s" % prefs.get("alert_mode", "briefing_only"),
        ]
        print_panel("\n".join(lines), title="Settings", style="cyan")

    async def _cmd_setup(self, args: List[str]) -> None:
        """Re-run onboarding."""
        from cli.onboarding import OnboardingFlow
        self._config.onboarding_step = 0
        self._config.onboarding_completed = False
        flow = OnboardingFlow(api=self._api, config=self._config)
        await flow.run()

    async def _cmd_notion(self, args: List[str]) -> None:
        """Notion integration management."""
        from cli.notion_setup import NotionSetup

        subcmd = args[0].lower() if args else "status"
        setup = NotionSetup(self._api, self._config)

        if subcmd == "connect":
            await setup.connect()

        elif subcmd == "disconnect":
            setup.disconnect()

        elif subcmd == "sync":
            if not self._config.notion or not self._config.notion.get("enabled"):
                print_warning("Notion is not connected. Use /notion connect first.")
                return
            # Sync reading (ingest new pages)
            with spinner("Syncing Notion pages..."):
                try:
                    result = await self._api.sync_platform("notion")
                    docs = result.get("documents_created", 0)
                    updated = result.get("documents_updated", 0)
                    print_success(
                        "Notion read sync: %d new, %d updated" % (docs, updated)
                    )
                except APIError as e:
                    print_error("Notion read sync failed: %s" % e.detail)
            # Sync commitments bidirectionally
            await self._notion_commitment_sync()

        elif subcmd == "workspace":
            notion_cfg = self._config.notion or {}
            url = notion_cfg.get("root_page_url", "")
            if url:
                import webbrowser
                webbrowser.open(url)
                print_info("Opening workspace in browser...")
            else:
                print_warning("No workspace URL available.")

        else:  # status
            notion_cfg = self._config.notion or {}
            enabled = notion_cfg.get("enabled", False)
            if not enabled:
                print_info("Notion is not connected. Use /notion connect to set up.")
                return
            lines = [
                "  Status: Connected",
                "  Read mode: %s" % notion_cfg.get("read_mode", "all"),
                "  Last read sync: %s" % (notion_cfg.get("last_read_sync") or "never"),
                "  Last write sync: %s" % (notion_cfg.get("last_write_sync") or "never"),
            ]
            url = notion_cfg.get("root_page_url", "")
            if url:
                lines.append("  Workspace: %s" % url)
            print_panel("\n".join(lines), title="Notion Integration", style="cyan")

    async def _notion_commitment_sync(self) -> None:
        """Run bidirectional commitment sync with Notion."""
        notion_cfg = self._config.notion
        if not notion_cfg or not notion_cfg.get("enabled"):
            return
        if not notion_cfg.get("commitments_db_id"):
            return

        with spinner("Syncing commitments with Notion..."):
            try:
                result = await self._api.sync_notion_commitments(
                    workspace_config=notion_cfg,
                )
                created = result.get("created_in_notion", 0)
                updated_n = result.get("updated_in_notion", 0)
                updated_l = result.get("updated_locally", 0)
                print_success(
                    "Commitment sync: %d created, %d updated in Notion, %d updated locally"
                    % (created, updated_n, updated_l)
                )
                errors = result.get("errors", [])
                for err in errors:
                    print_warning(err)
            except APIError as e:
                print_error("Commitment sync failed: %s" % e.detail)

    async def _cmd_digest(self, args: List[str]) -> None:
        """Generate and publish weekly digest."""
        notion_cfg = self._config.notion
        if not notion_cfg or not notion_cfg.get("enabled"):
            print_warning("Notion is not connected. Use /notion connect first.")
            return

        with spinner("Generating weekly digest..."):
            try:
                result = await self._api.publish_digest_to_notion(
                    workspace_config=notion_cfg,
                )
                url = result.get("url", "")
                stats = result.get("stats", {})
                print_success("Weekly digest published!")
                if url:
                    print_info("View in Notion: %s" % url)
                if stats:
                    print_muted(
                        "Completed: %d | New: %d | Pending: %d | Overdue: %d"
                        % (
                            stats.get("commitments_completed", 0),
                            stats.get("commitments_new", 0),
                            stats.get("commitments_pending", 0),
                            stats.get("commitments_overdue", 0),
                        )
                    )
            except APIError as e:
                print_error("Digest failed: %s" % e.detail)

    async def _cmd_prep(self, args: List[str]) -> None:
        """Generate meeting prep."""
        if not args:
            print_warning("Usage: /prep <meeting name or topic>")
            return

        user_id = self._config.user_id
        if not user_id:
            print_error("No user configured. Run /setup first.")
            return

        meeting_topic = " ".join(args)
        with spinner("Preparing for: %s..." % meeting_topic):
            try:
                result = await self._api.agent_query(
                    "Prepare a brief for my meeting about: %s. "
                    "Include relevant context from my documents, "
                    "any pending commitments with attendees, "
                    "and key talking points." % meeting_topic
                )
                answer = result.get("answer", result.get("response", ""))
                if answer:
                    print_markdown(answer)
                    # Publish to Notion if enabled
                    await self._publish_prep_to_notion(meeting_topic, answer)
                else:
                    print_info("No prep content generated.")
            except APIError as e:
                print_error("Meeting prep failed: %s" % e.detail)

    async def _publish_prep_to_notion(self, topic: str, prep_text: str) -> None:
        """Publish meeting prep to Notion if enabled. Non-blocking on failure."""
        notion_cfg = self._config.notion
        if not notion_cfg or not notion_cfg.get("enabled"):
            return
        if not notion_cfg.get("meeting_prep_db_id"):
            return
        try:
            from datetime import datetime, timezone
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            result = await self._api.publish_meeting_prep_to_notion(
                workspace_config=notion_cfg,
                title=topic,
                prep_text=prep_text,
                date=date_str,
            )
            url = result.get("url", "")
            if url:
                print_muted("Published to Notion: %s" % url)
        except APIError as e:
            logger.warning("Failed to publish meeting prep to Notion: %s", e.detail)

    async def _cmd_server(self, args: List[str]) -> None:
        """Server management: start, stop, restart, status, logs."""
        from cli.server import ServerManager
        server = ServerManager(self._config)

        if not args:
            args = ["status"]

        subcmd = args[0].lower()

        if subcmd == "status":
            db_status = "Running" if server.is_db_running() else "Stopped"
            srv_pid = server.get_server_pid()
            srv_status = "Running (PID %d)" % srv_pid if srv_pid else "Stopped"
            print_panel(
                "  Database: %s\n  Backend:  %s" % (db_status, srv_status),
                title="Server Status",
                style="cyan",
            )
        elif subcmd == "start":
            if not server.is_db_running():
                with spinner("Starting database..."):
                    db_ok = await server.start_db()
                if db_ok:
                    print_success("Database started.")
                else:
                    print_error("Failed to start database.")
                    return
            with spinner("Starting backend..."):
                srv_ok = await server.start_server()
            if srv_ok:
                print_success("Backend started (PID %s)." % server.get_server_pid())
            else:
                print_error("Failed to start backend.")
        elif subcmd == "stop":
            server.stop_server()
            await server.stop_db()
            print_success("Server and database stopped.")
        elif subcmd == "restart":
            with spinner("Restarting backend..."):
                ok = await server.restart_server()
            if ok:
                print_success("Backend restarted (PID %s)." % server.get_server_pid())
            else:
                print_error("Failed to restart backend.")
        elif subcmd == "logs":
            line_count = int(args[1]) if len(args) > 1 else 50
            logs = server.read_logs(lines=line_count)
            console.print(logs)
        else:
            print_warning("Unknown subcommand: %s" % subcmd)
            print_info("Usage: /server [start|stop|restart|status|logs]")

    async def _cmd_help(self, args: List[str]) -> None:
        """Show available commands."""
        rows = []
        for cmd, desc in self.COMMANDS.items():
            rows.append([cmd, desc])
        print_table("Commands", columns=["Command", "Description"], rows=rows)
        console.print()
        print_muted("Or just type a question to ask your AI assistant.")

    async def _cmd_quit(self, args: List[str]) -> None:
        """Exit the chat."""
        self._should_quit = True
