import asyncio
import html
import logging
from typing import Optional

from aiogram import Bot

from app.data.config import LOG_CHANNEL_ID


class TelegramLogHandler(logging.Handler):
    MAX_LEN = 3900

    def __init__(self, bot, chat_id: Optional[int]):
        super().__init__(level=logging.ERROR)
        self.bot = bot
        self.chat_id = chat_id

    def emit(self, record: logging.LogRecord):
        if not self.chat_id:
            return

        try:
            log_entry = self.format(record)
            msg = html.escape(log_entry)

            chunks = [
                msg[i : i + self.MAX_LEN] for i in range(0, len(msg), self.MAX_LEN)
            ]
            total = len(chunks)

            for idx, chunk in enumerate(chunks, start=1):
                text = (
                    f"<b>🚨 {record.levelname} LOG</b>\n"
                    f"📍 <i>{record.name}</i>\n\n"
                    f"<pre>{chunk}</pre>"
                )
                if total > 1:
                    text += f"\n\n<b>📦 Part {idx}/{total}</b>"

                self._send_to_telegram(text)

        except Exception:
            self.handleError(record)

    def _send_to_telegram(self, text: str):
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self.bot.send_message(self.chat_id, text))
        except RuntimeError:
            pass


def setup_logging(bot: Bot) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s\n%(message)s",
    )
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger().addHandler(TelegramLogHandler(bot, LOG_CHANNEL_ID))
