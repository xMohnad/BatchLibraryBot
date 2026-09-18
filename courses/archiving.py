from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import FSInputFile, URLInputFile

from config import ARCHIVE_CHANNEL
from courses.models import CAPTION_PATTERN, Course, CourseFile
from courses.uploads import ensure_files_uploaded

if TYPE_CHECKING:
    import re
    from pathlib import Path

    from aiogram import Bot
    from aiogram.types import Message, MessageId

logger = logging.getLogger(__name__)

TELEGRAM_UPLOAD_LIMIT = 50 * 1024 * 1024
"""Max size a bot can upload to Telegram via multipart/form-data (hard ceiling)."""

TELEGRAM_URL_SEND_LIMIT = 20 * 1024 * 1024
"""Max size Telegram will fetch itself when a file is sent by URL instead of uploaded directly."""


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


async def send_new_file_to_archive(
    bot: Bot,
    local_path: Path,
    filename: str,
    caption: str,
    size_bytes: int,
    cloudinary_url: str | None = None,
) -> Message:
    """Send a local file to the archive channel, by Cloudinary URL when possible or by direct upload otherwise."""
    if size_bytes > TELEGRAM_UPLOAD_LIMIT:
        raise ValueError(f"File exceeds Telegram's {TELEGRAM_UPLOAD_LIMIT // (1024 * 1024)} MB upload limit.")

    document = (
        URLInputFile(cloudinary_url, filename=filename)
        if cloudinary_url and size_bytes <= TELEGRAM_URL_SEND_LIMIT
        else FSInputFile(local_path, filename=filename)
    )

    try:
        return await bot.send_document(ARCHIVE_CHANNEL, document, caption=caption)
    except TelegramRetryAfter as e:
        logger.warning("Rate limited; sleeping for %s seconds", e.retry_after)
        await asyncio.sleep(e.retry_after)
        return await bot.send_document(ARCHIVE_CHANNEL, document, caption=caption)


async def archive_new_file(bot: Bot, course: Course, file: CourseFile) -> CourseFile:
    """Copy a single new file into the archive channel, attach it to `course`, and persist it."""
    await _copy_and_set_archive_id(bot, course, file)
    course.files.append(file)
    if not await ensure_files_uploaded(course):
        await course.save()
    return file


async def _copy_and_set_archive_id(bot: Bot, course: Course, file: CourseFile) -> MessageId:
    """Helper to copy a single file and set its archiveTelegramMessageId."""
    copied = await copy_to_archive(bot, file, course.formatted_info(file.title))
    file.archiveTelegramMessageId = copied.message_id
    return copied


async def apply_caption_edit(match: re.Match[str], message: Message) -> tuple[Course, CourseFile] | None:
    """Resolve the course for an edited/replied caption and persist the file update."""
    if course := await Course.get_course(match.group("course"), match.string):
        file = CourseFile.from_message(message, match)
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
    default_caption = media_events[-1].caption or ""
    course_files: defaultdict[str, list[CourseFile]] = defaultdict(list)
    course_captions: dict[str, str] = {}

    for msg in media_events:
        caption = msg.caption or default_caption
        if match := CAPTION_PATTERN.search(caption):
            name: str = match.group("course")
            course_files[name].append(CourseFile.from_message(msg, match))
            course_captions.setdefault(name, caption)

    for name, files in course_files.items():
        caption = course_captions[name]
        course = await Course.get_course(name, caption)
        if not course:
            continue

        if copy_to_archive_channel:
            copied_files: list[CourseFile] = []
            for file in files:
                try:
                    await _copy_and_set_archive_id(bot, course, file)
                    copied_files.append(file)
                    logger.info(
                        "Archived new file: message_id %d -> %d.",
                        file.originalTelegramMessageId,
                        file.archiveTelegramMessageId,
                    )
                except TelegramBadRequest:
                    logger.exception(
                        "Failed to copy message_id %d to archive; skipping.",
                        file.originalTelegramMessageId,
                    )

            files = copied_files
            if not files:
                logger.info("Parsed 0 file(s) for course '%s'", name)
                continue

        await course.upsert_files(files)
        await ensure_files_uploaded(course)
        logger.info("Parsed %d file(s) for course '%s'", len(files), name)
