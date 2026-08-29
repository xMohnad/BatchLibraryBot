"""Promote an existing (already-registered) user to admin."""

from __future__ import annotations

import argparse
import asyncio


async def _run(username: str, *, demote: bool) -> None:
    from database import client, init_database
    from database.models.user import Role, User

    await init_database()
    try:
        user = await User.get_by_username(username)
        if user is None:
            print(f"No user found with username '{username}'.")
            return

        user.role = Role.USER if demote else Role.ADMIN
        await user.save()
        print(f"'{user.username}' is now {user.role}.")
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("username", help="Username of the already-registered account to promote.")
    parser.add_argument("--demote", action="store_true", help="Demote back to a regular user instead of promoting.")
    args = parser.parse_args()

    asyncio.run(_run(args.username, demote=args.demote))


if __name__ == "__main__":
    main()
