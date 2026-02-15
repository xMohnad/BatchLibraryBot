from __future__ import annotations

import logging
import re
from collections import defaultdict

from aiogram import Bot, F, Router
from aiogram.types import Message

from app.data.config import ARCHIVE_CHANNEL, CHANNEL_ID
from app.database.models.course import Course, CourseFile, MessageType
from app.utils import CAPTION_PATTERN, IdFilter

router = Router(name=__name__)

logger = logging.getLogger(__name__)

router.channel_post.filter(IdFilter(CHANNEL_ID))
router.edited_channel_post.filter(IdFilter(CHANNEL_ID))


@router.channel_post(F.content_type.in_(MessageType))
async def handle_media(message: Message, bot: Bot, media_events: list[Message]) -> None:
    """Handle new media posts with caption."""
    logger.info("Handling new media post")
    default = media_events[-1].caption or ""
    course_files: defaultdict[str, list[CourseFile]] = defaultdict(list)
    for msg in media_events:
        caption = msg.caption or default
        if match := CAPTION_PATTERN.search(caption):
            course_title: str = match.group("course")
            course_file = await CourseFile.parse_file(msg, match)
            course_files[course_title].append(course_file)

    for name, files in course_files.items():
        if course := await Course.get_course(name):
            for file in files:
                logger.info(
                    "Copying course to archive. Original message_id: %d",
                    file.originalTelegramMessageId,
                )
                copied = await bot.copy_message(
                    ARCHIVE_CHANNEL,
                    file.fromChatId,
                    file.originalTelegramMessageId,
                    caption=course.formatted_info(file.title),
                )
                file.archiveTelegramMessageId = copied.message_id

                logger.info("Course copied. New message_id: %d", copied.message_id)
            await course.upsert_files(files)
            logger.info("Parsed %d courses from media posts", len(files))


@router.edited_channel_post(
    F.content_type.in_(MessageType),
    F.caption.regexp(CAPTION_PATTERN).as_("match"),
)
async def on_edit(message: Message, bot: Bot, match: re.Match[str]) -> None:
    """Handle edited media posts."""
    logger.info("Editing media post")

    course_name: str = match.group("course")
    if course := await Course.get_course(course_name):
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
            file = await CourseFile.parse_file(message, match)
            logger.info(
                "Copying course to archive. Original message_id: %d",
                file.originalTelegramMessageId,
            )
            copied = await bot.copy_message(
                ARCHIVE_CHANNEL,
                file.fromChatId,
                file.originalTelegramMessageId,
                caption=course.formatted_info(file.title),
            )
            file.archiveTelegramMessageId = copied.message_id
            course.files.append(file)
            await course.save()
            logger.info("Course copied. New message_id: %d", copied.message_id)
    else:
        logger.warning(f"Course not found for name: {course_name}. Ignoring edit.")
