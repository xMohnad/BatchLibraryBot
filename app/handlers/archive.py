from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.types import Message

from app.data.config import ARCHIVE_CHANNEL
from app.database.models.course import Course, CourseFile
from app.utils import CAPTION_PATTERN, SUPPORTED_MEDIA, IdFilter

router = Router(name=__name__)

logger = logging.getLogger(__name__)

router.channel_post.filter(IdFilter(ARCHIVE_CHANNEL))
router.edited_channel_post.filter(IdFilter(ARCHIVE_CHANNEL))

from collections import defaultdict


@router.channel_post(F.content_type.in_(SUPPORTED_MEDIA))
async def handle_archive_media(message: Message, media_events: list[Message]) -> None:
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
            await course.upsert_files(files)


@router.channel_post(
    F.reply_to_message.content_type.in_(SUPPORTED_MEDIA),
    F.reply_to_message.caption.regexp(CAPTION_PATTERN),
    F.reply_to_message.as_("replied"),
    F.text.contains("del"),
)
async def on_del_archive(message: Message, replied: Message) -> None:
    """Handle edited media post."""
    logger.info("Delete command (%s) received", message.text)

    if result := await Course.find_one(
        Course.files.archiveTelegramMessageId == replied.message_id  # pyright: ignore[reportAttributeAccessIssue]
    ):
        await replied.delete()
        await result.update(  # pyright: ignore[reportGeneralTypeIssues]
            {"$pull": {"files": {"archiveTelegramMessageId": replied.message_id}}}
        )
        logger.info(
            "Deleted specific file with message_id %d from course", replied.message_id
        )

    await message.delete()


@router.channel_post(
    F.reply_to_message.content_type.in_(SUPPORTED_MEDIA),
    F.reply_to_message.caption.regexp(CAPTION_PATTERN).as_("match"),
    F.reply_to_message.as_("replied"),
    F.text.contains("edit"),
)
async def on_edit_archive_reply(
    message: Message,
    match: re.Match[str],
    replied: Message,
) -> None:
    """Handle edit command sent as a reply."""
    logger.info("Edit command (%s) received", message.text)

    course_name: str = match.group("course")
    if course := await Course.get_course(course_name):
        file = await CourseFile.parse_file(replied, match)
        await course.upsert_files([file])
        logger.info(
            "Updated course with message_id %d (reply edit)",
            file.archiveTelegramMessageId,
        )

    await message.delete()


@router.edited_channel_post(
    F.content_type.in_(SUPPORTED_MEDIA),
    F.caption.regexp(CAPTION_PATTERN).as_("match"),
)
async def on_edit_archive_direct(message: Message, match: re.Match[str]) -> None:
    """Handle direct media edit in channel."""
    logger.info("Direct edit received")

    course_name: str = match.group("course")
    if course := await Course.get_course(course_name):
        file = await CourseFile.parse_file(message, match)
        await course.upsert_files([file])
        logger.info(
            "Updated course with message_id %d (direct edit)",
            file.archiveTelegramMessageId,
        )
