from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from pathlib import Path

from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import Message
from beanie import Document, init_beanie
from pydantic import Field
from pydantic.fields import Field
from rich import inspect, print

from app.data.config import ARCHIVE_CHANNEL
from app.database.base import database
from app.database.models.course import Course, CourseFile
from app.utils import (
    NUMBER,
    get_level,
    get_term,
)
from main import bot


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
            f"#المستوى_{self.level_word} "
            f"#الفصل_{self.term_word}"
        )

    @property
    def level_word(self) -> str:
        return NUMBER[self.level]

    @property
    def term_word(self) -> str:
        return NUMBER[self.term]


async def getFile(old: CourseMaterial):
    try:
        message = await bot.edit_message_caption(
            chat_id=ARCHIVE_CHANNEL,
            message_id=old.message_id,
            caption=old.formatted_info,
        )
    except TelegramRetryAfter as e:
        print(f"Rate limit hit! Sleeping for {e.retry_after} seconds...")
        await asyncio.sleep(e.retry_after)
        return await getFile(old)

    if isinstance(message, Message) and not (
        file := message.document or message.video or message.audio
    ):
        raise ValueError(
            "Message does not contain a supported file (document, video, or audio)."
        )

    if not (file_name := file.file_name) or not (file_size := file.file_size):
        raise ValueError("Invalid file metadata received from Telegram.")

    return CourseFile(
        fileId=file.file_id,
        title=old.title,
        archiveTelegramMessageId=old.course_id,
        originalTelegramMessageId=old.message_id,
        fromChatId=old.from_chat_id,
        chatId=ARCHIVE_CHANNEL,
        originalName=file_name,
        mimeType=file.mime_type,
        sizeBytes=file_size,
        extension=Path(file_name).suffix.lstrip("."),
    )


def parse_course_info(course_str: str) -> str:
    match = re.match(r"^(.*?)\s*\((.*?)\)", course_str)
    assert match
    return match.group(1).strip()


async def main():
    await init_beanie(
        database=database,
        document_models=[CourseMaterial, Course],
    )

    print("Starting Migration...")

    course_files: defaultdict[str, list[CourseFile]] = defaultdict(list)
    async for old in CourseMaterial.find(
        CourseMaterial.term == 2,
        # CourseMaterial.course == "",
    ):
        course_name = parse_course_info(old.course)
        await asyncio.sleep(0.4)
        file = await getFile(old)
        course_files[course_name].append(file)
        inspect(file)

    for name, files in course_files.items():
        if course := await Course.get_course(name, 2):
            await course.upsert_files(files)

    print("Migration Completed Successfully!")


if __name__ == "__main__":
    asyncio.run(main())
