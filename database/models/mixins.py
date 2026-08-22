from __future__ import annotations

from datetime import UTC, datetime

from beanie import Insert, Replace, Save, SaveChanges, Update, before_event
from pydantic import BaseModel, Field


class TimestampMixin(BaseModel):
    """Mixin that adds automatic `createdAt` and `updatedAt` timestamp fields."""

    createdAt: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Date and time when the document was created (UTC)."""

    updatedAt: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Date and time when the document was last updated (UTC)."""

    @before_event(Insert)
    def set_created_at(self):
        """Set `createdAt` and `updatedAt` right before the document is inserted."""
        self.createdAt = datetime.now(UTC)
        self.updatedAt = datetime.now(UTC)

    @before_event(Replace, SaveChanges, Save, Update)
    def set_updated_at(self):
        """Refresh `updatedAt` right before the document is saved or replaced."""
        self.updatedAt = datetime.now(UTC)
