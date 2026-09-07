from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest

from config import ARCHIVE_CHANNEL
from courses.archiving import apply_caption_edit, ingest_media_batch
from courses.models import CAPTION_PATTERN, Course, MessageType
from telegram.filters import IdFilter

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
    """Soft-delete an archived file from its course when a delete command is sent in reply to it."""
    logger.info("Delete command (%s) received", message.text)

    if result := await Course.find_by_file_archive_id(replied.message_id):
        course, file = result
        file.mark_deleted()
        await course.save()
        logger.info("Marked file (message_id=%d) as deleted in course %r", replied.message_id, course.courseName)
    else:
        logger.warning("No active file found (message_id=%d)", replied.message_id)

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
