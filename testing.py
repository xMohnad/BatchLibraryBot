from __future__ import annotations

import asyncio
import logging

from main import bot, dp, init_bot

logger = logging.getLogger(__name__)


async def main() -> None:
    await bot.delete_webhook()

    await init_bot()
    logger.info("Bot is running in polling mode")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
