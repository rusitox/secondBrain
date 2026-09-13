"""Backfill: transcribe historical Slack audio messages and ingest them.

The normal sync is incremental (since=last_sync_at), so audio messages sent
before this feature existed were never transcribed. This re-crawls the full
Slack history (since=None) for every Slack integration, but only ingests the
messages that carry an audio attachment — text-only messages already synced
are left untouched.

Usage:
    python scripts/backfill_slack_audio.py            # dry run: count only, no Whisper cost
    python scripts/backfill_slack_audio.py --ingest    # transcribe for real and store
"""
import argparse
import asyncio
import sys
from typing import Optional

sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select

from app.api.schemas.voice import TranscribeResponse
from app.core.config import get_settings
from app.core.database import get_session_factory
from app.models.integration import Integration, Platform
from app.services import integration_service
from app.services.connectors.slack import SlackConnector
from app.services.ingestion.embedder import Embedder
from app.services.ingestion.pipeline import IngestionPipeline
from app.services.voice.transcriber import WhisperTranscriber


class _CountingTranscriber(WhisperTranscriber):
    """Dry-run stand-in: downloads still happen (free), Whisper never gets called."""

    def __init__(self) -> None:
        super().__init__(mode="api", model_name="base", openai_api_key="")
        self.count = 0

    async def transcribe(
        self, audio_bytes: bytes, filename: str = "audio.webm", language: Optional[str] = None,
    ) -> TranscribeResponse:
        self.count += 1
        return TranscribeResponse(transcript="[dry-run: not transcribed]", language="", duration_seconds=None)


async def main(do_ingest: bool) -> None:
    settings = get_settings()
    session_factory = get_session_factory()

    async with session_factory() as db:
        result = await db.execute(select(Integration).where(Integration.platform == Platform.SLACK))
        integrations = result.scalars().all()
        if not integrations:
            print("No Slack integration found.")
            return

        for integration in integrations:
            token = integration_service.get_decrypted_token(integration)
            user_token = integration_service.get_decrypted_user_token(integration)

            counting = None if do_ingest else _CountingTranscriber()
            connector = SlackConnector(transcriber=counting)

            print(
                f"Fetching full Slack history for user {integration.user_id} "
                f"({'transcribing for real' if do_ingest else 'dry run, no Whisper cost'})..."
            )
            fetch_kwargs = {"access_token": token, "since": None}
            if user_token:
                fetch_kwargs["user_token"] = user_token
            items = await connector.fetch_items(**fetch_kwargs)

            audio_items = [item for item in items if item.metadata.get("has_audio")]
            print(f"  {len(items)} total messages, {len(audio_items)} with an audio transcript")

            if not do_ingest:
                continue
            if not audio_items:
                continue

            pipeline = IngestionPipeline(embedder=Embedder(api_key=settings.openai_api_key))
            ingest_result = await pipeline.ingest_batch(
                db=db,
                user_id=integration.user_id,
                items=[item.to_dict() for item in audio_items],
                source="slack",
            )
            await db.commit()
            print(
                f"  ingested: created={ingest_result.documents_created} "
                f"updated={ingest_result.documents_updated} skipped={ingest_result.documents_skipped}"
            )

    if do_ingest:
        print("Done.")
    else:
        print("Dry run complete — re-run with --ingest to transcribe and store these for real.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ingest", action="store_true",
        help="Actually transcribe (real Whisper API cost) and store the results.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.ingest))
