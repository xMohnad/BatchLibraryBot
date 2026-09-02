from __future__ import annotations

from typing import TYPE_CHECKING

from accounts.handlers import router as accounts
from courses.archive_handlers import router as archive
from courses.channel_handlers import router as channel
from courses.handlers import router as courses
from telegram.bot_handlers import router as bot

if TYPE_CHECKING:
    from aiogram import Dispatcher

routers = [channel, accounts, courses, bot, archive]


def setup_routes(dp: Dispatcher):
    dp.include_routers(*routers)
