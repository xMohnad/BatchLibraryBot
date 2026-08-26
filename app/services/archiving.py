from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from app.services.uploads import ensure_files_uploaded
from config import ARCHIVE_CHANNEL
from database.models.course import Course, CourseFile

if TYPE_CHECKING:
    import re

    from aiogram import Bot
    from aiogram.types import Message, MessageId

logger = logging.getLogger(__name__)


async def copy_to_archive(bot: Bot, file: CourseFile, caption: str) -> MessageId:
    """Copy a message to the archive channel, retrying once on flood-wait."""
    try:
        return await bot.copy_message(
            ARCHIVE_CHANNEL,
            file.fromChatId,
            file.originalTelegramMessageId,
            caption=caption,
        )
    except TelegramRetryAfter as e:
        logger.warning("Rate limited; sleeping for %s seconds", e.retry_after)
        await asyncio.sleep(e.retry_after)
        return await bot.copy_message(
            ARCHIVE_CHANNEL,
            file.fromChatId,
            file.originalTelegramMessageId,
            caption=caption,
        )


async def _copy_course_files(bot: Bot, course: Course, files: list[CourseFile]) -> list[CourseFile]:
    """Copy each file into the archive channel, skipping (and logging) failures."""
    copied_files: list[CourseFile] = []
    for file in files:
        try:
            copied = await copy_to_archive(bot, file, course.formatted_info(file.title))
        except TelegramBadRequest:
            logger.exception(
                "Failed to copy message_id %d to archive; skipping.",
                file.originalTelegramMessageId,
            )
            continue

        file.archiveTelegramMessageId = copied.message_id
        copied_files.append(file)
        logger.info("Archived new file: message_id %d -> %d.", file.originalTelegramMessageId, copied.message_id)

    return copied_files


async def apply_caption_edit(match: re.Match[str], message: Message) -> tuple[Course, CourseFile] | None:
    """Resolve the course for an edited/replied caption and persist the file update."""
    if course := await Course.get_course(match.group("course"), match.string):
        file = await CourseFile.from_message(message, match)
        await course.upsert_files([file])
        await ensure_files_uploaded(course)
        logger.info("Updated course with message_id %d", file.archiveTelegramMessageId)
        return course, file


async def ingest_media_batch(bot: Bot, media_events: list[Message], *, copy_to_archive_channel: bool) -> None:
    """Group a batch of channel media by course and persist it.

    Set `copy_to_archive_channel=True` for posts coming from the source channel
    (they still need to be copied into the archive channel first). Set it to
    `False` for posts that already live in the archive channel.
    """
    course_files, course_captions = await CourseFile.group_media_by_course(media_events)

    for name, files in course_files.items():
        caption = course_captions[name]
        course = await Course.get_course(name, caption)
        if not course:
            continue

        if copy_to_archive_channel:
            files = await _copy_course_files(bot, course, files)
            if not files:
                logger.info("Parsed 0 file(s) for course '%s'", name)
                continue

        await course.upsert_files(files)
        await ensure_files_uploaded(course)
        logger.info("Parsed %d file(s) for course '%s'", len(files), name)
