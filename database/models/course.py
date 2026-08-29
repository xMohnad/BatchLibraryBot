from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Self

from async_lru import alru_cache
from beanie import Document, Insert, PydanticObjectId, Save, Update, after_event
from pydantic import BaseModel, Field, model_validator
from pymongo import IndexModel
from rapidfuzz import fuzz, process

from database.models.mixins import TimestampMixin
from database.models.ordinal import Ordinal

if TYPE_CHECKING:
    from aiogram.types import Message

logger = logging.getLogger(__name__)

CAPTION_PATTERN = re.compile(r"(?P<course>.+?)(?:\s*\((?P<tutor>.+?)\))?\s*\|\s*(?P<title>.+)")


def _resolve_course_similarity(course: str, existing: list[str], threshold: int = 90) -> str:
    """Match `course` against `existing` course names, tolerating minor typos."""
    logger.info(f"Checking similarity for: '{course}'")

    if course in existing:
        logger.info(f"Exact match found in database for: '{course}'")
        return course

    match = process.extractOne(course, existing, scorer=fuzz.token_sort_ratio)

    logger.info(f"Best match: {match}")

    if match and match[1] >= threshold:
        logger.info(f"Accepted → returning: '{match[0]}' (score={match[1]})")
        return match[0]

    logger.info(f"Rejected → returning original: '{course}'")
    return course


class CourseType(StrEnum):
    PRACTICAL = "عملي"
    THEORETICAL = "نظري"


class MessageType(StrEnum):
    """This object represents a supported type of content in a message."""

    AUDIO = "audio"
    DOCUMENT = "document"
    VIDEO = "video"


class CourseFile(BaseModel):
    """Represents a file associated with a course."""

    id: PydanticObjectId = Field(default_factory=PydanticObjectId)
    """Unique identifier for this file."""

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

    url: str | None = None
    """Direct Cloudinary URL to the file, once uploaded."""

    publicId: str | None = None
    """Cloudinary public ID, used to manage (e.g. delete) the uploaded asset."""

    resourceType: str | None = None
    """Cloudinary resource type the file was stored under (image/video/raw)."""

    createdAt: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Date and time when the document was created (UTC)."""

    updatedAt: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Date and time when the document was last updated (UTC)."""

    @model_validator(mode="after")
    def update_timestamp(self) -> Self:
        """Automatically updates the 'updatedAt' field after updates any field."""
        self.updatedAt = datetime.now(UTC)
        return self

    @classmethod
    async def from_message(cls, message: Message, match: re.Match[str], **kwargs) -> CourseFile:
        """Build a CourseFile from a Telegram message."""
        kwargs.setdefault("originalTelegramMessageId", message.message_id)
        kwargs.setdefault("archiveTelegramMessageId", message.message_id)
        kwargs.setdefault("fromChatId", message.chat.id)
        kwargs.setdefault("chatId", message.chat.id)
        kwargs.setdefault("title", match.group("title"))

        content_type = message.content_type
        file = getattr(message, content_type)
        if content_type not in MessageType or not file:
            raise ValueError("Message does not contain a supported file (document, video, or audio).")

        if not (file_name := file.file_name) or not (file_size := file.file_size) or not (mime_type := file.mime_type):
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

    @classmethod
    async def group_media_by_course(
        cls, media_events: list[Message]
    ) -> tuple[dict[str, list[CourseFile]], dict[str, str]]:
        """Group a batch of media messages (e.g. an album/media group) by course.

        Messages in a media group only carry a caption on one item (usually the
        first), so messages without their own caption fall back to the last
        message's caption.

        Returns:
            A tuple of:
            - course_files: course title -> list of parsed `CourseFile` objects
            - course_captions: course title -> the caption used to resolve it
        """
        default_caption = media_events[-1].caption or ""
        course_files: defaultdict[str, list[CourseFile]] = defaultdict(list)
        course_captions: dict[str, str] = {}

        for msg in media_events:
            caption = msg.caption or default_caption
            if match := CAPTION_PATTERN.search(caption):
                course_title: str = match.group("course")
                course_file = await cls.from_message(msg, match)
                course_files[course_title].append(course_file)
                course_captions.setdefault(course_title, caption)

        return course_files, course_captions


