from datetime import date
from decimal import Decimal

import pytest
from factories import TODAY, make_benefit, make_catalog, make_change, make_status

from perkolator.models import BenefitCatalog, ChangeLog
from perkolator.schedule import (
    PlannedEvent,
    closing_benefits,
    first_saturday,
    format_usd,
    plan_events,
    window,
)

NO_CHANGES = ChangeLog()


def mixed_catalog() -> BenefitCatalog:
    return make_catalog(
        make_benefit(
            id="stream", name="Streaming", amount_usd=25, cadence="monthly", kind="auto",
            action="Pay it", enrollment_required=False,
        ),
        make_benefit(
            id="uber", name="Uber Cash", amount_usd=15, amount_label="$15 ($35 in December)",
            cadence="monthly", action="Ride", enrollment_required=False,
        ),
        make_benefit(id="resy", name="Resy", cadence="quarterly", action="Eat"),
        make_benefit(
            id="hotel", name="Hotel", amount_usd=300, cadence="semiannual", action="Book",
            enrollment_required=False,
        ),
        make_benefit(
            id="clear", name="CLEAR+", amount_usd=219, cadence="annual", kind="auto",
            action="Renew", enrollment_required=False,
        ),
        make_status("hilton", "Hilton Gold"),
        make_status("offers", "Amex Offers", enrollment_required=False),
    )  # fmt: skip


def single_catalog() -> BenefitCatalog:
    return make_catalog(make_benefit())


def planned(
    today: date = TODAY, changes: ChangeLog = NO_CHANGES, catalog: BenefitCatalog | None = None
) -> tuple[PlannedEvent, ...]:
    return plan_events(catalog or mixed_catalog(), changes, today)


def with_uid_prefix(events: tuple[PlannedEvent, ...], prefix: str) -> list[PlannedEvent]:
    return [event for event in events if event.uid.startswith(prefix)]


def by_uid(events: tuple[PlannedEvent, ...], prefix: str) -> PlannedEvent:
    (match,) = with_uid_prefix(events, prefix)
    return match


def uids(events: tuple[PlannedEvent, ...]) -> set[str]:
    return {event.uid for event in events}


def test_first_saturday() -> None:
    assert first_saturday(2026, 12) == date(2026, 12, 5)
    assert first_saturday(2027, 1) == date(2027, 1, 2)
    assert first_saturday(2027, 5) == date(2027, 5, 1)


def test_window_spans_to_end_of_next_year() -> None:
    assert window(TODAY) == (date(2026, 11, 1), date(2027, 12, 31))


@pytest.mark.parametrize(
    ("month", "expected"),
    [
        (1, ["stream", "uber"]),
        (3, ["stream", "uber", "resy"]),
        (6, ["stream", "uber", "resy", "hotel"]),
        (12, ["stream", "uber", "resy", "hotel", "clear"]),
    ],
)
def test_closing_benefits_by_cadence(month: int, expected: list[str]) -> None:
    assert [benefit.id for benefit in closing_benefits(mixed_catalog(), month)] == expected


def test_format_usd() -> None:
    assert format_usd(Decimal(100)) == "$100"
    assert format_usd(Decimal("12.95")) == "$12.95"
    assert format_usd(Decimal("100.00")) == "$100"
    assert format_usd(Decimal("7.5")) == "$7.50"


def test_event_counts_from_november_2026() -> None:
    events = planned(catalog=single_catalog())
    assert len(with_uid_prefix(events, "sweep-")) == 14
    assert len(with_uid_prefix(events, "deadline-")) == 5


def test_uids_unique_across_year_rollover() -> None:
    events = planned(today=date(2026, 12, 31))
    assert len(uids(events)) == len(events)
    assert {
        "deadline-2026-Q4@amex-platinum.perkolator",
        "sweep-2027-01@amex-platinum.perkolator",
        "deadline-2027-Q4@amex-platinum.perkolator",
    } <= uids(events)


def test_december_deadline_groups_use_before_auto() -> None:
    event = by_uid(planned(), "deadline-2026-Q4")
    assert event.day == date(2026, 12, 10)
    assert event.summary == "Amex Platinum: credits closing Dec 31"
    assert event.description == (
        "Needs a purchase or booking:\n"
        "- Uber Cash: $15 ($35 in December) — Ride\n"
        "- Resy: $100 — Eat\n"
        "- Hotel: $300 — Book\n"
        "\n"
        "Automatic, verify the credit posted:\n"
        "- Streaming: $25 — Pay it\n"
        "- CLEAR+: $219 — Renew"
    )


def test_deadline_summary_uses_real_month_end() -> None:
    assert by_uid(planned(), "deadline-2027-Q1").summary == "Amex Platinum: credits closing Mar 31"
    assert by_uid(planned(), "deadline-2027-Q2").summary == "Amex Platinum: credits closing Jun 30"


