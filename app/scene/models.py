from __future__ import annotations

from enum import StrEnum
from pathlib import Path  # noqa: TC003

from pydantic import BaseModel, field_validator


class File(BaseModel):
    """Represents a generated PDF file with editable metadata."""

    filepath: Path
    filename: str = "images.pdf"
    caption: str | None = None

    @field_validator("filename")
    @classmethod
    def ensure_extension(cls, filename: str) -> str:
        """Normalize filename and ensure it ends with `.pdf`."""
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        return filename

    model_config = {"validate_assignment": True}


class Action(StrEnum):
    clear = "clear"
    convert = "convert"

    filename = "filename"
    caption = "caption"

    back = "🔙 Back"
    restart = "🔄 Restart"
    exit = "🚫 Exit"
