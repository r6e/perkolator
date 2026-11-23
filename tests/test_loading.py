from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from factories import TODAY, catalog_yaml, make_benefit, make_catalog, make_change, write_file

from perkolator.loading import DataError, check_not_future, load_catalog, load_changes
from perkolator.models import ChangeLog

CATALOG = """\
card: platinum-us-personal
source_url: https://www.americanexpress.com/us/credit-cards/card/platinum/
verified_on: 2026-11-21
benefits:
  - id: walmart-plus
    name: Walmart+ Credit
    amount_usd: 12.95
    cadence: monthly
    kind: auto
    enrollment_required: false
    action: Pay the monthly membership with the card
"""
CHANGES = """\
changes:
  - id: 2026-11-21-resy-up
    detected_on: 2026-11-21
    summary: Resy up
    detail: more
"""


def test_load_catalog_reads_yaml(tmp_path: Path) -> None:
    catalog = load_catalog(write_file(tmp_path / "benefits.yaml", CATALOG))
    assert catalog.verified_on == TODAY
    assert catalog.benefits[0].amount_usd == Decimal("12.95")


def test_load_changes_reads_entries(tmp_path: Path) -> None:
    assert (
        load_changes(write_file(tmp_path / "changes.yaml", CHANGES)).changes[0].summary == "Resy up"
    )


def test_load_changes_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_changes(tmp_path / "absent.yaml") == ChangeLog()


def test_load_changes_empty_file_is_empty(tmp_path: Path) -> None:
    assert load_changes(write_file(tmp_path / "changes.yaml", "")) == ChangeLog()


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        pytest.param("- just\n- a list\n", "benefits.yaml", id="not-a-mapping"),
        pytest.param("card: [unclosed\n", "benefits.yaml", id="yaml-syntax"),
        pytest.param(catalog_yaml({"cadence": "weekly"}), "benefits.0.cadence", id="bad-enum"),
        pytest.param(CATALOG + "    cadence: annual\n", "duplicate key", id="duplicate-nested-key"),
        pytest.param(
            CATALOG.replace("card:", "card: x\ncard:"), "duplicate key", id="duplicate-top-key"
        ),
        pytest.param("? [a]\n: 1\n", "benefits.yaml", id="unhashable-key"),
        pytest.param(b"card: \xff\xfe\n", "benefits.yaml", id="not-utf8"),
        pytest.param('card: !!bool "text"\n', "benefits.yaml", id="tagged-bool"),
        pytest.param('card: !!timestamp "text"\n', "benefits.yaml", id="tagged-timestamp"),
        pytest.param('card: !!int ""\n', "benefits.yaml", id="tagged-empty-int"),
        pytest.param(
            catalog_yaml().replace("amount_usd: 100", "amount_usd: " + "9" * 5000),
            "benefits.yaml",
            id="number-too-long-to-parse",
        ),
        pytest.param(
            catalog_yaml().replace("verified_on: 2026-11-21", "verified_on: 0000-01-01"),
            "benefits.yaml",
            id="impossible-date",
        ),
        pytest.param(
            "card: " + "[" * 5000 + "]" * 5000 + "\n", "benefits.yaml", id="nested-too-deep"
        ),
        pytest.param(
            "card: !!python/object/apply:os.system ['true']\n", "benefits.yaml", id="python-tag"
        ),
    ],
)
def test_load_catalog_reports_bad_content_as_data_error(
    tmp_path: Path, content: str | bytes, expected: str
) -> None:
    with pytest.raises(DataError, match=expected):
        load_catalog(write_file(tmp_path / "benefits.yaml", content))


def test_load_catalog_missing_file_is_data_error(tmp_path: Path) -> None:
    with pytest.raises(DataError, match=r"benefits\.yaml"):
        load_catalog(tmp_path / "benefits.yaml")


def test_load_changes_directory_is_data_error(tmp_path: Path) -> None:
    (tmp_path / "changes.yaml").mkdir()
    with pytest.raises(DataError, match=r"changes\.yaml"):
        load_changes(tmp_path / "changes.yaml")


def test_check_not_future_accepts_today() -> None:
    check_not_future(make_catalog(make_benefit()), ChangeLog(changes=(make_change(),)), TODAY)


def test_check_not_future_rejects_future_verified_on() -> None:
    catalog = make_catalog(make_benefit(), verified_on=TODAY + timedelta(days=1))
    with pytest.raises(DataError, match="verified_on"):
        check_not_future(catalog, ChangeLog(), TODAY)


def test_check_not_future_rejects_future_change() -> None:
    change = make_change(detected_on=date(2027, 6, 1))
    with pytest.raises(DataError, match=change.id):
        check_not_future(make_catalog(make_benefit()), ChangeLog(changes=(change,)), TODAY)


def test_failure_with_no_message_still_names_its_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_: object, **__: object) -> None:
        raise MemoryError

    monkeypatch.setattr("yaml.load", explode)
    with pytest.raises(DataError, match="MemoryError"):
        load_catalog(write_file(tmp_path / "benefits.yaml", "card: x\n"))
