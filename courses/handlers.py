from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart

from config import ARCHIVE_CHANNEL
from courses.models import FILE_DEEP_LINK_PREFIX, Course
from telegram.filters import PrefixDeepLink

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message

router = Router(name="courses")
router.message.filter(F.chat.type == "private")

logger = logging.getLogger(__name__)


@router.message(CommandStart(), PrefixDeepLink(FILE_DEEP_LINK_PREFIX, "file_archive_id"))
async def send_file_by_deep_link(message: Message, bot: Bot, file_archive_id: str) -> None:
    """Send a single course file to the user via a `/start file<archiveMessageId>` deep link."""
    if not file_archive_id.isdigit():
        await message.answer("رابط غير صالح.")
        return

    result = await Course.find_by_file_archive_id(int(file_archive_id))
    if result is None:
        await message.answer("الملف غير موجود.")
        return

    _, file = result
    try:
        await bot.copy_message(message.chat.id, ARCHIVE_CHANNEL, file.archiveTelegramMessageId)
    except TelegramBadRequest:
        logger.exception("Failed to send file via deep link | archiveId=%d", file.archiveTelegramMessageId)
        await message.answer("حدث خطأ أثناء إرسال الملف.")
