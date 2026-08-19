from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aiogram import Dispatcher


# Source - https://stackoverflow.com/a/77894659
# Posted by abuztrade, modified by community. See post 'Timeline' for change history
# Retrieved 2025-12-01, License - CC BY-SA 4.0
class MediaMiddleware(BaseMiddleware):
    """Middleware for handling media groups."""

    def __init__(self, latency: float = 0.01):
        self.medias: dict[str, list[TelegramObject]] = {}
        self.latency = latency
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, object]], Awaitable[object]],
        event: TelegramObject,
        data: dict[str, object],
    ) -> object:
        data["media_events"] = [event]
        if isinstance(event, Message) and event.media_group_id:
            try:
                self.medias[event.media_group_id].append(event)
                return
            except KeyError:
                self.medias[event.media_group_id] = [event]
                await asyncio.sleep(self.latency)

                data["media_events"] = self.medias.pop(event.media_group_id)

        return await handler(event, data)


middlewares = [MediaMiddleware]


async def setup_middlewares(dp: Dispatcher) -> None:
    for middleware in middlewares:
        dp.channel_post.middleware(middleware())
        dp.message.middleware(middleware())
