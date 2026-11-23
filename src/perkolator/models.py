"""Schema for the benefit catalog and the change log.

Text that reaches subscribers' calendars is constrained here: bounded
length, no control or direction-override characters, and no links, web
addresses or email addresses.
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    UrlConstraints,
    model_validator,
)

from perkolator.text import is_unsafe

__all__ = [
    "AMOUNT_DECIMAL_PLACES",
    "MAX_AMOUNT_USD",
    "MAX_BENEFITS",
    "MAX_CHANGES",
    "Benefit",
    "BenefitCatalog",
    "Cadence",
    "Change",
    "ChangeLog",
    "Kind",
]

# Bounds on what one file can hold. They keep a valid file, and the feed built
# from it, small; `perkolator build` enforces the feed's own size limit.
MAX_BENEFITS: Final = 100
MAX_CHANGES: Final = 500
MAX_AMOUNT_USD: Final = 100_000
AMOUNT_DECIMAL_PLACES: Final = 2
_AMOUNT_DIGITS: Final = len(str(MAX_AMOUNT_USD)) + AMOUNT_DECIMAL_PLACES
_MAX_URL_LENGTH: Final = 300

_KEBAB: Final = r"^[a-z0-9]+(-[a-z0-9]+)*$"
_LINK_MARKERS: Final = ("://", "www.", "@")
# A dotted name ending in two or more letters of any script, such as
# "example.com". "U.S." and "$12.95" do not match. Calendar apps turn such
# names into links. Matched against text folded by _fold_lookalikes.
_BARE_DOMAIN: Final = re.compile(r"[\w-]+\.[^\W\d_]{2,}")
# The ideographic full stop acts as a dot in domain names; NFKC leaves it alone.
_DOT_LOOKALIKES: Final = str.maketrans({"\u3002": "."})
_MAX_TEXT_LENGTH: Final = 1000


def _reject_unsafe(text: str, *, allow_newline: bool) -> str:
    for character in text:
        if allow_newline and character == "\n":
            continue
        if is_unsafe(character):
            msg = f"contains a control or formatting character (U+{ord(character):04X})"
            raise ValueError(msg)
    return text


def _single_line(text: str) -> str:
    return _reject_unsafe(text, allow_newline=False)


def _multi_line(text: str) -> str:
    return _reject_unsafe(text, allow_newline=True)


def _fold_lookalikes(text: str) -> str:
    """Reduce full-width and other compatibility forms to the characters they imitate."""
    return unicodedata.normalize("NFKC", text).translate(_DOT_LOOKALIKES).casefold()


def _no_links(text: str) -> str:
    folded = _fold_lookalikes(text)
    if any(marker in folded for marker in _LINK_MARKERS) or _BARE_DOMAIN.search(folded):
        msg = "must not contain a link, web address or email address"
        raise ValueError(msg)
    return text


_Line = Annotated[str, Field(min_length=1), AfterValidator(_single_line)]
_ShownLine = Annotated[_Line, AfterValidator(_no_links)]
_Text = Annotated[str, Field(max_length=_MAX_TEXT_LENGTH), AfterValidator(_multi_line)]
_HttpsUrl = Annotated[
    HttpUrl, UrlConstraints(allowed_schemes=["https"], max_length=_MAX_URL_LENGTH)
]
_Slug = Annotated[str, Field(pattern=_KEBAB)]


def _require_unique(label: str, ids: Iterable[str]) -> None:
    repeated = sorted(value for value, count in Counter(ids).items() if count > 1)
    if repeated:
        msg = f"duplicate {label} ids: {', '.join(repeated)}"
        raise ValueError(msg)


class Cadence(StrEnum):
    """How often a benefit's allowance resets."""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMIANNUAL = "semiannual"
    ANNUAL = "annual"


class Kind(StrEnum):
    """What a benefit demands from the cardholder.

    Attributes:
        AUTO: Fires on an existing subscription; only needs a posting check.
        USE: Needs a deliberate purchase or booking inside the period.
        STATUS: Ongoing enrollment or protection with no deadline.
    """

    AUTO = "auto"
    USE = "use"
    STATUS = "status"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Benefit(_Model):
    """One card benefit.

    Attributes:
        id: Stable kebab-case identifier.
        name: Display name, shown in events.
        amount_usd: Value per period in dollars and cents, if the benefit has one.
        amount_label: Shown instead of the amount when one number misstates it.
        cadence: How often the allowance resets; absent exactly for status benefits.
        kind: What the benefit demands from the cardholder.
        enrollment_required: Whether a one-time enrollment or selection is needed.
        action: One imperative line saying how to use the benefit, shown in events.
        url: Reference link for maintainers; never shown in events.
        notes: Reference terms for maintainers; never shown in events.
    """

    id: Annotated[_Slug, Field(max_length=40)]
    name: Annotated[_ShownLine, Field(max_length=80)]
    amount_usd: (
        Annotated[
            Decimal,
            Field(
                gt=0,
                le=MAX_AMOUNT_USD,
                max_digits=_AMOUNT_DIGITS,
                decimal_places=AMOUNT_DECIMAL_PLACES,
            ),
        ]
        | None
    ) = None
    amount_label: Annotated[_ShownLine, Field(max_length=60)] | None = None
    cadence: Cadence | None = None
    kind: Kind
    enrollment_required: bool
    action: Annotated[_ShownLine, Field(max_length=200)]
    url: _HttpsUrl | None = None
    notes: _Text = ""

    @model_validator(mode="after")
    def _only_status_lacks_a_cadence(self) -> Self:
        if (self.kind is Kind.STATUS) != (self.cadence is None):
            msg = "cadence is required unless kind is 'status', which must not have one"
            raise ValueError(msg)
        return self


class BenefitCatalog(_Model):
    """Every benefit of one card, as last verified against the issuer.

    Attributes:
        card: Identifier of the card product; one fixed value.
        source_url: The issuer page the catalog is verified against; one fixed address.
        verified_on: Date the catalog was last checked against the source.
        benefits: The benefits, in display order.
    """

    card: Literal["platinum-us-personal"]
    source_url: Literal["https://www.americanexpress.com/us/credit-cards/card/platinum/"]
    verified_on: date
    benefits: Annotated[tuple[Benefit, ...], Field(min_length=1, max_length=MAX_BENEFITS)]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> Self:
        _require_unique("benefit", (benefit.id for benefit in self.benefits))
        return self


class Change(_Model):
    """A change the issuer made to the benefits.

    Attributes:
        id: Stable kebab-case identifier; the event keeps it if the text is reworded.
        detected_on: Date the change was noticed.
        summary: One line, shown in the event title.
        detail: Old value, new value and effective date, shown in the event body.
    """

    id: Annotated[_Slug, Field(max_length=60)]
    detected_on: date
    summary: Annotated[_ShownLine, Field(max_length=120)]
    detail: Annotated[_Text, Field(min_length=1), AfterValidator(_no_links)]


class ChangeLog(_Model):
    """All recorded changes.

    Attributes:
        changes: The changes, oldest first.
    """

    changes: Annotated[tuple[Change, ...], Field(max_length=MAX_CHANGES)] = ()

    @model_validator(mode="after")
    def _ids_are_unique(self) -> Self:
        _require_unique("change", (change.id for change in self.changes))
        return self

    @model_validator(mode="after")
    def _oldest_first(self) -> Self:
        days = [change.detected_on for change in self.changes]
        if days != sorted(days):
            msg = "changes must be listed oldest first"
            raise ValueError(msg)
        return self
