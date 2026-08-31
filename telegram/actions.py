from enum import StrEnum


class Action(StrEnum):
    """Callback/keyboard action identifiers shared across FSM scenes."""

    clear = "clear"
    convert = "convert"

    filename = "filename"
    caption = "caption"

    back = "🔙 Back"
    restart = "🔄 Restart"
    exit = "🚫 Exit"
