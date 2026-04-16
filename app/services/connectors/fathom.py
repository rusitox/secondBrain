"""Fathom connector for meeting transcripts.

Supports fetching transcripts via Fathom API or processing
exported text files.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from app.services.connectors.base import BaseConnector, ConnectorItem

logger = logging.getLogger(__name__)

FATHOM_API_URL = "https://api.fathom.video/v1"
REQUEST_TIMEOUT = 30.0


class FathomConnector(BaseConnector):
    """Connector for Fathom meeting transcripts."""

    @property
    def platform(self) -> str:
        return "fathom"

    async def fetch_items(
        self,
        access_token: str,
        since: Optional[datetime] = None,
    ) -> List[ConnectorItem]:
        """Fetch meeting transcripts from Fathom API."""
        items: List[ConnectorItem] = []
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            recordings = await self._list_recordings(client, headers, since)
            for recording in recordings:
                transcript = await self._get_transcript(
                    client, headers, recording["id"],
                )
                if transcript:
                    title = recording.get("title", "Untitled Meeting")
                    items.append(ConnectorItem(
                        content=f"Meeting: {title}\n\n{transcript}",
                        source_id=recording["id"],
                        metadata={
                            "title": title,
                            "timestamp": recording.get("created_at", ""),
                            "duration": recording.get("duration", 0),
                            "participants": recording.get("participants", []),
                            "type": "transcript",
                        },
                    ))

        logger.info("Fathom: fetched %d transcripts", len(items))
        return items

    async def validate_token(self, access_token: str) -> bool:
        """Check token validity against Fathom API."""
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.get(
                    f"{FATHOM_API_URL}/user",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def _list_recordings(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        since: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        """List recordings, optionally filtered by date."""
        params: Dict[str, Any] = {}
        if since:
            params["created_after"] = since.isoformat()

        resp = await client.get(
            f"{FATHOM_API_URL}/recordings",
            headers=headers,
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("recordings", data if isinstance(data, list) else [])

    async def _get_transcript(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        recording_id: str,
    ) -> Optional[str]:
        """Fetch the transcript text for a recording."""
        try:
            resp = await client.get(
                f"{FATHOM_API_URL}/recordings/{recording_id}/transcript",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            # Transcript could be a string or structured object
            if isinstance(data, str):
                return data
            return data.get("text", data.get("transcript", ""))
        except httpx.HTTPError as e:
            logger.warning("Failed to fetch transcript for %s: %s", recording_id, e)
            return None
