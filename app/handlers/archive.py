from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from beanie.operators import Pull

from app.services.archiving import apply_caption_edit, ingest_media_batch
from config import ARCHIVE_CHANNEL
from core.filters import IdFilter
from database.models.course import CAPTION_PATTERN, Course, MessageType

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message

router = Router(name=__name__)

logger = logging.getLogger(__name__)

router.channel_post.filter(IdFilter(ARCHIVE_CHANNEL))
router.edited_channel_post.filter(IdFilter(ARCHIVE_CHANNEL))

DELETE_COMMAND = re.compile(r"^/?del(ete)?$", re.IGNORECASE)
EDIT_COMMAND = re.compile(r"^/?edit$", re.IGNORECASE)


@router.channel_post(F.content_type.in_(MessageType))
async def handle_archive_media(message: Message, bot: Bot, media_events: list[Message]) -> None:
    """Handle new media posts with caption."""
    await ingest_media_batch(bot, media_events, copy_to_archive_channel=False)


@router.channel_post(
    F.reply_to_message.content_type.in_(MessageType),
    F.reply_to_message.caption.regexp(CAPTION_PATTERN),
    F.reply_to_message.as_("replied"),
    F.text.regexp(DELETE_COMMAND),
)
async def on_del_archive(message: Message, replied: Message) -> None:
    """Remove an archived file from its course when a delete command is sent in reply to it."""
    logger.info("Delete command (%s) received", message.text)

    if course := await Course.find_one(
        Course.files.archiveTelegramMessageId == replied.message_id  # pyright: ignore[reportAttributeAccessIssue]
    ):
        await course.update(Pull({"files": {"archiveTelegramMessageId": replied.message_id}}))
        logger.info("Deleted file (message_id=%d) from course %r", replied.message_id, course.courseName)
    else:
        logger.warning("No course found containing file (message_id=%d)", replied.message_id)

    await message.delete()


@router.channel_post(
    F.reply_to_message.content_type.in_(MessageType),
    F.reply_to_message.caption.regexp(CAPTION_PATTERN).as_("match"),
    F.reply_to_message.as_("replied"),
    F.text.regexp(EDIT_COMMAND),
)
async def on_edit_archive_reply(
    message: Message,
    match: re.Match[str],
    replied: Message,
) -> None:
    """Handle edit command sent as a reply."""
    logger.info("Edit command (%s) received", message.text)

    if result := await apply_caption_edit(match, replied):
        course, file = result
        try:
            await replied.edit_caption(caption=course.formatted_info(file.title))
        except TelegramBadRequest as e:
            if "message is not modified" in e.message.lower():
                logger.info("Skip update: message %d unchanged", file.archiveTelegramMessageId)
            else:
                logger.exception("Failed to update Telegram Message ID %d", file.archiveTelegramMessageId)

    await message.delete()


@router.edited_channel_post(
    F.content_type.in_(MessageType),
    F.caption.regexp(CAPTION_PATTERN).as_("match"),
)
async def on_edit_archive_direct(message: Message, match: re.Match[str]) -> None:
    """Handle direct media edit in channel."""
    logger.info("Direct edit received")
    await apply_caption_edit(match, message)
