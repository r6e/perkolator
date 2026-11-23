"""Render planned events as an iCalendar document."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Final

from icalendar import Calendar, Event

from perkolator.schedule import UID_DOMAIN, PlannedEvent

__all__ = ["render_ics"]

PRODUCT_ID: Final = f"-//{UID_DOMAIN}//EN"
CALENDAR_NAME: Final = "Amex Platinum Benefits"


def render_ics(events: Sequence[PlannedEvent], built_on: date) -> bytes:
    """Render events as an RFC 5545 calendar of all-day, non-blocking events.

    Args:
        events: The events to include, in output order.
        built_on: The build date, stamped on every event.

    Returns:
        The encoded calendar. The same arguments always give the same bytes.
    """
    stamp = datetime.combine(built_on, time.min, tzinfo=UTC)
    calendar = Calendar()
    calendar.add("PRODID", PRODUCT_ID)
    calendar.add("VERSION", "2.0")
    calendar.add("X-WR-CALNAME", CALENDAR_NAME)
    for planned in events:
        calendar.add_component(_to_component(planned, stamp))
    encoded: bytes = calendar.to_ical()
    return encoded


def _to_component(planned: PlannedEvent, stamp: datetime) -> Event:
    event = Event()
    event.add("UID", planned.uid)
    event.add("DTSTAMP", stamp)
    event.add("DTSTART", planned.day)
    event.add("DTEND", planned.day + timedelta(days=1))
    event.add("SUMMARY", planned.summary)
    event.add("DESCRIPTION", planned.description)
    event.add("TRANSP", "TRANSPARENT")
    return event
