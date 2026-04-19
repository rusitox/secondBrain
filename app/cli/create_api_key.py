"""Bootstrap script to create the first API key for a user.

Usage:
    python -m app.cli.create_api_key --user-id <UUID> --name "initial"

Run this on the server after deployment to generate the first API key.
The key is printed to stdout — copy it and use it with `secondbrain login`.
"""
import argparse
import asyncio
import secrets
import sys
import uuid

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.models.api_key import APIKey
from app.models.user import User


_KEY_PREFIX = "sb_live_"


def _generate_api_key() -> str:
    return _KEY_PREFIX + secrets.token_hex(16)


async def _create_key(user_id: uuid.UUID, name: str) -> None:
    session_factory = get_session_factory()

    async with session_factory() as db:
        # Verify user exists
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            print("ERROR: User {0} not found.".format(user_id), file=sys.stderr)
            sys.exit(1)

        # Generate key
        plaintext = _generate_api_key()
        key_hash = bcrypt.hashpw(
            plaintext.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        api_key = APIKey(
            user_id=user_id,
            key_hash=key_hash,
            key_prefix=plaintext[:12],
            name=name,
        )
        db.add(api_key)
        await db.commit()

        print("API key created for user: {0} ({1})".format(user.full_name, user.email))
        print("Key name: {0}".format(name))
        print("")
        print("Your API key (save it — it will not be shown again):")
        print("")
        print("  {0}".format(plaintext))
        print("")
        print("Use it with: secondbrain login")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an API key for a user")
    parser.add_argument(
        "--user-id",
        required=True,
        help="UUID of the user to create the key for",
    )
    parser.add_argument(
        "--name",
        default="initial",
        help="Human-readable name for the key (default: initial)",
    )
    args = parser.parse_args()

    try:
        user_id = uuid.UUID(args.user_id)
    except ValueError:
        print("ERROR: Invalid UUID: {0}".format(args.user_id), file=sys.stderr)
        sys.exit(1)

    asyncio.run(_create_key(user_id, args.name))


if __name__ == "__main__":
    main()
