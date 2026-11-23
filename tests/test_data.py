"""Checks on the live data files.

This suite runs before every deploy, including after the unattended watcher
has edited these files, so every assertion here must hold for any valid edit,
not just today's content. Formatting is checked separately, by
`perkolator normalize --check` in CI.
"""

from pathlib import Path

from perkolator.loading import load_catalog, load_changes
from perkolator.models import ChangeLog

DATA = Path(__file__).parent.parent / "data"


def test_real_catalog_loads() -> None:
    assert load_catalog(DATA / "benefits.yaml").card == "platinum-us-personal"


def test_real_changes_load() -> None:
    assert isinstance(load_changes(DATA / "changes.yaml"), ChangeLog)
