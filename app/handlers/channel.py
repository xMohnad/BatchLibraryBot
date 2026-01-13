from __future__ import annotations

import asyncio
import logging
import re

from aiogram import Bot, F, Router
from aiogram.types import Message

from app.data.config import ARCHIVE_CHANNEL, CHANNEL_ID
from app.database.models import CourseMaterial
from app.utils import CAPTION_PATTERN, SUPPORTED_MEDIA, IdFilter

router = Router(name=__name__)

logger = logging.getLogger(__name__)

router.channel_post.filter(IdFilter(CHANNEL_ID))
router.edited_channel_post.filter(IdFilter(CHANNEL_ID))


async def copy_and_update(course: CourseMaterial, bot: Bot) -> CourseMaterial:
    """Copy message to archive and insert course."""
    logger.info("Copying course to archive. Original message_id: %d", course.message_id)
    copied = await bot.copy_message(
        ARCHIVE_CHANNEL,
        course.from_chat_id,
        course.message_id,
        caption=course.formatted_info,
    )
    course.message_id = copied.message_id
    await course.insert()
    logger.info("Course copied. New message_id: %d", course.message_id)
    return course


@router.channel_post(F.content_type.in_(SUPPORTED_MEDIA))
async def handle_media(message: Message, bot: Bot, media_events: list[Message]) -> None:
    """Handle new media posts with caption."""
    logger.info("Handling new media post")
    caption = media_events[-1].caption or ""
    if match := CAPTION_PATTERN.search(caption):
        courses = [
            await CourseMaterial.parse_course(msg, match) for msg in media_events
        ]
        logger.info("Parsed %d courses from media posts", len(courses))
        await asyncio.gather(*(copy_and_update(c, bot) for c in courses))


@router.edited_channel_post(
    F.content_type.in_(SUPPORTED_MEDIA),
    F.caption.regexp(CAPTION_PATTERN).as_("match"),
)
async def on_edit(message: Message, bot: Bot, match: re.Match[str]) -> None:
    """Handle edited media posts."""
    logger.info("Editing media post")
    course = await CourseMaterial.parse_course(message, match)
    if original := await CourseMaterial.find_one(
        CourseMaterial.course_id == message.message_id
    ):
        if original != course:
            await original.set(course.model_dump(exclude={"id", "message_id"}))
            await bot.edit_message_caption(
                chat_id=ARCHIVE_CHANNEL,
                message_id=course.message_id,
                caption=course.formatted_info,
            )
            logger.info("Updated archived course. message_id: %d", course.message_id)
    else:
        await copy_and_update(course, bot)
