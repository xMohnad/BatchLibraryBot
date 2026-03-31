import re
from enum import Enum


class Ordinal(int, Enum):
    """
    Enum representing Arabic ordinal numbers from الأول to الثامن.
    Provides helper methods for converting between number and name.
    """

    الأول = 1
    الاول = 1
    الثاني = 2
    الثالث = 3
    الرابع = 4
    الخامس = 5
    السادس = 6
    السابع = 7
    الثامن = 8

    @classmethod
    def get_name(cls, value: int) -> str:
        """
        Return the Arabic ordinal name for a given integer value.

        Example:
            Ordinal.get_name(3) -> "الثالث"
        """
        return cls(value).name

    @classmethod
    def get_value(cls, name: str) -> int:
        """
        Return the integer value for a given Arabic ordinal name.

        Example:
            Ordinal.get_value("الثالث") -> 3
        """
        return cls[name].value

    @classmethod
    def get_semester(cls, text: str | None = None) -> int:
        """
        Extract the semester number from a text containing a hashtag like '#الفصل_<name>'.

        If the hashtag is not found, the default is the current semester

        Args:
            text (str): The text to search for the semester hashtag.

        Returns:
            int: The semester number corresponding to the ordinal name.
        """
        if not text or not (match := re.search(r"#الفصل_(\w+)", text)):
            from app.utils import get_semester

            return get_semester()

        return cls.get_value(match.group(1))
