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

    def _apply(self, text: str, *codes: str) -> str:
        """Apply ANSI codes to text. Supports multiple codes."""
        if not self.enabled:
            return text
        code_str = ";".join(codes)
        return f"\033[{code_str}m{text}\033[0m"

    def color(self, text: str, code: str) -> str:
        """Apply a single color code."""
        return self._apply(text, code)

    # Basic colors
    def green(self, text: str) -> str:
        return self._apply(text, self.GREEN)

    def yellow(self, text: str) -> str:
        return self._apply(text, self.YELLOW)

    def cyan(self, text: str) -> str:
        return self._apply(text, self.CYAN)

    def red(self, text: str) -> str:
        return self._apply(text, self.RED)

    def blue(self, text: str) -> str:
        return self._apply(text, self.BLUE)

    def magenta(self, text: str) -> str:
        return self._apply(text, self.MAGENTA)

    def white(self, text: str) -> str:
        return self._apply(text, self.WHITE)

    # Bright colors
    def bright_green(self, text: str) -> str:
        return self._apply(text, self.BRIGHT_GREEN)

    def bright_yellow(self, text: str) -> str:
        return self._apply(text, self.BRIGHT_YELLOW)

    def bright_cyan(self, text: str) -> str:
        return self._apply(text, self.BRIGHT_CYAN)

    def bright_red(self, text: str) -> str:
        return self._apply(text, self.BRIGHT_RED)

    # Styles
    def bold(self, text: str) -> str:
        return self._apply(text, self.BOLD)

    def dim(self, text: str) -> str:
        return self._apply(text, self.DIM)

    def underline(self, text: str) -> str:
        return self._apply(text, self.UNDERLINE)

    # Combined styles
    def bold_green(self, text: str) -> str:
        return self._apply(text, self.BOLD, self.GREEN)

    def bold_cyan(self, text: str) -> str:
        return self._apply(text, self.BOLD, self.CYAN)

    def bold_yellow(self, text: str) -> str:
        return self._apply(text, self.BOLD, self.YELLOW)

    def bold_red(self, text: str) -> str:
        return self._apply(text, self.BOLD, self.RED)

    def dim_cyan(self, text: str) -> str:
        return self._apply(text, self.DIM, self.CYAN)

    def dim_white(self, text: str) -> str:
        return self._apply(text, self.DIM, self.WHITE)

    def success(self, text: str) -> str:
        """Styled success message (bold green)."""
        return self._apply(text, self.BOLD, self.GREEN)

    def error(self, text: str) -> str:
        """Styled error message (bold red)."""
        return self._apply(text, self.BOLD, self.RED)

    def warning(self, text: str) -> str:
        """Styled warning message (bold yellow)."""
        return self._apply(text, self.BOLD, self.YELLOW)

    def info(self, text: str) -> str:
        """Styled info message (cyan)."""
        return self._apply(text, self.CYAN)

    def muted(self, text: str) -> str:
        """Muted text (dim white)."""
        return self._apply(text, self.DIM, self.WHITE)
