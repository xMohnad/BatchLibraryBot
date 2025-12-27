from __future__ import annotations

from aiogram import F, Router, html
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardRemove, User

from app.scene import SceneRegistry, register_scene

router = Router(name="bot")
router.message.filter(F.chat.type == "private")
registry = SceneRegistry(router)


register_scene(registry)


@router.message(CommandStart())
async def start(message: Message, event_from_user: User) -> None:
    await message.answer(
        f"Hello, {html.bold(event_from_user.full_name)}! Use /browse to start browsing.",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )
