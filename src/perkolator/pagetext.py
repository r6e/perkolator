"""Reduce the issuer's benefits page to the text a reader sees.

The watcher model is given this text as a file, so it needs no network
access. The page is untrusted input: this module only extracts text.
"""

from html.parser import HTMLParser
from itertools import groupby
from typing import Final

from perkolator.text import is_unsafe

__all__ = ["MAX_HTML_CHARS", "MAX_TEXT_CHARS", "PageError", "html_to_text"]

MAX_HTML_CHARS: Final = 10_000_000
MAX_TEXT_CHARS: Final = 200_000
_MIN_TEXT_CHARS: Final = 2_000
_REQUIRED_PHRASE: Final = "Platinum Card"
_HIDDEN_ELEMENTS: Final = frozenset({"script", "style", "noscript", "svg", "template"})


class PageError(Exception):
    """The downloaded page is not usable as the card's benefits page."""


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        if tag in _HIDDEN_ELEMENTS:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN_ELEMENTS and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        kept = "".join(
            character for character in data if character.isspace() or not is_unsafe(character)
        )
        if block := " ".join(kept.split()):
            self.blocks.append(block)


def html_to_text(html: str) -> str:
    """Return the page's visible text, one block per line.

    A line repeated back to back is kept once; a line that recurs elsewhere
    (such as "Enrollment required." under several benefits) is kept each time.

    Args:
        html: The downloaded page source.

    Returns:
        The text, at most `MAX_TEXT_CHARS` characters.

    Raises:
        PageError: If the source is too large or cannot be parsed, or its text
            is too short, too long or does not name the card.
    """
    if len(html) > MAX_HTML_CHARS:
        msg = f"page source is too large ({len(html)} characters, limit {MAX_HTML_CHARS})"
        raise PageError(msg)
    parser = _VisibleText()
    try:
        parser.feed(html)
        parser.close()
    except Exception as error:  # html.parser raises assorted types on malformed markup
        msg = f"page source cannot be parsed: {type(error).__name__}"
        raise PageError(msg) from error
    text = "\n".join(block for block, _ in groupby(parser.blocks))
    if len(text) > MAX_TEXT_CHARS:
        msg = f"page text is too long ({len(text)} characters, limit {MAX_TEXT_CHARS})"
        raise PageError(msg)
    if len(text) < _MIN_TEXT_CHARS:
        msg = f"page text is too short ({len(text)} characters) to be the benefits page"
        raise PageError(msg)
    if _REQUIRED_PHRASE not in text:
        msg = f"page text does not name the {_REQUIRED_PHRASE}"
        raise PageError(msg)
    return text
