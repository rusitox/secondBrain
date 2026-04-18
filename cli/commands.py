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
        """Connect a new platform (reuses onboarding flow)."""
        from cli.onboarding import OnboardingFlow
        flow = OnboardingFlow(api=self._api, config=self._config)
        await flow._step_platforms()
        self._config.save()

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
