import logging
import re
from datetime import datetime

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Filter
from aiogram.types import Message
from rapidfuzz import fuzz, process

from app.data.config import CHANNEL_ID


class IdFilter(Filter):
    def __init__(self, id: int) -> None:
        self.id = id

    async def __call__(self, message: Message) -> bool:
        return message.chat.id == self.id


CAPTION_PATTERN = re.compile(
    r"(?P<course>.+?)(?:\s*\((?P<tutor>.+?)\))?\s*\|\s*(?P<title>.+)"
)

SUPPORTED_MEDIA = {"video", "document", "audio"}

WORDS = {
    "الأول": 1,
    "الثاني": 2,
    "الثالث": 3,
    "الرابع": 4,
}
NUMBER = {v: k for k, v in WORDS.items()}


logger = logging.getLogger(__name__)


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
    """
    Returns current academic term (1 or 2).
    """
    return 1 if semester % 2 == 1 else 2


def get_available_levels() -> list[str]:
    """
    Returns available academic levels as Arabic words.
    Example: ['الأول', 'الثاني']
    """
    current_level = get_level()
    return [NUMBER[i] for i in range(1, current_level + 1)]


def get_available_terms() -> list[str]:
    """
    Returns available academic terms as Arabic words.
    Example: ['الأول'] or ['الأول', 'الثاني']
    """
    current_term = get_term()
    return [NUMBER[i] for i in range(1, current_term + 1)]


def resolve_course_similarity(course: str, existing: list[str], threshold=90) -> str:
    logger.info(f"Checking similarity for: '{course}'")

    if course in existing:
        logger.info(f"Exact match found in database for: '{course}'")
        return course

    match = process.extractOne(course, existing, scorer=fuzz.token_sort_ratio)

    logger.info(f"Best match: {match}")

    if match and match[1] >= threshold:
        logger.info(f"Accepted → returning: '{match[0]}' (score={match[1]})")
        return match[0]

    logger.info(f"Rejected → returning original: '{course}'")
    return course


def to_semester(level: int, term: int) -> int:
    """
    Convert academic level and term into semester number.
    """
    if level < 1:
        raise ValueError("Level must be >= 1")

    if term not in (1, 2):
        raise ValueError("Term must be 1 or 2")

    return (level - 1) * 2 + term
