"""Onboarding wizard — guides new users through 5-step initial setup.

Steps:
  1. Account creation (name, email, timezone)
  2. Platform connections (Outlook, Slack, Teams, Fathom)
  3. Identity & style configuration
  4. Initial data import with commitment review
  5. Preferences (briefing time, alert style)

State is persisted in CLIConfig so the wizard can resume after interruption.
"""
import logging
from typing import Callable, List, Optional

import httpx

from cli.api_client import APIClient, APIError
from cli.config import CLIConfig
from cli.display import (
    console,
    create_progress,
    print_error,
    print_info,
    print_muted,
    print_panel,
    print_success,
    print_table,
    print_warning,
    print_welcome,
    spinner,
)
from cli.prompts import (
    ALERT_STYLE_MENU,
    BRIEFING_TIME_PROMPT,
    COMMITMENT_REVIEW_MENU,
    HEURISTICS_PROMPT,
    IDENTITY_INTRO,
    IMPORT_INTRO,
    IMPORT_WINDOW_DAYS,
    IMPORT_WINDOW_MENU,
    ONBOARDING_COMPLETE,
    PLATFORM_IDS,
    PLATFORM_INSTRUCTIONS,
    PLATFORM_MENU,
    PLATFORM_NAMES,
    PLATFORM_TOKEN_ERROR,
    PREFERENCES_INTRO,
    RESUME_MESSAGE,
    STEP_NAMES,
    TONE_MENU,
    TONE_PRESETS,
    WELCOME_INTRO,
    WELCOME_SUBTITLE,
    WELCOME_TITLE,
)
from cli.notion_setup import NotionSetup
from cli.validators import (
    parse_selection,
    validate_email,
    validate_name,
    validate_time_24h,
    validate_timezone,
    validate_token,
)

logger = logging.getLogger(__name__)


