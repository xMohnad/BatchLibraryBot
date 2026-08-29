from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import IndexModel


class Session(Document):
    """Refresh-token session for a user."""

    userId: PydanticObjectId
    """Owner user ID."""

    refreshTokenHash: str
    """Hashed refresh token."""

    userAgent: str | None = None
    """Client user-agent."""

    ip: str | None = None
    """Client IP address."""

    createdAt: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Creation time (UTC)."""

    expiresAt: datetime
    """Expiration time (UTC)."""

    revoked: bool = False
    """Whether the session is revoked."""

    replacedBy: PydanticObjectId | None = None
    """Next session ID after rotation (for reuse detection)."""

    class Settings:
        name = "sessions"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("userId", 1)]),
            IndexModel([("refreshTokenHash", 1)], unique=True),
            IndexModel([("expiresAt", 1)], expireAfterSeconds=0),
        ]

    @classmethod
    async def revoke_all_for_user(cls, user_id: PydanticObjectId) -> None:
        cls.find(
            cls.userId == user_id,
            cls.revoked == False,  # noqa: E712
        ).update({"$set": {"revoked": True}})
