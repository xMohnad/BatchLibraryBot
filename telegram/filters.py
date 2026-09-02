from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.filters import CommandObject, Filter

if TYPE_CHECKING:
    from aiogram.types import Message


class PrefixDeepLink(Filter):
    """Matches `/start <prefix><value>` deep links and extracts the value."""

    def __init__(self, prefix: str, key: str) -> None:
        self.prefix = prefix
        self.key = key

    async def __call__(self, message: Message, command: CommandObject) -> bool | dict[str, str]:
        if command.args and command.args.startswith(self.prefix):
            return {self.key: command.args.removeprefix(self.prefix)}
        return False


class IdFilter(Filter):
    """Restrict a handler to updates coming from a specific chat id."""

    def __init__(self, chat_id: int) -> None:
        self.chat_id = chat_id

    async def __call__(self, message: Message) -> bool:
        return message.chat.id == self.chat_id
