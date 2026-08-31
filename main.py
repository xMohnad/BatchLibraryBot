from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from api import router as api_router
from config import WEBHOOK_EP, WEBHOOK_SECRET
from core.database import init_database
from telegram.bot import bot
from telegram.dispatcher import dp

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_database()
    yield
    from core.database import client

    await client.close()


app = FastAPI(lifespan=lifespan)
app.include_router(api_router)


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
