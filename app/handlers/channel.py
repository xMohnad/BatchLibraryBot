from __future__ import annotations

import asyncio
import re

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command, or_f
from aiogram.types import Message, User

from app.data.config import ARCHIVE_CHANNEL, CHANNEL_ID
from app.database.models import CourseMaterial
from app.utils import CAPTION_PATTERN, SUPPORTED_MEDIA

router = Router(name=__name__)
router.message.filter(F.chat.id == CHANNEL_ID)


def parse_course(message: Message, match: re.Match[str]) -> CourseMaterial:
    """Parse course information from a message caption."""
    level, term, course, title = match.groups()
    return CourseMaterial(
        course_id=message.media_group_id or message.message_id,
        level=level.strip(),
        term=term.strip(),
        course=course.strip(),
        title=title.strip(),
        message_id=message.message_id,
        from_chat_id=message.chat.id,
    )


async def is_admin(bot: Bot, user_id: int) -> bool:
    """Check if a user is admin in the channel."""
    member = await bot.get_chat_member(CHANNEL_ID, user_id)
    return member.status in [ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR]


async def insert_courses(messages: list[Message], match: re.Match[str]) -> None:
    """Insert multiple course materials into the database in bulk."""
    courses = [parse_course(msg, match) for msg in messages]
    if courses:
        await CourseMaterial.insert_many(courses)


@router.message(
    F.caption.regexp(CAPTION_PATTERN).as_("match"),
    F.content_type.in_(SUPPORTED_MEDIA),
    F.media_group_id.is_(None),
)
async def handle_media(message: Message, match: re.Match) -> None:
    """Handle single media messages."""
    await insert_courses([message], match)
    await message.reply("تم الإستلام. بانتظار موافقة الإدارة.")


@router.message(F.content_type.in_(SUPPORTED_MEDIA), F.media_group_id)
async def handle_group_media(message: Message, media_events: list[Message]) -> None:
    """Handle media groups."""
    caption = media_events[-1].caption or ""
    if match := CAPTION_PATTERN.search(caption):
        await insert_courses(media_events, match)
        await message.reply("تم الإستلام. بانتظار موافقة الإدارة.")


@router.message(
    or_f(Command("remove"), Command("add")),
    F.reply_to_message.as_("replied"),
    F.reply_to_message.content_type.in_(SUPPORTED_MEDIA),
)
async def handle_courses(
    message: Message, replied: Message, bot: Bot, event_from_user: User
):
    if not await is_admin(bot, event_from_user.id):
        await message.reply("You are NOT an admin.")
        return

    course_id = replied.media_group_id or replied.message_id
    courses = CourseMaterial.find(
        CourseMaterial.course_id == course_id,
        CourseMaterial.isarchived == False,
    )

    if courses and "/remove" in (message.text or ""):
        await courses.delete_many()
        await message.reply(
            f"Removed successfully. Thanks for your efforts, {event_from_user.full_name}"
        )
        return

    courses = await courses.to_list()

    # Bulk copy messages and update database
    async def copy_and_update(course: CourseMaterial):
        copied_msg = await bot.copy_message(
            ARCHIVE_CHANNEL,
            course.from_chat_id,
            course.message_id,
            caption=course.formatted_info,
        )
        await course.set(
            {
                CourseMaterial.message_id: copied_msg.message_id,
                CourseMaterial.isarchived: True,
            }
        )

    await asyncio.gather(*(copy_and_update(c) for c in courses))
    await message.reply(
        f"Archived successfully. Thanks for your efforts, {event_from_user.full_name}"
    )
