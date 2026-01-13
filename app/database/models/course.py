from __future__ import annotations

import re
from enum import Enum
from typing import Any, Mapping

from aiogram.types import Message
from beanie import Document
from beanie.odm.operators.update.general import Set
from pydantic.fields import Field

from app.utils import (
    NUMBER,
    extract_kind,
    get_courses_by_level,
    get_level,
    get_term,
    resolve_course_similarity,
)


class CourseType(str, Enum):
    PRACTICAL = "عملي"
    THEORETICAL = "نظري"


class CourseMaterial(Document):
    """Represents a course material with metadata"""

    level: int = Field(default_factory=get_level)
    term: int = Field(default_factory=get_term)
    course: str
    title: str
    course_id: int
    message_id: int
    from_chat_id: int

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CourseMaterial):
            return NotImplemented

        include = {"level", "term", "course", "title"}
        return self.model_dump(include=include) == other.model_dump(include=include)

    @property
    def formatted_info(self) -> str:
        """Get formatted course information"""
        return (
            f"{self.course} | {self.title}\n\n"
            f"#مستوى_{self.level_word} "
            f"#ترم_{self.term_word}"
        )

    @property
    def type(self) -> CourseType:
        return (
            CourseType.PRACTICAL
            if CourseType.PRACTICAL.value in self.course
            else CourseType.THEORETICAL
        )

    @property
    def level_word(self) -> str:
        return NUMBER[self.level]

    @property
    def term_word(self) -> str:
        return NUMBER[self.term]

    @property
    def update_fields(self) -> dict[Any, Any]:
        """Return fields used to update an existing CourseMaterial document."""
        return {
            CourseMaterial.level: self.level,
            CourseMaterial.term: self.term,
            CourseMaterial.course: self.course,
            CourseMaterial.title: self.title,
        }

    async def upsert_course(
        self,
        *args: Mapping[Any, Any] | bool,
        include: Mapping[str, Any] | None = None,
    ) -> None:
        """Insert or update CourseMaterial."""

        update_doc = self.update_fields
        if include:
            update_doc |= include

        await CourseMaterial.find_one(*args).upsert(  # pyright: ignore[reportGeneralTypeIssues]
            Set(update_doc),
            on_insert=self,
        )

    @classmethod
    async def parse_course(
        cls,
        message: Message,
        match: re.Match[str],
        similarity: bool = True,
        **kwargs,
    ) -> CourseMaterial:
        """Parse course information from a message caption."""
        kwargs.update(extract_kind(match.string))
        kwargs.setdefault("course_id", message.message_id)
        kwargs.setdefault("message_id", message.message_id)
        kwargs.setdefault("from_chat_id", message.chat.id)

        title = match.group("title")
        course = match.group("course")

        if similarity:
            courses = await get_courses_by_level(kwargs.get("level") or get_level())
            course = resolve_course_similarity(course, courses)

        return cls(course=course.strip(), title=title.strip(), **kwargs)
