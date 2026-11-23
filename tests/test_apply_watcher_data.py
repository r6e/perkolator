"""Integration tests for the script that takes the watcher's two data files, and nothing else."""

import subprocess
from pathlib import Path

import pytest
from factories import FAKE_CREDENTIAL, FAKE_CREDENTIAL_TAIL, SAFE_PATH

SCRIPT = Path(__file__).parent.parent / "scripts" / "apply-watcher-data.sh"
CATALOG = "benefits.yaml"
CHANGES = "changes.yaml"
SEED = {CATALOG: "card: old\n", CHANGES: "changes: []\n"}
UPDATED = {CATALOG: "card: new\n", CHANGES: "changes: []\n"}
ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "PATH": SAFE_PATH,
}


def run(cwd: Path, *command: str, check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        command, cwd=cwd, env=ENV, check=check, capture_output=True, text=True
    )


def write_files(directory: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A git checkout whose data directory holds the seed files."""
    repo = tmp_path / "repo"
    write_files(repo / "data", SEED)
    write_files(repo, {"src.py": "trusted = True\n"})
    run(repo, "git", "init", "-q", "-b", "main", check=True)
    run(repo, "git", "add", "-A", check=True)
    run(repo, "git", "commit", "-q", "-m", "seed", check=True)
    return repo


@pytest.fixture
def incoming(tmp_path: Path) -> Path:
    """The directory the watcher's artifact was downloaded into, with a valid update."""
    directory = tmp_path / "incoming"
    write_files(directory, UPDATED)
    return directory


def apply(checkout: Path, incoming: Path) -> subprocess.CompletedProcess[str]:
    return run(checkout, "bash", str(SCRIPT), str(incoming), check=False)


def changed_paths(checkout: Path) -> list[str]:
    status = run(checkout, "git", "status", "--porcelain", "-uall", check=True).stdout
    return sorted(line[3:] for line in status.splitlines())


def assert_refused(checkout: Path, incoming: Path, reason: str) -> subprocess.CompletedProcess[str]:
    result = apply(checkout, incoming)
    assert result.returncode != 0
    assert reason in result.stderr
    assert changed_paths(checkout) == []
    return result


def test_update_is_copied_into_the_data_directory(checkout: Path, incoming: Path) -> None:
    result = apply(checkout, incoming)
    assert result.returncode == 0, result.stderr
    assert (checkout / "data" / CATALOG).read_text() == UPDATED[CATALOG]
    assert changed_paths(checkout) == [f"data/{CATALOG}"]


def test_missing_directory_is_refused(checkout: Path, tmp_path: Path) -> None:
    assert_refused(checkout, tmp_path / "nowhere", "not a directory")


def test_no_argument_is_refused(checkout: Path) -> None:
    result = run(checkout, "bash", str(SCRIPT), check=False)
    assert result.returncode != 0
    assert "usage" in result.stderr


@pytest.mark.parametrize("missing", [CATALOG, CHANGES])
def test_missing_data_file_is_refused(checkout: Path, incoming: Path, missing: str) -> None:
    (incoming / missing).unlink()
    assert_refused(checkout, incoming, "is missing")


@pytest.mark.parametrize(
    "extra",
    ["extra.yaml", "nested/benefits.yaml", ".hidden", "benefits.yaml.bak", "name with space"],
)
def test_any_other_file_is_refused(checkout: Path, incoming: Path, extra: str) -> None:
    write_files(incoming, {extra: "x\n"})
    assert_refused(checkout, incoming, "may hold only")


def test_empty_extra_directory_is_refused(checkout: Path, incoming: Path) -> None:
    (incoming / "empty").mkdir()
    assert_refused(checkout, incoming, "may hold only")


def test_symlink_in_place_of_data_file_is_refused(checkout: Path, incoming: Path) -> None:
    (incoming / CATALOG).unlink()
    (incoming / CATALOG).symlink_to("/etc/passwd")
    assert_refused(checkout, incoming, "not a regular file")


def test_oversized_data_file_is_refused(checkout: Path, incoming: Path) -> None:
    write_files(incoming, {CATALOG: "x" * 300_000})
    assert_refused(checkout, incoming, "too large")


@pytest.mark.parametrize("name", [CATALOG, CHANGES])
def test_data_that_looks_like_a_credential_is_refused(
    checkout: Path, incoming: Path, name: str
) -> None:
    write_files(incoming, {name: f"notes: {FAKE_CREDENTIAL}\n"})
    result = assert_refused(checkout, incoming, "credential")
    assert FAKE_CREDENTIAL_TAIL not in result.stdout + result.stderr


def test_unchanged_data_is_refused_because_the_watcher_did_nothing(
    checkout: Path, incoming: Path
) -> None:
    write_files(incoming, SEED)
    assert_refused(checkout, incoming, "made no update")


def test_nothing_outside_the_data_directory_is_touched(checkout: Path, incoming: Path) -> None:
    apply(checkout, incoming)
    assert (checkout / "src.py").read_text() == "trusted = True\n"
