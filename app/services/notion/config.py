"""Configuration dataclass for the Notion workspace managed by the assistant."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class NotionWorkspaceConfig:
    """Persisted configuration for the assistant's Notion workspace.

    Serialised as a dict inside ``CLIConfig.notion``.
    """

    enabled: bool = False

    # Workspace page/database IDs (set during setup_workspace)
    root_page_id: Optional[str] = None
    root_page_url: Optional[str] = None
    commitments_db_id: Optional[str] = None
    briefings_db_id: Optional[str] = None
    meeting_prep_db_id: Optional[str] = None

    # Reading preferences
    read_mode: str = "all"  # "all" | "selected"
    selected_page_ids: List[str] = field(default_factory=list)
    excluded_page_ids: List[str] = field(default_factory=list)

    # Sync timestamps (ISO-8601)
    last_read_sync: Optional[str] = None
    last_write_sync: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "root_page_id": self.root_page_id,
            "root_page_url": self.root_page_url,
            "commitments_db_id": self.commitments_db_id,
            "briefings_db_id": self.briefings_db_id,
            "meeting_prep_db_id": self.meeting_prep_db_id,
            "read_mode": self.read_mode,
            "selected_page_ids": self.selected_page_ids,
            "excluded_page_ids": self.excluded_page_ids,
            "last_read_sync": self.last_read_sync,
            "last_write_sync": self.last_write_sync,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NotionWorkspaceConfig":
        return cls(
            enabled=data.get("enabled", False),
            root_page_id=data.get("root_page_id"),
            root_page_url=data.get("root_page_url"),
            commitments_db_id=data.get("commitments_db_id"),
            briefings_db_id=data.get("briefings_db_id"),
            meeting_prep_db_id=data.get("meeting_prep_db_id"),
            read_mode=data.get("read_mode", "all"),
            selected_page_ids=data.get("selected_page_ids", []),
            excluded_page_ids=data.get("excluded_page_ids", []),
            last_read_sync=data.get("last_read_sync"),
            last_write_sync=data.get("last_write_sync"),
        )
