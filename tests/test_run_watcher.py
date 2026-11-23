"""Tests for the script that picks a credential and runs the model with a fixed tool set."""

import os
import re
import subprocess
from pathlib import Path

import pytest
from factories import FAKE_CREDENTIAL, FAKE_CREDENTIAL_TAIL, FAKE_IDENTITY_TOKEN, make_stub

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "run-watcher.sh"
INJECTED = "::error::printed by the model"
LEGACY = "##[error]old style command"
EARLY_LINE = "early line"
PREFIX = "  | "


def script_constant(name: str) -> int:
    """Read one of the script's numeric settings, so the test cannot drift from it."""
    (value,) = re.findall(rf"^readonly {name}=(\d+)$", SCRIPT.read_text(), re.MULTILINE)
    return int(value)


MAX_TAIL_LINES = script_constant("ERROR_TAIL_LINES")
MAX_TAIL_LINE = script_constant("ERROR_LINE_BYTES") + len(PREFIX)

FAKE_CLAUDE = f"""#!/bin/sh
{{
  echo "api=${{ANTHROPIC_API_KEY-unset}}"
  echo "oauth=${{CLAUDE_CODE_OAUTH_TOKEN-unset}}"
  echo "autoupdate=${{DISABLE_AUTOUPDATER-unset}}"
  echo "rule=${{ANTHROPIC_FEDERATION_RULE_ID-unset}}"
  echo "workspace=${{ANTHROPIC_WORKSPACE_ID-unset}}"
  echo "identity=$(cat "${{ANTHROPIC_IDENTITY_TOKEN_FILE:-/dev/null}}")"
  echo "identity_file=${{ANTHROPIC_IDENTITY_TOKEN_FILE-unset}}"
  echo "request=${{ACTIONS_ID_TOKEN_REQUEST_TOKEN-unset}}${{ACTIONS_ID_TOKEN_REQUEST_URL-unset}}"
  for arg in "$@"; do echo "arg=$arg"; done
  echo "stdin=$(head -n 1)"
}} > "$RECORD"
echo "{INJECTED}"
for n in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do echo "{EARLY_LINE} $n" >&2; done
echo "{INJECTED}" >&2
echo "see {LEGACY}" >&2
head -c 200000 /dev/zero | tr '\\0' 'x' >&2
echo " after a very long line" >&2
# One line of 200 "#[" pairs.
printf '%s\\n' "$(head -c 400 /dev/zero | tr '\\0' '#' | sed 's/##/#[/g')" >&2
echo ":::error:::: ###[error]" >&2
printf 'reversed \\342\\200\\256 and csi \\302\\233 31m\\n' >&2
head -c 200000 /dev/zero | tr '\\0' ':' >&2
echo " after a very long run" >&2
printf 'overwritten\r::warning::after a carriage return\n' >&2
printf 'colour \033[31mred\n' >&2
echo "authentication failed" >&2
[ -n "${{FAKE_LAST_WORDS:-}}" ] && echo "$FAKE_LAST_WORDS"
exit "${{FAKE_EXIT:-0}}"
"""


# Stands in for GitHub's identity token endpoint: records how it was asked.
FAKE_CURL = r"""#!/bin/sh
{
  for arg in "$@"; do echo "arg=$arg"; done
  echo "config=$(cat)"
} > "$RECORD.curl"
[ -n "${CURL_EXIT:-}" ] && exit "$CURL_EXIT"
if [ "${CURL_BODY+set}" = set ]; then
  printf '%s' "$CURL_BODY"
else
  printf '%s' '{"value":"header.claims.signature"}'
fi
"""

FEDERATION = {
    "ANTHROPIC_FEDERATION_RULE_ID": "fdrl_test",
    "ANTHROPIC_ORGANIZATION_ID": "org-test",
    "ANTHROPIC_SERVICE_ACCOUNT_ID": "svac_test",
    "ANTHROPIC_WORKSPACE_ID": "wrkspc_test",
    "ACTIONS_ID_TOKEN_REQUEST_URL": "https://runner.invalid/token?api-version=2",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "request-token-value",
}


@pytest.fixture
def record(tmp_path: Path) -> Path:
    make_stub(tmp_path / "bin", "claude", FAKE_CLAUDE)
    make_stub(tmp_path / "bin", "curl", FAKE_CURL)
    return tmp_path / "record"


def run(record: Path, **env: str) -> subprocess.CompletedProcess[str]:
    full_env = {
        "PATH": f"{record.parent / 'bin'}:{os.environ['PATH']}",
        "RECORD": str(record),
        **env,
    }
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)],  # noqa: S607
        cwd=ROOT,
        env=full_env,
        check=False,
        capture_output=True,
        text=True,
    )


def recorded(record: Path) -> list[str]:
    return record.read_text().splitlines()


def test_api_key_is_preferred_when_both_are_set(record: Path) -> None:
    result = run(record, ANTHROPIC_API_KEY="key", CLAUDE_CODE_OAUTH_TOKEN="token")
    assert result.returncode == 0
    assert {"api=key", "oauth=unset"} <= set(recorded(record))
    assert "API key" in result.stdout