class Course(TimestampMixin, Document):
    """Represents a course linked to a subject and its files."""

    courseName: str
    """Name of the course or subject."""

    tutorName: str
    """Name of the tutor or instructor."""

    semester: Ordinal
    """Academic semester number (e.g., 1, 2, 3, ..., 8)."""

    isPractical: bool
    """Indicates whether the subject is practical (True) or theoretical (False)."""

    files: list[CourseFile] = Field(default_factory=list)
    """List of files associated with this course."""

    class Settings:
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("files.archiveTelegramMessageId", 1)]),
            IndexModel([("semester", 1), ("courseName", 1)]),
            IndexModel([("semester", 1), ("isPractical", 1), ("courseName", 1)]),
        ]

    @property
    def level(self) -> str:
        return Ordinal.get_name(Ordinal.current_level(self.semester))

    def formatted_info(self, title: str) -> str:
        """Get formatted course information."""
        return (
            f"{self.courseName} ({self.tutorName}) | {title}\n\n"
            f"#المستوى_{self.level} #الفصل_{Ordinal.get_name(self.semester)}"
        )

    @classmethod
    @alru_cache
    async def get_courses_name(cls, semester: int) -> list[str]:
        """Retrieve course names for a given academic semester, defaults to the current semester."""
        return await cls.distinct(Course.courseName, {"semester": semester})

    @classmethod
    @alru_cache
    async def _get_course(cls, courseName: str, semester: int) -> Course | None:
        """Fetch a Course object by name and semester with caching."""
        courses = await cls.get_courses_name(semester)
        course = _resolve_course_similarity(courseName, courses)
        return await cls.find_one(cls.courseName == course, cls.semester == semester)

    @classmethod
    async def get_course(cls, courseName: str, caption: str) -> Course | None:
        """Fetch a course by name using semester extracted from a caption."""
        return await cls._get_course(courseName=courseName, semester=Ordinal.get_semester(caption))

    @classmethod
    @alru_cache
    async def get_courses(cls, semester: int, is_practical: bool, course_name: str | None = None) -> list[Course]:
        """Fetch courses with caching."""
        query = {Course.semester: semester, Course.isPractical: is_practical}
        if course_name:
            query[Course.courseName] = course_name.strip()

        return await Course.find(query).to_list()

    @after_event(Insert, Save, Update)
    def _invalidate_caches(self) -> None:
        """Clear every course-related cache whenever a course is created or modified."""
        Course.get_courses_name.cache_clear()
        Course.get_courses.cache_clear()
        Course._get_course.cache_clear()

    def find_file_by_original_id(self, original_message_id: int) -> CourseFile | None:
        """Find a file in this course by its original (source-channel) message id."""
        return next((f for f in self.files if f.originalTelegramMessageId == original_message_id), None)

    def find_file_by_archive_id(self, archive_message_id: int) -> CourseFile | None:
        """Find a file in this course by its archive message id."""
        return next((f for f in self.files if f.archiveTelegramMessageId == archive_message_id), None)

    async def upsert_files(self, files: list[CourseFile]) -> bool:
        """Upsert files by archiveTelegramMessageId."""
        files_by_id = {f.archiveTelegramMessageId: f for f in self.files}
        updated = False

        for f in files:
            existing = files_by_id.get(f.archiveTelegramMessageId)

            if not existing:
                self.files.append(f)
                updated = True
                continue

            if existing.title != f.title:
                existing.title = f.title
                updated = True

            if existing.fileId != f.fileId:
                existing.fileId = f.fileId  # expected to change
                updated = True

        if updated:
            await self.save()

        return updated
