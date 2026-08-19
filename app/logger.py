from __future__ import annotations

import asyncio
import html
import logging
from typing import TYPE_CHECKING

from app.data.config import LOG_CHANNEL_ID

if TYPE_CHECKING:
    from aiogram import Bot


class TelegramLogHandler(logging.Handler):
    MAX_LEN = 3900

    def __init__(self, bot: Bot, chat_id: int | None) -> None:
        super().__init__(level=logging.ERROR)
        self.bot = bot
        self.chat_id = chat_id

    def emit(self, record: logging.LogRecord):
        if not (chat_id := self.chat_id):
            return

        try:
            log_entry = self.format(record)
            msg = html.escape(log_entry)

            chunks = [msg[i : i + self.MAX_LEN] for i in range(0, len(msg), self.MAX_LEN)]
            total = len(chunks)

            for idx, chunk in enumerate(chunks, start=1):
                text = f"<b>🚨 {record.levelname} LOG</b>\n📍 <i>{record.name}</i>\n\n<pre>{chunk}</pre>"
                if total > 1:
                    text += f"\n\n<b>📦 Part {idx}/{total}</b>"

                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.bot.send_message(chat_id, text))
                except RuntimeError:
                    pass

        except Exception:  # noqa: BLE001
            self.handleError(record)


def setup_logging(bot: Bot) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s\n%(message)s",
    )
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    telegram_handler = TelegramLogHandler(bot, LOG_CHANNEL_ID)
    logging.getLogger("aiogram").addHandler(telegram_handler)
    logging.getLogger().addHandler(telegram_handler)