@pytest.mark.parametrize("empty_key", [{}, {"ANTHROPIC_API_KEY": ""}])
def test_subscription_token_is_used_without_an_api_key(
    record: Path, empty_key: dict[str, str]
) -> None:
    result = run(record, CLAUDE_CODE_OAUTH_TOKEN="token", **empty_key)
    assert result.returncode == 0
    assert {"api=unset", "oauth=token"} <= set(recorded(record))
    assert "subscription token" in result.stdout


@pytest.mark.parametrize("env", [{}, {"ANTHROPIC_API_KEY": "", "CLAUDE_CODE_OAUTH_TOKEN": ""}])
def test_no_credential_fails_before_running_the_model(record: Path, env: dict[str, str]) -> None:
    result = run(record, **env)
    assert result.returncode != 0
    assert "ANTHROPIC_API_KEY" in result.stderr
    assert "ANTHROPIC_FEDERATION_RULE_ID" in result.stderr
    assert "CLAUDE_CODE_OAUTH_TOKEN" in result.stderr
    assert not record.exists()


def test_credentials_are_never_printed(record: Path) -> None:
    result = run(record, ANTHROPIC_API_KEY="key-value", CLAUDE_CODE_OAUTH_TOKEN="token-value")
    assert "key-value" not in result.stdout + result.stderr
    assert "token-value" not in result.stdout + result.stderr


def flag_values(args: list[str], flag: str) -> list[str]:
    """Return the values following `flag`, up to the next flag."""
    values = args[args.index(flag) + 1 :]
    return values[: next((i for i, value in enumerate(values) if value.startswith("--")), None)]


def test_model_runs_headless_with_only_file_tools(record: Path) -> None:
    run(record, ANTHROPIC_API_KEY="key")
    args = [line.removeprefix("arg=") for line in recorded(record) if line.startswith("arg=")]
    assert args[0] == "-p"
    assert {"--restricted", "--strict-mcp-config"} <= set(args)
    assert flag_values(args, "--permission-mode") == ["dontAsk"]
    assert flag_values(args, "--tools") == ["Read,Edit"]
    assert sorted(flag_values(args, "--allowedTools")) == [
        "Edit(data/benefits.yaml)",
        "Edit(data/changes.yaml)",
        "Read(data/**)",
        "Read(source/**)",
    ]
    assert flag_values(args, "--disallowedTools") == ["Read(//proc/**)"]
    assert "autoupdate=1" in recorded(record)


def test_prompt_is_the_tracked_file(record: Path) -> None:
    run(record, ANTHROPIC_API_KEY="key")
    first_line = (ROOT / "watcher" / "PROMPT.md").read_text().splitlines()[0]
    assert f"stdin={first_line}" in recorded(record)


def test_model_output_is_kept_out_of_the_log(record: Path) -> None:
    result = run(record, ANTHROPIC_API_KEY="key")
    assert "printed by the model" not in result.stdout + result.stderr


def test_model_failure_fails_the_script_and_shows_a_defused_error_tail(record: Path) -> None:
    result = run(record, ANTHROPIC_API_KEY="key", FAKE_EXIT="3")
    assert result.returncode != 0
    assert "authentication failed" in result.stderr
    assert "::" not in result.stderr
    assert "##[" not in result.stderr
    assert all(c == "\n" or " " <= c <= "~" for c in result.stderr)
    assert max(map(len, result.stderr.splitlines())) <= MAX_TAIL_LINE
    shown = result.stderr.splitlines()[1:]
    assert len(shown) == MAX_TAIL_LINES
    assert not any(line.endswith(f"{EARLY_LINE} 1") for line in shown)
    assert any(EARLY_LINE in line for line in shown)
    assert all(line.startswith(PREFIX) for line in shown)
    assert INJECTED not in result.stdout


def test_successful_run_shows_none_of_the_tool_error_stream(record: Path) -> None:
    result = run(record, ANTHROPIC_API_KEY="key")
    assert "authentication failed" not in result.stdout + result.stderr


def curl_record(record: Path) -> Path:
    """Where the fake curl writes how it was called; absent if it never ran."""
    return Path(f"{record}.curl")


def test_workload_identity_is_used_when_configured_without_an_api_key(record: Path) -> None:
    result = run(record, CLAUDE_CODE_OAUTH_TOKEN="token", ANTHROPIC_API_KEY="", **FEDERATION)
    assert result.returncode == 0
    assert {
        "api=unset",
        "oauth=unset",
        "rule=fdrl_test",
        "workspace=wrkspc_test",
        "identity=header.claims.signature",
    } <= set(recorded(record))
    assert "workload identity" in result.stdout


def test_identity_token_is_requested_for_the_anthropic_audience(record: Path) -> None:
    run(record, **FEDERATION)
    call = curl_record(record).read_text()
    assert "https://runner.invalid/token?api-version=2&audience=https://api.anthropic.com" in call
    assert "Authorization: Bearer request-token-value" in call.partition("config=")[2]
    assert "request-token-value" not in call.partition("config=")[0]


