import asyncio

from beanie import init_beanie
from pymongo import AsyncMongoClient

from accounts.models import PendingRegistration, Session, User
from config import MONGO_NAME, MONGO_URL
from courses.models import Course

client = AsyncMongoClient(MONGO_URL, tz_aware=True)
database = client[MONGO_NAME]


_lock = asyncio.Lock()
_db_initialized = False


async def init_database() -> None:
    """Initialize Beanie/MongoDB exactly once."""
    global _db_initialized

    async with _lock:
        if _db_initialized:
            return

        await init_beanie(
            database=database,
            document_models=[Course, User, PendingRegistration, Session],
        )
        _db_initialized = True
