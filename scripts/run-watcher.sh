#!/usr/bin/env bash
# Run the watcher model on watcher/PROMPT.md with two file tools and nothing else.
#
# Credential, first that is configured:
#   1. ANTHROPIC_API_KEY.
#   2. Workload identity: ANTHROPIC_FEDERATION_RULE_ID, ANTHROPIC_ORGANIZATION_ID
#      and ANTHROPIC_SERVICE_ACCOUNT_ID (and optionally ANTHROPIC_WORKSPACE_ID).
#      The job's GitHub identity token is fetched here and the tool exchanges
#      it for a short-lived access token, so no stored credential is involved.
#      Needs `id-token: write` on the job, and curl and jq.
#   3. CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`).
# Fails before starting the model if none is.
#
# The model reads untrusted page text. It has Read and Edit only: no shell, no
# network tool, no sub-agents. It may read the working directory and edit the
# two data files. These flags were checked against the tool version pinned in
# watcher/package.json; re-check them when that version changes.
#
# Nothing the tool prints reaches this log directly: the log is public, and the
# runner acts on "::name::" at the start of a line and "##[name]" anywhere, on
# either stream. On failure the end of its output is shown, both streams
# together, because the tool reports a refused credential on standard output.
# It is shown reduced to printable ASCII, without any line that looks like it
# carries a credential, with each line cut short and prefixed, runs of colons
# collapsed to one and every "#[" rewritten as "#(".
set -euo pipefail

readonly MODEL="claude-sonnet-5-5"
readonly MAX_TURNS=60
readonly PROMPT="watcher/PROMPT.md"
readonly ERROR_TAIL_LINES=20
readonly ERROR_LINE_BYTES=300
# An Anthropic key or token, or the two leading parts of a signed token.
# scripts/screen-data-files.sh keeps the same line; a test holds them together.
readonly CREDENTIAL_SHAPES='sk-ant-|eyJ[A-Za-z0-9_-]+\.eyJ'

readonly IDENTITY_AUDIENCE="https://api.anthropic.com"
# A signed token: three base64url parts, on one line.
readonly IDENTITY_TOKEN_SHAPE='^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$'
readonly FEDERATION_REQUIRED=(
  ANTHROPIC_FEDERATION_RULE_ID
  ANTHROPIC_ORGANIZATION_ID
  ANTHROPIC_SERVICE_ACCOUNT_ID
)
readonly FEDERATION_SETTINGS=("${FEDERATION_REQUIRED[@]}" ANTHROPIC_WORKSPACE_ID)

fail() {
  echo "$1" >&2
  exit 1
}

output="$(mktemp)"
identity="$(mktemp)"
readonly output identity
trap 'rm -f "${output}" "${identity}"' EXIT

# Write this job's GitHub identity token to the private file ${identity}. The
# request token goes to curl on standard input, not on its command line.
fetch_identity_token() {
  local token
  [[ -n "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" && -n "${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-}" ]] ||
    fail "No identity token is available: the job needs the 'id-token: write' permission."
  token="$(
    printf 'header = "Authorization: Bearer %s"\n' "${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" |
      curl --config - --fail --silent --show-error --proto '=https' --max-time 30 \
        "${ACTIONS_ID_TOKEN_REQUEST_URL}&audience=${IDENTITY_AUDIENCE}" |
      jq --exit-status --raw-output '.value | strings | select(length > 0)' 2>/dev/null
  )" || fail "GitHub did not return an identity token."
  [[ "${token}" =~ ${IDENTITY_TOKEN_SHAPE} ]] ||
    fail "GitHub returned something that is not an identity token."
  echo "::add-mask::${token}"
  printf '%s' "${token}" >"${identity}"
}

# An unset secret arrives as an empty string. Whatever a mode does not use is
# removed, so the tool cannot mistake an empty value for a credential.
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  unset CLAUDE_CODE_OAUTH_TOKEN "${FEDERATION_SETTINGS[@]}"
  echo "watcher: using the API key"
elif [[ -n "${ANTHROPIC_FEDERATION_RULE_ID:-}" ]]; then
  unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN
  for setting in "${FEDERATION_REQUIRED[@]}"; do
    [[ -n "${!setting:-}" ]] || fail "Workload identity also needs ${setting}."
  done
  [[ -n "${ANTHROPIC_WORKSPACE_ID:-}" ]] || unset ANTHROPIC_WORKSPACE_ID
  fetch_identity_token
  export ANTHROPIC_IDENTITY_TOKEN_FILE="${identity}"
  echo "watcher: using workload identity"
elif [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
  unset ANTHROPIC_API_KEY "${FEDERATION_SETTINGS[@]}"
  echo "watcher: using the subscription token"
else
  fail "Set ANTHROPIC_API_KEY, or ANTHROPIC_FEDERATION_RULE_ID and its companions, or CLAUDE_CODE_OAUTH_TOKEN."
fi

# The model's process must not be able to ask GitHub for another token.
unset ACTIONS_ID_TOKEN_REQUEST_URL ACTIONS_ID_TOKEN_REQUEST_TOKEN
export DISABLE_AUTOUPDATER=1

status=0
claude -p \
  --model "${MODEL}" \
  --max-turns "${MAX_TURNS}" \
  --permission-mode dontAsk \
  --restricted \
  --strict-mcp-config \
  --tools "Read,Edit" \
  --allowedTools \
  "Read(data/**)" \
  "Read(source/**)" \
  "Edit(data/benefits.yaml)" \
  "Edit(data/changes.yaml)" \
  --disallowedTools \
  "Read(//proc/**)" \
  <"${PROMPT}" >"${output}" 2>&1 || status=$?

if ((status != 0)); then
  echo "watcher: the model run failed (exit ${status}); end of its output:" >&2
  # Keep newlines and printable ASCII only and drop lines that look like they
  # carry a credential, before anything is cut. Then bound each line, collapse
  # runs of colons to one and turn every "#[" into "#(". Neither rewrite
  # lengthens a line, so the bound holds.
  tail -n "${ERROR_TAIL_LINES}" "${output}" |
    LC_ALL=C tr -cd '\012\040-\176' |
    sed -E -e "/${CREDENTIAL_SHAPES}/d" |
    LC_ALL=C cut -b "1-${ERROR_LINE_BYTES}" |
    sed -e 's/::*/:/g' -e 's/#\[/#(/g' -e 's/^/  | /' >&2
  exit "${status}"
fi
echo "watcher: the model finished"
