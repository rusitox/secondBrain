"""Alert manager — queues and displays proactive notifications during chat."""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

from cli.display import console, print_panel
from cli.prompts import PLATFORM_NAMES

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    """A single alert to be shown to the user."""

    alert_type: str  # "sync", "commitment"
    platform: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


class AlertManager:
    """Manages a queue of pending alerts shown between user inputs."""

    def __init__(self) -> None:
        self._pending = []  # type: List[Alert]

    @property
    def has_pending(self) -> bool:
        return len(self._pending) > 0

    def on_sync_result(self, platform: str, result: Dict[str, Any]) -> None:
        """Called by BackgroundSync when a sync produces results."""
        docs = result.get("documents_created", 0)
        updated = result.get("documents_updated", 0)
        commits = result.get("commitments_detected", 0)
        name = PLATFORM_NAMES.get(platform, platform)

        parts = []
        if docs > 0:
            parts.append("%d new documents" % docs)
        if updated > 0:
            parts.append("%d updated" % updated)
        if commits > 0:
            parts.append("%d new commitments" % commits)

        if parts:
            message = "%s sync: %s" % (name, ", ".join(parts))
            self._pending.append(Alert(
                alert_type="sync",
                platform=platform,
                message=message,
                details=result,
            ))

    def add_alert(self, alert_type: str, platform: str, message: str) -> None:
        """Add a custom alert to the queue."""
        self._pending.append(Alert(
            alert_type=alert_type,
            platform=platform,
            message=message,
        ))

    def show_pending(self) -> None:
        """Display and clear all pending alerts."""
        if not self._pending:
            return

        for alert in self._pending:
            style = "yellow" if alert.alert_type == "commitment" else "cyan"
            title = "Background Sync" if alert.alert_type == "sync" else "Alert"
            print_panel(alert.message, title=title, style=style)

        self._pending.clear()

    def clear(self) -> None:
        """Discard all pending alerts."""
        self._pending.clear()
