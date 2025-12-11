import logging
import re
from datetime import datetime

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from async_lru import alru_cache
from rapidfuzz import fuzz, process

from app.data.config import CHANNEL_ID

CAPTION_PATTERN = re.compile(
    r"/^(?P<course>.+\(.+\))\s*\|\s*(?P<title>.+)$/gm",
)

SUPPORTED_MEDIA = {"video", "document", "audio"}
WORDS = {
    "أول": 1,
    "ثاني": 2,
    "ثالث": 3,
    "رابع": 4,
}
NUMBER = {v: k for k, v in WORDS.items()}

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("pymongo").setLevel(logging.WARNING)

logger = logging.getLogger("Batch7LibraryBot")


async def is_admin(bot: Bot, user_id: int) -> bool:
    """Check if a user is admin in the channel."""
    member = await bot.get_chat_member(CHANNEL_ID, user_id)
    return member.status in [ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR]


def get_semester(date: datetime = datetime.now(), start_year: int = 2025):
    year = date.year
    month = date.month

    level = year - start_year
    term = 2 if (1 <= month < 9) else 1

    if term == 1:
        level += 1

    if level > 4:
        level = 4

    semester = level * 2

    if term == 1:
        semester -= 1

    return semester


def get_level(semester: int = get_semester()) -> int:
    """
    Returns the current academic level based on the semester number.
    Each 2 semesters correspond to one level.
    """
    if semester < 1:
        raise ValueError("Semester number must be positive")
    return (semester + 1) // 2


def get_term(semester: int = get_semester()) -> int:
    return 1 if semester % 2 == 1 else 2


def resolve_course_similarity(course: str, existing: list[str], threshold=80) -> str:
    logger.info(f"Checking similarity for: '{course}'")

    match = process.extractOne(course, existing, scorer=fuzz.WRatio)

    logger.info(f"Best match: {match}")

    if match and match[1] >= threshold:
        logger.info(f"Accepted → returning: '{match[0]}' (score={match[1]})")
        return match[0]

    logger.info(f"Rejected → returning original: '{course}'")
    return course


@alru_cache(maxsize=128)
async def course_similarity(course: str):
    from app.database.models.course import CourseMaterial

    existing = [doc.course for doc in await CourseMaterial.find_all().to_list()]
    return resolve_course_similarity(course, existing)
