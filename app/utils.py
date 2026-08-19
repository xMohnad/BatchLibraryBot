from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from aiogram.enums import ChatMemberStatus
from aiogram.filters import Filter
from rapidfuzz import fuzz, process

from app.data.config import CHANNEL_ID
from app.database.models.ordinal import Ordinal

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message

    from app.database.models import CourseFile


class IdFilter(Filter):
    def __init__(self, id: int) -> None:
        self.id = id

    async def __call__(self, message: Message) -> bool:
        return message.chat.id == self.id


CAPTION_PATTERN = re.compile(r"(?P<course>.+?)(?:\s*\((?P<tutor>.+?)\))?\s*\|\s*(?P<title>.+)")


logger = logging.getLogger(__name__)


async def is_admin(bot: Bot, user_id: int) -> bool:
    """Check if a user is admin in the channel."""
    member = await bot.get_chat_member(CHANNEL_ID, user_id)
    return member.status in [ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR]


async def group_media_by_course(
    media_events: list[Message],
) -> tuple[dict[str, list[CourseFile]], dict[str, str]]:
    """Group a batch of media messages (e.g. an album/media group) by course.

    Messages in a media group only carry a caption on one item (usually the
    first), so messages without their own caption fall back to the last
    message's caption.

    Returns:
        A tuple of:
        - course_files: course title -> list of parsed `CourseFile` objects
        - course_captions: course title -> the caption used to resolve it
    """
    from app.database.models.course import CourseFile

    default_caption = media_events[-1].caption or ""
    course_files: defaultdict[str, list[CourseFile]] = defaultdict(list)
    course_captions: dict[str, str] = {}

    for msg in media_events:
        caption = msg.caption or default_caption
        if match := CAPTION_PATTERN.search(caption):
            course_title: str = match.group("course")
            course_file = await CourseFile.from_message(msg, match)
            course_files[course_title].append(course_file)
            course_captions.setdefault(course_title, caption)

    return course_files, course_captions


def get_semester(date: datetime | None = None, start_year: int = 2025) -> int:
    """Calculate the current semester number based on a date."""
    date = date or datetime.now(UTC)
    year = date.year
    month = date.month

    level = year - start_year
    term = 2 if (1 <= month < 9) else 1

    if term == 1:
        level += 1

    level = min(level, 4)

    semester = level * 2

    if term == 1:
        semester -= 1

    return semester


def get_level(semester: int | None = None) -> int:
    """Returns the current academic level based on the semester number.

    Each 2 semesters correspond to one level.
    """
    semester = semester if semester is not None else get_semester()
    if semester < 1:
        raise ValueError("Semester number must be positive")
    return (semester + 1) // 2


def get_term(semester: int | None = None) -> int:
    """Returns current academic term (1 or 2)."""
    semester = semester if semester is not None else get_semester()
    return 1 if semester % 2 == 1 else 2


def get_available_levels() -> list[str]:
    """Returns available academic levels as Arabic words."""
    current_level = get_level()
    return [Ordinal.get_name(i) for i in range(1, current_level + 1)]


def get_available_terms() -> list[str]:
    """Returns available academic terms as Arabic words."""
    current_term = get_term()
    return [Ordinal.get_name(i) for i in range(1, current_term + 1)]


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
    """Convert academic level and term into semester number."""
    if level < 1:
        raise ValueError("Level must be >= 1")

    if term not in (1, 2):
        raise ValueError("Term must be 1 or 2")

    return (level - 1) * 2 + term
