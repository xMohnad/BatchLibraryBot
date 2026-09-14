from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Self

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, ConfigDict, Field
from pymongo import IndexModel

from accounts.models import User

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aiogram.types import User as TelegramUser

    from courses.models import Course, CourseFile

logger = logging.getLogger(__name__)

type FieldValue = str | int | float | bool | None
"""JSON-primitive type allowed in a logged before/after value."""


class ActionType(StrEnum):
    """The kind of change a logged operation made."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class EntityType(StrEnum):
    """The kind of record a logged operation acted on."""

    COURSE = "course"
    COURSE_FILE = "course_file"
    ACCOUNT = "account"
    PERMISSION = "permission"


class ActorSource(StrEnum):
    """Where a logged operation originated from."""

    WEB = "web"
    TELEGRAM = "telegram"


class Actor(BaseModel):
    """Identifies who performed a logged action."""

    model_config = ConfigDict(frozen=True)

    source: ActorSource
    """Which side of the app the action came from: the web API or a Telegram bot handler."""

    userId: PydanticObjectId | None = None
    """Linked account id, set when the actor is (or matches) a registered `User`."""

    fullName: str | None = None
    """Display name: the account's name, or the raw Telegram name if unregistered."""

    telegramId: int | None = None
    """Telegram user id, when the actor came from (or is linked to) Telegram."""

    telegramUsername: str | None = None
    """Telegram @username, when Telegram supplied one."""

    @classmethod
    def from_user(cls, user: User, *, source: ActorSource = ActorSource.WEB) -> Actor:
        """Build an actor from an authenticated, registered account."""
        return cls(
            source=source,
            userId=user.id,
            fullName=user.fullName,
            telegramId=user.telegramId,
            telegramUsername=user.telegramUsername,
        )

    @classmethod
    async def from_telegram_user(cls, telegram_user: TelegramUser | None) -> Actor:
        """Resolve the Telegram sender of an action into an actor.

        Matches against a registered `User` by Telegram ID when possible, so the
        log links back to the account. Otherwise falls back to the raw Telegram
        identity (full name + Telegram ID/username). Telegram never attaches
        sender info to channel posts, so `telegram_user` may be `None` there -
        that's logged as an unidentifiable actor rather than guessed at.
        """
        if telegram_user is None:
            return cls(source=ActorSource.TELEGRAM, fullName="Unknown (channel post)")

        if user := await User.get_by_telegram_id(telegram_user.id):
            return cls.from_user(user, source=ActorSource.TELEGRAM)

        return cls(
            source=ActorSource.TELEGRAM,
            fullName=telegram_user.full_name,
            telegramId=telegram_user.id,
            telegramUsername=telegram_user.username,
        )


class FieldChange(BaseModel):
    """A single field's value before and after an action."""

    field: str
    before: FieldValue
    after: FieldValue

    @classmethod
    def diff(
        cls,
        before: BaseModel | Mapping[str, FieldValue] | None,
        after: BaseModel | Mapping[str, FieldValue] | None,
        fields: Iterable[str],
    ) -> list[FieldChange]:
        """Build the field-level changes between two states of an entity."""

        def value_of(state: BaseModel | Mapping[str, FieldValue] | None, field: str) -> FieldValue:
            if state is None:
                return None

            if isinstance(state, Mapping):
                return state.get(field)

            return getattr(state, field, None)

        return [
            FieldChange(field=field, before=old, after=new)
            for field in fields
            if (old := value_of(before, field)) != (new := value_of(after, field))
        ]


