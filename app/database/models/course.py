from __future__ import annotations

import re
from enum import Enum

from aiogram.types import Message
from beanie import Document
from pydantic.fields import Field

from app.utils import NUMBER, course_similarity, get_level, get_term


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

    @classmethod
    async def parse_course(
        cls,
        message: Message,
        match: re.Match[str],
        **kwargs,
    ) -> CourseMaterial:
        """Parse course information from a message caption."""
        course = await course_similarity(match.group("course"))
        title = match.group("title")
        kwargs.setdefault("course_id", message.message_id)
        kwargs.setdefault("message_id", message.message_id)
        kwargs.setdefault("from_chat_id", message.chat.id)

        return cls(course=course.strip(), title=title.strip(), **kwargs)
