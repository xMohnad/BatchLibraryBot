from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import F, Router, html
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import ReplyKeyboardRemove

from telegram.scenes import SceneRegistry, register_scene

if TYPE_CHECKING:
    from aiogram.types import Message, User

router = Router(name="bot")
router.message.filter(F.chat.type == "private")


register_scene(SceneRegistry(router))


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
