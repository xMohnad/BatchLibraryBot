from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart

from accounts.models import PendingRegistration, User
from config import (
    CHANNEL_ID,
    REGISTRATION_CODE_TTL_MINUTES,
    REGISTRATION_MAX_CODE_SENDS,
)
from telegram.filters import PrefixDeepLink

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message
    from aiogram.types import User as TelegramUser

router = Router(name="accounts")
router.message.filter(F.chat.type == "private")

REGISTRATION_DEEP_LINK_PREFIX = "reg_"

ALLOWED_CHAT_MEMBER_STATUSES = {
    ChatMemberStatus.CREATOR,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.RESTRICTED,
}


@router.message(CommandStart(), PrefixDeepLink(REGISTRATION_DEEP_LINK_PREFIX, "registration_token"))
async def start_registration(
    message: Message, bot: Bot, event_from_user: TelegramUser, registration_token: str
) -> None:
    pending = await PendingRegistration.find_one(PendingRegistration.token == registration_token)
    if pending is None or pending.is_expired:
        await message.answer("رابط التسجيل غير صالح أو منتهي الصلاحية.")
        return

    # Already registered
    if await User.get_by_telegram_id(event_from_user.id):
        await message.answer("حسابك مسجّل بالفعل، يمكنك تسجيل الدخول مباشرة.")
        return

    # Token bound to another user
    if pending.telegramId is not None and pending.telegramId != event_from_user.id:
        await message.answer("هذا الرابط مرتبط بحساب مختلف.")
        return

    # Channel membership
    try:
        member = await bot.get_chat_member(CHANNEL_ID, event_from_user.id)
    except TelegramBadRequest:
        await message.answer("تعذر التحقق من عضويتك، حاول لاحقًا.")
        return

    if member.status not in ALLOWED_CHAT_MEMBER_STATUSES:
        await message.answer("يجب أن تكون عضوًا في قناة الدفعة لإتمام التسجيل.")
        return

    # Rate limit (resend cooldown)
    if pending.is_in_cooldown:
        await message.answer("الرجاء الانتظار قليلًا قبل طلب رمز جديد.")
        return

    # Max sends
    if pending.codeSendCount >= REGISTRATION_MAX_CODE_SENDS:
        await message.answer("تجاوزت الحد الأقصى لطلب رمز التحقق لهذا التسجيل. الرجاء التسجيل من جديد.")
        return

    code = pending.issue_code(event_from_user.id, event_from_user.username)
    await pending.save()

    await message.answer(
        f"رمز التحقق الخاص بك: <code>{code}</code>\n"
        f"صالح لمدة {REGISTRATION_CODE_TTL_MINUTES} دقائق فقط.\n\n"
        "⚠️ لا تشارك هذا الرمز مع أي شخص."
    )
