"""Unit tests for ServerManager (mocked subprocess/docker)."""
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from cli.config import CLIConfig
from cli.server import ServerManager, _pid_alive


@pytest.fixture
def config(tmp_path: Path) -> CLIConfig:
    cfg = CLIConfig(_config_path=tmp_path / "config.json")
    cfg.db_port = 5432
    cfg.server_port = 8000
    return cfg


@pytest.fixture
def manager(config: CLIConfig, tmp_path: Path) -> ServerManager:
    return ServerManager(config, project_dir=tmp_path)


class TestDockerAvailability:
    def test_docker_available(self, manager: ServerManager) -> None:
        with patch("cli.server.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert manager.is_docker_available() is True

    def test_docker_not_available(self, manager: ServerManager) -> None:
        with patch("cli.server.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError
            assert manager.is_docker_available() is False

    def test_docker_daemon_not_running(self, manager: ServerManager) -> None:
        with patch("cli.server.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert manager.is_docker_available() is False


class TestDbRunning:
    def test_db_running(self, manager: ServerManager) -> None:
        with patch("cli.server.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="true\n")
            assert manager.is_db_running() is True

    def test_db_not_running(self, manager: ServerManager) -> None:
        with patch("cli.server.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            assert manager.is_db_running() is False

    def test_db_container_not_exists(self, manager: ServerManager) -> None:
        with patch("cli.server.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError
            assert manager.is_db_running() is False


class TestDbContainerExists:
    def test_exists(self, manager: ServerManager) -> None:
        with patch("cli.server.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert manager.db_container_exists() is True

    def test_not_exists(self, manager: ServerManager) -> None:
        with patch("cli.server.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert manager.db_container_exists() is False


class TestStartDb:
    async def test_already_running(self, manager: ServerManager) -> None:
        with patch.object(manager, "is_db_running", return_value=True):
            result = await manager.start_db()
            assert result is True

    async def test_start_existing_container(self, manager: ServerManager) -> None:
        with patch.object(manager, "is_db_running", return_value=False), \
             patch.object(manager, "db_container_exists", return_value=True), \
             patch("cli.server.subprocess.run") as mock_run, \
             patch.object(manager, "_wait_for_db", return_value=True):
            mock_run.return_value = MagicMock(returncode=0)
            result = await manager.start_db()
            assert result is True
            # Should have called docker start, not docker compose
            mock_run.assert_called_once()
            assert "start" in mock_run.call_args[0][0]

    async def test_start_fresh_compose(self, manager: ServerManager) -> None:
        with patch.object(manager, "is_db_running", return_value=False), \
             patch.object(manager, "db_container_exists", return_value=False), \
             patch("cli.server.subprocess.run") as mock_run, \
             patch.object(manager, "_wait_for_db", return_value=True):
            mock_run.return_value = MagicMock(returncode=0)
            result = await manager.start_db()
            assert result is True

    async def test_compose_fails(self, manager: ServerManager) -> None:
        with patch.object(manager, "is_db_running", return_value=False), \
             patch.object(manager, "db_container_exists", return_value=False), \
             patch("cli.server.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            result = await manager.start_db()
            assert result is False


class TestStopDb:
    async def test_stop(self, manager: ServerManager) -> None:
        with patch("cli.server.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = await manager.stop_db()
            assert result is True


class TestServerRunning:
    def test_no_pid_file(self, manager: ServerManager) -> None:
        assert manager.is_server_running() is False

    def test_pid_alive(self, manager: ServerManager, tmp_path: Path) -> None:
        with patch.object(manager, "_read_pid", return_value=12345), \
             patch("cli.server._pid_alive", return_value=True):
            assert manager.is_server_running() is True

    def test_pid_dead(self, manager: ServerManager) -> None:
        with patch.object(manager, "_read_pid", return_value=12345), \
             patch("cli.server._pid_alive", return_value=False):
            assert manager.is_server_running() is False


class TestStopServer:
    def test_stop_no_pid(self, manager: ServerManager) -> None:
        with patch.object(manager, "_read_pid", return_value=None):
            assert manager.stop_server() is True

    def test_stop_with_pid(self, manager: ServerManager, config: CLIConfig) -> None:
        with patch.object(manager, "_read_pid", return_value=12345), \
             patch("cli.server.os.kill") as mock_kill, \
             patch.object(manager, "_clear_pid"):
            manager.stop_server()
            mock_kill.assert_called_once_with(12345, __import__("signal").SIGTERM)
            assert config.server_pid is None


class TestFindFreePort:
    def test_finds_free_port(self) -> None:
        # Port 0 should always find something
        port = ServerManager.find_free_port(49152)
        assert port >= 49152

    def test_raises_when_no_port(self) -> None:
        with patch("socket.socket") as mock_socket:
            mock_socket.return_value.__enter__ = MagicMock()
            mock_socket.return_value.__exit__ = MagicMock()
            mock_socket.return_value.__enter__.return_value.bind = MagicMock(
                side_effect=OSError
            )
            with pytest.raises(RuntimeError, match="No free port"):
                ServerManager.find_free_port(5432, max_attempts=2)


class TestRunMigrations:
    def test_success(self, manager: ServerManager) -> None:
        with patch("cli.server.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert manager.run_migrations() is True

    def test_failure(self, manager: ServerManager) -> None:
        with patch("cli.server.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="migration error")
            assert manager.run_migrations() is False


class TestReadLogs:
    def test_no_log_file(self, manager: ServerManager) -> None:
        result = manager.read_logs()
        assert "no log file" in result

    def test_read_last_lines(self, manager: ServerManager) -> None:
        from cli.server import LOG_FILE
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOG_FILE.write_text("line1\nline2\nline3\nline4\n")
        try:
            result = manager.read_logs(lines=2)
            assert "line3" in result
            assert "line4" in result
        finally:
            LOG_FILE.unlink()


class TestPidAlive:
    def test_alive(self) -> None:
        import os
        # Current process should be alive
        assert _pid_alive(os.getpid()) is True

    def test_dead(self) -> None:
        # Very high PID unlikely to exist
        assert _pid_alive(999999999) is False
