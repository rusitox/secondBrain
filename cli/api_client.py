"""API client — async httpx wrapper for the FastAPI backend."""
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Timeouts: 30s for normal ops, 120s for agent queries, 300s for sync operations
_DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_AGENT_TIMEOUT = httpx.Timeout(120.0, connect=10.0)
_SYNC_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


class APIError(Exception):
    """Raised when an API call fails."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class APIClient:
    """Async HTTP client for the secondBrain API."""

    def __init__(
        self,
        server_url: str,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self._base_url = server_url.rstrip("/")
        self._user_id = user_id
        self._api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None

    def set_user_id(self, user_id: str) -> None:
        """Set the user ID for authenticated requests."""
        self._user_id = user_id

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> Dict[str, str]:
        """Build request headers."""
        headers: Dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = "Bearer %s" % self._api_key
        elif self._user_id:
            headers["X-User-Id"] = self._user_id
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[httpx.Timeout] = None,
    ) -> Dict[str, Any]:
        """Make an HTTP request and return JSON response."""
        url = self._base_url + path
        client = self._get_client()
        resp = await client.request(
            method=method,
            url=url,
            json=json,
            params=params,
            headers=self._headers(),
            timeout=timeout or _DEFAULT_TIMEOUT,
        )

        if resp.status_code == 204:
            return {}

        try:
            data = resp.json()
        except ValueError:
            data = {"detail": resp.text}

        if resp.status_code >= 400:
            detail = data.get("detail", str(data)) if isinstance(data, dict) else str(data)
            raise APIError(resp.status_code, detail)

        return data

    # --- Health ---

    async def health_check(self) -> bool:
        """Check if the backend is reachable."""
        try:
            await self._request("GET", "/")
            return True
        except (httpx.ConnectError, httpx.TimeoutException, APIError):
            return False

    # --- Users ---

    async def get_me(self) -> Dict[str, Any]:
        """Get the currently authenticated user's profile."""
        return await self._request("GET", "/users/me")

    async def create_user(
        self, email: str, full_name: str, timezone: str = "UTC"
    ) -> Dict[str, Any]:
        """Create a new user."""
        return await self._request("POST", "/users/", json={
            "email": email,
            "full_name": full_name,
            "timezone": timezone,
        })

    async def get_user(self, user_id: str) -> Dict[str, Any]:
        """Get user by ID."""
        return await self._request("GET", f"/users/{user_id}")

    async def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        """Get user statistics."""
        return await self._request("GET", f"/users/{user_id}/stats")

    # --- Identity ---

    async def create_identity(
        self,
        user_id: str,
        persona_description: str = "",
        tone_guidelines: str = "",
        heuristics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create user identity."""
        return await self._request("POST", f"/users/{user_id}/identity", json={
            "persona_description": persona_description,
            "tone_guidelines": tone_guidelines,
            "heuristics": heuristics or {},
        })

    async def get_identity(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user identity, returns None if not found."""
        try:
            return await self._request("GET", f"/users/{user_id}/identity")
        except APIError as e:
            if e.status_code == 404:
                return None
            raise

    async def update_identity(
        self, user_id: str, **fields: Any
    ) -> Dict[str, Any]:
        """Update user identity (partial)."""
        return await self._request("PATCH", f"/users/{user_id}/identity", json=fields)

    # --- Integrations ---

    async def create_integration(
        self,
        user_id: str,
        platform: str,
        access_token: str,
        refresh_token: str = "",
    ) -> Dict[str, Any]:
        """Create a new integration."""
        return await self._request("POST", "/integrations/", json={
            "user_id": user_id,
            "platform": platform,
            "access_token": access_token,
            "refresh_token": refresh_token,
        })

    async def list_integrations(self, platform: Optional[str] = None) -> List[Dict[str, Any]]:
        """List user's integrations."""
        params = {}
        if platform:
            params["platform"] = platform
        result = await self._request("GET", "/integrations/", params=params)
        return result if isinstance(result, list) else []

    async def delete_integration(self, integration_id: str) -> None:
        """Delete an integration."""
        await self._request("DELETE", f"/integrations/{integration_id}")

    async def set_integration_user_token(
        self, integration_id: str, user_token: str
    ) -> None:
        """Store a User Token on an existing integration (Slack DM access)."""
        await self._request(
            "POST",
            f"/integrations/{integration_id}/user-token",
            json={"user_token": user_token},
        )

    # --- Ingestion ---

    async def sync_platform(self, platform: str) -> Dict[str, Any]:
        """Trigger a sync for a platform."""
        return await self._request(
            "POST", f"/ingest/sync/{platform}", timeout=_SYNC_TIMEOUT
        )

    async def ingest_raw(
        self,
        content: str,
        source: str,
        source_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Ingest raw text."""
        return await self._request("POST", "/ingest/raw", json={
            "content": content,
            "source": source,
            "source_id": source_id,
            "metadata_": metadata or {},
        })

    # --- Query ---

    async def query(self, question: str, **kwargs: Any) -> Dict[str, Any]:
        """RAG query."""
        payload: Dict[str, Any] = {"question": question}
        payload.update(kwargs)
        return await self._request("POST", "/query", json=payload)

    async def agent_query(
        self, question: str, session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Agentic multi-tool query."""
        payload: Dict[str, Any] = {"question": question}
        if session_id is not None:
            payload["session_id"] = session_id
        return await self._request("POST", "/agent/query", json=payload, timeout=_AGENT_TIMEOUT)

    # --- Briefing ---

    async def get_briefing(self, user_id: str) -> Dict[str, Any]:
        """Generate a daily briefing."""
        return await self._request("GET", f"/briefing/{user_id}")

    async def schedule_briefing(
        self,
        user_id: str,
        hour: int = 7,
        minute: int = 0,
        timezone: str = "UTC",
    ) -> Dict[str, Any]:
        """Schedule a daily briefing."""
        return await self._request("POST", f"/briefing/{user_id}/schedule", json={
            "hour": hour,
            "minute": minute,
            "timezone": timezone,
        })

    # --- Commitments ---

    async def list_commitments(
        self, filter_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List commitments. filter_type: 'pending', 'overdue', or None for all."""
        if filter_type in ("pending", "overdue"):
            path = f"/commitments/filter/{filter_type}"
        else:
            path = "/commitments/"
        result = await self._request("GET", path)
        return result if isinstance(result, list) else []

    async def update_commitment(
        self, commitment_id: str, **fields: Any
    ) -> Dict[str, Any]:
        """Update a commitment (e.g., status change)."""
        return await self._request("PATCH", f"/commitments/{commitment_id}", json=fields)

    async def delete_commitment(self, commitment_id: str) -> None:
        """Delete a commitment."""
        await self._request("DELETE", f"/commitments/{commitment_id}")

    # --- Preferences / Onboarding / Notion Config ---

    async def get_preferences(self) -> Dict[str, Any]:
        """Get full preferences, onboarding state, and Notion config."""
        return await self._request("GET", "/users/me/preferences")

    async def update_preferences(self, prefs: Dict[str, Any]) -> Dict[str, Any]:
        """Merge keys into server-side preferences."""
        return await self._request("PATCH", "/users/me/preferences", json={
            "preferences": prefs,
        })

    async def get_onboarding(self) -> Dict[str, Any]:
        """Get onboarding step and completed status."""
        return await self._request("GET", "/users/me/onboarding")

    async def update_onboarding(
        self,
        step: Optional[int] = None,
        completed: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Update onboarding step and/or completed flag."""
        payload: Dict[str, Any] = {}
        if step is not None:
            payload["step"] = step
        if completed is not None:
            payload["completed"] = completed
        return await self._request("PATCH", "/users/me/onboarding", json=payload)

    async def get_notion_config(self) -> Dict[str, Any]:
        """Get Notion workspace config from server."""
        return await self._request("GET", "/users/me/notion-config")

    async def update_notion_config(
        self, config: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Replace Notion config on server."""
        return await self._request("PUT", "/users/me/notion-config", json={
            "config": config,
        })

    # --- Notion ---

    async def sync_notion_commitments(
        self, workspace_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Bidirectional sync of commitments with Notion."""
        return await self._request(
            "POST", "/ingest/notion/sync-commitments",
            json={"workspace_config": workspace_config},
            timeout=_SYNC_TIMEOUT,
        )

    async def publish_briefing_to_notion(
        self,
        workspace_config: Dict[str, Any],
        briefing_text: str,
        date: str = "",
    ) -> Dict[str, Any]:
        """Publish a briefing to Notion."""
        return await self._request(
            "POST", "/ingest/notion/publish-briefing",
            json={
                "workspace_config": workspace_config,
                "briefing_text": briefing_text,
                "date": date,
            },
            timeout=_SYNC_TIMEOUT,
        )

    async def publish_digest_to_notion(
        self,
        workspace_config: Dict[str, Any],
        week_start: str = "",
        week_end: str = "",
    ) -> Dict[str, Any]:
        """Generate and publish a weekly digest to Notion."""
        return await self._request(
            "POST", "/ingest/notion/publish-digest",
            json={
                "workspace_config": workspace_config,
                "week_start": week_start,
                "week_end": week_end,
            },
            timeout=_SYNC_TIMEOUT,
        )

    async def publish_meeting_prep_to_notion(
        self,
        workspace_config: Dict[str, Any],
        title: str,
        prep_text: str,
        date: str = "",
    ) -> Dict[str, Any]:
        """Publish meeting prep to Notion."""
        return await self._request(
            "POST", "/ingest/notion/publish-meeting-prep",
            json={
                "workspace_config": workspace_config,
                "title": title,
                "prep_text": prep_text,
                "date": date,
            },
            timeout=_SYNC_TIMEOUT,
        )
