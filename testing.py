from __future__ import annotations

import asyncio
import logging

from app.bot import bot, dp, init_bot
from app.database import init_database

logger = logging.getLogger(__name__)


async def main() -> None:
    await bot.delete_webhook()

    await init_database()

    await init_bot()
    logger.info("Bot is running in polling mode")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
