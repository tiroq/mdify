"""Formatting helpers for CLI output."""

from __future__ import annotations

import os
from typing import TextIO


class Colorizer:
    """ANSI color and style helper for terminal output."""

    # ANSI color codes
    RESET = "0"
    BOLD = "1"
    DIM = "2"
    ITALIC = "3"
    UNDERLINE = "4"
    
    # Colors
    BLACK = "30"
    RED = "31"
    GREEN = "32"
    YELLOW = "33"
    BLUE = "34"
    MAGENTA = "35"
    CYAN = "36"
    WHITE = "37"
    BRIGHT_BLACK = "90"
    BRIGHT_RED = "91"
    BRIGHT_GREEN = "92"
    BRIGHT_YELLOW = "93"
    BRIGHT_BLUE = "94"
    BRIGHT_MAGENTA = "95"
    BRIGHT_CYAN = "96"
    BRIGHT_WHITE = "97"

    def __init__(self, stream: TextIO) -> None:
        force_color = os.environ.get("FORCE_COLOR")
        no_color = os.environ.get("NO_COLOR")
        self.enabled = bool(force_color) or (stream.isatty() and not no_color)

    def color(self, text: str, code: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def green(self, text: str) -> str:
        return self.color(text, "32")

    def yellow(self, text: str) -> str:
        return self.color(text, "33")

    def cyan(self, text: str) -> str:
        return self.color(text, "36")
