from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command

if TYPE_CHECKING:
    from aiogram.types import Message

router = Router(name=__name__)


@router.message(Command("id"))
async def get_id(message: Message) -> None:
    response = f"ID: <code>{message.chat.id}</code>\nName: {message.chat.full_name}"
    if message.reply_to_message and (chat := message.reply_to_message.forward_from_chat):
        response += f"\nForwarded From Chat ID: <code>{chat.id}</code>\nChat Name: {chat.full_name}"

    await message.reply(response)
