"""Unit tests for the onboarding wizard flow.

Tests mock APIClient calls and console input to validate the wizard logic
without a running backend.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cli.api_client import APIClient, APIError
from cli.config import CLIConfig
from cli.onboarding import OnboardingFlow


def _make_config(**overrides) -> CLIConfig:
    """Create a CLIConfig with test defaults."""
    defaults = dict(
        server_url="http://test:8000",
        user_id=None,
        user_name=None,
        user_email=None,
        onboarding_completed=False,
        onboarding_step=0,
        platforms_connected=[],
        identity_configured=False,
        initial_import_done=False,
        preferences={},
    )
    defaults.update(overrides)
    config = CLIConfig(**defaults)
    config.save = MagicMock()  # Don't write to disk
    return config


def _make_api() -> APIClient:
    """Create a mock APIClient."""
    api = MagicMock(spec=APIClient)
    api.create_user = AsyncMock(return_value={
        "id": "user-123", "email": "test@test.com", "full_name": "Test User",
    })
    api.get_user = AsyncMock(return_value={
        "id": "user-123", "email": "test@test.com", "full_name": "Test User",
    })
    api.create_integration = AsyncMock(return_value={"id": "int-1"})
    api.create_identity = AsyncMock(return_value={"id": "id-1"})
    api.get_identity = AsyncMock(return_value=None)
    api.update_identity = AsyncMock(return_value={"id": "id-1"})
    api.sync_platform = AsyncMock(return_value={
        "documents_created": 10, "commitments_detected": 2,
    })
    api.list_commitments = AsyncMock(return_value=[])
    api.schedule_briefing = AsyncMock(return_value={"id": "sched-1"})
    api.get_user_stats = AsyncMock(return_value={
        "documents_total": 10, "commitments_pending": 2,
    })
    api.set_user_id = MagicMock()
    return api


class TestStepWelcome:
    """Tests for step 1: account creation."""

    @pytest.mark.asyncio
    async def test_creates_user_and_saves_config(self) -> None:
        api = _make_api()
        config = _make_config()
        flow = OnboardingFlow(api=api, config=config)

        inputs = iter(["Mariano Ortega", "mariano@test.com", "America/Argentina/Buenos_Aires"])
        with patch("cli.onboarding._ask", side_effect=lambda p, **kw: next(inputs)):
            result = await flow._step_welcome()

        assert result is True
        api.create_user.assert_awaited_once_with(
            "mariano@test.com", "Mariano Ortega", "America/Argentina/Buenos_Aires",
        )
        assert config.user_id == "user-123"
        assert config.user_name == "Mariano Ortega"
        assert config.user_email == "mariano@test.com"

    @pytest.mark.asyncio
    async def test_empty_name_aborts(self) -> None:
        api = _make_api()
        config = _make_config()
        flow = OnboardingFlow(api=api, config=config)

        with patch("cli.onboarding._ask", return_value=""):
            result = await flow._step_welcome()

        assert result is False
        api.create_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_duplicate_email_offers_login(self) -> None:
        api = _make_api()
        api.create_user = AsyncMock(side_effect=APIError(409, "Duplicate"))
        config = _make_config()
        flow = OnboardingFlow(api=api, config=config)

        inputs = iter(["Test User", "dup@test.com", "UTC", "user-123"])
        with patch("cli.onboarding._ask", side_effect=lambda p, **kw: next(inputs)):
            result = await flow._step_welcome()

        assert result is True
        api.get_user.assert_awaited_once_with("user-123")


class TestStepPlatforms:
    """Tests for step 2: platform connections."""

    @pytest.mark.asyncio
    async def test_skip_platforms(self) -> None:
        api = _make_api()
        config = _make_config(user_id="user-123")
        flow = OnboardingFlow(api=api, config=config)

        with patch("cli.onboarding._ask", return_value="s"):
            result = await flow._step_platforms()

        assert result is True
        assert config.platforms_connected == []

    @pytest.mark.asyncio
    async def test_connect_single_platform(self) -> None:
        api = _make_api()
        config = _make_config(user_id="user-123")
        flow = OnboardingFlow(api=api, config=config)

        call_count = [0]

        def mock_ask(prompt, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return "2"  # Select Slack
            return "xoxb-1234-5678-abcdefghij"  # Token

        with patch("cli.onboarding._ask", side_effect=mock_ask):
            result = await flow._step_platforms()

        assert result is True
        assert "slack" in config.platforms_connected
        api.create_integration.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_multiple_platforms(self) -> None:
        api = _make_api()
        config = _make_config(user_id="user-123")
        flow = OnboardingFlow(api=api, config=config)

        call_count = [0]

        def mock_ask(prompt, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return "1, 2"  # Select Outlook and Slack
            return "xoxb-some-long-valid-token-12345"  # Token for each

        with patch("cli.onboarding._ask", side_effect=mock_ask):
            result = await flow._step_platforms()

        assert result is True
        assert "outlook" in config.platforms_connected
        assert "slack" in config.platforms_connected


class TestStepIdentity:
    """Tests for step 3: identity configuration."""

    @pytest.mark.asyncio
    async def test_create_identity_with_preset_tone(self) -> None:
        api = _make_api()
        config = _make_config(user_id="user-123")
        flow = OnboardingFlow(api=api, config=config)

        inputs = iter([
            "CTO at startup",  # persona
            "2",               # tone: friendly but professional
            "",                # no heuristics (empty line)
            "y",               # confirm
        ])
        with patch("cli.onboarding._ask", side_effect=lambda p, **kw: next(inputs)):
            with patch("cli.onboarding._ask_choice", side_effect=["2", "y"]):
                result = await flow._step_identity()

        assert result is True
        assert config.identity_configured is True
        api.create_identity.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_identity_with_custom_tone_and_rules(self) -> None:
        api = _make_api()
        config = _make_config(user_id="user-123")
        flow = OnboardingFlow(api=api, config=config)

        call_count = [0]
        responses = [
            "Engineering manager",  # persona
            "Direct and concise",   # custom tone
            "Prioritize investors", # rule 1
            "Bob = CTO partner",    # rule 2
            "",                     # end rules
        ]

        def mock_ask(prompt, **kw):
            nonlocal call_count
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(responses):
                return responses[idx]
            return ""

        with patch("cli.onboarding._ask", side_effect=mock_ask):
            with patch("cli.onboarding._ask_choice", side_effect=["4", "y"]):
                result = await flow._step_identity()

        assert result is True
        call_args = api.create_identity.call_args
        assert call_args[1]["heuristics"]["rule_1"] == "Prioritize investors"


class TestStepInitialImport:
    """Tests for step 4: initial data import."""

    @pytest.mark.asyncio
    async def test_skip_when_no_platforms(self) -> None:
        api = _make_api()
        config = _make_config(user_id="user-123", platforms_connected=[])
        flow = OnboardingFlow(api=api, config=config)

        result = await flow._step_initial_import()

        assert result is True
        api.sync_platform.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sync_connected_platforms(self) -> None:
        api = _make_api()
        config = _make_config(user_id="user-123", platforms_connected=["slack", "outlook"])
        flow = OnboardingFlow(api=api, config=config)

        with patch("cli.onboarding._ask_choice", return_value="2"):
            result = await flow._step_initial_import()

        assert result is True
        assert api.sync_platform.await_count == 2
        assert config.initial_import_done is True

    @pytest.mark.asyncio
    async def test_sync_failure_continues(self) -> None:
        api = _make_api()
        api.sync_platform = AsyncMock(side_effect=[
            APIError(500, "Slack down"),
            {"documents_created": 5, "commitments_detected": 1},
        ])
        config = _make_config(user_id="user-123", platforms_connected=["slack", "outlook"])
        flow = OnboardingFlow(api=api, config=config)

        with patch("cli.onboarding._ask_choice", return_value="1"):
            result = await flow._step_initial_import()

        assert result is True  # Continues despite slack failure


class TestStepPreferences:
    """Tests for step 5: preferences."""

    @pytest.mark.asyncio
    async def test_set_briefing_time(self) -> None:
        api = _make_api()
        config = _make_config(user_id="user-123")
        flow = OnboardingFlow(api=api, config=config)

        inputs = iter(["08:30"])

        with patch("cli.onboarding._ask", side_effect=lambda p, **kw: next(inputs)):
            with patch("cli.onboarding._ask_choice", return_value="2"):
                result = await flow._step_preferences()

        assert result is True
        assert config.preferences["briefing_hour"] == 8
        assert config.preferences["briefing_minute"] == 30
        assert config.preferences["alert_mode"] == "briefing_only"
        api.schedule_briefing.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_default_time_on_empty(self) -> None:
        api = _make_api()
        config = _make_config(user_id="user-123")
        flow = OnboardingFlow(api=api, config=config)

        with patch("cli.onboarding._ask_validated", return_value=None):
            with patch("cli.onboarding._ask_choice", return_value="1"):
                result = await flow._step_preferences()

        assert result is True
        assert config.preferences["briefing_hour"] == 7
        assert config.preferences["briefing_minute"] == 0


class TestOnboardingResume:
    """Tests for resume from interrupted onboarding."""

    @pytest.mark.asyncio
    async def test_resume_skip_to_chat(self) -> None:
        config = _make_config(
            user_id="user-123", user_name="Test", onboarding_step=2,
        )
        api = _make_api()
        flow = OnboardingFlow(api=api, config=config)

        with patch("cli.onboarding._ask_choice", return_value="s"):
            result = await flow.run()

        assert result is False

    @pytest.mark.asyncio
    async def test_resume_continue_skips_completed_steps(self) -> None:
        """Resuming from step 3 should skip steps 1 and 2."""
        api = _make_api()
        config = _make_config(
            user_id="user-123",
            user_name="Test",
            user_email="test@test.com",
            onboarding_step=2,  # Steps 1 and 2 already done
            platforms_connected=[],  # No platforms
        )
        flow = OnboardingFlow(api=api, config=config)

        # Resume with "c", then go through steps 3-5
        ask_responses = [
            # Step 3: identity
            "CTO at startup",   # persona
            "",                 # no heuristics (empty = stop)
            # Step 5: preferences
            "08:00",           # briefing time
        ]
        call_count = [0]

        def mock_ask(prompt, **kw):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(ask_responses):
                return ask_responses[idx]
            return ""

        # c=resume, 1=tone preset, y=confirm identity, 2=alert briefing_only
        choice_responses = iter(["c", "1", "y", "2"])

        with patch("cli.onboarding._ask", side_effect=mock_ask):
            with patch("cli.onboarding._ask_choice", side_effect=choice_responses):
                result = await flow.run()

        assert result is True
        # Step 1 (create_user) should NOT have been called
        api.create_user.assert_not_awaited()
        assert config.onboarding_completed is True
        assert config.onboarding_step == 5


class TestFullFlow:
    """End-to-end test of complete onboarding wizard."""

    @pytest.mark.asyncio
    async def test_complete_flow_with_skip_platforms(self) -> None:
        """Full flow: create user, skip platforms, set identity, skip import, set prefs."""
        api = _make_api()
        config = _make_config()
        flow = OnboardingFlow(api=api, config=config)

        # Sequence of all _ask inputs for the full flow
        ask_responses = [
            # Step 1: welcome
            "Test User",
            "test@example.com",
            "UTC",
            # Step 2: platforms
            "s",              # skip
            # Step 3: identity
            "Software Engineer",  # persona
            "",                   # no rules (empty = stop heuristics loop)
            # Step 5: preferences
            "09:00",             # briefing time
        ]
        call_count = [0]

        def mock_ask(prompt, **kw):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(ask_responses):
                return ask_responses[idx]
            return ""

        # _ask_choice calls: tone=2 (preset), confirm=y, alert_mode=1
        choice_responses = iter(["2", "y", "1"])

        with patch("cli.onboarding._ask", side_effect=mock_ask):
            with patch("cli.onboarding._ask_choice", side_effect=choice_responses):
                result = await flow.run()

        assert result is True
        assert config.onboarding_completed is True
        assert config.onboarding_step == 5
        assert config.user_id == "user-123"
        assert config.identity_configured is True
        assert config.save.call_count >= 5  # Saved after each step