def test_api_key_is_preferred_over_workload_identity(record: Path) -> None:
    result = run(record, ANTHROPIC_API_KEY="key", **FEDERATION)
    assert result.returncode == 0
    assert {"api=key", "rule=unset", "identity_file=unset"} <= set(recorded(record))
    assert not curl_record(record).exists()


@pytest.mark.parametrize(
    "credential",
    [pytest.param({"ANTHROPIC_API_KEY": "key"}, id="api-key"), pytest.param({}, id="identity")],
)
def test_model_cannot_request_another_identity_token(
    record: Path, credential: dict[str, str]
) -> None:
    run(record, **FEDERATION, **credential)
    assert "request=unsetunset" in recorded(record)


def test_identity_token_file_is_private_and_removed_afterwards(record: Path) -> None:
    run(record, **FEDERATION)
    (line,) = [line for line in recorded(record) if line.startswith("identity_file=")]
    token_file = Path(line.removeprefix("identity_file="))
    assert not token_file.is_relative_to(ROOT)
    assert not token_file.exists()


def test_identity_tokens_are_masked_and_never_otherwise_printed(record: Path) -> None:
    result = run(record, **FEDERATION)
    output = (result.stdout + result.stderr).splitlines()
    assert "::add-mask::header.claims.signature" in output
    assert [line for line in output if "header.claims.signature" in line] == [
        "::add-mask::header.claims.signature"
    ]
    assert "request-token-value" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("missing", "reason"),
    [
        ("ANTHROPIC_ORGANIZATION_ID", "ANTHROPIC_ORGANIZATION_ID"),
        ("ANTHROPIC_SERVICE_ACCOUNT_ID", "ANTHROPIC_SERVICE_ACCOUNT_ID"),
        ("ACTIONS_ID_TOKEN_REQUEST_URL", "id-token: write"),
        ("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "id-token: write"),
    ],
)
def test_incomplete_workload_identity_fails_before_running_the_model(
    record: Path, missing: str, reason: str
) -> None:
    result = run(record, **(FEDERATION | {missing: ""}))
    assert result.returncode != 0
    assert reason in result.stderr
    assert not record.exists()


@pytest.mark.parametrize(
    "curl",
    [
        pytest.param({"CURL_EXIT": "22"}, id="request-failed"),
        pytest.param({"CURL_BODY": ""}, id="empty-body"),
        pytest.param({"CURL_BODY": "not json"}, id="not-json"),
        pytest.param({"CURL_BODY": "{}"}, id="no-value"),
        pytest.param({"CURL_BODY": '{"value":""}'}, id="empty-value"),
        pytest.param({"CURL_BODY": '{"value":null}'}, id="null-value"),
        pytest.param({"CURL_BODY": '{"value":7}'}, id="value-not-text"),
        pytest.param({"CURL_BODY": '{"value":"not a token"}'}, id="not-token-shaped"),
        pytest.param({"CURL_BODY": r'{"value":"a.b.c\n::error::x"}'}, id="second-line"),
    ],
)
def test_failed_identity_token_request_fails_before_running_the_model(
    record: Path, curl: dict[str, str]
) -> None:
    result = run(record, **FEDERATION, **curl)
    assert result.returncode != 0
    assert "identity token" in result.stderr
    assert "::" not in result.stdout
    assert not record.exists()


def test_unset_workspace_is_not_passed_on(record: Path) -> None:
    run(record, **(FEDERATION | {"ANTHROPIC_WORKSPACE_ID": ""}))
    assert "workspace=unset" in recorded(record)


def test_empty_workload_identity_settings_do_not_reach_other_modes(record: Path) -> None:
    empty = dict.fromkeys(FEDERATION, "")
    run(record, CLAUDE_CODE_OAUTH_TOKEN="token", **empty)
    assert {"oauth=token", "rule=unset", "workspace=unset"} <= set(recorded(record))


def test_failure_reason_printed_on_standard_output_is_shown(record: Path) -> None:
    reason = "API Error: Token exchange failed with status 401"
    result = run(record, ANTHROPIC_API_KEY="key", FAKE_EXIT="1", FAKE_LAST_WORDS=reason)
    assert result.returncode == 1
    assert f"{PREFIX}{reason}" in result.stderr.splitlines()
    assert reason not in result.stdout


@pytest.mark.parametrize("credential", [FAKE_CREDENTIAL, FAKE_IDENTITY_TOKEN], ids=["key", "jwt"])
def test_failure_lines_that_look_like_a_credential_are_withheld(
    record: Path, credential: str
) -> None:
    result = run(
        record, ANTHROPIC_API_KEY="key", FAKE_EXIT="1", FAKE_LAST_WORDS=f"denied for {credential}"
    )
    assert FAKE_CREDENTIAL_TAIL not in result.stdout + result.stderr
    assert "authentication failed" in result.stderr
