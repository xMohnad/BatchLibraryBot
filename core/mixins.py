from __future__ import annotations

from datetime import UTC, datetime

from beanie import Replace, Update, before_event
from pydantic import BaseModel, Field


class TimestampMixin(BaseModel):
    """Mixin that adds automatic `createdAt` and `updatedAt` timestamp fields."""

    createdAt: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Date and time when the document was created (UTC)."""

    updatedAt: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Date and time when the document was last updated (UTC)."""

    @before_event(Update, Replace)
    def set_updated_at(self):
        """Refresh `updatedAt` right before the document is saved or replaced."""
        self.updatedAt = datetime.now(UTC)
