import logging

from aiogram import Dispatcher
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, ErrorEvent

from core.log import setup_logging
from telegram.bot import bot
from telegram.middlewares import setup_middlewares
from telegram.routers import setup_routes

logger = logging.getLogger(__name__)

dp = Dispatcher()


@dp.errors()
async def global_error_handler(event: ErrorEvent):
    """Logs all uncaught exceptions during update processing and forwards them to the Telegram log channel."""
    logger.critical("Unhandled exception", exc_info=event.exception)


async def setup_dispatcher() -> None:
    setup_logging(bot)

    setup_middlewares(dp)
    setup_routes(dp)

    await bot.set_my_commands(
        [
            BotCommand(command="/start", description="Start chatting"),
            BotCommand(command="/browse", description="Browse available materials"),
            BotCommand(command="/img2pdf", description="Convert images into a PDF"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )
