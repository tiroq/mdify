"""Formatting helpers for CLI output."""

from __future__ import annotations

import os
from typing import TextIO


class Colorizer:
    """ANSI color helper for terminal output."""

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
