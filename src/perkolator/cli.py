"""Command line entry point: build the feed, check or rewrite the data, or extract page text."""

import argparse
import logging
import os
import re
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final, assert_never

from perkolator.dumping import dump_yaml
from perkolator.feed import render_ics
from perkolator.loading import DataError, check_not_future, load_catalog, load_changes
from perkolator.models import BenefitCatalog, ChangeLog
from perkolator.pagetext import PageError, html_to_text
from perkolator.schedule import plan_events
from perkolator.text import is_unsafe

__all__ = ["CATALOG_FILE", "CHANGES_FILE", "MAX_ERROR_CHARS", "main"]

CATALOG_FILE: Final = "benefits.yaml"
CHANGES_FILE: Final = "changes.yaml"
DEFAULT_DATA_DIR: Final = Path("data")
DEFAULT_OUT: Final = Path("_site/amex-platinum.ics")

_ADJACENT_COLON: Final = re.compile(r":(?=:)")
MAX_ERROR_CHARS: Final = 300
"""Longest error line the command writes; error text can quote untrusted input."""

_EXIT_OK: Final = 0
_EXIT_FAILED: Final = 1
_OUTPUT_MODE: Final = 0o644
# The real feed is about 20 kB. The schema's bounds keep any valid file well
# under this in practice; this is the hard limit on what gets published.
_MAX_FEED_BYTES: Final = 1_000_000

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Build:
    data_dir: Path
    today: date
    out: Path


@dataclass(frozen=True, slots=True)
class _Validate:
    data_dir: Path
    today: date
    verified_today: bool
    keeps_benefits_of: Path | None


@dataclass(frozen=True, slots=True)
class _Normalize:
    data_dir: Path
    today: date
    check: bool


@dataclass(frozen=True, slots=True)
class _ExtractText:
    html: Path
    out: Path


type _Command = _Build | _Validate | _Normalize | _ExtractText


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line interface.

    Args:
        argv: Arguments without the program name; defaults to the process arguments.

    Returns:
        0 on success, 1 when the input is invalid or a file cannot be read or written.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    command = _parse(argv)
    try:
        _run(command)
    except (DataError, PageError) as error:
        return _fail(str(error))
    except UnicodeDecodeError as error:
        return _fail(f"input is not UTF-8 text: {error}")
    except OSError as error:
        return _fail(f"{error.filename}: {error.strerror}" if error.filename else str(error))
    except Exception as error:  # noqa: BLE001 - a traceback could quote input into a public log
        return _fail(f"unexpected {type(error).__name__}: {error}")
    return _EXIT_OK


def _fail(message: str) -> int:
    """Log one bounded line that a CI runner cannot read as a command.

    Error text can quote the input, and the watcher's log is public. GitHub's
    runner acts on "::name::" at the start of a line and "##[name]" anywhere,
    so no two colons are left adjacent and every "#[" is split.
    Invisible and control characters are dropped.
    """
    visible = "".join(c for c in " ".join(message.split()) if not is_unsafe(c))
    line = _ADJACENT_COLON.sub(": ", visible).replace("#[", "# [")
    logger.error("%s", line[:MAX_ERROR_CHARS])
    return _EXIT_FAILED


def _today() -> date:
    return datetime.now(tz=UTC).date()


def _parse(argv: Sequence[str] | None) -> _Command:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    common.add_argument(
        "--today",
        type=date.fromisoformat,
        default=_today(),
        help="build date as YYYY-MM-DD (default: current UTC date)",
    )
    parser = argparse.ArgumentParser(prog="perkolator", description=__doc__)
    commands = parser.add_subparsers(required=True)

    build = commands.add_parser(
        "build", parents=[common], help="validate the data and write the calendar feed"
    )
    build.add_argument("--out", type=Path, default=DEFAULT_OUT)
    build.set_defaults(make=lambda a: _Build(a.data_dir, a.today, a.out))

    validate = commands.add_parser(
        "validate", parents=[common], help="validate the data without writing anything"
    )
    validate.add_argument(
        "--verified-today",
        action="store_true",
        help="also require the catalog's verified_on to equal the build date",
    )
    validate.add_argument(
        "--keeps-benefits-of",
        type=Path,
        metavar="CATALOG",
        help="also require every benefit in this earlier catalog file to still be present",
    )
    validate.set_defaults(
        make=lambda a: _Validate(a.data_dir, a.today, a.verified_today, a.keeps_benefits_of)
    )

    normalize = commands.add_parser(
        "normalize",
        parents=[common],
        help="rewrite the data files from their validated content, dropping comments",
    )
    normalize.add_argument(
        "--check",
        action="store_true",
        help="write nothing; fail if either file is not already in the written form",
    )
    normalize.set_defaults(make=lambda a: _Normalize(a.data_dir, a.today, a.check))

    extract = commands.add_parser(
        "extract-text", help="write the visible text of a downloaded benefits page"
    )
    extract.add_argument("--html", type=Path, required=True)
    extract.add_argument("--out", type=Path, required=True)
    extract.set_defaults(make=lambda a: _ExtractText(a.html, a.out))

    parsed = parser.parse_args(argv)
    command: _Command = parsed.make(parsed)
    return command


