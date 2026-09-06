"""Manual trigger for the I+D platform domain agent (specs/plan-multi-agent-knowledge.md, Phase 6).

Unlike scripts/run_domain_agent.py, this agent has no batch size — it
queries the I+D platform's MCP server for current state each run rather than
draining a queue of unprocessed documents.

Usage:
    python scripts/run_rd_domain_agent.py --email mariano@example.com
    python scripts/run_rd_domain_agent.py --user-id <uuid>

Requires id_brain_mcp_url / id_brain_mcp_api_key set in .env — the script
exits early with a clear message if they're missing.
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
from app.services.agent.knowledge.rd_agent import run_rd_domain_agent
from app.services.ingestion.embedder import Embedder
from app.services.user_service import get_user_by_email

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_rd_domain_agent")


async def _resolve_user_id(db, args: argparse.Namespace) -> uuid.UUID:
    if args.user_id:
        return uuid.UUID(args.user_id)
    user = await get_user_by_email(db, args.email)
    if user is None:
        raise SystemExit(f"No user found with email={args.email!r}")
    return user.id


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", help="User UUID (use this or --email)")
    parser.add_argument("--email", help="User email (looked up to get the UUID)")
    args = parser.parse_args()

    if not args.user_id and not args.email:
        raise SystemExit("Pass either --user-id or --email")

    settings = get_settings()
    if not settings.id_brain_mcp_url:
        raise SystemExit("id_brain_mcp_url is not set — add it (and id_brain_mcp_api_key) to .env first")
    embedder = Embedder(api_key=settings.openai_api_key) if settings.openai_api_key else None

    session_factory = get_session_factory()
    async with session_factory() as db:
        user_id = await _resolve_user_id(db, args)
        logger.info("Running rd domain agent for user=%s", user_id)
        result = await run_rd_domain_agent(db, user_id, embedder=embedder)
        await db.commit()
        logger.info("Result: %s", result)


if __name__ == "__main__":
    asyncio.run(main())
