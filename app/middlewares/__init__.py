from __future__ import annotations

from typing import TYPE_CHECKING

from .channel import middlewares as channel_middleware

if TYPE_CHECKING:
    from aiogram import Dispatcher


async def setup_middlewares(dp: Dispatcher):
    for middleware in channel_middleware:
        dp.channel_post.middleware(middleware())
        dp.message.middleware(middleware())


__all__ = ["setup_middlewares"]
