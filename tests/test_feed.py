from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from factories import TODAY, parse_calendar
from icalendar import Event

from perkolator.feed import render_ics
from perkolator.schedule import PlannedEvent

HOSTILE = "a, b; c\\d\nsecond line " + "x" * 200
HOSTILE_LINE = HOSTILE.replace("\n", " ")


EVENT = PlannedEvent(
    uid="sweep-2026-12@amex-platinum.perkolator",
    day=date(2026, 12, 5),
    summary="Amex Platinum: monthly sweep",
    description="Do the thing",
)


def only_event(data: bytes) -> Event:
    (event,) = parse_calendar(data).events
    return event


def decoded_date(event: Event, name: str) -> date:
    value = event.decoded(name)
    assert isinstance(value, date)
    return value


def test_calendar_headers() -> None:
    calendar = parse_calendar(render_ics([EVENT], TODAY))
    assert calendar["PRODID"] == "-//amex-platinum.perkolator//EN"
    assert calendar["VERSION"] == "2.0"
    assert calendar["X-WR-CALNAME"] == "Amex Platinum Benefits"


def test_event_is_all_day_and_transparent() -> None:
    event = only_event(render_ics([EVENT], TODAY))
    start = decoded_date(event, "DTSTART")
    assert start == EVENT.day
    assert type(start) is date
    assert decoded_date(event, "DTEND") == EVENT.day + timedelta(days=1)
    assert event["TRANSP"] == "TRANSPARENT"
    assert event["UID"] == EVENT.uid
    assert decoded_date(event, "DTSTAMP") == datetime(
        TODAY.year, TODAY.month, TODAY.day, tzinfo=UTC
    )


def test_hostile_text_round_trips() -> None:
    event = only_event(
        render_ics([replace(EVENT, summary=HOSTILE_LINE, description=HOSTILE)], TODAY)
    )
    assert str(event["DESCRIPTION"]) == HOSTILE
    assert str(event["SUMMARY"]) == HOSTILE_LINE


def test_no_raw_line_exceeds_75_octets() -> None:
    data = render_ics([replace(EVENT, description=HOSTILE + " — é" * 40)], TODAY)
    assert max(len(line) for line in data.split(b"\r\n")) <= 75


def test_same_input_same_bytes() -> None:
    events = [EVENT]
    assert render_ics(events, TODAY) == render_ics(events, TODAY)


def test_empty_event_list_is_valid_calendar() -> None:
    assert parse_calendar(render_ics([], TODAY)).events == []
