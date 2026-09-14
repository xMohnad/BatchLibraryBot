from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, ConfigDict, Field
from pymongo import IndexModel

from accounts.models import User
from core.context import current_actor

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aiogram.types import Message

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

    telegramChannel: str | None = None
    """Display title of the Telegram channel or chat where the action/post occurred."""

    actorSignature: str | None = None
    """Author signature attached to a channel post ."""

    @classmethod
    def from_user(cls, user: User) -> Actor:
        """Build an actor instance for an authenticated Web API user."""
        return cls(source=ActorSource.WEB, userId=user.id)

    @classmethod
    async def from_telegram_message(cls, message: Message) -> Actor:
        """Resolve a Telegram `Message` into an `Actor`."""
        user_id: PydanticObjectId | None = None

        if message.from_user and (user := await User.get_by_telegram_id(message.from_user.id)):
            user_id = user.id

        return cls(
            source=ActorSource.TELEGRAM,
            userId=user_id,
            telegramChannel=message.sender_chat.title if message.sender_chat else None,
            actorSignature=message.author_signature,
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
    async def record(
        cls,
        *,
        action: ActionType,
        entity_type: EntityType,
        entity_id: str | int | PydanticObjectId | None = None,
        parent_id: str | int | PydanticObjectId | None = None,
        parent_label: str | None = None,
        changes: list[FieldChange] | None = None,
    ) -> None:
        """Record a single audit-trail entry."""
        actor = current_actor.get()
        if not actor:
            return
        entry = cls(
            action=action,
            entityType=entity_type,
            actor=actor,
            entityId=str(entity_id) if entity_id is not None else None,
            parentId=str(parent_id) if parent_id is not None else None,
            parentLabel=parent_label,
            changes=changes or [],
        )

        try:
            await entry.insert()
        except Exception:
            logger.exception(
                "Failed to record audit entry (%s %s: %s)", entry.action, entry.entityType, entry.parentLabel
            )

    @classmethod
    async def record_course(
        cls,
        course: Course,
        action: ActionType,
        changes: list[FieldChange] | None = None,
    ) -> None:
        await cls.record(
            entity_type=EntityType.COURSE,
            action=action,
            entity_id=course.id,
            parent_id=course.id,
            parent_label=course.courseName,
            changes=changes,
        )

    @classmethod
    async def record_file(
        cls,
        course: Course,
        file: CourseFile,
        action: ActionType,
        changes: list[FieldChange] | None = None,
    ) -> None:
        await cls.record(
            entity_type=EntityType.COURSE_FILE,
            action=action,
            entity_id=file.archiveTelegramMessageId,
            parent_id=course.id,
            parent_label=course.courseName,
            changes=changes,
        )
