"""Shared Strands OpenAIModel construction — used by every Strands agent in this codebase.

Extracted from strands_orchestrator.py so the reasoning_effort guard (a real
bug fix, not incidental behavior) has one place to live instead of being
copy-pasted into every new agent factory.
"""
from typing import Optional

_REASONING_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def build_openai_model(api_key: Optional[str] = None, model: Optional[str] = None):
    """Build a Strands OpenAIModel from settings (or explicit overrides).

    Reasoning models (e.g. gpt-5.6-luna, o1, o3) reject function tools via
    /v1/chat/completions unless reasoning_effort is set to "none".
    """
    from strands.models.openai import OpenAIModel

    from app.core.config import get_settings

    settings = get_settings()
    raw_model = model or settings.llm_model
    # Strip the "openai/" provider prefix if present (e.g. "openai/gpt-4o" → "gpt-4o")
    model_id = raw_model.split("/", 1)[-1] if "/" in raw_model else raw_model

    is_reasoning = any(model_id.startswith(p) for p in _REASONING_PREFIXES)
    extra_params: dict = {"reasoning_effort": "none"} if is_reasoning else {}

    return OpenAIModel(
        model_id=model_id,
        client_args={"api_key": api_key or settings.llm_api_key},
        params=extra_params if extra_params else None,
    )
