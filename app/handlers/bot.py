from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import F, Router, html
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import ReplyKeyboardRemove

from app.core.filters import RegistrationDeepLink
from app.scene import SceneRegistry, register_scene
from config import REGISTRATION_CODE_TTL_MINUTES
from database.models.registration import PendingRegistration

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message, User

router = Router(name="bot")
router.message.filter(F.chat.type == "private")


register_scene(SceneRegistry(router))


@router.message(CommandStart(), RegistrationDeepLink())
async def start_registration(message: Message, bot: Bot, event_from_user: User, registration_token: str) -> None:
    pending = await PendingRegistration.find_one(PendingRegistration.token == registration_token)

    if pending is None or pending.is_expired:
        await message.answer("رابط التسجيل غير صالح أو منتهي الصلاحية.")
        return

    if error := await pending.validate_for_telegram(bot=bot, telegram_user=event_from_user):
        await message.answer(error)
        return

    code = pending.issue_code(telegram_user=event_from_user)
    await pending.save()

    await message.answer(
        f"رمز التحقق الخاص بك: <code>{code}</code>\n"
        f"صالح لمدة {REGISTRATION_CODE_TTL_MINUTES} دقائق فقط.\n\n"
        "⚠️ لا تشارك هذا الرمز مع أي شخص."
    )


@router.message(Command("id"))
async def get_id(message: Message, event_from_user: User) -> None:
    lines = [
        f"Your Name: {event_from_user.full_name}",
        f"Your ID: <code>{event_from_user.id}</code>",
    ]
    if message.reply_to_message and (chat := message.reply_to_message.forward_from_chat):
        lines.append(f"Chat Name: {chat.full_name}")
        lines.append(f"Forwarded From Chat ID: <code>{chat.id}</code>")

    await message.reply("\n".join(lines))


@router.message(CommandStart())
async def start(message: Message, event_from_user: User) -> None:
    await message.answer(
        f"Hello, {html.bold(event_from_user.full_name)}! Use /browse to start browsing.",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )
