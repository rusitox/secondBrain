"""Abstract base class for platform connectors.

All connectors follow the same interface: fetch new items since
last_sync_at, return them as a list of dicts ready for the pipeline.
"""
import abc
from datetime import datetime
from typing import Any, Dict, List, Optional


class ConnectorItem:
    """A single item fetched from a platform connector."""

    def __init__(
        self,
        content: str,
        source_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.content = content
        self.source_id = source_id
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "source_id": self.source_id,
            "metadata": self.metadata,
        }


class BaseConnector(abc.ABC):
    """Abstract connector interface.

    Subclasses must implement fetch_items() to retrieve new data
    from their respective platform.
    """

    @property
    @abc.abstractmethod
    def platform(self) -> str:
        """Return the platform identifier (e.g. 'slack', 'outlook')."""
        ...

    @abc.abstractmethod
    async def fetch_items(
        self,
        access_token: str,
        since: Optional[datetime] = None,
    ) -> List[ConnectorItem]:
        """Fetch items from the platform since the given timestamp.

        Args:
            access_token: Decrypted OAuth/API token.
            since: Only fetch items newer than this. If None, fetch all.

        Returns:
            List of ConnectorItem objects ready for ingestion.
        """
        ...

    @abc.abstractmethod
    async def validate_token(self, access_token: str) -> bool:
        """Check whether the given token is still valid."""
        ...
