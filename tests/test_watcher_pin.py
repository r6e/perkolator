"""The model's restrictions were checked by hand against one tool version; a bump must be deliberate."""

import json
from pathlib import Path

WATCHER = Path(__file__).parent.parent / "watcher"
PACKAGE = "@anthropic-ai/claude-code"
# The version scripts/run-watcher.sh's flags were last probed against: with them
# the model had exactly Read and Edit, could edit only the two data files, and
# could not read outside the working directory or under /proc. Probe again
# before changing this.
LAST_PROBED_VERSION = "2.1.325"


def test_declared_version_is_the_probed_one() -> None:
    declared = json.loads((WATCHER / "package.json").read_text())["dependencies"][PACKAGE]
    assert declared == LAST_PROBED_VERSION


def test_locked_version_is_the_probed_one_and_has_a_hash() -> None:
    locked = json.loads((WATCHER / "package-lock.json").read_text())["packages"]
    entry = locked[f"node_modules/{PACKAGE}"]
    assert entry["version"] == LAST_PROBED_VERSION
    assert entry["integrity"].startswith("sha512-")
