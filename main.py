import logging
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    ErrorEvent,
    Update,
)
from beanie import init_beanie
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import setup_middlewares, setup_routes
from app.data.config import TELEGRAM_BOT_TOKEN, WEBHOOK_EP, WEBHOOK_SECRET, WEBHOOK_URL
from app.database.base import database
from app.database.models import Course
from app.logger import setup_logging

logger = logging.getLogger(__name__)

bot = Bot(
    TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML, link_preview_is_disabled=True
    ),
)


dp = Dispatcher()

@dp.errors()
async def global_error_handler(event: ErrorEvent):
    """
    Logs all uncaught exceptions during update processing and forwards them
    to the Telegram log channel (especially required in Webhook mode).
    """
    logger.critical("Critical error caused by %s", event.exception, exc_info=True)


async def init_bot() -> None:
    setup_logging(bot)

    # Init database
    await init_beanie(database=database, document_models=[Course])

    # Load middlewares and routes
    await setup_middlewares(dp)
    await setup_routes(dp)

    await bot.set_my_commands(
        [
            BotCommand(command="/start", description="Start chatting"),
            BotCommand(command="/browse", description="Browse available materials"),
            BotCommand(command="/img2pdf", description="Convert images into a PDF"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_bot()
    await bot.set_webhook(WEBHOOK_URL, secret_token=WEBHOOK_SECRET)
    logger.info("Webhook set and bot ready")

    yield
    from app.database.base import client

    await client.close()
    logger.info("Bot stopped")


app = FastAPI(lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index():
    return "<h1>Bot is running</h1>"


@app.post(f"/{WEBHOOK_EP}", include_in_schema=False)
async def telegram_webhook(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    update = Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}
