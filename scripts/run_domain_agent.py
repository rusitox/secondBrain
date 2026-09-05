"""Manual trigger for a knowledge domain agent (specs/plan-multi-agent-knowledge.md, Phase 1).

Lets you run and inspect a single extraction batch before wiring the agent
to the sync scheduler.

Usage:
    python scripts/run_domain_agent.py --source slack --email mariano@example.com
    python scripts/run_domain_agent.py --source slack --user-id <uuid> --batch-size 10
"""
import argparse
import asyncio
import logging
import os
import pathlib
import sys
import uuid

# Suppress SQLAlchemy echo before the engine is created.
os.environ["DEBUG"] = "false"
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

# Anchor sys.path to the repo root regardless of cwd.
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=False)

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.services.agent.knowledge.domain_agent import REGISTERED_SOURCES, run_domain_agent
from app.services.ingestion.embedder import Embedder
from app.services.user_service import get_user_by_email

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_domain_agent")


async def _resolve_user_id(db, args: argparse.Namespace) -> uuid.UUID:
    if args.user_id:
        return uuid.UUID(args.user_id)
    user = await get_user_by_email(db, args.email)
    if user is None:
        raise SystemExit(f"No user found with email={args.email!r}")
    return user.id


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=REGISTERED_SOURCES)
    parser.add_argument("--user-id", help="User UUID (use this or --email)")
    parser.add_argument("--email", help="User email (looked up to get the UUID)")
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()

    if not args.user_id and not args.email:
        raise SystemExit("Pass either --user-id or --email")

    settings = get_settings()
    embedder = Embedder(api_key=settings.openai_api_key) if settings.openai_api_key else None

    session_factory = get_session_factory()
    async with session_factory() as db:
        user_id = await _resolve_user_id(db, args)
        logger.info("Running %s domain agent for user=%s batch_size=%d", args.source, user_id, args.batch_size)
        result = await run_domain_agent(
            args.source, db, user_id, batch_size=args.batch_size, embedder=embedder,
        )
        await db.commit()
        logger.info("Result: %s", result)


if __name__ == "__main__":
    asyncio.run(main())
