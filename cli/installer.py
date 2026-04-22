"""Interactive installer for secondBrain.

Handles: Docker check, DB startup, API key collection, config generation,
migrations, backend startup, and transition to onboarding.
"""
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

import httpx
from cryptography.fernet import Fernet

from cli.config import CLIConfig, DEFAULT_CONFIG_DIR
from cli.display import (
    console,
    print_error,
    print_info,
    print_panel,
    print_success,
    print_warning,
    print_welcome,
    spinner,
)
from cli.server import LOG_FILE, ServerManager

logger = logging.getLogger(__name__)

ENV_FILE = Path(".env")


class Installer:
    """Interactive installer for secondBrain."""

    def __init__(
        self,
        config: CLIConfig,
        project_dir: Optional[Path] = None,
    ) -> None:
        self._config = config
        self._project_dir = project_dir or Path.cwd()
        self._server = ServerManager(config, project_dir=self._project_dir)

    async def run(self) -> bool:
        """Run the full installation flow.

        Returns True if installation completed successfully.
        """
        print_welcome(
            "secondBrain Installer",
            "Let's set up everything you need to get started.",
        )

        # Check if already installed
        if self._config.installed:
            return await self._handle_reinstall()

        # Step 1: Docker
        console.print("\n[title]Step 1/6: Checking Docker[/title]")
        if not await self._step_docker():
            return False

        # Step 2: Database
        console.print("\n[title]Step 2/6: Setting up Database[/title]")
        if not await self._step_database():
            return False

        # Step 3: API keys
        console.print("\n[title]Step 3/6: API Configuration[/title]")
        if not await self._step_api_keys():
            return False

        # Step 4: Generate config
        console.print("\n[title]Step 4/6: Generating Configuration[/title]")
        if not self._step_generate_config():
            return False

        # Step 5: Migrations
        console.print("\n[title]Step 5/6: Database Migrations[/title]")
        if not self._step_migrations():
            return False

        # Step 6: Start backend
        console.print("\n[title]Step 6/6: Starting Backend[/title]")
        if not await self._step_start_server():
            return False

        # Mark as installed
        self._config.installed = True
        self._config.save()

        self._show_summary()
        return True

    # ── Step 1: Docker ─────────────────────────────────────────────

    async def _step_docker(self) -> bool:
        """Verify Docker is installed and running."""
        with spinner("Checking Docker..."):
            available = self._server.is_docker_available()

        if available:
            print_success("  Docker: Running")
            return True

        # Docker not available — check if installed but not running
        docker_installed = _command_exists("docker")
        if docker_installed:
            print_warning("  Docker is installed but not running.")
            print_info("  Please start Docker Desktop and press Enter to retry.")
            while True:
                response = _prompt("  [Enter] Retry  [q] Quit: ").strip().lower()
                if response == "q":
                    return False
                with spinner("Checking Docker..."):
                    if self._server.is_docker_available():
                        print_success("  Docker: Running")
                        return True
                print_warning("  Docker still not responding. Try again?")
        else:
            print_error("  Docker is not installed.")
            if sys.platform == "darwin":
                print_info("  Install it with: brew install --cask docker")
            elif sys.platform == "win32":
                print_info("  Install it with: winget install Docker.DockerDesktop")
            else:
                print_info("  Install Docker Engine: https://docs.docker.com/engine/install/")
            return False

    # ── Step 2: Database ───────────────────────────────────────────

    async def _step_database(self) -> bool:
        """Start PostgreSQL + pgvector via Docker."""
        if self._server.is_db_running():
            print_success("  Database: Already running")
            return True

        # Find a free port
        db_port = self._config.db_port
        try:
            db_port = ServerManager.find_free_port(db_port)
        except RuntimeError:
            print_error(f"  No free port found starting from {self._config.db_port}")
            return False

        if db_port != self._config.db_port:
            print_info(f"  Port {self._config.db_port} is in use, using {db_port} instead")

        self._config.db_port = db_port
        self._config.save()

        with spinner("Starting PostgreSQL + pgvector..."):
            started = await self._server.start_db(port=db_port)

        if started:
            print_success(f"  Database: Running on localhost:{db_port}")
            return True

        print_error("  Failed to start database. Check Docker logs:")
        print_info("    docker logs secondbrain-db")
        return False

    # ── Step 3: API Keys ───────────────────────────────────────────

    async def _step_api_keys(self) -> bool:
        """Collect and validate API keys from the user."""
        print_info("  secondBrain uses OpenAI for embeddings and Claude for AI reasoning.\n")

        # OpenAI key (required for embeddings)
        openai_key = await self._collect_api_key(
            name="OpenAI",
            purpose="embeddings",
            url="https://platform.openai.com/api-keys",
            prefix="sk-",
            required=True,
        )
        if openai_key is None:
            return False
        self._openai_key = openai_key

        console.print()

        # LLM key (optional — commitment detection and briefing won't work without it)
        llm_key = await self._collect_api_key(
            name="LLM provider (Anthropic/OpenAI/Google)",
            purpose="AI reasoning (briefings, commitment detection, queries)",
            url="https://console.anthropic.com/settings/keys",
            prefix="",
            required=False,
        )
        self._llm_key = llm_key or ""

        return True

    async def _collect_api_key(
        self,
        name: str,
        purpose: str,
        url: str,
        prefix: str,
        required: bool,
    ) -> Optional[str]:
        """Prompt for an API key with validation and retry."""
        skip_text = "" if required else "  [s] Skip (some features won't work)\n"

        while True:
            console.print(f"  [title]{name} API Key[/title] (for {purpose})")
            console.print(f"  Get one at: {url}")
            key = _prompt_password(f"  Paste your API key: ")

            if not key:
                if required:
                    print_error(f"  {name} API key is required.")
                    continue
                return None

            if key.lower() == "s" and not required:
                print_warning(f"  Skipping {name}. Some features will be limited.")
                return None

            # Validate
            with spinner(f"  Validating {name} key..."):
                valid = await self._validate_api_key(name.lower(), key)

            if valid:
                print_success(f"  {name}: Valid")
                return key

            print_error(f"  {name}: Invalid key or API error")
            console.print(f"  [r] Retry\n{skip_text}  [q] Quit")
            choice = _prompt("  > ").strip().lower()
            if choice == "q":
                return None if not required else None
            if choice == "s" and not required:
                print_warning(f"  Skipping {name}.")
                return None

    async def _validate_api_key(self, provider: str, key: str) -> bool:
        """Validate an API key by making a lightweight API call."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if "openai" in provider:
                    resp = await client.get(
                        "https://api.openai.com/v1/models",
                        headers={"Authorization": f"Bearer {key}"},
                    )
                    return resp.status_code == 200
                elif "claude" in provider or "anthropic" in provider:
                    resp = await client.get(
                        "https://api.anthropic.com/v1/models",
                        headers={
                            "x-api-key": key,
                            "anthropic-version": "2023-06-01",
                        },
                    )
                    return resp.status_code == 200
        except httpx.HTTPError:
            pass
        return False

    # ── Step 4: Generate Config ────────────────────────────────────

    def _step_generate_config(self) -> bool:
        """Generate .env file and Fernet key."""
        fernet_key = Fernet.generate_key().decode()
        print_success("  Fernet encryption key: Generated")

        db_port = self._config.db_port
        db_url_async = f"postgresql+asyncpg://secondbrain:secondbrain_dev@localhost:{db_port}/secondbrain"
        db_url_sync = f"postgresql+psycopg2://secondbrain:secondbrain_dev@localhost:{db_port}/secondbrain"

        env_path = self._project_dir / ENV_FILE

        # Handle existing .env
        if env_path.exists():
            console.print("\n  [warning]An .env file already exists.[/warning]")
            console.print("  [o] Overwrite  [m] Merge (keep existing, add missing)  [k] Keep existing")
            choice = _prompt("  > ").strip().lower()
            if choice == "k":
                print_info("  Keeping existing .env")
                return True
            if choice == "m":
                return self._merge_env(
                    env_path, db_url_async, db_url_sync,
                    fernet_key,
                )

        # Write fresh .env
        env_content = (
            f"# Database\n"
            f"DATABASE_URL={db_url_async}\n"
            f"DATABASE_URL_SYNC={db_url_sync}\n"
            f"SUPABASE_URL=\n"
            f"SUPABASE_KEY=\n"
            f"\n"
            f"# AI Models\n"
            f"OPENAI_API_KEY={self._openai_key}\n"
            f"LLM_API_KEY={self._llm_key}\n"
            f"\n"
            f"# Security\n"
            f"FERNET_KEY={fernet_key}\n"
            f"\n"
            f"# App Settings\n"
            f"APP_ENV=development\n"
            f"DEBUG=false\n"
        )
        env_path.write_text(env_content, encoding="utf-8")
        # Restrict permissions
        try:
            env_path.chmod(0o600)
        except OSError:
            pass  # Windows
        print_success("  Environment file: Written to .env")

        return True

    def _merge_env(
        self,
        env_path: Path,
        db_url_async: str,
        db_url_sync: str,
        fernet_key: str,
    ) -> bool:
        """Merge new values into existing .env, keeping existing keys."""
        existing = {}
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

        defaults = {
            "DATABASE_URL": db_url_async,
            "DATABASE_URL_SYNC": db_url_sync,
            "OPENAI_API_KEY": self._openai_key,
            "LLM_API_KEY": self._llm_key,
            "FERNET_KEY": fernet_key,
            "APP_ENV": "development",
            "DEBUG": "false",
        }

        added = 0
        with open(str(env_path), "a", encoding="utf-8") as f:
            for key, value in defaults.items():
                if key not in existing:
                    f.write(f"{key}={value}\n")
                    added += 1

        print_success(f"  Merged .env ({added} keys added, existing keys preserved)")
        return True

    # ── Step 5: Migrations ─────────────────────────────────────────

    def _step_migrations(self) -> bool:
        """Run database migrations."""
        with spinner("Running database migrations..."):
            success = self._server.run_migrations()

        if success:
            print_success("  Migrations: Applied successfully")
            return True

        print_error("  Migrations failed. Check the error above.")
        print_info("  You can retry with: alembic upgrade head")
        return False

    # ── Step 6: Start Server ───────────────────────────────────────

    async def _step_start_server(self) -> bool:
        """Start the backend server."""
        # Find a free port
        server_port = self._config.server_port
        try:
            server_port = ServerManager.find_free_port(server_port)
        except RuntimeError:
            print_error(f"  No free port found starting from {self._config.server_port}")
            return False

        if server_port != self._config.server_port:
            print_info(f"  Port {self._config.server_port} is in use, using {server_port} instead")

        with spinner(f"Starting backend on http://localhost:{server_port}..."):
            started = await self._server.start_server(port=server_port)

        if started:
            pid = self._server.get_server_pid()
            print_success(f"  Backend: Running on http://localhost:{server_port} (PID {pid})")
            return True

        print_error("  Failed to start backend server.")
        print_info("  Check logs with: cat ~/.secondbrain/server.log")
        return False

    # ── Reinstall ──────────────────────────────────────────────────

    async def _handle_reinstall(self) -> bool:
        """Handle the case where secondBrain is already installed."""
        print_panel(
            "  secondBrain is already installed.\n\n"
            f"  Database:  {'Running' if self._server.is_db_running() else 'Stopped'}\n"
            f"  Backend:   {'Running' if self._server.is_server_running() else 'Stopped'}\n"
            f"  Config:    {self._config._config_path}",
            title="Existing Installation",
            style="cyan",
        )

        console.print("\n  [r] Reinstall from scratch (keeps data)")
        console.print("  [u] Update (re-run migrations)")
        console.print("  [c] Reconfigure (API keys, server settings)")
        console.print("  [q] Cancel\n")

        choice = _prompt("  > ").strip().lower()

        if choice == "r":
            self._config.installed = False
            return await self.run()
        elif choice == "u":
            return self._step_migrations()
        elif choice == "c":
            if not await self._step_api_keys():
                return False
            return self._step_generate_config()
        else:
            print_info("  Installation cancelled.")
            return False

    # ── Summary ────────────────────────────────────────────────────

    def _show_summary(self) -> None:
        """Show installation summary."""
        pid = self._server.get_server_pid() or "?"
        console.print()
        print_panel(
            f"  Database:  PostgreSQL 16 + pgvector (Docker, port {self._config.db_port})\n"
            f"  Backend:   http://localhost:{self._config.server_port} (PID {pid})\n"
            f"  Config:    {self._config._config_path}\n"
            f"  Logs:      {LOG_FILE}\n\n"
            "  Now let's set up your account and connect your platforms.",
            title="Installation Complete!",
            style="green",
        )
        console.print()


# ── Helpers ────────────────────────────────────────────────────────


def _command_exists(cmd: str) -> bool:
    """Check if a command exists on the system PATH."""
    import shutil
    return shutil.which(cmd) is not None


def _prompt(text: str) -> str:
    """Simple input prompt."""
    try:
        return console.input(text)
    except EOFError:
        return ""


def _prompt_password(text: str) -> str:
    """Password-style input (hidden)."""
    try:
        return console.input(text, password=True)
    except EOFError:
        return ""
