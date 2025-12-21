from __future__ import annotations

import re

from aiogram.types import Message
from beanie import Document
from pydantic.fields import Field

from app.utils import NUMBER, course_similarity, get_level, get_term


class CourseMaterial(Document):
    """Represents a course material with metadata"""

    level: int = Field(default_factory=get_level)
    term: int = Field(default_factory=get_term)
    course: str
    title: str
    course_id: int
    message_id: int
    from_chat_id: int

    @property
    def formatted_info(self) -> str:
        """Get formatted course information"""
        return (
            f"{self.course} | {self.title}\n\n"
            f"#مستوى_{self.level_word} "
            f"#ترم_{self.term_word}"
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
