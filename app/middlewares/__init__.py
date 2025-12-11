from __future__ import annotations

from aiogram import Dispatcher

from .channel import middlewares as channel_middleware


async def setup_middlewares(dp: Dispatcher):
    for middleware in channel_middleware:
        dp.channel_post.middleware(middleware())


__all__ = ["setup_middlewares"]
