from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name=__name__)


@router.message(Command("id"))
async def get_id(message: Message) -> None:
    response = f"ID: <code>{message.chat.id}</code>\nName: {message.chat.full_name}"
    if message.reply_to_message and (
        chat := message.reply_to_message.forward_from_chat
    ):
        response += (
            f"\nForwarded From Chat ID: <code>{chat.id}</code>"
            f"\nChat Name: {chat.full_name}"
        )

    await message.reply(response)
