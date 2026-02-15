from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Self

from aiogram.types import Message
from async_lru import alru_cache
from beanie import Document, Indexed, Replace, Save, before_event
from pydantic import BaseModel, Field, model_validator
from pydantic.fields import Field

from app.utils import (
    NUMBER,
    get_level,
    get_semester,
    get_term,
    resolve_course_similarity,
)


class CourseType(str, Enum):
    PRACTICAL = "عملي"
    THEORETICAL = "نظري"


class MessageType(str, Enum):
    """This object represents a supported type of content in a message."""

    AUDIO = "audio"
    DOCUMENT = "document"
    VIDEO = "video"


class Gender(str, Enum):
    """Enumeration of possible user genders."""

    male = "male"
    """Male gender."""

    female = "female"
    """Female gender."""

    unknown = "unknown"
    """Undefined or not specified gender."""


class BaseDocument(Document):
    """Base document containing common timestamp fields."""

    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """Date and time when the document was created (UTC)."""

    updatedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """Date and time when the document was last updated (UTC)."""

    @before_event(Save, Replace)
    def update_timestamp(self):
        """Automatically updates the 'updatedAt' field before saving or replacing the document."""
        self.updatedAt = datetime.now(timezone.utc)


class Users(BaseDocument):
    """Represents a system user."""

    telegramId: Annotated[int, Indexed(unique=True)]
    """Unique Telegram user identifier."""

    fullName: str
    """Full name of the user as provided by Telegram."""

    gender: Gender = Gender.unknown
    """User gender (male, female, or unknown)."""

    isAdmin: bool = False
    """Indicates whether the user has administrator privileges."""


class CourseFile(BaseModel):
    """Represents a file associated with a course."""

    title: str
    """Human-readable title of the file."""

    archiveTelegramMessageId: int
    """Telegram message ID where the file is stored in the archive channel."""

    chatId: int
    """Chat ID of the archive channel."""

    originalTelegramMessageId: int
    """Original Telegram message ID from the source chat."""

    fromChatId: int
    """Source chat ID where the file was originally sent."""

    fileId: str
    """Unique Telegram file identifier."""

    originalName: str
    """Original filename as uploaded by the user."""

    mimeType: str
    """MIME type of the file (e.g., application/pdf, image/png)."""

    telegramMessageType: MessageType
    """The type of the message based on Telegram content (e.g., AUDIO, DOCUMENT, VIDEO)."""

    extension: str
    """File extension without dot (e.g., pdf, png, mp4)."""

    sizeBytes: int
    """File size in bytes."""

    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """Date and time when the document was created (UTC)."""

    updatedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """Date and time when the document was last updated (UTC)."""

    @model_validator(mode="after")
    def update_timestamp(self) -> Self:
        """Automatically updates the 'updatedAt' field after updates any field."""
        self.updatedAt = datetime.now(timezone.utc)
        return self

    @classmethod
    async def parse_file(
        cls, message: Message, match: re.Match[str], **kwargs
    ) -> CourseFile:
        """Parse course file information from a Telegram message."""
        kwargs.setdefault("originalTelegramMessageId", message.message_id)
        kwargs.setdefault("archiveTelegramMessageId", message.message_id)
        kwargs.setdefault("fromChatId", message.chat.id)
        kwargs.setdefault("chatId", message.chat.id)
        kwargs.setdefault("title", match.group("title"))

        content_type = message.content_type
        file = getattr(message, content_type)
        if content_type not in MessageType or not file:
            raise ValueError(
                "Message does not contain a supported file (document, video, or audio)."
            )

        if (
            not (file_name := file.file_name)
            or not (file_size := file.file_size)
            or not (mime_type := file.mime_type)
        ):
            raise ValueError("Invalid file metadata received from Telegram.")

        extension = Path(file_name).suffix.lstrip(".")
        return cls(
            fileId=file.file_id,
            originalName=file_name,
            mimeType=mime_type,
            sizeBytes=file_size,
            extension=extension,
            telegramMessageType=MessageType(content_type),
            **kwargs,
        )


class Course(BaseDocument):
    """Represents a course linked to a subject and its files."""

    courseName: Annotated[str, Indexed()]
    """Name of the course or subject."""

    tutorName: str
    """Name of the tutor or instructor."""

    semester: int = Field(..., ge=1, le=8)
    """Academic semester number (e.g., 1, 2, 3, ..., 8)."""

    isPractical: bool
    """Indicates whether the subject is practical (True) or theoretical (False)."""

    files: list[CourseFile] = Field(default_factory=list)
    """List of files associated with this course."""

    class Settings:
        indexes = [
            "files.originalTelegramMessageId",
            "files.archiveTelegramMessageId",
            "files.fileId",
        ]

    @property
    def level(self) -> str:
        return NUMBER[get_level(self.semester)]

    @property
    def term(self) -> str:
        return NUMBER[get_term(self.semester)]

    def formatted_info(self, title: str) -> str:
        """Get formatted course information"""
        return (
            f"{self.courseName} ({self.tutorName}) | {title}\n\n"
            f"#المستوى_{self.level} #الفصل_{self.term}"
        )

    @classmethod
    @alru_cache(ttl=60 * 60 * 2)
    async def get_courses_name(cls, semester: int = get_semester()) -> list[str]:
        """
        Retrieve course names for a given academic

        Results are cached to reduce repeated database queries
        for the same semester.

        Returns:
            list[str]: A list of course names associated with the given semester.
        """
        return await cls.distinct(Course.courseName, {"semester": semester})

    @classmethod
    @alru_cache(ttl=60 * 60 * 2)
    async def get_course(
        cls, courseName: str, semester: int = get_semester()
    ) -> Course | None:
        courses = await cls.get_courses_name(semester)
        course = resolve_course_similarity(courseName, courses)
        return await cls.find_one(cls.courseName == course, cls.semester == semester)

    async def upsert_files(self, files: list[CourseFile]) -> bool:
        """Update file title if fileId exists, otherwise add new file."""

        files_by_id = {f.fileId: f for f in self.files}
        updated = False

        for new_file in files:
            if new_file.fileId in files_by_id:
                existing_file = files_by_id[new_file.fileId]
                if existing_file.title != new_file.title:
                    existing_file.title = new_file.title

            else:
                # Add new file
                self.files.append(new_file)
                updated = True

        if updated:
            await self.save()

        return updated
