from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest

from app.config import ARCHIVE_CHANNEL
from app.database.models.course import CAPTION_PATTERN, Course, CourseFile, MessageType
from app.filters import IdFilter

if TYPE_CHECKING:
    from aiogram.types import Message

router = Router(name=__name__)

logger = logging.getLogger(__name__)

router.channel_post.filter(IdFilter(ARCHIVE_CHANNEL))
router.edited_channel_post.filter(IdFilter(ARCHIVE_CHANNEL))

DELETE_COMMAND = re.compile(r"^/?del(ete)?$", re.IGNORECASE)
EDIT_COMMAND = re.compile(r"^/?edit$", re.IGNORECASE)


@router.channel_post(F.content_type.in_(MessageType))
async def handle_archive_media(message: Message, media_events: list[Message]) -> None:
    """Handle new media posts with caption."""
    logger.info("Handling new media post")

    course_files, course_captions = await CourseFile.group_media_by_course(media_events)

    for name, files in course_files.items():
        caption = course_captions[name]
        if course := await Course.get_course(name, caption):
            await course.upsert_files(files)


@router.channel_post(
    F.reply_to_message.content_type.in_(MessageType),
    F.reply_to_message.caption.regexp(CAPTION_PATTERN),
    F.reply_to_message.as_("replied"),
    F.text.regexp(DELETE_COMMAND),
)
async def on_del_archive(message: Message, replied: Message) -> None:
    """Handle edited media post."""
    logger.info("Delete command (%s) received", message.text)

    if result := await Course.find_one(
        Course.files.archiveTelegramMessageId == replied.message_id  # pyright: ignore[reportAttributeAccessIssue]
    ):
        await result.update(  # pyright: ignore[reportGeneralTypeIssues]
            {"$pull": {"files": {"archiveTelegramMessageId": replied.message_id}}}
        )
        logger.info("Deleted specific file with message_id %d from course", replied.message_id)

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

    course_name: str = match.group("course")
    if course := await Course.get_course(course_name, match.string):
        file = await CourseFile.from_message(replied, match)
        try:
            await course.upsert_files([file])
            await replied.edit_caption(caption=course.formatted_info(file.title))
            logger.info(
                "Updated course with message_id %d (reply edit)",
                file.archiveTelegramMessageId,
            )
        except TelegramBadRequest as e:
            if "message is not modified" in e.message.lower():
                logger.warning(
                    "Update skipped for Message ID %d: Content is identical.",
                    file.archiveTelegramMessageId,
                )
            else:
                logger.exception(
                    "Telegram API error while updating Message ID %d",
                    file.archiveTelegramMessageId,
                )

    await message.delete()


@router.edited_channel_post(
    F.content_type.in_(MessageType),
    F.caption.regexp(CAPTION_PATTERN).as_("match"),
)
async def on_edit_archive_direct(message: Message, match: re.Match[str]) -> None:
    """Handle direct media edit in channel."""
    logger.info("Direct edit received")

    course_name: str = match.group("course")
    if course := await Course.get_course(course_name, match.string):
        file = await CourseFile.from_message(message, match)
        await course.upsert_files([file])
        logger.info(
            "Updated course with message_id %d (direct edit)",
            file.archiveTelegramMessageId,
        )
