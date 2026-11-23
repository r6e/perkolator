"""Builders for test data."""

from datetime import date
from pathlib import Path

import yaml
from icalendar import Calendar

from perkolator.models import Benefit, BenefitCatalog, Change

TODAY = date(2026, 11, 21)
SOURCE_URL = "https://www.americanexpress.com/us/credit-cards/card/platinum/"
SAFE_PATH = "/usr/bin:/bin:/usr/local/bin"
# Split so that secret scanners do not flag this file.
FAKE_CREDENTIAL_TAIL = "abcdef"
FAKE_CREDENTIAL = "sk-" + "ant-api03-" + FAKE_CREDENTIAL_TAIL
# Shaped like a signed identity token: two base64url JSON objects and a signature.
FAKE_IDENTITY_TOKEN = "eyJ" + "hbGciOiJ" + ".eyJ" + "zdWIiOiJ." + FAKE_CREDENTIAL_TAIL


def benefit_fields(**overrides: object) -> dict[str, object]:
    """Return raw fields for a valid quarterly `use` benefit, with overrides applied."""
    fields: dict[str, object] = {
        "id": "resy",
        "name": "Resy Credit",
        "amount_usd": 100,
        "cadence": "quarterly",
        "kind": "use",
        "enrollment_required": True,
        "action": "Pay at a Resy restaurant with the card",
    }
    return fields | overrides


def make_benefit(**overrides: object) -> Benefit:
    """Build a validated benefit."""
    return Benefit.model_validate(benefit_fields(**overrides))


def make_status(benefit_id: str, name: str, *, enrollment_required: bool = True) -> Benefit:
    """Build a validated status benefit, which has no cadence or amount."""
    return make_benefit(
        id=benefit_id,
        name=name,
        kind="status",
        cadence=None,
        amount_usd=None,
        action="Enroll",
        enrollment_required=enrollment_required,
    )


def catalog_fields(*benefits: Benefit, **overrides: object) -> dict[str, object]:
    """Return raw fields for a valid catalog, with overrides applied."""
    fields: dict[str, object] = {
        "card": "platinum-us-personal",
        "source_url": SOURCE_URL,
        "verified_on": TODAY,
        "benefits": benefits,
    }
    return fields | overrides


def make_catalog(*benefits: Benefit, **overrides: object) -> BenefitCatalog:
    """Build a validated catalog from the given benefits."""
    return BenefitCatalog.model_validate(catalog_fields(*benefits, **overrides))


def change_fields(**overrides: object) -> dict[str, object]:
    """Return raw fields for a valid change, with overrides applied."""
    fields: dict[str, object] = {
        "id": "2026-11-21-resy-cut",
        "detected_on": TODAY,
        "summary": "Resy credit cut to $50",
        "detail": "Was $100 a quarter.",
    }
    return fields | overrides


def make_change(**overrides: object) -> Change:
    """Build a validated change."""
    return Change.model_validate(change_fields(**overrides))


def catalog_yaml(*benefits: dict[str, object], **catalog_overrides: object) -> str:
    """Return YAML for a catalog with one benefit per override mapping (one default if none)."""
    entries = [benefit_fields(**overrides) for overrides in benefits or ({},)]
    fields = catalog_fields() | {"benefits": entries} | catalog_overrides
    return yaml.safe_dump(fields, sort_keys=False)


def changes_yaml(*changes: dict[str, object]) -> str:
    """Return YAML for a change log with one change per override mapping."""
    entries = [change_fields(**overrides) for overrides in changes]
    return yaml.safe_dump({"changes": entries}, sort_keys=False)


def write_file(path: Path, content: str | bytes) -> Path:
    """Write text (as UTF-8) or raw bytes, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return path


def parse_calendar(data: bytes) -> Calendar:
    """Parse an encoded calendar, failing the test if it is not one."""
    calendar = Calendar.from_ical(data)
    assert isinstance(calendar, Calendar)
    return calendar


def benefits_page_html(body: str = "") -> str:
    """Return HTML long enough, and naming the card, to pass as the benefits page."""
    filler = "".join(f"<p>Platinum Card benefit paragraph number {n}.</p>" for n in range(120))
    return f"<html><head><title>The Platinum Card</title></head><body>{filler}{body}</body></html>"


def make_stub(directory: Path, name: str, script: str) -> Path:
    """Write an executable shell stub called `name` and return the directory to put on PATH."""
    stub = directory / name
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(script)
    stub.chmod(0o755)
    return directory
