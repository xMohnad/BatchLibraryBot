from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, ConfigDict, Field
from pymongo import IndexModel

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aiogram.types import Message

    from accounts.models import User

logger = logging.getLogger(__name__)

type FieldValue = str | int | bool | None
"""JSON-primitive type allowed in a logged before/after value."""

type EntityState = BaseModel | Mapping[str, FieldValue] | None
"""Either side of a before/after comparison."""


def read_field(state: EntityState, field: str) -> FieldValue:
    """Read `field` off a mapping (persisted dict state) or a model instance (in-memory)."""
    if state is None:
        return None
    if isinstance(state, Mapping):
        return state.get(field)
    return getattr(state, field, None)


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
    """Author signature attached to a channel post."""

    @classmethod
    def from_user(cls, user: User) -> Actor:
        """Build an actor instance for an authenticated Web API user."""
        return cls(source=ActorSource.WEB, userId=user.id)

    @classmethod
    async def from_telegram_message(cls, message: Message) -> Actor:
        """Resolve a Telegram `Message` into an `Actor`."""
        from accounts.models import User

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
        before: EntityState,
        after: EntityState,
        fields: Iterable[str],
    ) -> list[FieldChange]:
        """Build the field-level changes between two states of an entity."""
        changes: list[FieldChange] = []
        for field in fields:
            old, new = read_field(before, field), read_field(after, field)
            if old != new:
                changes.append(FieldChange(field=field, before=old, after=new))
        return changes


class AuditLog(Document):
    """Immutable audit-trail entry recording a single create/update/delete operation."""

    action: ActionType
    """What happened."""

    entityType: EntityType
    """Kind of entity this entry is about."""

    actor: Actor
    """Who did it."""

    entityId: str
    """String form of the affected record's own id."""

    entityLabel: str | None = None
    """Display label for the affected record."""

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
        ]

    @classmethod
    async def record(
        cls,
        *,
        action: ActionType,
        entity_type: EntityType,
        actor: Actor,
        entity_id: str | int | PydanticObjectId,
        entity_label: str | None = None,
        parent_id: str | int | PydanticObjectId | None = None,
        parent_label: str | None = None,
        changes: list[FieldChange] | None = None,
    ) -> None:
        """Record a single audit-trail entry for the current actor, if any."""
        entry = cls(
            action=action,
            entityType=entity_type,
            actor=actor,
            entityId=str(entity_id),
            entityLabel=entity_label,
            parentId=str(parent_id) if parent_id is not None else None,
            parentLabel=parent_label,
            changes=changes or [],
        )

        try:
            await entry.insert()
        except Exception:
            logger.exception(
                "Failed to record audit entry (%s %s: %s)", entry.action, entry.entityType, entry.entityLabel
            )
