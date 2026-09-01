"""Microsoft Graph connector for Outlook emails, calendar events, and Teams chat.

Uses OAuth2 with Microsoft Graph API v1.0. Handles pagination and
token refresh for long-running syncs.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.services.connectors.base import BaseConnector, ConnectorItem

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
DEFAULT_PAGE_SIZE = 50
MAX_PAGES = 100  # Safety limit to prevent infinite pagination loops
REQUEST_TIMEOUT = 30.0


class MSGraphConnector(BaseConnector):
    """Connector for Microsoft Graph (Outlook + Teams)."""

    @property
    def platform(self) -> str:
        return "outlook"

    async def fetch_items(
        self,
        access_token: str,
        since: Optional[datetime] = None,
    ) -> List[ConnectorItem]:
        """Fetch emails and calendar events from Microsoft Graph."""
        items: List[ConnectorItem] = []
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            headers = {"Authorization": f"Bearer {access_token}"}

            # Fetch emails
            emails = await self._fetch_emails(client, headers, since)
            items.extend(emails)

            # Fetch calendar events
            events = await self._fetch_calendar_events(client, headers, since)
            items.extend(events)

        logger.info("MSGraph: fetched %d items (emails + events)", len(items))
        return items

    async def validate_token(self, access_token: str) -> bool:
        """Check token validity against /me endpoint."""
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.get(
                    f"{GRAPH_BASE_URL}/me",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def _fetch_emails(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        since: Optional[datetime],
    ) -> List[ConnectorItem]:
        """Fetch emails with pagination.

        Requests plain-text body to avoid large HTML payloads.
        On first sync (no `since`), limits to last 6 months.
        """
        items: List[ConnectorItem] = []
        url = f"{GRAPH_BASE_URL}/me/messages"

        # Default to 6 months ago if no since date (avoid pulling all history)
        effective_since = since or (
            datetime.now(timezone.utc) - timedelta(days=180)
        )

        params: Dict[str, Any] = {
            "$top": DEFAULT_PAGE_SIZE,
            "$select": "id,subject,body,from,receivedDateTime",
            "$orderby": "receivedDateTime desc",
            "$filter": f"receivedDateTime ge {effective_since.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        }

        # Request plain text body to avoid large HTML payloads
        email_headers = {**headers, "Prefer": 'outlook.body-content-type="text"'}

        for _ in range(MAX_PAGES):
            if not url:
                break
            resp = await client.get(url, headers=email_headers, params=params)
            resp.raise_for_status()
            data = resp.json()

            for msg in data.get("value", []):
                body_content = (msg.get("body") or {}).get("content", "")
                from_addr = (
                    (msg.get("from") or {})
                    .get("emailAddress", {})
                    .get("address", "")
                )
                subject = msg.get("subject", "")

                items.append(ConnectorItem(
                    content=f"Subject: {subject}\n\n{body_content}",
                    source_id=msg["id"],
                    metadata={
                        "author": from_addr,
                        "subject": subject,
                        "timestamp": msg.get("receivedDateTime", ""),
                        "type": "email",
                    },
                ))

            # Next page
            url = data.get("@odata.nextLink")
            params = {}  # nextLink includes params

        return items

    async def _fetch_calendar_events(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        since: Optional[datetime],
    ) -> List[ConnectorItem]:
        """Fetch calendar events with pagination."""
        items: List[ConnectorItem] = []
        url = f"{GRAPH_BASE_URL}/me/events"
        params: Dict[str, Any] = {
            "$top": DEFAULT_PAGE_SIZE,
            "$select": "id,subject,body,start,end,organizer,attendees",
            "$orderby": "start/dateTime desc",
        }
        if since:
            params["$filter"] = f"start/dateTime ge '{since.isoformat()}'"

        for _ in range(MAX_PAGES):
            if not url:
                break
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

            for event in data.get("value", []):
                body_content = (event.get("body") or {}).get("content", "")
                subject = event.get("subject", "")
                organizer = (
                    (event.get("organizer") or {})
                    .get("emailAddress", {})
                    .get("address", "")
                )
                attendees = [
                    a.get("emailAddress", {}).get("address", "")
                    for a in event.get("attendees", [])
                ]
                start_time = event.get("start", {}).get("dateTime", "")

                items.append(ConnectorItem(
                    content=f"Meeting: {subject}\n\n{body_content}",
                    source_id=event["id"],
                    metadata={
                        "author": organizer,
                        "subject": subject,
                        "timestamp": start_time,
                        "type": "calendar_event",
                        "attendees": attendees,
                    },
                ))

            url = data.get("@odata.nextLink")
            params = {}

        return items
