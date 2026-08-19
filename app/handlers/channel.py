from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from app.data.config import ARCHIVE_CHANNEL, CHANNEL_ID
from app.database.models.course import Course, CourseFile, MessageType
from app.utils import CAPTION_PATTERN, IdFilter, group_media_by_course

if TYPE_CHECKING:
    import re

    from aiogram.types import Message, MessageId

router = Router(name=__name__)

logger = logging.getLogger(__name__)

router.channel_post.filter(IdFilter(CHANNEL_ID))
router.edited_channel_post.filter(IdFilter(CHANNEL_ID))


@router.channel_post(F.content_type.in_(MessageType))
async def handle_media(message: Message, bot: Bot, media_events: list[Message]) -> None:
    """Handle new media posts with caption."""
    logger.info("Handling new media post")

    course_files, course_captions = await group_media_by_course(media_events)

    for name, files in course_files.items():
        caption = course_captions[name]
        if course := await Course.get_course(name, caption):
            copied_files: list[CourseFile] = []
            for file in files:
                logger.info(
                    "Copying course to archive. Original message_id: %d",
                    file.originalTelegramMessageId,
                )
                try:
                    copied = await _copy_to_archive(bot, file, course.formatted_info(file.title))
                except TelegramBadRequest:
                    logger.exception(
                        "Failed to copy message_id %d to archive; skipping file.",
                        file.originalTelegramMessageId,
                    )
                    continue

                file.archiveTelegramMessageId = copied.message_id
                copied_files.append(file)

                logger.info("Course copied. New message_id: %d", copied.message_id)

            if copied_files:
                await course.upsert_files(copied_files)
            logger.info("Parsed %d file(s) for course '%s'", len(copied_files), name)


async def _copy_to_archive(bot: Bot, file: CourseFile, caption: str) -> MessageId:
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


@router.edited_channel_post(
    F.content_type.in_(MessageType),
    F.caption.regexp(CAPTION_PATTERN).as_("match"),
)
async def on_edit(message: Message, bot: Bot, match: re.Match[str]) -> None:
    """Handle edited media posts."""
    logger.info("Editing media post")

    course_name: str = match.group("course")
    if course := await Course.get_course(course_name, match.string):
        files_by_id = {f.originalTelegramMessageId: f for f in course.files}
        if message.message_id in files_by_id:
            file = files_by_id[message.message_id]
            if file.title == match.group("title"):
                logger.info("Title is identical. No changes needed. Skipping update.")
                return

            file.title = match.group("title")
            logger.info(
                "Updated course with message_id %d (channel edit)",
                file.archiveTelegramMessageId,
            )
            await bot.edit_message_caption(
                chat_id=ARCHIVE_CHANNEL,
                message_id=file.archiveTelegramMessageId,
                caption=course.formatted_info(file.title),
            )
            logger.info(
                "Updated archived course. message_id: %d",
                file.originalTelegramMessageId,
            )
            await course.save()
            logger.info("Course document saved with updated file title.")
        else:
            logger.info(
                f"File NOT found in course (Message ID: {message.message_id}). Treating as new file addition..."
            )
            file = await CourseFile.from_message(message, match)
            logger.info(
                "Copying course to archive. Original message_id: %d",
                file.originalTelegramMessageId,
            )

            copied = await _copy_to_archive(bot, file, course.formatted_info(file.title))

            file.archiveTelegramMessageId = copied.message_id
            course.files.append(file)
            await course.save()
            logger.info("Course copied. New message_id: %d", copied.message_id)
    else:
        logger.warning(f"Course not found for name: {course_name}. Ignoring edit.")
