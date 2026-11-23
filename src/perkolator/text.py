"""The unsafe-character rule shared by the schema and the page-text reducer."""

import unicodedata
from typing import Final

__all__ = ["is_unsafe"]

# Invisible or direction-changing: control, format, private use, surrogate,
# and the line and paragraph separators.
_UNSAFE_CATEGORIES: Final = frozenset({"Cc", "Cf", "Co", "Cs", "Zl", "Zp"})


def is_unsafe(character: str) -> bool:
    """Return whether a character is invisible or changes text direction.

    Newline, tab and the other ASCII controls count as unsafe; callers that
    allow some of them check for those first.
    """
    return unicodedata.category(character) in _UNSAFE_CATEGORIES
