from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.bot import bot, dp, init_bot
from app.config import WEBHOOK_EP, WEBHOOK_SECRET, WEBHOOK_URL
from app.database import init_database

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not WEBHOOK_URL:
        raise RuntimeError(
            "WEBHOOK_URL is not configured. Set HOST_URL (and optionally "
            "WEBHOOK_ENDPOINT) in the environment, or run the bot in polling "
            "mode via testing.py instead."
        )

    await init_database()
    await init_bot()
    await bot.set_webhook(WEBHOOK_URL, secret_token=WEBHOOK_SECRET)
    logger.info("Webhook set and bot ready")

    yield
    from app.database import client

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
