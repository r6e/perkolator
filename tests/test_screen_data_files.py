"""Tests for the credential tripwire run on the watcher's output before upload and on intake."""

import re
import subprocess
from pathlib import Path

import pytest
from factories import (
    FAKE_CREDENTIAL,
    FAKE_CREDENTIAL_TAIL,
    FAKE_IDENTITY_TOKEN,
    SAFE_PATH,
    make_stub,
)

SCRIPT = Path(__file__).parent.parent / "scripts" / "screen-data-files.sh"
LOG_SCRIPT = SCRIPT.parent / "run-watcher.sh"


def screen(*files: Path, path: str = SAFE_PATH) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), *map(str, files)],  # noqa: S607
        env={"PATH": path},
        check=False,
        capture_output=True,
        text=True,
    )


def data_file(tmp_path: Path, content: str, name: str = "benefits.yaml") -> Path:
    path = tmp_path / name
    path.write_text(content)
    return path


def test_clean_files_pass(tmp_path: Path) -> None:
    result = screen(data_file(tmp_path, "card: x\n"), data_file(tmp_path, "changes: []\n", "c"))
    assert result.returncode == 0, result.stderr


def test_no_files_is_refused() -> None:
    result = screen()
    assert result.returncode != 0
    assert "usage" in result.stderr


@pytest.mark.parametrize("credential", [FAKE_CREDENTIAL, FAKE_IDENTITY_TOKEN], ids=["key", "jwt"])
def test_credential_in_any_file_is_refused_without_echoing_it(
    tmp_path: Path, credential: str
) -> None:
    clean = data_file(tmp_path, "card: x\n", "ok.yaml")
    result = screen(clean, data_file(tmp_path, f"notes: {credential}\n"))
    assert result.returncode != 0
    assert "credential" in result.stderr
    assert FAKE_CREDENTIAL_TAIL not in result.stdout + result.stderr


def test_missing_file_is_refused(tmp_path: Path) -> None:
    assert screen(tmp_path / "nowhere.yaml").returncode != 0


def test_grep_failing_is_refused_rather_than_passed(tmp_path: Path) -> None:
    stubs = make_stub(tmp_path / "bin", "grep", "#!/bin/sh\nexit 2\n")
    result = screen(data_file(tmp_path, "card: x\n"), path=f"{stubs}:{SAFE_PATH}")
    assert result.returncode != 0
    assert "grep failed" in result.stderr


def credential_shapes(script: Path) -> str:
    (shapes,) = re.findall(r"^readonly CREDENTIAL_SHAPES='(.+)'$", script.read_text(), re.MULTILINE)
    assert isinstance(shapes, str)
    return shapes


def test_data_files_and_failure_logs_are_screened_for_the_same_shapes() -> None:
    assert credential_shapes(SCRIPT) == credential_shapes(LOG_SCRIPT)
