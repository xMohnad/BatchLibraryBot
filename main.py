from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllPrivateChats,
    Update,
)
from beanie import init_beanie
from fastapi import FastAPI, Request

from app import setup_middlewares, setup_routes
from app.data.config import TELEGRAM_BOT_TOKEN, WEBHOOK_EP, WEBHOOK_SECRET, WEBHOOK_URL
from app.database.base import database
from app.database.models import CourseMaterial
from app.utils import logger

bot = Bot(
    TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML, link_preview_is_disabled=True
    ),
)


dp = Dispatcher()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_beanie(database=database, document_models=[CourseMaterial])
    await setup_middlewares(dp)
    await setup_routes(dp)

    await bot.set_webhook(WEBHOOK_URL)

    await bot.set_my_commands(
        [
            BotCommand(command="/start", description="start chat."),
            BotCommand(command="/browse", description="browse material."),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )

    await bot.set_my_commands(
        [
            BotCommand(command="/archive", description="Archive a material"),
            BotCommand(command="/remove", description="Remove a material not checked"),
        ],
        scope=BotCommandScopeAllChatAdministrators(),
    )

    logger.info("Webhook set and bot ready")

    yield
    from app.database.base import client

    await client.close()
    logger.info("Bot stopped")


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def index(_: Request):
    return "Telegram is live"


@app.post(f"/{WEBHOOK_EP}/{WEBHOOK_SECRET}")
async def telegram_webhook(request: Request, update: Update):
    await dp.feed_update(bot, update)
    return {"ok": True}
