"""Unit tests for CLI configuration."""
import json
from pathlib import Path

import pytest

from cli.config import CLIConfig, DEFAULT_SERVER_URL


class TestCLIConfig:
    """Tests for CLIConfig dataclass."""

    def test_defaults(self) -> None:
        config = CLIConfig()
        assert config.server_url == DEFAULT_SERVER_URL
        assert config.user_id is None
        assert config.user_name is None
        assert config.onboarding_completed is False
        assert config.onboarding_step == 0
        assert config.platforms_connected == []
        assert config.identity_configured is False
        assert config.initial_import_done is False
        assert config.preferences == {}

    def test_load_missing_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / "nonexistent" / "config.json"
        config = CLIConfig.load(config_path)
        assert config.server_url == DEFAULT_SERVER_URL
        assert config.user_id is None

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config = CLIConfig(_config_path=config_path)
        config.user_id = "test-uuid-123"
        config.user_name = "Test User"
        config.onboarding_completed = True
        config.platforms_connected = ["slack", "outlook"]
        config.preferences = {"briefing_time": "07:30"}
        config.save()

        loaded = CLIConfig.load(config_path)
        assert loaded.user_id == "test-uuid-123"
        assert loaded.user_name == "Test User"
        assert loaded.onboarding_completed is True
        assert loaded.platforms_connected == ["slack", "outlook"]
        assert loaded.preferences["briefing_time"] == "07:30"

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        config_path = tmp_path / "nested" / "deep" / "config.json"
        config = CLIConfig(_config_path=config_path)
        config.user_id = "abc"
        config.save()
        assert config_path.exists()

    def test_load_corrupt_json(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text("not valid json {{{", encoding="utf-8")
        config = CLIConfig.load(config_path)
        assert config.server_url == DEFAULT_SERVER_URL
        assert config.user_id is None

    def test_load_preserves_server_url(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        data = {"server_url": "http://custom:9000", "user_id": "u1"}
        config_path.write_text(json.dumps(data), encoding="utf-8")
        config = CLIConfig.load(config_path)
        assert config.server_url == "http://custom:9000"

    def test_reset(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config = CLIConfig(
            server_url="http://custom:9000",
            user_id="abc",
            onboarding_completed=True,
            _config_path=config_path,
        )
        config.reset()
        assert config.user_id is None
        assert config.onboarding_completed is False
        assert config.server_url == "http://custom:9000"
        assert config_path.exists()

    def test_save_file_format(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config = CLIConfig(_config_path=config_path)
        config.user_id = "test"
        config.save()
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        assert "server_url" in raw
        assert "user_id" in raw
        assert "onboarding_completed" in raw
        assert "preferences" in raw
