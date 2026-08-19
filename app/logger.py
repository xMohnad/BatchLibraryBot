from __future__ import annotations

import asyncio
import html
import logging
from typing import TYPE_CHECKING

from app.config import LOG_CHANNEL_ID

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message

_CHUNK_SIZE = 3000
_TELEGRAM_MESSAGE_LIMIT = 4096


class TelegramLogHandler(logging.Handler):
    """Forward ERROR+ log records to a Telegram chat, split into safe-sized chunks."""

    def __init__(self, bot: Bot, chat_id: int | None) -> None:
        super().__init__(level=logging.ERROR)
        self.bot = bot
        self.chat_id = chat_id
        self._tasks: set[asyncio.Task[Message]] = set()

    def emit(self, record: logging.LogRecord) -> None:
        if not self.chat_id:
            return

        try:
            message = self.format(record)
            for text in self._build_messages(record, message):
                self._schedule_send(text)
        except Exception:  # noqa: BLE001
            self.handleError(record)

    def _build_messages(self, record: logging.LogRecord, message: str) -> list[str]:
        """Split raw `message` into chunks and wrap each as a readable Telegram message.

        Chunking happens on the *raw* text before escaping, so no HTML entity
        (e.g. `&amp;`) is ever cut in half.
        """
        raw_chunks = [message[i : i + _CHUNK_SIZE] for i in range(0, len(message), _CHUNK_SIZE)] or [""]
        total = len(raw_chunks)

        texts = []
        for idx, chunk in enumerate(raw_chunks, start=1):
            part = f" <code>{idx}/{total}</code>" if total > 1 else ""
            header = f"<b>{record.levelname}</b>{part} · <code>{html.escape(record.name)}</code> · <code>{record.filename}:{record.lineno}</code>\n\n"

            code = f'<pre><code class="language-python">{html.escape(chunk)}</code></pre>'
            body = f"<blockquote expandable>{code}</blockquote>"

            texts.append((header + body)[:_TELEGRAM_MESSAGE_LIMIT])  # defensive hard cap
        return texts

    def _schedule_send(self, text: str) -> None:
        """Fire-and-forget the send, keeping a reference so the task isn't GC'd mid-flight."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        if chat_id := self.chat_id:
            task = loop.create_task(self.bot.send_message(chat_id, text))
            self._tasks.add(task)
            task.add_done_callback(self._on_send_done)

    def _on_send_done(self, task: asyncio.Task[Message]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (exc := task.exception()):
            # Print rather than log, to avoid feeding back into this same handler.
            print(f"[TelegramLogHandler] failed to deliver log message: {exc!r}")


def setup_logging(bot: Bot) -> None:
    """Configure root logging and forward ERROR+ records to LOG_CHANNEL_ID."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s\n%(message)s",
    )
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    telegram_handler = TelegramLogHandler(bot, LOG_CHANNEL_ID)
    logging.getLogger("aiogram").addHandler(telegram_handler)
    logging.getLogger().addHandler(telegram_handler)
