"""Onboarding wizard — guides new users through initial setup.

Full implementation in Phase 7B.
"""
import logging
from typing import Optional

from cli.api_client import APIClient
from cli.config import CLIConfig
from cli.display import print_info, print_welcome

logger = logging.getLogger(__name__)


class OnboardingFlow:
    """Multi-step onboarding wizard."""

    def __init__(self, api: APIClient, config: CLIConfig) -> None:
        self._api = api
        self._config = config

    async def run(self) -> bool:
        """Run the onboarding wizard. Returns True if completed."""
        print_welcome(
            "Welcome to secondBrain",
            "Your AI Chief of Staff\n\nOnboarding will be available in Phase 7B.",
        )
        print_info("Onboarding wizard not yet implemented. Use the API directly for now.")
        return False
