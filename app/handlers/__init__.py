from __future__ import annotations

from typing import TYPE_CHECKING

from .archive import router as archive
from .bot import router as bot
from .channel import router as channel
from .commands import router as commands

if TYPE_CHECKING:
    from aiogram import Dispatcher

routers = [channel, bot, archive, commands]


async def setup_routes(dp: Dispatcher):
    dp.include_routers(*routers)
