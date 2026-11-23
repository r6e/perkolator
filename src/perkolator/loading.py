"""Read the data files, turning every failure into one error type."""

from collections.abc import Hashable
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from perkolator.models import BenefitCatalog, ChangeLog

__all__ = ["DataError", "check_not_future", "load_catalog", "load_changes"]


class DataError(Exception):
    """A data file is missing, unreadable or invalid."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that refuses a mapping with a repeated key."""

    def construct_mapping(
        self,
        node: yaml.MappingNode,
        deep: bool = False,  # noqa: FBT001, FBT002
    ) -> dict[Hashable, object]:
        """Build the mapping, raising on the first repeated or unhashable key."""
        seen: set[Hashable] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            problem = None
            if not isinstance(key, Hashable):
                problem = "mapping key is not a plain value"
            elif key in seen:
                problem = f"duplicate key {key!r}"
            if problem:
                raise yaml.constructor.ConstructorError(None, None, problem, key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load_catalog(path: Path) -> BenefitCatalog:
    """Load and validate the benefit catalog.

    Args:
        path: Location of the catalog YAML file.

    Returns:
        The validated catalog.

    Raises:
        DataError: If the file is missing, unreadable, not valid YAML, or breaks the schema.
    """
    return _validate(path, _read(path), BenefitCatalog)


def load_changes(path: Path) -> ChangeLog:
    """Load and validate the change log; a missing or empty file means no changes.

    Args:
        path: Location of the change log YAML file.

    Returns:
        The validated change log.

    Raises:
        DataError: If the file is unreadable, not valid YAML, or breaks the schema.
    """
    if not path.exists():
        return ChangeLog()
    raw = _read(path)
    return ChangeLog() if raw is None else _validate(path, raw, ChangeLog)


def check_not_future(catalog: BenefitCatalog, changes: ChangeLog, today: date) -> None:
    """Reject dates later than the build date.

    Args:
        catalog: The loaded catalog.
        changes: The loaded change log.
        today: The build date.

    Raises:
        DataError: If the catalog or any change is dated after `today`.
    """
    if catalog.verified_on > today:
        msg = f"verified_on {catalog.verified_on} is after {today}"
        raise DataError(msg)
    for change in changes.changes:
        if change.detected_on > today:
            msg = f"change {change.id}: detected_on {change.detected_on} is after {today}"
            raise DataError(msg)


def _read(path: Path) -> object:
    try:
        # _UniqueKeyLoader derives from SafeLoader, so this is a safe load.
        return yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)  # noqa: S506
    except Exception as error:  # the YAML loader raises assorted types on hostile input
        one_line = " ".join(str(error).split()) or type(error).__name__
        msg = f"{path}: {one_line}"
        raise DataError(msg) from error


def _validate[M: BaseModel](path: Path, raw: object, model: type[M]) -> M:
    try:
        return model.model_validate(raw)
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "(root)"
        msg = f"{path}: {location}: {first['msg']} ({error.error_count()} problem(s) in total)"
        raise DataError(msg) from error
