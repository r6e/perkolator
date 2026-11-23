"""Decide which calendar events exist, on which days, and what they say."""

import calendar
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Final

from perkolator.models import Benefit, BenefitCatalog, Cadence, Change, ChangeLog, Kind

__all__ = ["UID_DOMAIN", "PlannedEvent", "plan_events"]

# Card first, so another card's feed could never reuse an identifier.
UID_DOMAIN: Final = "amex-platinum.perkolator"
DEADLINE_MONTHS: Final = (3, 6, 9, 12)
DEADLINE_DAY: Final = 10
CHANGE_DELAY_DAYS: Final = 2
CHANGE_RETENTION_DAYS: Final = 90

_CLOSING_MONTHS: Final[dict[Cadence, tuple[int, ...]]] = {
    Cadence.MONTHLY: tuple(range(1, 13)),
    Cadence.QUARTERLY: DEADLINE_MONTHS,
    Cadence.SEMIANNUAL: (6, 12),
    Cadence.ANNUAL: (12,),
}
_SUMMARY_PREFIX: Final = "Amex Platinum"
_SWEEP_FIXED: Final = (
    "Every month (10 min):\n"
    "- Add every Amex Offer to the card (Amex app > Offers > add all)\n"
    "- Travel in the next 90 days? Check Amex Travel hotel programs before booking, "
    "make sure an airline is selected for the fee credit, "
    "and put hotel and rental status numbers on the reservation"
)
_SWEEP_SEE_DEADLINE: Final = f"Credits closing this month are in the event on the {DEADLINE_DAY}th."
_HEADING_CLOSING: Final = "Closing this month, needs a purchase:"
_HEADING_AUDIT: Final = "Annual enrollment audit, confirm each is still active:"
_HEADING_USE: Final = "Needs a purchase or booking:"
_HEADING_AUTO: Final = "Automatic, verify the credit posted:"
_STALE_AFTER: Final = "6 weeks"
_WATCHER_URL: Final = "https://github.com/r6e/perkolator/actions"


@dataclass(frozen=True, slots=True)
class PlannedEvent:
    """One all-day calendar event.

    Attributes:
        uid: Identifier that stays the same across rebuilds.
        day: The day the event falls on.
        summary: Event title.
        description: Event body.
    """

    uid: str
    day: date
    summary: str
    description: str


def first_saturday(year: int, month: int) -> date:
    """Return the first Saturday of the given month."""
    first = date(year, month, 1)
    return first + timedelta(days=(calendar.SATURDAY - first.weekday()) % 7)


def window(today: date) -> tuple[date, date]:
    """Return the first and last day events are planned for.

    Args:
        today: The build date.

    Returns:
        The first of the build month and December 31 of the following year.
    """
    return today.replace(day=1), date(today.year + 1, 12, 31)


def closing_benefits(catalog: BenefitCatalog, month: int) -> tuple[Benefit, ...]:
    """Return the benefits whose period ends on the last day of the month, in catalog order."""
    return tuple(
        benefit
        for benefit in catalog.benefits
        if benefit.cadence is not None and month in _CLOSING_MONTHS[benefit.cadence]
    )


def format_usd(amount: Decimal) -> str:
    """Format a dollar amount, dropping cents when they are zero."""
    return f"${amount:.0f}" if amount == amount.to_integral_value() else f"${amount:.2f}"


def plan_events(
    catalog: BenefitCatalog, changes: ChangeLog, today: date
) -> tuple[PlannedEvent, ...]:
    """Plan every event in the window.

    Args:
        catalog: The verified benefits.
        changes: Recorded issuer changes.
        today: The build date; nothing else reads the clock.

    Returns:
        Sweep, deadline and change events sorted by day, then identifier.
    """
    events = [
        *_recurring_events(catalog, today),
        *(_change_event(change) for change in _recent(changes, today)),
    ]
    return tuple(sorted(events, key=lambda event: (event.day, event.uid)))


def _uid(local_part: str) -> str:
    return f"{local_part}@{UID_DOMAIN}"


