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
