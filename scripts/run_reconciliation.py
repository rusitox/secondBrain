"""Manual trigger for the reconciliation engine (specs/plan-multi-agent-knowledge.md, Phase 4).

Not wired to the live sync scheduler yet — see run_reconciliation's
docstring for why. Run this after a batch of domain agents (scripts/
run_domain_agent.py) to reconcile whatever they extracted.

Usage:
    python scripts/run_reconciliation.py --email mariano@example.com
    python scripts/run_reconciliation.py --user-id <uuid> --entity-type person
"""
import argparse
import asyncio
import logging
import os
import pathlib
import sys
import uuid

os.environ["DEBUG"] = "false"
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=False)

from sqlalchemy import select

from app.core.database import get_session_factory
from app.models.entity import EntityType
from app.models.user import User
from app.services.agent.knowledge.reconciliation import run_reconciliation

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_reconciliation")


async def _resolve_user_id(db, args: argparse.Namespace) -> uuid.UUID:
    if args.user_id:
        return uuid.UUID(args.user_id)
    result = await db.execute(select(User).where(User.email == args.email))
    user = result.scalar_one_or_none()
    if user is None:
        raise SystemExit(f"No user found with email={args.email!r}")
    return user.id


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", help="User UUID (use this or --email)")
    parser.add_argument("--email", help="User email (looked up to get the UUID)")
    parser.add_argument(
        "--entity-type", choices=[t.value for t in EntityType],
        help="Limit to one entity type (default: all)",
    )
    args = parser.parse_args()

    if not args.user_id and not args.email:
        raise SystemExit("Pass either --user-id or --email")

    session_factory = get_session_factory()
    async with session_factory() as db:
        user_id = await _resolve_user_id(db, args)
        entity_type = EntityType(args.entity_type) if args.entity_type else None
        logger.info("Running reconciliation for user=%s entity_type=%s", user_id, args.entity_type)
        result = await run_reconciliation(db, user_id, entity_type=entity_type)
        await db.commit()
        logger.info("Result: %s", result)


if __name__ == "__main__":
    asyncio.run(main())
