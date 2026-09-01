from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import ClassVar

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import IndexModel

from config import (
    REGISTRATION_CODE_RESEND_COOLDOWN_SECONDS,
    REGISTRATION_CODE_TTL_MINUTES,
)
from core.mixins import TimestampMixin
from core.security import generate_registration_code, hash_code


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"


class CoursePermission(BaseModel):
    """Grants a USER the ability to add and/or edit material for one specific course."""

    courseId: PydanticObjectId
    """Target course ID."""

    canAdd: bool = False
    """Allow adding new files."""

    canEdit: bool = False
    """Allow editing/deleting course content."""


class User(TimestampMixin, Document):
    """A registered, Telegram-verified account with a website username/password."""

    username: str
    """Unique login username (stored lowercase)."""

    passwordHash: str
    """Hashed password."""

    fullName: str
    """User full name."""

    gender: Gender
    """User gender."""

    telegramId: int
    """Unique Telegram user ID."""

    telegramUsername: str | None = None
    """Telegram @username."""

    role: Role = Role.USER
    """User role."""

    permissions: list[CoursePermission] = Field(default_factory=list)
    """Per-course permissions."""

    isActive: bool = True
    """Whether the account is enabled."""

    failedLoginAttempts: int = 0
    """Number of consecutive failed logins."""

    lockedUntil: datetime | None = None
    """Account lock expiration time."""

    class Settings:
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("username", 1)], unique=True),
            IndexModel([("telegramId", 1)], unique=True),
        ]

    @property
    def is_locked(self) -> bool:
        return self.lockedUntil is not None and self.lockedUntil > datetime.now(UTC)

    def permission_for(self, course_id: PydanticObjectId) -> CoursePermission | None:
        return next((p for p in self.permissions if p.courseId == course_id), None)

    def can_add(self, course_id: PydanticObjectId) -> bool:
        if self.role is Role.ADMIN:
            return True
        perm = self.permission_for(course_id)
        return bool(perm and perm.canAdd)

    def can_edit(self, course_id: PydanticObjectId) -> bool:
        if self.role is Role.ADMIN:
            return True
        perm = self.permission_for(course_id)
        return bool(perm and perm.canEdit)

    @classmethod
    async def get_by_username(cls, username: str) -> User | None:
        return await cls.find_one(cls.username == username.strip().lower())

    @classmethod
    async def get_by_telegram_id(cls, telegram_id: int) -> User | None:
        return await cls.find_one(cls.telegramId == telegram_id)


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


class PendingRegistration(Document):
    """Temporary registration record awaiting Telegram verification."""

    token: str
    """Unique, URL-safe token used in the bot deep link."""

    username: str
    """Desired username."""

    passwordHash: str
    """Hashed password."""

    fullName: str
    """User full name."""

    gender: Gender
    """User gender."""

    telegramId: int | None = None
    """Telegram user ID after verification."""

    telegramUsername: str | None = None
    """Telegram @username after verification."""

    codeHash: str | None = None
    """Hashed verification code."""

    codeExpiresAt: datetime | None = None
    """Verification code expiration time."""

    codeAttempts: int = 0
    """Number of entered code attempts."""

    codeSendCount: int = 0
    """Number of times code was sent."""

    lastCodeSentAt: datetime | None = None
    """Last code send timestamp."""

    createdAt: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Creation time (UTC)."""

    expiresAt: datetime
    """Overall expiration time (TTL)."""

    class Settings:
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("token", 1)], unique=True),
            IndexModel([("expiresAt", 1)], expireAfterSeconds=0),
        ]

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.expiresAt

    @property
    def code_is_expired(self) -> bool:
        return self.codeExpiresAt is None or datetime.now(UTC) >= self.codeExpiresAt

    @property
    def is_in_cooldown(self) -> bool:
        """Return True if resend cooldown has not passed yet."""
        return (
            self.lastCodeSentAt is not None
            and (datetime.now(UTC) - self.lastCodeSentAt).total_seconds() < REGISTRATION_CODE_RESEND_COOLDOWN_SECONDS
        )

    def issue_code(self, user_id: int, username: str | None) -> str:
        now = datetime.now(UTC)
        code = generate_registration_code()

        self.telegramId, self.telegramUsername = user_id, username
        self.codeHash = hash_code(code)
        self.codeExpiresAt = now + timedelta(minutes=REGISTRATION_CODE_TTL_MINUTES)
        self.codeAttempts = 0
        self.codeSendCount += 1
        self.lastCodeSentAt = now

        return code
