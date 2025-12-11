from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.database.base import client


# Source - https://stackoverflow.com/a/77894659
# Posted by abuztrade, modified by community. See post 'Timeline' for change history
# Retrieved 2025-12-01, License - CC BY-SA 4.0
class MediaMiddleware(BaseMiddleware):
    """Middleware for handling media groups"""

    def __init__(self, latency: int | float = 0.01):
        self.medias = {}
        self.latency = latency
        super(MediaMiddleware, self).__init__()

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
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


class DatabaseMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with client.start_session() as session:
            data["session"] = session
            await handler(event, data)


middlewares = [DatabaseMiddleware, MediaMiddleware]

__all__ = ["middlewares"]