class AuditLog(Document):
    """Immutable audit-trail entry recording a single create/update/delete operation."""

    action: ActionType
    """What happened."""

    entityType: EntityType
    """Kind of entity this entry is about."""

    actor: Actor
    """Who did it."""

    entityId: str | None = None
    """String form of the affected record's own id."""

    parentId: str | None = None
    """String form of the owning/parent record's id, when the entity belongs to one."""

    parentLabel: str | None = None
    """Display label for the parent, kept even if the parent is later renamed/deleted."""

    summary: str
    """Short human-readable label for the affected entity (course/file/account name)."""

    changes: list[FieldChange] = Field(default_factory=list)
    """Field-level before/after values"""

    createdAt: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """When the action happened (UTC)."""

    class Settings:
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("createdAt", -1)]),
            IndexModel([("entityType", 1), ("action", 1), ("createdAt", -1)]),
            IndexModel([("entityId", 1)]),
            IndexModel([("parentId", 1)]),
            IndexModel([("actor.userId", 1)]),
            IndexModel([("actor.telegramId", 1)]),
        ]

    @classmethod
    def build(
        cls,
        *,
        action: ActionType,
        entity_type: EntityType,
        actor: Actor,
        summary: str,
        entity_id: str | int | PydanticObjectId | None = None,
        parent_id: str | int | PydanticObjectId | None = None,
        parent_label: str | None = None,
        changes: list[FieldChange] | None = None,
    ) -> AuditLog:
        """Construct an entry without persisting it."""
        return cls(
            action=action,
            entityType=entity_type,
            actor=actor,
            entityId=str(entity_id) if entity_id is not None else None,
            parentId=str(parent_id) if parent_id is not None else None,
            parentLabel=parent_label,
            summary=summary,
            changes=changes or [],
        )

    @classmethod
    async def record(
        cls,
        *,
        action: ActionType,
        entity_type: EntityType,
        actor: Actor,
        summary: str,
        entity_id: str | int | PydanticObjectId | None = None,
        parent_id: str | int | PydanticObjectId | None = None,
        parent_label: str | None = None,
        changes: list[FieldChange] | None = None,
    ) -> None:
        """Record a single audit-trail entry."""
        entry = cls.build(
            action=action,
            entity_type=entity_type,
            actor=actor,
            summary=summary,
            entity_id=entity_id,
            parent_id=parent_id,
            parent_label=parent_label,
            changes=changes,
        )
        try:
            await entry.insert()
        except Exception:
            logger.exception("Failed to record audit entry (%s %s: %s)", entry.action, entry.entityType, entry.summary)

    @classmethod
    async def record_many(cls, entries: list[Self]) -> None:
        """Record several audit-trail entries in a single round trip."""
        try:
            if entries:
                await cls.insert_many(entries)
        except Exception:
            logger.exception("Failed to record %d audit entries", len(entries))

    @classmethod
    async def record_course(
        cls,
        course: Course,
        action: ActionType,
        actor: Actor,
        changes: list[FieldChange] | None = None,
    ) -> None:
        verb = {"create": "Created", "update": "Updated", "delete": "Deleted"}[action]
        await cls.record(
            entity_type=EntityType.COURSE,
            action=action,
            actor=actor,
            entity_id=course.id,
            parent_id=course.id,
            parent_label=course.courseName,
            summary=f"{verb} course '{course.courseName}' ({course.tutorName})",
            changes=changes,
        )

    @classmethod
    def build_file_audit(
        cls,
        course: Course,
        file: CourseFile,
        action: ActionType,
        actor: Actor,
        changes: list[FieldChange] | None = None,
        *,
        via_telegram: bool = False,
    ) -> AuditLog:
        verb = {"create": "Added", "update": "Renamed", "delete": "Deleted"}[action]
        suffix = " via Telegram" if via_telegram else ""
        return cls.build(
            entity_type=EntityType.COURSE_FILE,
            action=action,
            actor=actor,
            entity_id=file.archiveTelegramMessageId,
            parent_id=course.id,
            parent_label=course.courseName,
            summary=f"{verb} file '{file.title}' in course '{course.courseName}'{suffix}",
            changes=changes,
        )

    @classmethod
    async def record_file(
        cls,
        course: Course,
        file: CourseFile,
        action: ActionType,
        actor: Actor,
        changes: list[FieldChange] | None = None,
        *,
        via_telegram: bool = False,
    ) -> None:
        entry = cls.build_file_audit(
            course=course,
            file=file,
            action=action,
            actor=actor,
            changes=changes,
            via_telegram=via_telegram,
        )

        try:
            await entry.insert()
        except Exception:
            logger.exception("Failed to record audit entry (%s %s: %s)", entry.action, entry.entityType, entry.summary)