def test_deadline_omits_empty_heading() -> None:
    event = by_uid(planned(catalog=single_catalog()), "deadline-2026-Q4")
    assert event.description == (
        "Needs a purchase or booking:\n- Resy Credit: $100 — Pay at a Resy restaurant with the card"
    )


def test_benefit_without_amount_omits_the_colon() -> None:
    catalog = make_catalog(make_benefit(amount_usd=None, action="Eat"))
    event = by_uid(planned(catalog=catalog), "deadline-2026-Q4")
    assert event.description.endswith("- Resy Credit — Eat")


def test_sweep_lists_use_benefits_only_in_non_deadline_months() -> None:
    november = by_uid(planned(), "sweep-2026-11")
    assert (
        "Closing this month, needs a purchase:\n- Uber Cash: $15 ($35 in December) — Ride"
        in november.description
    )
    assert "Streaming" not in november.description
    assert "Resy" not in november.description


def test_deadline_month_sweep_points_to_the_10th() -> None:
    december = by_uid(planned(), "sweep-2026-12")
    assert "Credits closing this month are in the event on the 10th." in december.description
    assert "Closing this month, needs a purchase:" not in december.description


def test_sweep_without_closing_use_benefits_has_no_closing_section() -> None:
    november = by_uid(planned(catalog=single_catalog()), "sweep-2026-11")
    assert "Closing this month" not in november.description


def test_sweep_starts_with_fixed_block_and_day() -> None:
    december = by_uid(planned(), "sweep-2026-12")
    assert december.day == date(2026, 12, 5)
    assert december.summary == "Amex Platinum: monthly sweep"
    assert december.description.startswith(
        "Every month (10 min):\n"
        "- Add every Amex Offer to the card (Amex app > Offers > add all)\n"
        "- Travel in the next 90 days? Check Amex Travel hotel programs before booking, "
        "make sure an airline is selected for the fee credit, "
        "and put hotel and rental status numbers on the reservation\n\n"
    )


def test_january_sweep_has_enrollment_audit_and_others_do_not() -> None:
    events = planned()
    assert (
        "Annual enrollment audit, confirm each is still active:\n"
        "- Resy\n- Hilton Gold\n- Amex Offers" in by_uid(events, "sweep-2027-01").description
    )
    assert "Annual enrollment audit" not in by_uid(events, "sweep-2027-02").description


def test_sweep_footer_carries_verified_on() -> None:
    assert by_uid(planned(), "sweep-2026-12").description.endswith(
        "Terms last verified 2026-11-21. If that is more than 6 weeks before this event, "
        "the watcher has stopped: https://github.com/r6e/perkolator/actions"
    )


def test_change_event_two_days_after_detection() -> None:
    change = make_change(id="2026-11-25-resy-cut", detected_on=date(2026, 11, 25))
    events = planned(today=date(2026, 11, 25), changes=ChangeLog(changes=(change,)))
    assert by_uid(events, "change-") == PlannedEvent(
        uid="change-2026-11-25-resy-cut@amex-platinum.perkolator",
        day=date(2026, 11, 27),
        summary="Amex Platinum changed: Resy credit cut to $50",
        description="Was $100 a quarter.",
    )


def test_change_uid_survives_rewording() -> None:
    before = ChangeLog(changes=(make_change(),))
    after = ChangeLog(changes=(make_change(summary="Reworded", detail="Also reworded."),))
    assert uids(planned(changes=before)) == uids(planned(changes=after))


def test_changes_older_than_90_days_dropped() -> None:
    old = make_change(id="old", detected_on=date(2026, 8, 22), summary="Old")
    kept = make_change(id="kept", detected_on=date(2026, 8, 23), summary="Kept")
    events = planned(changes=ChangeLog(changes=(old, kept)))
    assert [event.summary for event in with_uid_prefix(events, "change-")] == [
        "Amex Platinum changed: Kept"
    ]


def test_empty_changelog_yields_no_change_events() -> None:
    assert not with_uid_prefix(planned(), "change-")


def test_uids_stable_when_a_benefit_is_added() -> None:
    larger = make_catalog(make_benefit(), make_benefit(id="extra", cadence="annual"))
    assert uids(planned(catalog=single_catalog())) == uids(planned(catalog=larger))


def test_uids_stable_across_days_in_same_month() -> None:
    assert uids(planned(today=date(2026, 11, 1))) == uids(planned(today=date(2026, 11, 30)))


def test_events_sorted_by_day_then_uid() -> None:
    events = planned()
    assert list(events) == sorted(events, key=lambda event: (event.day, event.uid))
