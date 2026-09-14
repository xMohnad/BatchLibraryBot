from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import FSInputFile, URLInputFile

from config import ARCHIVE_CHANNEL
from core.audit import ActionType, Actor, AuditLog, FieldChange
from courses.models import Course, CourseFile
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


async def apply_caption_edit(match: re.Match[str], message: Message, actor: Actor) -> tuple[Course, CourseFile] | None:
    """Resolve the course for an edited/replied caption and persist the file update."""
    course = await Course.get_course(match.group("course"), match.string)
    if course is None:
        return None

    file = CourseFile.from_message(message, match)
    await _log_file_upserts(course, [file], actor)
    await ensure_files_uploaded(course)
    logger.info("Updated course with message_id %d", file.archiveTelegramMessageId)

    return course, file


async def _log_file_upserts(course: Course, new_files: list[CourseFile], actor: Actor) -> None:
    """Upsert `new_files` into `course` and record an audit entry for each add/edit."""
    old_files = {f.archiveTelegramMessageId: f.model_copy() for f in course.files}
    if not await course.upsert_files(new_files):
        return

    entries = []
    for file in new_files:
        old_file = old_files.get(file.archiveTelegramMessageId)
        changes = FieldChange.diff(old_file, file, CourseFile.AUDIT_FIELDS)
        if not changes:
            continue

        entries.append(
            AuditLog.build_file_audit(
                course=course,
                file=file,
                action=ActionType.UPDATE if old_file else ActionType.CREATE,
                actor=actor,
                changes=changes,
                via_telegram=True,
            )
        )

    await AuditLog.record_many(entries)


async def ingest_media_batch(bot: Bot, media_events: list[Message], *, copy_to_archive_channel: bool) -> None:
    """Group a batch of channel media by course and persist it.

    Set `copy_to_archive_channel=True` for posts coming from the source channel
    (they still need to be copied into the archive channel first). Set it to
    `False` for posts that already live in the archive channel.
    """
    course_files, course_captions = await CourseFile.group_media_by_course(media_events)
    actor = await Actor.from_telegram_user(media_events[0].from_user if media_events else None)

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

        await _log_file_upserts(course, files, actor)
        await ensure_files_uploaded(course)
        logger.info("Parsed %d file(s) for course '%s'", len(files), name)