def _months(start: date, end: date) -> Iterator[tuple[int, int]]:
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        year, month = (
            (year + 1, calendar.JANUARY) if month == calendar.DECEMBER else (year, month + 1)
        )


def _recurring_events(catalog: BenefitCatalog, today: date) -> Iterator[PlannedEvent]:
    for year, month in _months(*window(today)):
        yield _sweep_event(catalog, year, month)
        if month in DEADLINE_MONTHS:
            yield _deadline_event(catalog, year, month)


def _amount(benefit: Benefit) -> str | None:
    if benefit.amount_label is not None:
        return benefit.amount_label
    if benefit.amount_usd is None:
        return None
    return format_usd(benefit.amount_usd)


def _benefit_line(benefit: Benefit) -> str:
    amount = _amount(benefit)
    label = benefit.name if amount is None else f"{benefit.name}: {amount}"
    return f"- {label} — {benefit.action}"


def _lines_of_kind(benefits: Iterable[Benefit], kind: Kind) -> Iterator[str]:
    return (_benefit_line(benefit) for benefit in benefits if benefit.kind is kind)


def _section(heading: str, lines: Iterable[str]) -> str | None:
    body = list(lines)
    return "\n".join([heading, *body]) if body else None


def _join(sections: Iterable[str | None]) -> str:
    return "\n\n".join(section for section in sections if section)


def _closing_section(catalog: BenefitCatalog, month: int) -> str | None:
    if month in DEADLINE_MONTHS:
        return _SWEEP_SEE_DEADLINE
    return _section(_HEADING_CLOSING, _lines_of_kind(closing_benefits(catalog, month), Kind.USE))


def _audit_section(catalog: BenefitCatalog, month: int) -> str | None:
    if month != calendar.JANUARY:
        return None
    needs_enrollment = (
        benefit
        for benefit in catalog.benefits
        if benefit.enrollment_required or benefit.kind is Kind.STATUS
    )
    return _section(_HEADING_AUDIT, (f"- {benefit.name}" for benefit in needs_enrollment))


def _footer(catalog: BenefitCatalog) -> str:
    return (
        f"Terms last verified {catalog.verified_on.isoformat()}. If that is more than "
        f"{_STALE_AFTER} before this event, the watcher has stopped: {_WATCHER_URL}"
    )


def _sweep_event(catalog: BenefitCatalog, year: int, month: int) -> PlannedEvent:
    return PlannedEvent(
        uid=_uid(f"sweep-{year}-{month:02d}"),
        day=first_saturday(year, month),
        summary=f"{_SUMMARY_PREFIX}: monthly sweep",
        description=_join(
            [
                _SWEEP_FIXED,
                _closing_section(catalog, month),
                _audit_section(catalog, month),
                _footer(catalog),
            ]
        ),
    )


def _deadline_event(catalog: BenefitCatalog, year: int, month: int) -> PlannedEvent:
    closing = closing_benefits(catalog, month)
    quarter = DEADLINE_MONTHS.index(month) + 1
    last_day = calendar.monthrange(year, month)[1]
    return PlannedEvent(
        uid=_uid(f"deadline-{year}-Q{quarter}"),
        day=date(year, month, DEADLINE_DAY),
        summary=f"{_SUMMARY_PREFIX}: credits closing {calendar.month_abbr[month]} {last_day}",
        description=_join(
            [
                _section(_HEADING_USE, _lines_of_kind(closing, Kind.USE)),
                _section(_HEADING_AUTO, _lines_of_kind(closing, Kind.AUTO)),
            ]
        ),
    )


def _recent(changes: ChangeLog, today: date) -> Iterator[Change]:
    cutoff = today - timedelta(days=CHANGE_RETENTION_DAYS)
    return (change for change in changes.changes if change.detected_on >= cutoff)


def _change_event(change: Change) -> PlannedEvent:
    return PlannedEvent(
        uid=_uid(f"change-{change.id}"),
        day=change.detected_on + timedelta(days=CHANGE_DELAY_DAYS),
        summary=f"{_SUMMARY_PREFIX} changed: {change.summary}",
        description=change.detail,
    )
