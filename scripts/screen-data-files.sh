#!/usr/bin/env bash
# Refuse data files that carry what looks like a credential.
#
# usage: screen-data-files.sh <file>...
#
# Run on the watcher's output before it leaves the job that holds the model
# credential, and again by the job that takes it in. It is a tripwire, not a
# guarantee: it catches a credential written out plainly. Matching text is
# never printed.
set -euo pipefail

# An Anthropic key or token (API keys, access tokens and subscription tokens
# all start "sk-ant-"), or the two leading parts of a signed identity token.
# scripts/run-watcher.sh keeps the same line for its failure log; a test holds
# the two together.
readonly CREDENTIAL_SHAPES='sk-ant-|eyJ[A-Za-z0-9_-]+\.eyJ'

fail() {
  echo "$1" >&2
  exit 1
}

# grep exits 0 on a match and 1 on none; anything else means it could not look.
found() {
  local status=0
  grep -q "$@" || status=$?
  ((status <= 1)) || fail "grep failed (exit ${status}); refusing rather than passing unchecked data"
  ((status == 0))
}

[[ $# -ge 1 ]] || fail "usage: screen-data-files.sh <file>..."

for file in "$@"; do
  [[ -f "${file}" && ! -L "${file}" ]] || fail "${file} is not a regular file"
  if found -E -e "${CREDENTIAL_SHAPES}" -- "${file}"; then
    fail "${file##*/} contains what looks like a credential"
  fi
done
