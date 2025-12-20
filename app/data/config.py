import secrets
import urllib.parse
from pathlib import Path

from environs import Env

env = Env()
env.read_env()

DIR = Path(__file__).absolute().parent.parent

TELEGRAM_BOT_TOKEN = env.str("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = env.int("CHANNEL_ID", default=0)
ARCHIVE_CHANNEL = env.int("ARCHIVE_CHANNEL", default=0)

HOST_URL = env.str("HOST_URL", None)
WEBHOOK_EP = env.str("WEBHOOK_ENDPOINT", "webhook")
WEBHOOK_SECRET = env.str("WEBHOOK_SECRET", secrets.token_hex(32))

WEBHOOK_URL = env.str("WEBHOOK_ENDPOINT", None)
if HOST_URL and WEBHOOK_EP and WEBHOOK_SECRET:
    WEBHOOK_URL = f"{HOST_URL}/{WEBHOOK_EP}/{WEBHOOK_SECRET}"

MONGO_HOST = env.str("MONGO_HOST", "localhost")
MONGO_PORT = env.int("MONGO_PORT", 27017)
MONGO_USER = env.str("MONGO_USER", None)
MONGO_PASS = env.str("MONGO_PASS", None)
MONGO_NAME = env.str("MONGO_NAME", "bot")

MONGO_URL = env.str("MONGO_URL", f"mongodb://{MONGO_HOST}:{MONGO_PORT}/")
if MONGO_USER and MONGO_PASS:
    MONGO_URL = f"mongodb://{urllib.parse.quote(MONGO_USER)}:{urllib.parse.quote(MONGO_PASS)}@{MONGO_HOST}:{MONGO_PORT}/"
