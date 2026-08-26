from __future__ import annotations

import secrets
import tempfile
import urllib.parse
from pathlib import Path

from dotenv import load_dotenv
from environs import env

load_dotenv()

env.read_env()


TMP = Path(tempfile.gettempdir()) / "Bot"
"""Temporary directory."""

TMP.mkdir(parents=True, exist_ok=True)

CLOUDINARY_URL = env.str("CLOUDINARY_URL", None)

SEMESTER_START_YEAR = env.int("SEMESTER_START_YEAR", 2025)

TELEGRAM_BOT_TOKEN = env.str("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = env.int("CHANNEL_ID", default=0)
ARCHIVE_CHANNEL = env.int("ARCHIVE_CHANNEL", default=0)
LOG_CHANNEL_ID = env.int("LOG_CHANNEL_ID", default=None)

HOST_URL = env.str("HOST_URL", None)
WEBHOOK_EP = env.str("WEBHOOK_ENDPOINT", "webhook")
WEBHOOK_SECRET = env.str("WEBHOOK_SECRET", secrets.token_hex(32))

WEBHOOK_URL: str | None = None
if HOST_URL and WEBHOOK_EP:
    WEBHOOK_URL = f"{HOST_URL}/{WEBHOOK_EP}"

MONGO_HOST = env.str("MONGO_HOST", "localhost")
MONGO_PORT = env.int("MONGO_PORT", 27017)
MONGO_USER = env.str("MONGO_USER", None)
MONGO_PASS = env.str("MONGO_PASS", None)
MONGO_NAME = env.str("MONGO_NAME", "bot")

MONGO_URL = env.str("MONGO_URL", f"mongodb://{MONGO_HOST}:{MONGO_PORT}/")
if MONGO_USER and MONGO_PASS:
    MONGO_URL = (
        f"mongodb://{urllib.parse.quote(MONGO_USER)}:{urllib.parse.quote(MONGO_PASS)}@{MONGO_HOST}:{MONGO_PORT}/"
    )
