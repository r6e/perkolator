import stat
from datetime import date, timedelta
from pathlib import Path

import pytest
from factories import (
    TODAY,
    benefits_page_html,
    catalog_yaml,
    changes_yaml,
    parse_calendar,
    write_file,
)

from perkolator.cli import CATALOG_FILE, CHANGES_FILE, MAX_ERROR_CHARS, main
from perkolator.loading import load_catalog

BUILD_DATE = TODAY.isoformat()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    write_file(tmp_path / "data" / CATALOG_FILE, catalog_yaml())
    return tmp_path / "data"


@pytest.fixture
def out(tmp_path: Path) -> Path:
    return tmp_path / "feed" / "amex.ics"


def build(data_dir: Path, out: Path, today: str = BUILD_DATE) -> int:
    return main(["build", "--data-dir", str(data_dir), "--out", str(out), "--today", today])


def validate(
    data_dir: Path,
    today: str = BUILD_DATE,
    *,
    verified_today: bool = False,
    keeps_benefits_of: Path | None = None,
) -> int:
    flags = ["--verified-today"] if verified_today else []
    if keeps_benefits_of is not None:
        flags += ["--keeps-benefits-of", str(keeps_benefits_of)]
    return main(["validate", "--data-dir", str(data_dir), "--today", today, *flags])


def normalize(data_dir: Path, *, check: bool = False) -> int:
    flags = ["--check"] if check else []
    return main(["normalize", "--data-dir", str(data_dir), "--today", BUILD_DATE, *flags])


def test_build_writes_parseable_feed(data_dir: Path, out: Path) -> None:
    assert build(data_dir, out) == 0
    assert len(parse_calendar(out.read_bytes()).events) == 19


@pytest.mark.parametrize(
    "smuggled",
    ['!!int "##[error]fake ::error::fake"', '!!int "' + "9x" * 5000 + '"'],
    ids=["runner-commands", "unbounded-length"],
)
def test_error_line_cannot_carry_runner_commands_or_unbounded_text(
    data_dir: Path, caplog: pytest.LogCaptureFixture, smuggled: str
) -> None:
    write_file(data_dir / CATALOG_FILE, f"card: {smuggled}\n")
    assert validate(data_dir) == 1
    message = only_log_line(caplog)
    assert CATALOG_FILE in message
    assert "##[" not in message
    assert "::" not in message
    assert len(message) <= MAX_ERROR_CHARS


def only_log_line(caplog: pytest.LogCaptureFixture) -> str:
    """Return the single line the command logged."""
    (record,) = caplog.records
    return record.getMessage()


QUOTED_MARKER = "##[error]quoted from the data"
NAMELESS_IO_FAILURE = "disk went away"


def unknown_key_error(data_dir: Path, caplog: pytest.LogCaptureFixture, key: str) -> str:
    """Return the error line for a catalog with an extra key, which the message quotes raw."""
    write_file(data_dir / CATALOG_FILE, catalog_yaml() + f'"{key}": 1\n')
    assert validate(data_dir) == 1
    return only_log_line(caplog)


