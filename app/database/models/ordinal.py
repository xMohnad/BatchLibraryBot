from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum

from app.config import SEMESTER_START_YEAR


class Ordinal(int, Enum):
    """Enum representing Arabic ordinal numbers from الأول to الثامن.

    Provides helper methods for converting between number and name, as well
    as the academic-calendar logic (semester / level / term) used across
    the app.
    """

    الأول = 1
    الاول = الأول  # alias
    الثاني = 2
    الثالث = 3
    الرابع = 4
    الخامس = 5
    السادس = 6
    السابع = 7
    الثامن = 8

    @classmethod
    def get_name(cls, value: int) -> str:
        """Return the Arabic ordinal name for a given integer value.

        Example:
            Ordinal.get_name(3) -> "الثالث"
        """
        return cls(value).name

    @classmethod
    def get_value(cls, name: str) -> int:
        """Return the integer value for a given Arabic ordinal name.

        Example:
            Ordinal.get_value("الثالث") -> 3
        """
        return cls[name].value

    @classmethod
    def get_semester(cls, text: str | None = None) -> int:
        """Extract the semester number from a text containing a hashtag like '#الفصل_<name>'.

        If the hashtag is not found, the default is the current semester

        Args:
            text (str): The text to search for the semester hashtag.

        Returns:
            int: The semester number corresponding to the ordinal name.
        """
        if not text or not (match := re.search(r"#الفصل_(\w+)", text)):
            return cls.current_semester()

        return cls.get_value(match.group(1))

    @classmethod
    def current_semester(cls, date: datetime | None = None, start_year: int = SEMESTER_START_YEAR) -> int:
        """Calculate the current semester number based on a date.

        The academic year runs September (term 1) through August (term 2 of
        the following calendar year), with `start_year` being the year level 1 /
        term 1 began. Dates before the program starts default to semester 1;
        dates after it ends clamp to level 4's semesters.
        """
        date = date or datetime.now(UTC)
        term = 1 if date.month >= 9 else 2
        level = date.year - start_year + (1 if term == 1 else 0)

        if level < 1:
            return 1  # program hasn't started yet

        if level > 4:
            return 8  # already graduated -> freeze at the last semester

        return cls.to_semester(level, term)

    @classmethod
    def current_level(cls, semester: int | None = None) -> int:
        """Returns the current academic level based on the semester number.

        Each 2 semesters correspond to one level.
        """
        semester = semester if semester is not None else cls.current_semester()
        if semester < 1:
            raise ValueError("Semester number must be positive")
        return (semester + 1) // 2

    @classmethod
    def current_term(cls, semester: int | None = None) -> int:
        """Returns current academic term (1 or 2)."""
        semester = semester if semester is not None else cls.current_semester()
        return 1 if semester % 2 == 1 else 2

    @staticmethod
    def to_semester(level: int, term: int) -> int:
        """Convert academic level and term into semester number."""
        if level < 1:
            raise ValueError("Level must be >= 1")

        if term not in (1, 2):
            raise ValueError("Term must be 1 or 2")

        return (level - 1) * 2 + term

    @classmethod
    def available_levels(cls) -> list[str]:
        """Returns available academic levels as Arabic words."""
        current_level = cls.current_level()
        return [cls.get_name(i) for i in range(1, current_level + 1)]

    @classmethod
    def available_terms(cls) -> list[str]:
        """Returns available academic terms as Arabic words."""
        current_term = cls.current_term()
        return [cls.get_name(i) for i in range(1, current_term + 1)]
