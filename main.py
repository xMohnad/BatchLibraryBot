from __future__ import annotations

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

from app.config import TELEGRAM_BOT_TOKEN, WEBHOOK_EP, WEBHOOK_SECRET, WEBHOOK_URL
from app.database.base import database
from app.database.models import Course
from app.handlers import setup_routes
from app.logger import setup_logging
from app.middlewares import setup_middlewares

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
    if not WEBHOOK_URL:
        raise RuntimeError(
            "WEBHOOK_URL is not configured. Set HOST_URL (and optionally "
            "WEBHOOK_ENDPOINT) in the environment, or run the bot in polling "
            "mode via testing.py instead."
        )

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
