from __future__ import annotations

import re

from aiogram import Bot, F, Router
from aiogram.types import Message, MessageOriginChannel

from app.data.config import ARCHIVE_CHANNEL
from app.database.models import CourseMaterial
from app.utils import CAPTION_PATTERN, SUPPORTED_MEDIA, IdFilter

router = Router(name=__name__)


router.channel_post.filter(IdFilter(ARCHIVE_CHANNEL))
router.edited_channel_post.filter(IdFilter(ARCHIVE_CHANNEL))


@router.channel_post(
    F.content_type.in_(SUPPORTED_MEDIA), F.forward_origin.as_("origin")
)
async def handle_forward_media(
    message: Message, origin: MessageOriginChannel, bot: Bot
) -> None:
    """Handle new forward media post."""
    id = await bot.copy_message(
        ARCHIVE_CHANNEL,
        message.chat.id,
        message.message_id,
    )

    if match := CAPTION_PATTERN.search(message.caption or ""):
        course = await CourseMaterial.parse_course(
            message,
            match,
            course_id=origin.message_id,
            message_id=id.message_id,
            from_chat_id=origin.chat.id,
        )
        await course.insert()

    await message.delete()


@router.channel_post(F.content_type.in_(SUPPORTED_MEDIA))
async def handle_archive_media(message: Message, media_events: list[Message]) -> None:
    """Handle new media posts with caption."""

    caption = media_events[-1].caption or ""
    if match := CAPTION_PATTERN.search(caption):
        courses = [
            await CourseMaterial.parse_course(msg, match) for msg in media_events
        ]
        await CourseMaterial.insert_many(courses)


@router.channel_post(
    F.reply_to_message.content_type.in_(SUPPORTED_MEDIA),
    F.reply_to_message.caption.regexp(CAPTION_PATTERN),
    F.reply_to_message.as_("replied"),
    F.text.contains("del"),
)
async def on_del_archive(message: Message, replied: Message) -> None:
    """Handle edited media post."""

    if original := await CourseMaterial.find_one(
        CourseMaterial.message_id == replied.message_id
    ):
        await original.delete()
        await replied.delete()

    await message.delete()


@router.channel_post(
    F.reply_to_message.content_type.in_(SUPPORTED_MEDIA),
    F.reply_to_message.caption.regexp(CAPTION_PATTERN).as_("match"),
    F.reply_to_message.message_id.as_("message_id"),
    F.text.contains("edit"),
)
@router.edited_channel_post(
    F.content_type.in_(SUPPORTED_MEDIA),
    F.caption.regexp(CAPTION_PATTERN).as_("match"),
    F.message_id.as_("message_id"),
)
async def on_edit_archive(
    message: Message, match: re.Match[str], message_id: int
) -> None:
    """Handle edited media post."""

    course = await CourseMaterial.parse_course(message, match)
    if original := await CourseMaterial.find_one(
        CourseMaterial.message_id == message_id,
    ):
        await original.set(
            course.model_dump(
                exclude={
                    "id",
                    "message_id",
                    "course_id",
                    "from_chat_id",
                }
            )
        )
    else:
        await course.insert()

    if message.reply_to_message and "edit" in (message.text or ""):
        await message.delete()
