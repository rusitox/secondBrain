"""Server lifecycle management — start/stop/status for backend and database."""
import asyncio
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional

import httpx

from cli.config import CLIConfig, DEFAULT_CONFIG_DIR

logger = logging.getLogger(__name__)

PID_FILE = DEFAULT_CONFIG_DIR / "server.pid"
LOG_FILE = DEFAULT_CONFIG_DIR / "server.log"

# How long to wait for services to become ready
DB_READY_TIMEOUT = 30.0
SERVER_READY_TIMEOUT = 15.0
HEALTH_POLL_INTERVAL = 0.5


class ServerManager:
    """Manages the backend server and database lifecycle."""

    def __init__(self, config: CLIConfig, project_dir: Optional[Path] = None) -> None:
        if config.is_remote_mode:
            raise RuntimeError(
                "ServerManager cannot be used in remote mode. "
                "The server at %s is managed externally." % config.server_url
            )
        self._config = config
        self._project_dir = project_dir or Path.cwd()

    # ── Docker / Database ──────────────────────────────────────────

    def is_docker_available(self) -> bool:
        """Check if Docker CLI is available and daemon is running."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def is_db_running(self) -> bool:
        """Check if the secondbrain-db container is running."""
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", "secondbrain-db"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0 and result.stdout.strip() == "true"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def db_container_exists(self) -> bool:
        """Check if the secondbrain-db container exists (running or stopped)."""
        try:
            result = subprocess.run(
                ["docker", "inspect", "secondbrain-db"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    async def start_db(self, port: Optional[int] = None) -> bool:
        """Start the PostgreSQL container via docker compose.

        If port is specified, uses it; otherwise uses config or finds a free one.
        Returns True if the database is ready.
        """
        if self.is_db_running():
            logger.info("Database container already running")
            return True

        db_port = port or self._config.db_port
        env = os.environ.copy()
        env["DB_PORT"] = str(db_port)

        # If container exists but stopped, just start it
        if self.db_container_exists():
            result = subprocess.run(
                ["docker", "start", "secondbrain-db"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.error("Failed to start existing container: %s", result.stderr)
                return False
        else:
            # Fresh start via compose
            result = subprocess.run(
                ["docker", "compose", "up", "-d", "db"],
                capture_output=True,
                text=True,
                cwd=str(self._project_dir),
                env=env,
                timeout=120,
            )
            if result.returncode != 0:
                logger.error("docker compose up failed: %s", result.stderr)
                return False

        # Wait for DB to be ready
        return await self._wait_for_db(db_port)

    async def stop_db(self) -> bool:
        """Stop the database container."""
        try:
            result = subprocess.run(
                ["docker", "stop", "secondbrain-db"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    async def _wait_for_db(self, port: int) -> bool:
        """Poll until PostgreSQL accepts connections."""
        elapsed = 0.0
        while elapsed < DB_READY_TIMEOUT:
            try:
                result = subprocess.run(
                    [
                        "docker", "exec", "secondbrain-db",
                        "pg_isready", "-U", "secondbrain",
                    ],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            await asyncio.sleep(HEALTH_POLL_INTERVAL)
            elapsed += HEALTH_POLL_INTERVAL

        logger.error("Database did not become ready within %.0fs", DB_READY_TIMEOUT)
        return False

    # ── Backend Server ─────────────────────────────────────────────

    def is_server_running(self) -> bool:
        """Check if the backend server process is alive."""
        pid = self._read_pid()
        if pid is None:
            return False
        return _pid_alive(pid)

    def get_server_pid(self) -> Optional[int]:
        """Return the server PID if running, else None."""
        pid = self._read_pid()
        if pid is not None and _pid_alive(pid):
            return pid
        return None

    async def start_server(self, port: Optional[int] = None) -> bool:
        """Start the FastAPI backend as a background process.

        Returns True if the server is up and responding to health checks.
        """
        if self.is_server_running():
            logger.info("Server already running (PID %s)", self._read_pid())
            return True

        server_port = port or self._config.server_port
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        log_handle = open(str(LOG_FILE), "a")  # noqa: SIM115

        # Use sys.executable to ensure we use the same Python
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "app.main:app",
                "--host", "127.0.0.1",
                "--port", str(server_port),
            ],
            cwd=str(self._project_dir),
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )

        self._write_pid(proc.pid)
        self._config.server_pid = proc.pid
        self._config.server_port = server_port
        self._config.server_url = f"http://localhost:{server_port}"
        self._config.save()

        # Wait for health check
        ready = await self._wait_for_server(server_port)
        if not ready:
            # Server failed to start — clean up
            self.stop_server()
            return False

        return True

    def stop_server(self) -> bool:
        """Stop the backend server process."""
        pid = self._read_pid()
        if pid is None:
            return True

        try:
            if sys.platform == "win32":
                # Windows: terminate the process
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True,
                    timeout=10,
                )
            else:
                os.kill(pid, signal.SIGTERM)
        except (OSError, subprocess.TimeoutExpired):
            pass

        self._clear_pid()
        self._config.server_pid = None
        self._config.save()
        return True

    async def restart_server(self) -> bool:
        """Stop and restart the backend server."""
        self.stop_server()
        await asyncio.sleep(1.0)
        return await self.start_server()

    async def _wait_for_server(self, port: int) -> bool:
        """Poll the health endpoint until it responds."""
        url = f"http://localhost:{port}/health"
        elapsed = 0.0
        async with httpx.AsyncClient(timeout=3.0) as client:
            while elapsed < SERVER_READY_TIMEOUT:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        return True
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(HEALTH_POLL_INTERVAL)
                elapsed += HEALTH_POLL_INTERVAL

        logger.error("Server did not become ready within %.0fs", SERVER_READY_TIMEOUT)
        return False

    def read_logs(self, lines: int = 50) -> str:
        """Read the last N lines from the server log."""
        if not LOG_FILE.exists():
            return "(no log file found)"
        all_lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(all_lines[-lines:])

    # ── Migrations ─────────────────────────────────────────────────

    def run_migrations(self) -> bool:
        """Run alembic upgrade head."""
        env = os.environ.copy()
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            cwd=str(self._project_dir),
            env=env,
            timeout=60,
        )
        if result.returncode != 0:
            logger.error("Migrations failed: %s", result.stderr)
            return False
        return True

    # ── Port Discovery ─────────────────────────────────────────────

    @staticmethod
    def find_free_port(start: int, max_attempts: int = 10) -> int:
        """Find a free TCP port starting from `start`."""
        import socket
        for offset in range(max_attempts):
            port = start + offset
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("127.0.0.1", port))
                    return port
            except OSError:
                continue
        raise RuntimeError(
            f"No free port found in range {start}-{start + max_attempts - 1}"
        )

    # ── PID file helpers ───────────────────────────────────────────

    def _read_pid(self) -> Optional[int]:
        """Read PID from file, or from config as fallback."""
        if PID_FILE.exists():
            try:
                return int(PID_FILE.read_text().strip())
            except (ValueError, OSError):
                pass
        return self._config.server_pid

    def _write_pid(self, pid: int) -> None:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(pid))

    def _clear_pid(self) -> None:
        try:
            PID_FILE.unlink(missing_ok=True)
        except TypeError:
            # Python 3.8: missing_ok not supported
            try:
                PID_FILE.unlink()
            except FileNotFoundError:
                pass


def _pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive."""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return str(pid) in result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
