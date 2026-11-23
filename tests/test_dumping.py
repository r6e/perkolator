"""Tests for writing validated data back out as YAML."""

from pathlib import Path

from factories import make_benefit, make_catalog, make_change, write_file

from perkolator.dumping import dump_yaml
from perkolator.loading import load_catalog, load_changes
from perkolator.models import ChangeLog

CATALOG = make_catalog(
    make_benefit(
        amount_usd="12.95",
        amount_label="$12.95: a month",
        url="https://example.com/terms",
        notes="First line.\nSecond line # not a comment.\n" + "long " * 40,
    ),
    make_benefit(id="plain", name="Plain # one"),
)
CHANGES = ChangeLog(changes=(make_change(detail="Was $100.\nNow $50."),))


def test_catalog_survives_a_round_trip(tmp_path: Path) -> None:
    path = write_file(tmp_path / "benefits.yaml", dump_yaml(CATALOG))
    assert load_catalog(path) == CATALOG


def test_change_log_survives_a_round_trip(tmp_path: Path) -> None:
    path = write_file(tmp_path / "changes.yaml", dump_yaml(CHANGES))
    assert load_changes(path) == CHANGES


def test_unset_optional_fields_are_left_out() -> None:
    text = dump_yaml(make_catalog(make_benefit()))
    assert "notes" not in text
    assert "null" not in text


def test_dates_and_amounts_are_written_plainly() -> None:
    text = dump_yaml(CATALOG)
    assert "verified_on: 2026-11-21\n" in text
    assert "amount_usd: 12.95\n" in text
    assert "amount_usd: 100\n" in text


def test_output_uses_no_anchors_tags_or_directives() -> None:
    shared = make_benefit()
    text = dump_yaml(make_catalog(shared, shared.model_copy(update={"id": "other"})))
    assert not any(line.lstrip().startswith(("&", "*", "!", "%")) for line in text.splitlines())
    assert ": &" not in text
    assert ": *" not in text
    assert ": !" not in text


def test_empty_change_log_keeps_its_list() -> None:
    assert dump_yaml(ChangeLog()) == "changes: []\n"
