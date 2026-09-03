"""Incremental Fathom sync via MCP.

Fathom has no public REST API (api.fathom.video is NXDOMAIN).
This script bridges the gap between Claude Code's Fathom MCP access
and the secondBrain ingestion pipeline.

Modes:
  --check   Print last_sync_at from DB so the caller knows which
            meetings to fetch (ISO 8601 UTC, or "NEVER" if none).

  --ingest  Read a JSON array of meetings from stdin and ingest them
            into the DB, then update last_sync_at and sync status.

Workflow (run from a Claude Code session):
  1. python scripts/sync_fathom_incremental.py --check
     → e.g. "2026-09-01T22:00:00Z"

  2. Claude calls list_meetings(created_after=<date>) via Fathom MCP,
     fetches transcripts, and builds a JSON array:
     [{"source_id":"123","date":"2026-09-01","title":"...","content":"..."}]

  3. echo '[{...}]' | python scripts/sync_fathom_incremental.py --ingest
     → ingests each meeting, updates last_sync_at to the latest
       successfully ingested meeting date.

NOTE: USER_ID is hardcoded for a single-user self-hosted deployment.
      Update it if the user UUID changes (e.g. after a DB wipe).
"""
import asyncio
import json
import logging
import os
import pathlib
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Suppress SQLAlchemy echo before engine is created.
# DEBUG=false must be set before load_dotenv so .env cannot override it.
os.environ["DEBUG"] = "false"
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

# Anchor sys.path to the repo root regardless of cwd.
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=False)  # override=False: don't overwrite DEBUG=false above

from app.core.database import get_session_factory
from app.core.config import get_settings
from app.services.ingestion.pipeline import IngestionPipeline
from app.services.ingestion.embedder import Embedder
from sqlalchemy import select
from app.models.integration import Integration

USER_ID = uuid.UUID("889ff4f4-b782-4e9f-bfb1-e310ae132827")
PLATFORM = "fathom"


async def _get_fathom_integration(db) -> Optional[Integration]:
    result = await db.execute(
        select(Integration).where(
            Integration.user_id == USER_ID,
            Integration.platform == PLATFORM,
        )
    )
    return result.scalar_one_or_none()


async def check_mode() -> None:
    """Print last sync date so the caller knows which meetings to fetch."""
    sf = get_session_factory()
    async with sf() as db:
        integ = await _get_fathom_integration(db)
        if not integ:
            print("NO_INTEGRATION")
            return
        if integ.last_sync_at:
            dt = integ.last_sync_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            print(dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
        else:
            print("NEVER")


async def ingest_mode(meetings: List[Dict[str, Any]]) -> None:
    """Ingest a list of meetings and update the integration record."""
    if not meetings:
        print("No meetings to ingest.")
        return

    settings = get_settings()

    # Wire in commitment detection when an LLM API key is available,
    # matching the behaviour of the server-side ingestion pipeline.
    commitment_detector = None
    if settings.llm_api_key:
        from app.services.llm.claude_client import ClaudeClient
        from app.services.commitments.detector import CommitmentDetector
        commitment_detector = CommitmentDetector(
            ClaudeClient(api_key=settings.llm_api_key, model=settings.llm_model)
        )

    pipeline = IngestionPipeline(
        embedder=Embedder(api_key=settings.openai_api_key),
        commitment_detector=commitment_detector,
    )

    errors: List[str] = []
    # Track the latest date among successfully ingested meetings so we only
    # advance last_sync_at when data was actually persisted. Advancing to
    # now() on a partial failure would permanently skip the failed meetings.
    last_success_dt: Optional[datetime] = None

    sf = get_session_factory()
    async with sf() as db:
        # Load integration once; reuse the same ORM object for the status update.
        integ = await _get_fathom_integration(db)

        for m in meetings:
            source_id = m.get("source_id")
            if not source_id:
                errors.append(f"Meeting missing source_id: {m}")
                print(f"  SKIP — missing source_id: {m}")
                continue
            source_id = str(source_id)

            title = m.get("title", "Untitled Meeting")
            date_str = m.get("date", "")
            content = m.get("content", "")

            if not content:
                print(f"  SKIP {source_id} — no content")
                continue

            try:
                result = await pipeline.ingest_raw(
                    db=db,
                    user_id=USER_ID,
                    content=content,
                    source=PLATFORM,
                    source_id=source_id,
                    metadata={
                        "title": title,
                        "date": date_str,
                        "recording_url": f"https://fathom.video/calls/{source_id}",
                    },
                )
                print(
                    f"  {source_id} — created={result.documents_created} "
                    f"updated={result.documents_updated} — {title[:60]}"
                )

                # Advance cursor to the latest successfully ingested meeting date.
                if date_str:
                    try:
                        meeting_dt = datetime.fromisoformat(date_str).replace(
                            tzinfo=timezone.utc
                        )
                        if last_success_dt is None or meeting_dt > last_success_dt:
                            last_success_dt = meeting_dt
                    except ValueError:
                        pass  # unparseable date — still ingested, just can't advance cursor

            except Exception as e:
                errors.append(f"{source_id}: {e}")
                print(f"  ERROR {source_id}: {e}")

        # Update the integration record within the same session so the
        # commit below persists both the documents and the status atomically.
        if integ:
            if last_success_dt is not None:
                integ.last_sync_at = last_success_dt
            integ.last_sync_status = "error" if errors else "success"
            integ.last_sync_error = "; ".join(errors)[:500] if errors else None

        await db.commit()

    total_created = 0  # pipeline doesn't aggregate; already printed per-meeting
    print(f"\nDone. meetings_processed={len(meetings)} errors={len(errors)}")
    if errors:
        for e in errors:
            print(f"  - {e}")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "--check":
        asyncio.run(check_mode())

    elif mode == "--ingest":
        raw = sys.stdin.read().strip()
        if not raw:
            print(
                "Error: no data on stdin. Pipe a JSON array of meetings.",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            meetings = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON — {e}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(meetings, list):
            print(
                f"Error: expected a JSON array, got {type(meetings).__name__}",
                file=sys.stderr,
            )
            sys.exit(1)
        asyncio.run(ingest_mode(meetings))

    else:
        print(f"Unknown mode: {mode}. Use --check or --ingest.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
