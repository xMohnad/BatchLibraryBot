from __future__ import annotations

from pathlib import Path

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
