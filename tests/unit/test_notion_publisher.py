"""Unit tests for NotionPublisher (mocked HTTP)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notion.config import NotionWorkspaceConfig
from app.services.notion.publisher import NotionPublisher, _map_status


class TestMapStatus:
    def test_pending(self) -> None:
        assert _map_status("pending") == "Pending"

    def test_completed(self) -> None:
        assert _map_status("completed") == "Completed"

    def test_cancelled(self) -> None:
        assert _map_status("cancelled") == "Cancelled"

    def test_unknown_defaults_to_pending(self) -> None:
        assert _map_status("unknown") == "Pending"

    def test_case_insensitive(self) -> None:
        assert _map_status("COMPLETED") == "Completed"


class TestNotionWorkspaceConfig:
    def test_to_dict_roundtrip(self) -> None:
        config = NotionWorkspaceConfig(
            enabled=True,
            root_page_id="root-123",
            commitments_db_id="comm-456",
            briefings_db_id="brief-789",
            meeting_prep_db_id="meet-012",
            read_mode="all",
        )
        d = config.to_dict()
        restored = NotionWorkspaceConfig.from_dict(d)
        assert restored.enabled is True
        assert restored.root_page_id == "root-123"
        assert restored.commitments_db_id == "comm-456"
        assert restored.briefings_db_id == "brief-789"
        assert restored.meeting_prep_db_id == "meet-012"
        assert restored.read_mode == "all"

    def test_from_dict_defaults(self) -> None:
        config = NotionWorkspaceConfig.from_dict({})
        assert config.enabled is False
        assert config.root_page_id is None
        assert config.read_mode == "all"
        assert config.selected_page_ids == []

    def test_from_dict_with_lists(self) -> None:
        config = NotionWorkspaceConfig.from_dict({
            "selected_page_ids": ["a", "b"],
            "excluded_page_ids": ["c"],
        })
        assert config.selected_page_ids == ["a", "b"]
        assert config.excluded_page_ids == ["c"]


class TestPublisherInit:
    def test_creates_with_token_and_config(self) -> None:
        config = NotionWorkspaceConfig()
        publisher = NotionPublisher("ntn_test", config)
        assert publisher._token == "ntn_test"
        assert publisher._config is config

    def test_publish_briefing_requires_db(self) -> None:
        config = NotionWorkspaceConfig(briefings_db_id=None)
        publisher = NotionPublisher("ntn_test", config)
        with pytest.raises(RuntimeError, match="Briefings database not set up"):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                publisher.publish_briefing("text", "2026-04-18")
            )

    def test_create_commitment_requires_db(self) -> None:
        config = NotionWorkspaceConfig(commitments_db_id=None)
        publisher = NotionPublisher("ntn_test", config)
        with pytest.raises(RuntimeError, match="Commitments database not set up"):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                publisher.create_commitment_row({"commitment_text": "test"})
            )
