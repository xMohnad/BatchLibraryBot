from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import IndexModel

from database.models.mixins import TimestampMixin


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
