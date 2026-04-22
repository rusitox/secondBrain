"""Unit tests for Installer (mocked Docker, subprocess, API calls)."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cli.config import CLIConfig
from cli.installer import Installer


@pytest.fixture
def config(tmp_path: Path) -> CLIConfig:
    cfg = CLIConfig(_config_path=tmp_path / "config.json")
    cfg.db_port = 5432
    cfg.server_port = 8000
    return cfg


@pytest.fixture
def installer(config: CLIConfig, tmp_path: Path) -> Installer:
    return Installer(config=config, project_dir=tmp_path)


class TestStepDocker:
    async def test_docker_available(self, installer: Installer) -> None:
        with patch.object(installer._server, "is_docker_available", return_value=True):
            result = await installer._step_docker()
            assert result is True

    async def test_docker_not_installed(self, installer: Installer) -> None:
        with patch.object(installer._server, "is_docker_available", return_value=False), \
             patch("cli.installer._command_exists", return_value=False):
            result = await installer._step_docker()
            assert result is False


class TestStepDatabase:
    async def test_db_already_running(self, installer: Installer) -> None:
        with patch.object(installer._server, "is_db_running", return_value=True):
            result = await installer._step_database()
            assert result is True

    async def test_db_starts_successfully(self, installer: Installer) -> None:
        with patch.object(installer._server, "is_db_running", return_value=False), \
             patch.object(installer._server, "find_free_port", return_value=5432), \
             patch.object(installer._server, "start_db", return_value=True):
            result = await installer._step_database()
            assert result is True

    async def test_db_fails_to_start(self, installer: Installer) -> None:
        with patch.object(installer._server, "is_db_running", return_value=False), \
             patch.object(installer._server, "find_free_port", return_value=5432), \
             patch.object(installer._server, "start_db", return_value=False):
            result = await installer._step_database()
            assert result is False

    async def test_port_conflict_uses_next(
        self, installer: Installer, config: CLIConfig,
    ) -> None:
        with patch.object(installer._server, "is_db_running", return_value=False), \
             patch("cli.installer.ServerManager.find_free_port", return_value=5433), \
             patch.object(installer._server, "start_db", return_value=True):
            result = await installer._step_database()
            assert result is True
            assert config.db_port == 5433


class TestStepApiKeys:
    async def test_both_keys_provided(self, installer: Installer) -> None:
        with patch("cli.installer._prompt_password", side_effect=["sk-test-openai", "sk-ant-test"]), \
             patch.object(installer, "_validate_api_key", return_value=True):
            result = await installer._step_api_keys()
            assert result is True
            assert installer._openai_key == "sk-test-openai"
            assert installer._llm_key == "sk-ant-test"

    async def test_openai_key_invalid_then_valid(self, installer: Installer) -> None:
        call_count = 0

        async def validate_side_effect(provider, key):
            nonlocal call_count
            call_count += 1
            if "openai" in provider:
                return call_count > 1  # First call fails, second succeeds
            return True

        with patch("cli.installer._prompt_password", side_effect=[
            "bad-key", "r", "sk-good-key", "sk-ant-test",
        ]), \
             patch("cli.installer._prompt", return_value="r"), \
             patch.object(installer, "_validate_api_key", side_effect=validate_side_effect):
            result = await installer._step_api_keys()
            assert result is True


class TestStepGenerateConfig:
    def test_creates_env_file(
        self, installer: Installer, tmp_path: Path,
    ) -> None:
        installer._openai_key = "sk-test"
        installer._llm_key = "sk-ant-test"
        installer._project_dir = tmp_path

        result = installer._step_generate_config()
        assert result is True

        env_path = tmp_path / ".env"
        assert env_path.exists()
        content = env_path.read_text()
        assert "sk-test" in content
        assert "sk-ant-test" in content
        assert "FERNET_KEY=" in content
        assert "DATABASE_URL=" in content

    def test_keeps_existing_env(
        self, installer: Installer, tmp_path: Path,
    ) -> None:
        installer._openai_key = "sk-test"
        installer._llm_key = ""
        installer._project_dir = tmp_path

        env_path = tmp_path / ".env"
        env_path.write_text("EXISTING_KEY=value\n")

        with patch("cli.installer._prompt", return_value="k"):
            result = installer._step_generate_config()
            assert result is True
            # Original content preserved
            assert "EXISTING_KEY=value" in env_path.read_text()

    def test_merges_env(
        self, installer: Installer, tmp_path: Path,
    ) -> None:
        installer._openai_key = "sk-new"
        installer._llm_key = ""
        installer._project_dir = tmp_path

        env_path = tmp_path / ".env"
        env_path.write_text("OPENAI_API_KEY=sk-old\n")

        with patch("cli.installer._prompt", return_value="m"):
            result = installer._step_generate_config()
            assert result is True
            content = env_path.read_text()
            # Old key preserved, new keys added
            assert "OPENAI_API_KEY=sk-old" in content
            assert "FERNET_KEY=" in content


class TestStepMigrations:
    def test_success(self, installer: Installer) -> None:
        with patch.object(installer._server, "run_migrations", return_value=True):
            result = installer._step_migrations()
            assert result is True

    def test_failure(self, installer: Installer) -> None:
        with patch.object(installer._server, "run_migrations", return_value=False):
            result = installer._step_migrations()
            assert result is False


class TestStepStartServer:
    async def test_starts_successfully(self, installer: Installer) -> None:
        with patch.object(installer._server, "find_free_port", return_value=8000), \
             patch.object(installer._server, "start_server", return_value=True), \
             patch.object(installer._server, "get_server_pid", return_value=12345):
            result = await installer._step_start_server()
            assert result is True

    async def test_start_fails(self, installer: Installer) -> None:
        with patch.object(installer._server, "find_free_port", return_value=8000), \
             patch.object(installer._server, "start_server", return_value=False):
            result = await installer._step_start_server()
            assert result is False


class TestValidateApiKey:
    async def test_valid_openai_key(self, installer: Installer) -> None:
        with patch("cli.installer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client.get = AsyncMock(return_value=MagicMock(status_code=200))
            mock_client_cls.return_value = mock_client

            result = await installer._validate_api_key("openai", "sk-test")
            assert result is True

    async def test_invalid_openai_key(self, installer: Installer) -> None:
        with patch("cli.installer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client.get = AsyncMock(return_value=MagicMock(status_code=401))
            mock_client_cls.return_value = mock_client

            result = await installer._validate_api_key("openai", "bad-key")
            assert result is False


class TestHandleReinstall:
    async def test_cancel(self, installer: Installer) -> None:
        installer._config.installed = True
        with patch.object(installer._server, "is_db_running", return_value=True), \
             patch.object(installer._server, "is_server_running", return_value=True), \
             patch("cli.installer._prompt", return_value="q"):
            result = await installer._handle_reinstall()
            assert result is False

    async def test_update_runs_migrations(self, installer: Installer) -> None:
        installer._config.installed = True
        with patch.object(installer._server, "is_db_running", return_value=True), \
             patch.object(installer._server, "is_server_running", return_value=True), \
             patch("cli.installer._prompt", return_value="u"), \
             patch.object(installer, "_step_migrations", return_value=True):
            result = await installer._handle_reinstall()
            assert result is True
