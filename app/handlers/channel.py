from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import F, Router

from app.services.archiving import copy_to_archive, ingest_media_batch
from config import ARCHIVE_CHANNEL, CHANNEL_ID
from core.filters import IdFilter
from database.models.course import CAPTION_PATTERN, Course, CourseFile, MessageType

if TYPE_CHECKING:
    import re

    from aiogram import Bot
    from aiogram.types import Message

router = Router(name=__name__)

logger = logging.getLogger(__name__)

router.channel_post.filter(IdFilter(CHANNEL_ID))
router.edited_channel_post.filter(IdFilter(CHANNEL_ID))


@router.channel_post(F.content_type.in_(MessageType))
async def handle_media(message: Message, bot: Bot, media_events: list[Message]) -> None:
    """Handle new media posts with caption."""
    await ingest_media_batch(bot, media_events, copy_to_archive_channel=True)


@router.edited_channel_post(
    F.content_type.in_(MessageType),
    F.caption.regexp(CAPTION_PATTERN).as_("match"),
)
async def on_edit(message: Message, bot: Bot, match: re.Match[str]) -> None:
    """Handle edited media posts."""
    logger.info("Editing media post")

    course_name: str = match.group("course")
    if course := await Course.get_course(course_name, match.string):
        if file := course.find_file_by_original_id(message.message_id):
            new_title = match.group("title")
            if file.title == new_title:
                logger.info("Title unchanged for message_id %d, skipping.", file.originalTelegramMessageId)
                return

            file.title = new_title
            await bot.edit_message_caption(
                chat_id=ARCHIVE_CHANNEL,
                message_id=file.archiveTelegramMessageId,
                caption=course.formatted_info(file.title),
            )
            await course.save()
            logger.info("Updated title for message_id %d.", file.originalTelegramMessageId)
        else:
            file = await CourseFile.from_message(message, match)
            copied = await copy_to_archive(bot, file, course.formatted_info(file.title))
            file.archiveTelegramMessageId = copied.message_id
            course.files.append(file)
            await course.save()
            logger.info("Archived new file: message_id %d -> %d.", message.message_id, copied.message_id)
    else:
        logger.warning("Course not found for name: %s. Ignoring edit.", course_name)