def _run(command: _Command) -> None:
    match command:
        case _Build(data_dir, today, out):
            catalog, changes = _load(data_dir, today)
            events = plan_events(catalog, changes, today)
            feed = render_ics(events, today)
            if len(feed) > _MAX_FEED_BYTES:
                msg = f"the feed is too large ({len(feed)} bytes, limit {_MAX_FEED_BYTES})"
                raise DataError(msg)
            _write_atomically(out, feed)
            logger.info("wrote %d events to %s", len(events), out)
        case _Validate():
            _validate(command)
        case _Normalize():
            _normalize(command)
        case _ExtractText(html, out):
            text = html_to_text(html.read_text(encoding="utf-8"))
            _write_atomically(out, text.encode())
            logger.info("wrote %d characters of page text to %s", len(text), out)
        case _:
            assert_never(command)


def _validate(command: _Validate) -> None:
    catalog, changes = _load(command.data_dir, command.today)
    if command.verified_today and catalog.verified_on != command.today:
        msg = f"verified_on is {catalog.verified_on}, not {command.today}; the check did not run"
        raise DataError(msg)
    if command.keeps_benefits_of is not None:
        _require_benefits_kept(catalog, load_catalog(command.keeps_benefits_of))
    logger.info("%d benefits and %d changes are valid", len(catalog.benefits), len(changes.changes))


def _require_benefits_kept(catalog: BenefitCatalog, earlier: BenefitCatalog) -> None:
    """Refuse a catalog that drops an earlier benefit, or the schedule its reminders need.

    The issuer's page omits benefits cardholders still have, so its silence is
    not grounds for an unattended removal.
    """
    now = {benefit.id: benefit for benefit in catalog.benefits}
    lost = [
        benefit.id
        for benefit in earlier.benefits
        if benefit.id not in now or (benefit.cadence and not now[benefit.id].cadence)
    ]
    if lost:
        msg = (
            f"benefits removed or left without a schedule: {', '.join(lost)}. "
            "An automatic update may not do that; make the change by hand if it is real"
        )
        raise DataError(msg)


def _normalize(command: _Normalize) -> None:
    data_dir = command.data_dir
    catalog, changes = _load(data_dir, command.today)
    written = {
        data_dir / CATALOG_FILE: dump_yaml(catalog).encode(),
        data_dir / CHANGES_FILE: dump_yaml(changes).encode(),
    }
    if not command.check:
        for path, content in written.items():
            _write_atomically(path, content)
        logger.info("rewrote %s and %s in %s", CATALOG_FILE, CHANGES_FILE, data_dir)
        return
    stale = [path.name for path, content in written.items() if _read_if_present(path) != content]
    if stale:
        msg = f"{' and '.join(stale)} not in the written form; run `perkolator normalize`"
        raise DataError(msg)
    logger.info("%s and %s are in the written form", CATALOG_FILE, CHANGES_FILE)


def _read_if_present(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def _load(data_dir: Path, today: date) -> tuple[BenefitCatalog, ChangeLog]:
    catalog = load_catalog(data_dir / CATALOG_FILE)
    changes = load_changes(data_dir / CHANGES_FILE)
    check_not_future(catalog, changes, today)
    return catalog, changes


def _write_atomically(out: Path, content: bytes) -> None:
    """Write via a temporary file, readable by all (a web host serves the feed)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        Path(temporary).chmod(_OUTPUT_MODE)
        Path(temporary).replace(out)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
