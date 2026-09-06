"""Unit tests for build_openai_model — shared across every Strands agent factory.

Extracted from strands_orchestrator.py (see TestBuildAgentReasoningGuard in
test_strands_orchestrator.py for the original indirect coverage); this file
tests the helper directly so new agent factories (domain agents, etc.) can
rely on it without re-deriving the reasoning_effort guard's behavior.
"""
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from app.services.agent.strands_model import build_openai_model


def _run_build(llm_model: str, api_key: Optional[str] = None):
    settings = MagicMock()
    settings.llm_model = llm_model
    settings.llm_api_key = "sk-test"

    with patch("strands.models.openai.OpenAIModel") as mock_model_cls, \
         patch("app.core.config.get_settings", return_value=settings):
        build_openai_model(api_key=api_key)
    return mock_model_cls


class TestBuildOpenAIModel:
    def test_reasoning_model_gets_reasoning_effort_none(self) -> None:
        mock_model_cls = _run_build("openai/gpt-5.6-luna")
        _, kwargs = mock_model_cls.call_args
        assert kwargs["params"] == {"reasoning_effort": "none"}
        assert kwargs["model_id"] == "gpt-5.6-luna"

    @pytest.mark.parametrize("model_id", ["o1", "o1-mini", "o3", "o3-mini", "o4-mini"])
    def test_o_series_models_get_reasoning_effort_none(self, model_id: str) -> None:
        mock_model_cls = _run_build(model_id)
        _, kwargs = mock_model_cls.call_args
        assert kwargs["params"] == {"reasoning_effort": "none"}

    def test_non_reasoning_model_gets_no_params(self) -> None:
        mock_model_cls = _run_build("openai/gpt-4o-mini")
        _, kwargs = mock_model_cls.call_args
        assert kwargs["params"] is None
        assert kwargs["model_id"] == "gpt-4o-mini"

    def test_explicit_api_key_overrides_settings(self) -> None:
        mock_model_cls = _run_build("openai/gpt-4o-mini", api_key="sk-explicit")
        _, kwargs = mock_model_cls.call_args
        assert kwargs["client_args"] == {"api_key": "sk-explicit"}

    def test_falls_back_to_settings_api_key(self) -> None:
        mock_model_cls = _run_build("openai/gpt-4o-mini")
        _, kwargs = mock_model_cls.call_args
        assert kwargs["client_args"] == {"api_key": "sk-test"}
