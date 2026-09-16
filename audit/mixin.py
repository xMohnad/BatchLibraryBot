from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from beanie import Document, Insert, PydanticObjectId, Replace, Update, after_event, before_event

from audit.models import ActionType, Actor, AuditLog, EntityState, EntityType, FieldChange, read_field
from core.context import current_actor

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True)
class ChildAuditSpec:
    """Declares how to audit one embedded list of child entities on an `AuditableDocument`."""

    list_attr: str
    """Name of the list field on the parent document."""

    entity_type: EntityType
    """Entity type recorded for each child."""

    audit_fields: list[str]
    """Child fields tracked for changes."""

    key_field: str = "id"
    """Field identifying a child across saves, used to match old items to new ones."""

    entity_id_field: str | None = None
    """Field logged as the entry's entityId; defaults to `key_field`."""

    label_field: str | None = None
    """Field logged as the entry's entityLabel."""

    soft_delete_field: str | None = None
    """Boolean field that, on flipping to True, is logged as a delete instead of an update."""

    @property
    def id_field(self) -> str:
        return self.entity_id_field or self.key_field


class AuditableDocument(Document):
    """Document mixin that automatically records audit-trail entries from Beanie hooks.

    Subclasses inherit this mixin to automatically diff and log top-level field
    changes and embedded child collections during Beanie insert/Update operations.

    Note: subclasses must set `use_state_management = True` in their own
    `Settings` so `_get_saved_state` can see the pre-save state without a DB round-trip.
    """

    ENTITY_TYPE: ClassVar[EntityType]
    """The entity type recorded in audit logs for this document."""

    AUDIT_FIELDS: ClassVar[list[str]] = []
    """Top-level field names to track for changes."""

    LABEL_FIELD: ClassVar[str | None] = None
    """Field name used as the primary display label in audit entries."""

    SOFT_DELETE_FIELD: ClassVar[str | None] = None
    """Boolean field name whose False -> True transition logs a DELETE action instead of UPDATE."""

    AUDIT_CHILDREN: ClassVar[list[ChildAuditSpec]] = []
    """Specs for embedded list attributes audited as distinct child entities."""

    def _audit_label(self) -> str | None:
        return getattr(self, self.LABEL_FIELD, None) if self.LABEL_FIELD else None

    @staticmethod
    def _resolve_action(before: EntityState, after: EntityState, soft_delete_field: str | None) -> ActionType:
        """Decide the action for one before/after pair.

        `after=None` means the record vanished from its list: always a delete.
        Otherwise the default is CREATE (no prior state) or UPDATE, unless
        `soft_delete_field` just flipped to True, which is logged as a delete.
        """
        if after is None:
            return ActionType.DELETE

        default = ActionType.CREATE if before is None else ActionType.UPDATE
        if (
            soft_delete_field
            and read_field(after, soft_delete_field) is True
            and read_field(before, soft_delete_field) is not True
        ):
            return ActionType.DELETE
        return default

    async def _record_change(
        self,
        actor: Actor,
        *,
        entity_type: EntityType,
        entity_id: str | int | PydanticObjectId,
        entity_label: str | None,
        parent_id: PydanticObjectId | None,
        parent_label: str | None,
        before: EntityState,
        after: EntityState,
        fields: Iterable[str],
        soft_delete_field: str | None,
    ) -> None:
        """Diff `before`/`after` on `fields` and record one audit entry."""
        changes = FieldChange.diff(before, after, fields)
        if before is not None and after is not None and not changes:
            return

        await AuditLog.record(
            action=self._resolve_action(before, after, soft_delete_field),
            entity_type=entity_type,
            actor=actor,
            entity_id=entity_id,
            entity_label=entity_label,
            parent_id=parent_id,
            parent_label=parent_label,
            changes=changes,
        )

    async def _record_self(self, actor: Actor, old_state: dict | None) -> None:
        if self.id is None:
            raise ValueError(f"Audit tracking failed: Document of type {self.ENTITY_TYPE} missing ID.")

        await self._record_change(
            actor,
            entity_type=self.ENTITY_TYPE,
            entity_id=self.id,
            entity_label=self._audit_label(),
            parent_id=None,
            parent_label=None,
            before=old_state,
            after=self,
            fields=self.AUDIT_FIELDS,
            soft_delete_field=self.SOFT_DELETE_FIELD,
        )

    async def _record_child_change(
        self, actor: Actor, spec: ChildAuditSpec, *, before: EntityState, after: EntityState
    ) -> None:
        item = after if after is not None else before
        item_id = read_field(item, spec.id_field)
        if item_id is None:
            raise ValueError(f"Audit tracking failed: Child entity missing ID on field '{spec.id_field}'")

        raw_label = read_field(item, spec.label_field) if spec.label_field else None

        await self._record_change(
            actor,
            entity_type=spec.entity_type,
            entity_id=item_id,
            entity_label=str(raw_label) if raw_label is not None else None,
            parent_id=self.id,
            parent_label=self._audit_label(),
            before=before,
            after=after,
            fields=spec.audit_fields,
            soft_delete_field=spec.soft_delete_field,
        )

    async def _record_children(self, actor: Actor, old_state: dict | None) -> None:
        for spec in self.AUDIT_CHILDREN:
            old_items = {read_field(item, spec.key_field): item for item in (old_state or {}).get(spec.list_attr, [])}
            new_items = getattr(self, spec.list_attr)
            seen_keys = set()

            for item in new_items:
                key = read_field(item, spec.key_field)
                seen_keys.add(key)
                await self._record_child_change(actor, spec, before=old_items.get(key), after=item)

            for key, old_item in old_items.items():
                if key not in seen_keys:
                    await self._record_child_change(actor, spec, before=old_item, after=None)

    @after_event(Insert)
    async def _audit_insert(self) -> None:
        if actor := current_actor.get():
            await self._record_self(actor, old_state=None)
            await self._record_children(actor, old_state=None)

    @before_event(Update, Replace)
    async def _audit_save(self) -> None:
        if actor := current_actor.get():
            old_state = await self._get_saved_state()
            if old_state is None:
                return

            await self._record_self(actor, old_state)
            await self._record_children(actor, old_state)

    async def _get_saved_state(self) -> dict | None:
        """The document's state as last persisted, or as currently stored in the DB."""
        old_state = self.get_saved_state()
        if old_state is None and self.id is not None:
            db_doc = await self.__class__.get(self.id)
            old_state = db_doc.model_dump() if db_doc else None
        return old_state
