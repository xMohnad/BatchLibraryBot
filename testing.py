from __future__ import annotations

import asyncio

from app.utils import logger
from main import bot, dp, init_bot


async def main() -> None:
    await bot.delete_webhook()

    await init_bot()
    logger.info("Bot is running in polling mode")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
