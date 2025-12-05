from __future__ import annotations

from aiogram import Dispatcher

from .channel import middlewares as channel_middleware


async def setup_middlewares(dp: Dispatcher):
    for middleware in channel_middleware:
        dp.message.middleware(middleware())
        dp.callback_query.middleware(middleware())
        dp.inline_query.middleware(middleware())


__all__ = ["setup_middlewares"]
