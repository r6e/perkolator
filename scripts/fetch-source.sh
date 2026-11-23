#!/usr/bin/env bash
# Download the issuer's benefits page to the given file.
#
# usage: fetch-source.sh <output file>
#
# A plain request for one fixed public address: https only, and refused if a
# redirect leaves the issuer's site. The result is untrusted input for
# `perkolator extract-text`.
set -euo pipefail

readonly URL="https://www.americanexpress.com/us/credit-cards/card/platinum/"
readonly SITE="https://www.americanexpress.com/"
readonly MAX_BYTES=20000000

fail() {
  echo "$1" >&2
  exit 1
}

[[ $# -eq 1 ]] || fail "usage: fetch-source.sh <output file>"

landed="$(curl --fail --silent --show-error --location \
  --proto '=https' --proto-redir '=https' --max-redirs 3 \
  --max-time 60 --max-filesize "${MAX_BYTES}" \
  --output "$1" --write-out '%{url_effective}' "${URL}")"

[[ "${landed}" == "${SITE}"* ]] || fail "the request was redirected away from ${SITE}"
