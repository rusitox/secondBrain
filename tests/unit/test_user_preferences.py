"""Unit tests for user preferences model properties and CLI config extensions."""
import json
from unittest.mock import MagicMock, PropertyMock

import pytest

from app.api.schemas.user import (
    NotionConfigUpdate,
    OnboardingState,
    OnboardingUpdate,
    UserPreferencesResponse,
    UserPreferencesUpdate,
)
from app.models.user import User


class TestUserModelProperties:
    """Test the preferences/notion_config property methods using the class directly."""

    def test_preferences_getter_none(self) -> None:
        assert User.preferences.fget is not None
        # Test the getter logic directly
        mock_user = MagicMock(spec=User)
        mock_user.preferences_json = None
        result = User.preferences.fget(mock_user)
        assert result == {}

    def test_preferences_getter_valid(self) -> None:
        mock_user = MagicMock(spec=User)
        mock_user.preferences_json = '{"briefing_hour": 8}'
        result = User.preferences.fget(mock_user)
        assert result["briefing_hour"] == 8

    def test_preferences_getter_invalid_json(self) -> None:
        mock_user = MagicMock(spec=User)
        mock_user.preferences_json = "not valid json"
        result = User.preferences.fget(mock_user)
        assert result == {}

    def test_preferences_setter_dict(self) -> None:
        mock_user = MagicMock(spec=User)
        User.preferences.fset(mock_user, {"key": "value"})
        assert json.loads(mock_user.preferences_json) == {"key": "value"}

    def test_preferences_setter_empty_dict(self) -> None:
        mock_user = MagicMock(spec=User)
        User.preferences.fset(mock_user, {})
        assert mock_user.preferences_json == "{}"

    def test_preferences_setter_none(self) -> None:
        mock_user = MagicMock(spec=User)
        User.preferences.fset(mock_user, None)
        assert mock_user.preferences_json is None

    def test_notion_config_getter_none(self) -> None:
        mock_user = MagicMock(spec=User)
        mock_user.notion_config_json = None
        result = User.notion_config.fget(mock_user)
        assert result is None

    def test_notion_config_getter_valid(self) -> None:
        mock_user = MagicMock(spec=User)
        mock_user.notion_config_json = '{"enabled": true, "root_page_id": "abc"}'
        result = User.notion_config.fget(mock_user)
        assert result["enabled"] is True
        assert result["root_page_id"] == "abc"

    def test_notion_config_setter(self) -> None:
        mock_user = MagicMock(spec=User)
        User.notion_config.fset(mock_user, {"enabled": True})
        assert json.loads(mock_user.notion_config_json) == {"enabled": True}

    def test_notion_config_setter_none(self) -> None:
        mock_user = MagicMock(spec=User)
        User.notion_config.fset(mock_user, None)
        assert mock_user.notion_config_json is None


class TestPreferencesSchemas:
    def test_onboarding_state(self) -> None:
        state = OnboardingState(step=3, completed=False)
        assert state.step == 3
        assert state.completed is False

    def test_onboarding_update_partial(self) -> None:
        update = OnboardingUpdate(step=2)
        assert update.step == 2
        assert update.completed is None

    def test_onboarding_update_full(self) -> None:
        update = OnboardingUpdate(step=5, completed=True)
        assert update.step == 5
        assert update.completed is True

    def test_preferences_response(self) -> None:
        resp = UserPreferencesResponse(
            preferences={"key": "val"},
            onboarding=OnboardingState(step=1, completed=False),
            notion_config=None,
        )
        assert resp.preferences == {"key": "val"}
        assert resp.onboarding.step == 1

    def test_preferences_update(self) -> None:
        update = UserPreferencesUpdate(preferences={"new_key": 42})
        assert update.preferences["new_key"] == 42

    def test_notion_config_update(self) -> None:
        update = NotionConfigUpdate(config={"enabled": True})
        assert update.config["enabled"] is True

    def test_notion_config_update_none(self) -> None:
        update = NotionConfigUpdate(config=None)
        assert update.config is None

    def test_onboarding_step_negative_rejected(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            OnboardingUpdate(step=-1)

    def test_onboarding_step_too_high_rejected(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            OnboardingUpdate(step=11)


class TestCLIConfigExtensions:
    def test_is_remote_mode_localhost(self) -> None:
        from cli.config import CLIConfig
        config = CLIConfig(server_url="http://localhost:8000")
        assert not config.is_remote_mode

    def test_is_remote_mode_127(self) -> None:
        from cli.config import CLIConfig
        config = CLIConfig(server_url="http://127.0.0.1:8000")
        assert not config.is_remote_mode

    def test_is_remote_mode_remote(self) -> None:
        from cli.config import CLIConfig
        config = CLIConfig(server_url="http://myserver:8080")
        assert config.is_remote_mode

    def test_is_remote_mode_tailscale(self) -> None:
        from cli.config import CLIConfig
        config = CLIConfig(server_url="http://oracle-vm:8080")
        assert config.is_remote_mode

    def test_apply_server_state(self) -> None:
        from cli.config import CLIConfig
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            config = CLIConfig(_config_path=path)

            config.apply_server_state({
                "onboarding": {"step": 3, "completed": False},
                "preferences": {"briefing_hour": 9},
                "notion_config": {"enabled": True},
            })

            assert config.onboarding_step == 3
            assert config.onboarding_completed is False
            assert config.preferences["briefing_hour"] == 9
            assert config.notion["enabled"] is True

    def test_apply_server_state_preserves_local_prefs(self) -> None:
        from cli.config import CLIConfig
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            config = CLIConfig(_config_path=path)
            config.preferences = {"local_key": "local_val"}

            config.apply_server_state({
                "onboarding": {"step": 0, "completed": False},
                "preferences": {"server_key": "server_val"},
            })

            assert config.preferences["local_key"] == "local_val"
            assert config.preferences["server_key"] == "server_val"

    def test_api_key_field(self) -> None:
        from cli.config import CLIConfig
        config = CLIConfig(api_key="sb_live_test123")
        assert config.api_key == "sb_live_test123"

    def test_api_key_default_none(self) -> None:
        from cli.config import CLIConfig
        config = CLIConfig()
        assert config.api_key is None
