from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.filters import Filter

if TYPE_CHECKING:
    from aiogram.types import Message


class IdFilter(Filter):
    """Restrict a handler to updates coming from a specific chat id."""

    def __init__(self, chat_id: int) -> None:
        self.chat_id = chat_id

    async def __call__(self, message: Message) -> bool:
        return message.chat.id == self.chat_id
