from __future__ import annotations

from beanie import Document
from pydantic.fields import Field


class CourseMaterial(Document):
    """Represents a course material with metadata"""

    course_id: str | int
    level: str
    term: str
    course: str
    title: str
    message_id: int
    from_chat_id: int
    isarchived: bool = Field(default=False)

    @property
    def formatted_info(self) -> str:
        """Get formatted course information"""
        return (
            f"المستوى: {self.level}\n"
            f"الترم: {self.term}\n"
            f"المقرر: {self.course}\n"
            f"العنوان: {self.title}"
        )