def test_error_line_drops_invisible_and_terminal_control_characters(
    data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    message = unknown_key_error(data_dir, caplog, "red\\e[31m zero\\u200Bwidth")
    assert "red[31m zerowidth" in message


def test_error_line_breaks_up_runs_of_command_markers(
    data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    message = unknown_key_error(data_dir, caplog, ":::error:::: ###[error]")
    assert "error" in message
    assert "::" not in message
    assert "##[" not in message


def test_unexpected_failure_is_one_safe_line_not_a_traceback(
    data_dir: Path, out: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def explode(*_: object) -> None:
        raise RuntimeError(QUOTED_MARKER)

    monkeypatch.setattr("perkolator.cli.plan_events", explode)
    assert build(data_dir, out) == 1
    message = only_log_line(caplog)
    assert "RuntimeError" in message
    assert "##[" not in message
    assert not out.exists()


def test_io_failure_without_a_file_name_still_says_what_failed(
    data_dir: Path, out: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def explode(*_: object) -> None:
        raise OSError(NAMELESS_IO_FAILURE)

    monkeypatch.setattr("perkolator.cli._write_atomically", explode)
    assert build(data_dir, out) == 1
    assert NAMELESS_IO_FAILURE in caplog.text
    assert "None" not in caplog.text


@pytest.fixture
def previous(tmp_path: Path) -> Path:
    """The catalog as it stood before an update: two benefits."""
    return write_file(tmp_path / "previous.yaml", catalog_yaml({}, {"id": "equinox"}))


def test_validate_accepts_an_update_that_keeps_every_earlier_benefit(
    data_dir: Path, previous: Path
) -> None:
    write_file(data_dir / CATALOG_FILE, catalog_yaml({"id": "new"}, {"id": "equinox"}, {}))
    assert validate(data_dir, keeps_benefits_of=previous) == 0


def test_validate_refuses_an_update_that_drops_a_benefit(
    data_dir: Path, previous: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert validate(data_dir, keeps_benefits_of=previous) == 1
    assert "equinox" in caplog.text
    assert "by hand" in caplog.text
    assert validate(data_dir) == 0


def test_validate_refuses_an_update_that_strips_a_benefit_of_its_schedule(
    data_dir: Path, previous: Path, caplog: pytest.LogCaptureFixture
) -> None:
    hollowed = catalog_yaml({}, {"id": "equinox", "kind": "status", "cadence": None})
    write_file(data_dir / CATALOG_FILE, hollowed)
    assert validate(data_dir) == 0
    assert validate(data_dir, keeps_benefits_of=previous) == 1
    assert "equinox" in caplog.text
    assert "by hand" in caplog.text


def test_validate_accepts_an_update_that_changes_a_schedule(data_dir: Path, previous: Path) -> None:
    write_file(data_dir / CATALOG_FILE, catalog_yaml({}, {"id": "equinox", "cadence": "monthly"}))
    assert validate(data_dir, keeps_benefits_of=previous) == 0


def test_validate_refuses_when_the_earlier_catalog_is_unreadable(
    data_dir: Path, tmp_path: Path
) -> None:
    assert validate(data_dir, keeps_benefits_of=tmp_path / "missing.yaml") == 1


def test_build_refuses_to_write_an_outsized_feed(
    data_dir: Path, out: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("perkolator.cli._MAX_FEED_BYTES", 100)
    assert build(data_dir, out) == 1
    assert not out.exists()
    assert "too large" in caplog.text


def test_build_is_deterministic_for_fixed_today(data_dir: Path, out: Path, tmp_path: Path) -> None:
    second = tmp_path / "second.ics"
    assert build(data_dir, out) == 0
    assert build(data_dir, second) == 0
    assert out.read_bytes() == second.read_bytes()


def test_build_defaults_today_to_current_date(data_dir: Path, out: Path) -> None:
    assert main(["build", "--data-dir", str(data_dir), "--out", str(out)]) == 0
    assert out.read_bytes().startswith(b"BEGIN:VCALENDAR")


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        pytest.param(CATALOG_FILE, catalog_yaml({"cadence": "weekly"}), id="bad-cadence"),
        pytest.param(CATALOG_FILE, "card: [unclosed\n", id="yaml-syntax"),
        pytest.param(CATALOG_FILE, b"card: \xff\xfe\n", id="not-utf8"),
        pytest.param(CATALOG_FILE, catalog_yaml({}, {}), id="duplicate-benefit-id"),
        pytest.param(
            CATALOG_FILE,
            catalog_yaml(verified_on=TODAY + timedelta(days=1)),
            id="future-verified-on",
        ),
        pytest.param(CHANGES_FILE, changes_yaml({"detected_on": "not-a-date"}), id="bad-change"),
        pytest.param(
            CHANGES_FILE, changes_yaml({"detected_on": date(2027, 6, 1)}), id="future-change"
        ),
    ],
)
def test_bad_data_returns_1_and_leaves_feed_untouched(
    data_dir: Path, out: Path, filename: str, content: str | bytes, caplog: pytest.LogCaptureFixture
) -> None:
    write_file(out, b"OLD")
    write_file(data_dir / filename, content)
    assert build(data_dir, out) == 1
    assert validate(data_dir) == 1
    assert out.read_bytes() == b"OLD"
    assert caplog.records[-1].levelname == "ERROR"


def test_build_with_missing_catalog_returns_1(tmp_path: Path, out: Path) -> None:
    assert build(tmp_path / "nowhere", out) == 1
    assert not out.exists()


def test_build_with_unwritable_destination_returns_1(data_dir: Path, tmp_path: Path) -> None:
    blocker = write_file(tmp_path / "blocker", "a file where a directory is needed")
    assert build(data_dir, blocker / "amex.ics") == 1


def test_build_with_invalid_today_exits_2(data_dir: Path, out: Path) -> None:
    with pytest.raises(SystemExit) as raised:
        build(data_dir, out, today="tomorrow")
    assert raised.value.code == 2


def test_validate_ok_returns_0(data_dir: Path) -> None:
    assert validate(data_dir) == 0


def test_build_leaves_no_temp_files(data_dir: Path, out: Path) -> None:
    assert build(data_dir, out) == 0
    assert [path.name for path in out.parent.iterdir()] == [out.name]


def extract(html: Path, out: Path) -> int:
    return main(["extract-text", "--html", str(html), "--out", str(out)])


def test_extract_text_writes_the_page_text(tmp_path: Path) -> None:
    html = write_file(tmp_path / "page.html", benefits_page_html("<p>Up to $400 Resy</p>"))
    out = tmp_path / "source" / "page.txt"
    assert extract(html, out) == 0
    assert "Up to $400 Resy" in out.read_text(encoding="utf-8")


@pytest.mark.parametrize("content", ["<p>Access Denied</p>", b"\xff\xfe"], ids=["blocked", "bytes"])
def test_extract_text_of_unusable_page_returns_1(tmp_path: Path, content: str | bytes) -> None:
    html = write_file(tmp_path / "page.html", content)
    out = tmp_path / "page.txt"
    assert extract(html, out) == 1
    assert not out.exists()


def test_extract_text_of_missing_file_names_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert extract(tmp_path / "missing.html", tmp_path / "page.txt") == 1
    assert "missing.html" in caplog.text


def test_written_files_are_world_readable(data_dir: Path, out: Path) -> None:
    assert build(data_dir, out) == 0
    assert stat.S_IMODE(out.stat().st_mode) == 0o644


def test_validate_verified_today_accepts_a_catalog_verified_on_the_build_date(
    data_dir: Path,
) -> None:
    assert validate(data_dir, verified_today=True) == 0


def test_validate_verified_today_rejects_an_older_verification(
    data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    assert validate(data_dir, tomorrow, verified_today=True) == 1
    assert "verified_on" in caplog.text
    assert validate(data_dir, tomorrow) == 0


SMUGGLED = ("#", "&", "%YAML", "next run", "next_run")


def test_normalize_removes_everything_the_schema_does_not_hold(data_dir: Path) -> None:
    catalog = data_dir / CATALOG_FILE
    marked = catalog.read_text().replace(
        "card: platinum-us-personal\n",
        "card: &note_to_the_next_run platinum-us-personal  # words for the next run\n",
    )
    catalog.write_text(f"%YAML 1.1\n---\n{marked}# a full line for the next run\n")
    before = load_catalog(catalog)
    assert all(marker in catalog.read_text() for marker in SMUGGLED)

    assert normalize(data_dir) == 0

    assert load_catalog(catalog) == before
    assert not [marker for marker in SMUGGLED if marker in catalog.read_text()]


def snapshot(data_dir: Path) -> list[bytes]:
    return [(data_dir / name).read_bytes() for name in (CATALOG_FILE, CHANGES_FILE)]


def test_normalize_is_stable(data_dir: Path) -> None:
    assert normalize(data_dir) == 0
    first = snapshot(data_dir)
    assert normalize(data_dir) == 0
    assert snapshot(data_dir) == first


def test_normalize_check_passes_on_files_in_the_written_form(data_dir: Path) -> None:
    assert normalize(data_dir) == 0
    assert normalize(data_dir, check=True) == 0


def test_normalize_check_fails_and_writes_nothing_when_files_would_change(
    data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert normalize(data_dir) == 0
    with (data_dir / CATALOG_FILE).open("a") as handle:
        handle.write("# a hand-written comment\n")
    before = snapshot(data_dir)
    assert normalize(data_dir, check=True) == 1
    assert snapshot(data_dir) == before
    assert CATALOG_FILE in caplog.text
    assert "perkolator normalize" in caplog.text


def test_normalize_of_invalid_data_changes_nothing(data_dir: Path) -> None:
    catalog = write_file(data_dir / CATALOG_FILE, catalog_yaml(card="Not A Slug"))
    before = catalog.read_bytes()
    assert normalize(data_dir) == 1
    assert catalog.read_bytes() == before
