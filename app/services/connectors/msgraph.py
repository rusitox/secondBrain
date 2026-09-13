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
        **kwargs: Any,
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

        params: Optional[Dict[str, Any]] = {
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

            # Next page — passing params=None (not {}) is required here:
            # httpx.get(url_with_query, params={}) REPLACES the URL's
            # existing query string with the (empty) params dict, which
            # silently discarded @odata.nextLink's pagination cursor on
            # every page past the first. params=None leaves the URL's own
            # query string (already complete) untouched.
            url = data.get("@odata.nextLink")
            params = None

        return items

    # How far back/forward calendarView's sliding window reaches on every
    # sync — see _fetch_calendar_events's docstring for why this replaces
    # an open-ended, `since`-based fetch for calendar events specifically.
    _CALENDAR_VIEW_DAYS_BACK = 7
    _CALENDAR_VIEW_DAYS_FORWARD = 90

    async def _fetch_calendar_events(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        since: Optional[datetime],
    ) -> List[ConnectorItem]:
        """Fetch calendar events (as actual dated occurrences) with pagination.

        Uses /me/calendarView, NOT /me/events — /events with a
        `start/dateTime` filter only matches an event whose OWN start
        falls in range. For a RECURRING event, that "own start" is the
        series' very first occurrence ever, not whichever occurrence
        actually lands on the date being asked about — so a question like
        "what meetings do I have tomorrow" silently never saw recurring
        meetings at all, no matter how far back the sync history went.
        /me/calendarView expands recurring series into real per-day
        occurrences, each with its own id and start time, which is what a
        calendar tool actually needs.

        calendarView requires an explicit end bound (no open-ended future
        the way /events allowed) — so `since` is ignored here in favor of
        a fixed sliding window (days back/forward from now) run on every
        sync. That's the right model for a calendar: "what's near-term
        right now" rather than an incremental append-only cursor. Anything
        further out than the forward window simply gets captured once a
        later sync's window reaches it.
        """
        items: List[ConnectorItem] = []
        url = f"{GRAPH_BASE_URL}/me/calendarView"
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=self._CALENDAR_VIEW_DAYS_BACK)
        window_end = now + timedelta(days=self._CALENDAR_VIEW_DAYS_FORWARD)
        params: Optional[Dict[str, Any]] = {
            "$top": DEFAULT_PAGE_SIZE,
            "$select": "id,subject,body,start,end,organizer,attendees,isCancelled",
            "$orderby": "start/dateTime",
            "startDateTime": window_start.strftime("%Y-%m-%dT%H:%M:%S"),
            "endDateTime": window_end.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        # Request UTC times so dateTime values always include timezone info ("Z" suffix)
        # and are unambiguously comparable with datetime.now(timezone.utc).
        calendar_headers = {**headers, "Prefer": 'outlook.timezone="UTC"'}

        for _ in range(MAX_PAGES):
            if not url:
                break
            resp = await client.get(url, headers=calendar_headers, params=params)
            resp.raise_for_status()
            data = resp.json()

            for event in data.get("value", []):
                if event.get("isCancelled"):
                    continue

                body_content = (event.get("body") or {}).get("content", "")
                # Some occurrences (e.g. private/restricted-detail events)
                # have subject explicitly null, not merely absent — `.get`'s
                # default only covers the latter.
                subject = event.get("subject") or ""
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

            # See _fetch_emails's matching comment — params=None (not {})
            # is required so httpx doesn't overwrite @odata.nextLink's own
            # query string, which for calendarView specifically includes
            # the *required* startDateTime/endDateTime bounds. Losing them
            # past page 1 turned every paginated calendar sync into a 400.
            url = data.get("@odata.nextLink")
            params = None

        return items