def _ask(prompt: str, password: bool = False) -> str:
    """Prompt user for input. Returns stripped string."""
    try:
        if password:
            import getpass
            return getpass.getpass(prompt + " ").strip()
        return console.input(prompt + " ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def _ask_validated(prompt: str, validator: Callable[[str], Optional[str]]) -> Optional[str]:
    """Prompt user until valid input, or empty to abort.

    Returns the valid input string, or None if user sent empty input.
    """
    while True:
        value = _ask(prompt)
        if not value:
            return None
        error = validator(value)
        if error is None:
            return value
        print_warning(error)


def _ask_choice(prompt: str, valid: set) -> str:
    """Prompt until user picks one of the valid choices."""
    while True:
        value = _ask(prompt).lower()
        if value in valid:
            return value
        print_warning("Invalid choice. Try again.")


class OnboardingFlow:
    """Multi-step onboarding wizard with resume support."""

    def __init__(self, api: APIClient, config: CLIConfig) -> None:
        self._api = api
        self._config = config

    async def run(self) -> bool:
        """Run the onboarding wizard. Returns True if completed."""
        # Handle resume
        if self._config.onboarding_step > 0 and self._config.user_name:
            action = self._handle_resume()
            if action == "s":
                return False
            if action == "r":
                self._config.onboarding_step = 0
                self._config.onboarding_completed = False

        # Show welcome for fresh start
        if self._config.onboarding_step == 0:
            print_welcome(WELCOME_TITLE, WELCOME_SUBTITLE)
            console.print(WELCOME_INTRO)
            console.print()

        # Run steps, resuming from last completed step
        steps = [
            (1, self._step_welcome),
            (2, self._step_platforms),
            (3, self._step_identity),
            (4, self._step_initial_import),
            (5, self._step_preferences),
        ]

        for step_num, step_fn in steps:
            if self._config.onboarding_step >= step_num:
                continue
            console.rule(
                "Step %d/%d: %s" % (step_num, len(steps), STEP_NAMES[step_num])
            )
            console.print()
            success = await step_fn()
            if not success:
                self._config.save()
                return False
            self._config.onboarding_step = step_num
            self._config.save()
            await self._sync_onboarding_to_server(step_num, completed=False)
            console.print()

        # Mark completed
        self._config.onboarding_completed = True
        self._config.save()
        await self._sync_onboarding_to_server(
            self._config.onboarding_step, completed=True,
        )
        await self._show_summary()
        return True

    async def _sync_onboarding_to_server(
        self, step: int, completed: bool,
    ) -> None:
        """Persist onboarding state to server (best-effort)."""
        try:
            await self._api.update_onboarding(step=step, completed=completed)
        except (APIError, httpx.HTTPError, OSError):
            pass  # Server may not support this yet — local state is authoritative

    def _handle_resume(self) -> str:
        """Handle resume from interrupted onboarding. Returns action: c/r/s."""
        step = self._config.onboarding_step + 1  # next step to do
        step_name = STEP_NAMES.get(step, "Unknown")
        console.print(RESUME_MESSAGE.format(
            name=self._config.user_name,
            step=step,
            step_name=step_name,
        ))
        console.print()
        return _ask_choice(">", {"c", "r", "s"})

    # ── Step 1: Account Creation ──────────────────────────────────

    async def _step_welcome(self) -> bool:
        """Step 1: Create user account."""
        name = _ask_validated("What's your name?\n>", validate_name)
        if not name:
            return False

        email = _ask_validated("And your email?\n>", validate_email)
        if not email:
            return False

        tz = _ask_validated(
            "What timezone are you in? (e.g., America/Argentina/Buenos_Aires)\n>",
            validate_timezone,
        )
        if not tz:
            return False

        # Create user via API
        with spinner("Creating your account..."):
            try:
                user = await self._api.create_user(email, name, tz)
            except APIError as e:
                if e.status_code == 409:
                    print_warning("An account with this email already exists.")
                    print_info("If this is you, enter your user ID to continue.")
                    user_id = _ask("User ID:\n>")
                    if not user_id:
                        return False
                    try:
                        user = await self._api.get_user(user_id)
                    except APIError:
                        print_error("Could not find that user ID.")
                        return False
                else:
                    print_error("Failed to create account: " + e.detail)
                    return False

        # Save to config
        self._config.user_id = user["id"]
        self._config.user_name = name
        self._config.user_email = email
        self._api.set_user_id(user["id"])

        print_success("Great, %s! Your account is ready." % name)
        return True

    # ── Step 2: Platform Connections ──────────────────────────────

    async def _step_platforms(self) -> bool:
        """Step 2: Connect communication platforms."""
        console.print(PLATFORM_MENU)
        console.print()

        choice = _ask(">")
        if not choice:
            return False

        if choice.lower() == "s":
            print_info("Skipping platform connections. You can add them later with /connect.")
            return True

        selection = parse_selection(choice, max_val=4)
        if selection is None:
            print_warning("Invalid selection. Enter numbers like: 1, 2, 4")
            return await self._step_platforms()

        platforms = [PLATFORM_IDS[s] for s in selection]

        for platform in platforms:
            success = await self._connect_platform(platform)
            if success:
                if platform not in self._config.platforms_connected:
                    self._config.platforms_connected.append(platform)
            console.print()

        connected = self._config.platforms_connected
        if connected:
            names = [PLATFORM_NAMES.get(p, p) for p in connected]
            print_success("Platforms connected: " + ", ".join(names))
        else:
            print_info("No platforms connected yet. You can add them later with /connect.")

        # Offer Notion as optional integration
        console.print()
        console.rule("Notion Integration (Optional)")
        console.print()
        notion_setup = NotionSetup(self._api, self._config)
        await notion_setup.run_onboarding_step()

        return True

    async def _connect_platform(self, platform: str) -> bool:
        """Connect a single platform. Returns True if successful."""
        name = PLATFORM_NAMES.get(platform, platform)
        console.print("Let's connect %s." % name)
        console.print()
        console.print(PLATFORM_INSTRUCTIONS.get(platform, ""))
        console.print()

        while True:
            token = _ask("Paste your token:\n>", password=True)
            if not token:
                print_info("Skipping %s." % name)
                return False

            # Local format validation
            error = validate_token(platform, token)
            if error:
                print_warning(error)
                continue

            # Create integration via API
            with spinner("Validating token..."):
                try:
                    await self._api.create_integration(
                        user_id=self._config.user_id,
                        platform=platform,
                        access_token=token,
                    )
                except APIError as e:
                    print_error("Token rejected: " + e.detail)
                    console.print(PLATFORM_TOKEN_ERROR)
                    action = _ask_choice(">", {"r", "s", "h"})
                    if action == "s":
                        return False
                    if action == "h":
                        console.print(PLATFORM_INSTRUCTIONS.get(platform, ""))
                    continue

            print_success("Connected to %s!" % name)
            return True

    # ── Step 3: Identity & Style ──────────────────────────────────

    async def _step_identity(self) -> bool:
        """Step 3: Configure identity and communication style."""
        console.print(IDENTITY_INTRO)
        console.print()

        # Role / persona
        persona = _ask(
            "How would you describe your professional role? (brief, 1-2 sentences)\n>"
        )
        if not persona:
            return False

        # Tone
        console.print(TONE_MENU)
        console.print()
        tone_choice = _ask_choice(">", {"1", "2", "3", "4"})
        if tone_choice in ("1", "2", "3"):
            tone = TONE_PRESETS[int(tone_choice) - 1]
        else:
            tone = _ask("Describe the tone you'd like:\n>")
            if not tone:
                return False

        # Heuristics
        console.print(HEURISTICS_PROMPT)
        heuristics_list = []  # type: List[str]
        while True:
            rule = _ask(">")
            if not rule:
                break
            heuristics_list.append(rule)

        heuristics = {}
        for i, rule in enumerate(heuristics_list):
            heuristics["rule_%d" % (i + 1)] = rule

        # Show summary for confirmation
        console.print()
        lines = [
            "  Role: %s" % persona,
            "  Tone: %s" % tone,
        ]
        if heuristics_list:
            lines.append("  Rules:")
            for rule in heuristics_list:
                lines.append("    - %s" % rule)
        print_panel("\n".join(lines), title="Your Profile", style="cyan")
        console.print()

        confirm = _ask_choice("Does this look right? [y/n]", {"y", "n"})
        if confirm == "n":
            print_info("Let's try again.")
            return await self._step_identity()

        # Save via API
        with spinner("Saving your profile..."):
            try:
                existing = await self._api.get_identity(self._config.user_id)
                if existing:
                    await self._api.update_identity(
                        self._config.user_id,
                        persona_description=persona,
                        tone_guidelines=tone,
                        heuristics=heuristics,
                    )
                else:
                    await self._api.create_identity(
                        self._config.user_id,
                        persona_description=persona,
                        tone_guidelines=tone,
                        heuristics=heuristics,
                    )
            except APIError as e:
                print_error("Failed to save profile: " + e.detail)
                return False

        self._config.identity_configured = True
        print_success("Profile saved!")
        return True

    # ── Step 4: Initial Data Import ───────────────────────────────

    async def _step_initial_import(self) -> bool:
        """Step 4: Import historical data from connected platforms."""
        if not self._config.platforms_connected:
            print_info("No platforms connected — skipping import.")
            print_info("Connect platforms with /connect, then sync with /sync.")
            return True

        console.print(IMPORT_INTRO)
        console.print()
        console.print(IMPORT_WINDOW_MENU)
        console.print()
        window = _ask_choice(">", {"1", "2", "3", "4"})
        # days_back = IMPORT_WINDOW_DAYS[int(window)]  # Future: pass to sync

        total_docs = 0
        total_commitments = 0

        for platform in self._config.platforms_connected:
            name = PLATFORM_NAMES.get(platform, platform)
            with spinner("Syncing %s..." % name):
                try:
                    result = await self._api.sync_platform(platform)
                    docs = result.get("documents_created", 0)
                    commits = result.get("commitments_detected", 0)
                    total_docs += docs
                    total_commitments += commits
                    print_success(
                        "%s: %d documents, %d commitments detected"
                        % (name, docs, commits)
                    )
                except APIError as e:
                    print_error("%s sync failed: %s" % (name, e.detail))

        console.print()
        print_info(
            "Import complete! %d documents, %d commitments detected."
            % (total_docs, total_commitments)
        )

        # Offer commitment review
        if total_commitments > 0:
            await self._review_commitments()

        self._config.initial_import_done = True
        return True

    async def _review_commitments(self) -> None:
        """Review detected commitments after import."""
        console.print()
        console.print("Would you like to review the detected commitments? [y/n]")
        choice = _ask_choice(">", {"y", "n"})
        if choice == "n":
            return

        try:
            commitments = await self._api.list_commitments("pending")
        except APIError:
            print_error("Could not load commitments.")
            return

        if not commitments:
            print_info("No pending commitments found.")
            return

        # Show as table
        rows = []
        for i, c in enumerate(commitments, 1):
            rows.append([
                str(i),
                c.get("priority", "P2"),
                c.get("description", "")[:50],
                c.get("due_date", "—"),
            ])
        print_table(
            "Pending Commitments",
            columns=["#", "Priority", "Commitment", "Due"],
            rows=rows,
        )
        console.print()
        console.print(COMMITMENT_REVIEW_MENU)
        action = _ask_choice(">", {"a", "r", "d", "s"})

        if action == "a":
            print_success("All commitments accepted.")
        elif action == "d":
            for c in commitments:
                try:
                    await self._api.delete_commitment(c["id"])
                except APIError:
                    pass
            print_info("All commitments dismissed.")
        elif action == "r":
            await self._review_commitments_one_by_one(commitments)

    async def _review_commitments_one_by_one(
        self, commitments: list
    ) -> None:
        """Review each commitment individually."""
        for c in commitments:
            console.print()
            desc = c.get("description", "No description")
            due = c.get("due_date", "No date")
            source = c.get("source_text", "")[:80] if c.get("source_text") else ""
            print_panel(
                "  %s\n  Due: %s\n  Source: %s" % (desc, due, source),
                title="Commitment",
                style="yellow",
            )
            console.print("  [a] Accept  [c] Mark completed  [d] Dismiss  [s] Skip rest")
            action = _ask_choice(">", {"a", "c", "d", "s"})
            if action == "a":
                continue
            elif action == "c":
                try:
                    await self._api.update_commitment(c["id"], status="completed")
                except APIError:
                    print_error("Failed to update.")
            elif action == "d":
                try:
                    await self._api.delete_commitment(c["id"])
                except APIError:
                    print_error("Failed to delete.")
            elif action == "s":
                break

    # ── Step 5: Preferences ───────────────────────────────────────

    async def _step_preferences(self) -> bool:
        """Step 5: Configure daily briefing and alert preferences."""
        console.print(PREFERENCES_INTRO)
        console.print()
        console.print(BRIEFING_TIME_PROMPT)

        time_str = _ask_validated(">", validate_time_24h)
        if not time_str:
            time_str = "07:00"
            print_info("Using default: 07:00")

        hour, minute = (int(x) for x in time_str.split(":"))

        # Alert style
        console.print()
        console.print(ALERT_STYLE_MENU)
        console.print()
        alert_choice = _ask_choice(">", {"1", "2", "3"})
        alert_modes = {"1": "immediate", "2": "briefing_only", "3": "manual"}
        alert_mode = alert_modes[alert_choice]

        # Schedule briefing
        with spinner("Configuring your preferences..."):
            try:
                user_id = self._config.user_id
                # Determine timezone from user record or config
                tz = self._config.preferences.get("timezone", "UTC")
                await self._api.schedule_briefing(user_id, hour, minute, tz)
            except APIError as e:
                print_warning("Could not schedule briefing: " + e.detail)

        self._config.preferences["briefing_hour"] = hour
        self._config.preferences["briefing_minute"] = minute
        self._config.preferences["alert_mode"] = alert_mode

        # Sync preferences to server
        try:
            await self._api.update_preferences(self._config.preferences)
        except (APIError, httpx.HTTPError, OSError):
            pass  # Best-effort sync

        print_success(
            "Briefing scheduled at %02d:%02d. Alert mode: %s."
            % (hour, minute, alert_mode)
        )
        return True

    # ── Summary ───────────────────────────────────────────────────

    async def _show_summary(self) -> None:
        """Show final onboarding summary."""
        platforms = ", ".join(
            PLATFORM_NAMES.get(p, p) for p in self._config.platforms_connected
        ) or "None"

        # Try to get stats
        docs = 0
        commits = 0
        try:
            stats = await self._api.get_user_stats(self._config.user_id)
            docs = stats.get("documents_total", 0)
            commits = stats.get("commitments_pending", 0)
        except APIError:
            pass

        briefing_h = self._config.preferences.get("briefing_hour", 7)
        briefing_m = self._config.preferences.get("briefing_minute", 0)
        briefing_time = "%02d:%02d" % (briefing_h, briefing_m)

        console.print()
        print_panel(
            ONBOARDING_COMPLETE.format(
                platforms=platforms,
                documents=str(docs),
                commitments=str(commits),
                briefing_time=briefing_time,
            ),
            title="Setup Complete",
            style="green",
        )
