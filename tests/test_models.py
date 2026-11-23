from datetime import date
from decimal import Decimal

import pytest
from factories import (
    make_benefit,
    make_catalog,
    make_change,
    make_status,
)
from pydantic import ValidationError

from perkolator.models import MAX_BENEFITS, MAX_CHANGES, Benefit, Cadence, ChangeLog, Kind

BIDI_OVERRIDE = chr(0x202E)
LINE_SEPARATOR = chr(0x2028)


def test_valid_benefit_round_trips() -> None:
    benefit = make_benefit()
    assert Benefit.model_validate(benefit.model_dump()) == benefit
    assert benefit.cadence is Cadence.QUARTERLY
    assert benefit.kind is Kind.USE
    assert benefit.amount_label is None
    assert benefit.url is None


@pytest.mark.parametrize(
    "override",
    [
        {"id": "Bad ID"},
        {"id": "x" * 41},
        {"amount_usd": 0},
        {"amount_usd": -5},
        {"amount_usd": 100_001},
        {"amount_usd": "1e4000"},
        {"amount_usd": "1e999999"},
        {"amount_usd": "12.955"},
        {"url": "https://example.com/" + "x" * 300},
        {"amount_label": ""},
        {"amount_label": "x" * 61},
        {"cadence": "weekly"},
        {"cadence": "ongoing"},
        {"name": ""},
        {"name": "x" * 81},
        {"action": ""},
        {"action": "x" * 201},
        {"action": "two\nlines"},
        {"action": f"flip{BIDI_OVERRIDE}ped"},
        {"action": f"split{LINE_SEPARATOR}line"},
        {"name": "form\x0cfeed"},
        {"name": "Enroll at https://evil.example"},
        {"action": "Visit www.evil.example now"},
        {"amount_label": "see http://evil.example"},
        {"action": "Enroll at evil.com today"},
        {"action": "Go to evil.com/claim"},
        {"name": "a.b.example Credit"},
        {"action": "Mail help@evil"},
        {"action": "Go to evil" + chr(0x3002) + "com"},
        {"action": "Go to evil" + chr(0xFF0E) + "com"},
        {"action": "Go to evil" + chr(0xFF61) + "com"},
        {"action": "Go to " + "".join(chr(ord(c) + 0xFEE0) for c in "evil") + ".com"},
        {"action": "Go to " + chr(0x43F) + chr(0x440) + "." + chr(0x440) + chr(0x444)},
        {"action": "Mail help" + chr(0xFF20) + "evil"},
        {"action": "Mail help" + chr(0xFE6B) + "evil"},
        {"notes": "x" * 1001},
        {"notes": f"bad{BIDI_OVERRIDE}note"},
        {"url": "http://resy.com/"},
        {"url": "ftp://resy.com/"},
        {"unknown_field": 1},
        {"kind": "status"},
        {"kind": "use", "cadence": None},
        {"kind": "auto", "cadence": None},
    ],
)
def test_invalid_benefit_rejected(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_benefit(**override)


def test_status_benefit_has_no_cadence() -> None:
    benefit = make_status("hilton-gold", "Hilton Gold")
    assert benefit.kind is Kind.STATUS
    assert benefit.cadence is None


def test_notes_may_span_lines_and_url_must_be_https() -> None:
    benefit = make_benefit(notes="line one\nline two", url="https://resy.com/")
    assert benefit.notes == "line one\nline two"
    assert str(benefit.url) == "https://resy.com/"


def test_catalog_rejects_duplicate_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        make_catalog(make_benefit(), make_benefit())


def test_catalog_rejects_empty_benefits() -> None:
    with pytest.raises(ValidationError):
        make_catalog()


@pytest.mark.parametrize(
    "source_url",
    [
        "http://www.americanexpress.com/us/credit-cards/card/platinum/",
        "https://evil.example/us/credit-cards/card/platinum/",
        "https://www.americanexpress.com\\@evil.example/",
        "https://www.americanexpress.com:8443/us/credit-cards/card/platinum/",
        "https://www.americanexpress.com/us/credit-cards/card/gold/",
        "https://www.americanexpress.com/us/credit-cards/card/platinum/?next=evil",
    ],
)
def test_catalog_source_url_must_be_the_one_issuer_page(source_url: str) -> None:
    with pytest.raises(ValidationError):
        make_catalog(make_benefit(), source_url=source_url)


@pytest.mark.parametrize("amount", ["0.01", "100000", "100000.00"])
def test_amount_bounds_are_inclusive(amount: str) -> None:
    assert make_benefit(amount_usd=amount).amount_usd == Decimal(amount)


def test_amount_just_over_the_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_benefit(amount_usd="100000.01")


@pytest.mark.parametrize("card", ["gold-us-personal", "platinum-us-business", ""])
def test_catalog_card_must_be_the_one_product(card: str) -> None:
    with pytest.raises(ValidationError):
        make_catalog(make_benefit(), card=card)


def test_text_with_abbreviations_and_amounts_is_not_mistaken_for_a_link() -> None:
    action = "Buy at a U.S. store, e.g. for $12.95, with the card. Then check it posted"
    assert make_benefit(action=action).action == action


@pytest.mark.parametrize(
    "override",
    [
        {"summary": ""},
        {"summary": "two\nlines"},
        {"summary": "x" * 121},
        {"summary": "Verify at https://evil.example"},
        {"detail": ""},
        {"detail": "x" * 1001},
        {"detail": "Go to www.evil.example"},
        {"detail": "Call or visit amex-enroll.example/login"},
        {"summary": "Write to claims@evil"},
        {"detail": f"flip{BIDI_OVERRIDE}ped"},
        {"id": "Not Kebab"},
        {"id": ""},
    ],
)
def test_invalid_change_rejected(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_change(**override)


def test_change_detail_may_span_lines() -> None:
    assert make_change(detail="old: $100\nnew: $50").detail == "old: $100\nnew: $50"


def test_changelog_rejects_duplicate_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        ChangeLog(changes=(make_change(), make_change()))


def test_changelog_rejects_out_of_order_entries() -> None:
    later = make_change(id="later", detected_on=date(2026, 12, 1))
    earlier = make_change(id="earlier", detected_on=date(2026, 11, 1))
    with pytest.raises(ValidationError, match="oldest first"):
        ChangeLog(changes=(later, earlier))


def test_changelog_defaults_to_empty() -> None:
    assert ChangeLog().changes == ()


def test_catalog_rejects_more_benefits_than_any_card_has() -> None:
    benefits = [make_benefit(id=f"b{n}") for n in range(MAX_BENEFITS + 1)]
    with pytest.raises(ValidationError):
        make_catalog(*benefits)
    assert len(make_catalog(*benefits[:MAX_BENEFITS]).benefits) == MAX_BENEFITS


def test_change_log_rejects_more_changes_than_the_limit() -> None:
    changes = tuple(make_change(id=f"c{n}") for n in range(MAX_CHANGES + 1))
    with pytest.raises(ValidationError):
        ChangeLog(changes=changes)
    assert len(ChangeLog(changes=changes[:MAX_CHANGES]).changes) == MAX_CHANGES
