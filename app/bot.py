import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, ErrorEvent

from app.handlers import setup_routes
from app.services.middlewares import setup_middlewares
from config import TELEGRAM_BOT_TOKEN
from core.log import setup_logging

logger = logging.getLogger(__name__)

bot = Bot(
    TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
)


dp = Dispatcher()


@dp.errors()
async def global_error_handler(event: ErrorEvent):
    """Logs all uncaught exceptions during update processing and forwards them to the Telegram log channel."""
    logger.critical("Unhandled exception", exc_info=event.exception)


async def init_bot() -> None:
    setup_logging(bot)

    # Load middlewares and routes
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
