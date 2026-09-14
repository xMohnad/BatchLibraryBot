from __future__ import annotations

import logging
import mimetypes
import re
from collections import defaultdict
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Self

from async_lru import alru_cache
from beanie import Document, Insert, PydanticObjectId, Save, Update, after_event
from beanie.operators import In
from pydantic import BaseModel, Field, model_validator
from pymongo import IndexModel

from core.mixins import TimestampMixin
from core.text_matching import resolve_best_match
from courses.ordinal import Ordinal

if TYPE_CHECKING:
    from aiogram.types import Audio, Message, Video
    from aiogram.types import Document as TelegramDocument

logger = logging.getLogger(__name__)

CAPTION_PATTERN = re.compile(r"(?P<course>.+?)(?:\s*\((?P<tutor>.+?)\))?\s*\|\s*(?P<title>.+)")

FILE_DEEP_LINK_PREFIX = "file_"


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

    AUDIT_FIELDS: ClassVar[list[str]] = ["title", "originalName", "sizeBytes", "extension"]

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

    isDeleted: bool = False
    """Whether this file has been soft-deleted."""

    createdAt: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Date and time when the document was created (UTC)."""

    updatedAt: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Date and time when the document was last updated (UTC)."""

    @model_validator(mode="after")
    def update_timestamp(self) -> Self:
        """Automatically updates the 'updatedAt' field after updates any field."""
        self.updatedAt = datetime.now(UTC)
        return self

    def mark_deleted(self) -> None:
        """Flag this file as deleted without removing it from the database."""
        self.isDeleted = True
        self.updatedAt = datetime.now(UTC)

    @classmethod
    def from_message(cls, message: Message, match: re.Match[str] | None = None, **kwargs) -> CourseFile:
        """Build a CourseFile from a Telegram message."""
        kwargs.setdefault("originalTelegramMessageId", message.message_id)
        kwargs.setdefault("archiveTelegramMessageId", message.message_id)
        kwargs.setdefault("fromChatId", message.chat.id)
        kwargs.setdefault("chatId", message.chat.id)
        if match is not None:
            kwargs.setdefault("title", match.group("title"))

        content_type = message.content_type
        file: Audio | TelegramDocument | Video | None = getattr(message, content_type, None)
        if content_type not in MessageType or file is None:
            raise ValueError("Message does not contain a supported file (document, video, or audio).")

        file_size = kwargs.pop("sizeBytes", None) or file.file_size
        if file_size is None:
            raise ValueError("Telegram did not report a file size for this message.")

        mime_type = kwargs.pop("mimeType", None) or file.mime_type
        file_name = kwargs.pop("originalName", None) or file.file_name
        if not file_name:
            guess_extension = mimetypes.guess_extension(mime_type) if mime_type else None
            if guess_extension is None:
                raise ValueError("Cannot determine file extension")

            file_name = f"{kwargs['title']}{guess_extension}"

        mime_type = mime_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"

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
                course_file = cls.from_message(msg, match)
                course_files[course_title].append(course_file)
                course_captions.setdefault(course_title, caption)

        return course_files, course_captions


class Course(TimestampMixin, Document):
    """Represents a course linked to a subject and its files."""

    AUDIT_FIELDS: ClassVar[list[str]] = ["courseName", "tutorName", "isPractical"]

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

    isDeleted: bool = False
    """Whether this course has been soft-deleted."""

    class Settings:
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("files.archiveTelegramMessageId", 1), ("isDeleted", 1)]),
            IndexModel([("isDeleted", 1), ("semester", 1), ("isPractical", 1), ("courseName", 1)]),
            IndexModel([("isDeleted", 1), ("semester", 1), ("createdAt", -1)]),
            IndexModel([("isDeleted", 1), ("createdAt", -1)]),
        ]

    @property
    def level(self) -> str:
        return Ordinal.get_name(Ordinal.current_level(self.semester))

    @property
    def active_files(self) -> list[CourseFile]:
        """Files belonging to this course that have not been soft-deleted."""
        return [f for f in self.files if not f.isDeleted]

    def mark_deleted(self) -> None:
        """Flag this course as deleted without removing it from the database."""
        self.isDeleted = True

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
        return await cls.distinct(Course.courseName, {"semester": semester, "isDeleted": False})

    @classmethod
    @alru_cache
    async def _get_course(cls, courseName: str, semester: int) -> Course | None:
        """Fetch a Course object by name and semester with caching."""
        courses = await cls.get_courses_name(semester)
        if course := resolve_best_match(courseName, courses):
            logger.info("Match: '%s' -> '%s' (semester=%s)", courseName, course, semester)
            return await cls.find_one(cls.courseName == course, cls.semester == semester, cls.isDeleted == False)  # noqa: E712

    @classmethod
    async def get_course(cls, courseName: str, caption: str) -> Course | None:
        """Fetch a course by name using semester extracted from a caption."""
        return await cls._get_course(courseName=courseName, semester=Ordinal.get_semester(caption))

    @classmethod
    @alru_cache
    async def get_courses(cls, semester: int, is_practical: bool, course_name: str | None = None) -> list[Course]:
        """Fetch courses with caching."""
        query = {Course.semester: semester, Course.isPractical: is_practical, Course.isDeleted: False}
        if course_name:
            query[Course.courseName] = course_name.strip()

        return await Course.find(query).to_list()

    @classmethod
    @alru_cache
    async def get_current_courses(cls) -> list[Course]:
        """Fetch every non-deleted course for the current semester, newest first, with caching."""
        semester = Ordinal.current_semester()
        return (
            await Course.find(Course.semester == semester, Course.isDeleted == False)  # noqa: E712
            .sort("-createdAt")
            .to_list()
        )

    @classmethod
    @alru_cache
    async def get_cached(cls, course_id: PydanticObjectId) -> Course | None:
        """Fetch a single course by id, with caching."""
        return await cls.get(course_id)

    @classmethod
    def list_query(
        cls,
        *,
        level: int | None = None,
        term: int | None = None,
        is_practical: bool | None = None,
        is_deleted: bool | None = False,
    ):
        """Build a find query for course listings, filtered by the given fields."""
        query: dict[object, object] = {}
        if is_deleted is not None:
            query[Course.isDeleted] = is_deleted

        semesters: list[int] | None = None
        if level is not None and term is not None:
            semesters = [Ordinal.to_semester(level, term)]
        elif level is not None:
            semesters = [Ordinal.to_semester(level, t) for t in (1, 2)]
        elif term is not None:
            semesters = [Ordinal.to_semester(lvl, term) for lvl in range(1, 5)]

        if semesters:
            query[Course.semester] = {"$in": semesters}

        if is_practical is not None:
            query[Course.isPractical] = is_practical

        return cls.find(query)

    @classmethod
    async def get_many(cls, course_ids: list[PydanticObjectId]) -> dict[PydanticObjectId, Course]:
        """Fetch several courses by id at once, keyed by id."""
        if not course_ids:
            return {}
        courses = await Course.find(In(Course.id, course_ids)).to_list()
        return {course.id: course for course in courses if course.id is not None}

    @after_event(Insert, Save, Update)
    def _invalidate_caches(self) -> None:
        """Clear every course-related cache whenever a course is created or modified."""
        Course.get_courses_name.cache_clear()
        Course.get_courses.cache_clear()
        Course._get_course.cache_clear()
        Course.get_current_courses.cache_clear()
        Course.get_cached.cache_clear()
        Course._find_by_file_archive_id_cached.cache_clear()

    def _find_file(self, attr: str, value: int, *, include_deleted: bool) -> CourseFile | None:
        """Find a file in this course by matching `attr` against `value`."""
        files = self.files if include_deleted else self.active_files
        return next((f for f in files if getattr(f, attr) == value), None)

    def find_file_by_original_id(self, original_message_id: int, *, include_deleted: bool = False) -> CourseFile | None:
        """Find a file in this course by its original (source-channel) message id.

        Soft-deleted files are skipped unless `include_deleted` is True.
        """
        return self._find_file("originalTelegramMessageId", original_message_id, include_deleted=include_deleted)

    def find_file_by_archive_id(self, archive_message_id: int, *, include_deleted: bool = False) -> CourseFile | None:
        """Find a file in this course by its archive message id.

        Soft-deleted files are skipped unless `include_deleted` is True.
        """
        return self._find_file("archiveTelegramMessageId", archive_message_id, include_deleted=include_deleted)

    @classmethod
    @alru_cache
    async def _find_by_file_archive_id_cached(
        cls, archive_message_id: int, *, include_deleted: bool = False
    ) -> tuple[Course, CourseFile] | None:
        """Cached lookup backing `find_by_file_archive_id`."""
        filters = {cls.files.archiveTelegramMessageId: archive_message_id}  # pyright: ignore[reportAttributeAccessIssue]
        if not include_deleted:
            filters[cls.isDeleted] = False

        course = await cls.find_one(filters)
        if course and (file := course.find_file_by_archive_id(archive_message_id, include_deleted=include_deleted)):
            return course, file
        return None

    @classmethod
    async def find_by_file_archive_id(
        cls, archive_message_id: int, *, include_deleted: bool = False
    ) -> tuple[Course, CourseFile] | None:
        """Find the course and file for a given archive-channel message id, across all courses.

        Soft-deleted courses/files are skipped unless `include_deleted` is True.
        """
        return await cls._find_by_file_archive_id_cached(archive_message_id, include_deleted=include_deleted)

    async def upsert_files(self, files: list[CourseFile]) -> bool:
        """Upsert files by archiveTelegramMessageId. Returns whether anything changed."""
        files_by_id = {f.archiveTelegramMessageId: f for f in self.files}
        changed = False

        for f in files:
            existing = files_by_id.get(f.archiveTelegramMessageId)

            if not existing:
                self.files.append(f)
                changed = True
                continue

            if existing.title != f.title:
                existing.title = f.title
                changed = True

            if existing.fileId != f.fileId:
                existing.fileId = f.fileId  # expected to change
                changed = True

        if changed:
            await self.save()

        return changed
