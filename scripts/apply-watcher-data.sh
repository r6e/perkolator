#!/usr/bin/env bash
# Copy the watcher's two data files, and nothing else, into data/.
#
# usage: apply-watcher-data.sh <directory the watcher's artifact was downloaded into>
#
# The directory is untrusted: it was written by a job that ran a model over a
# web page. Nothing in it is executed. The script exits non-zero, having
# written nothing, unless the directory holds exactly the two data files, each
# a regular file of reasonable size that passes screen-data-files.sh, and at
# least one differs from the copy in data/ (a watcher that changed nothing did
# not run properly: it always updates verified_on).
set -euo pipefail

readonly NAMES=(benefits.yaml changes.yaml)
readonly MAX_BYTES=262144
here="$(dirname "${BASH_SOURCE[0]}")"
readonly here

fail() {
  echo "$1" >&2
  exit 1
}

is_data_file() {
  local name
  for name in "${NAMES[@]}"; do
    [[ "$1" == "${incoming}/${name}" ]] && return 0
  done
  return 1
}

[[ $# -eq 1 ]] || fail "usage: apply-watcher-data.sh <directory>"
readonly incoming="$1"
[[ -d "${incoming}" && ! -L "${incoming}" ]] || fail "${incoming} is not a directory"

# Captured first, so `set -e` sees find failing.
entries="$(find "${incoming}" -mindepth 1)"
while IFS= read -r entry; do
  [[ -z "${entry}" ]] || is_data_file "${entry}" ||
    fail "the watcher's output may hold only ${NAMES[*]}; found something else"
done <<<"${entries}"

changed=false
for name in "${NAMES[@]}"; do
  file="${incoming}/${name}"
  [[ -e "${file}" || -L "${file}" ]] || fail "${name} is missing from the watcher's output"
  [[ -f "${file}" && ! -L "${file}" ]] || fail "${name} in the watcher's output is not a regular file"
  size="$(wc -c <"${file}")"
  ((size <= MAX_BYTES)) || fail "${name} in the watcher's output is too large (limit ${MAX_BYTES} bytes)"
  "${here}/screen-data-files.sh" "${file}"
  cmp -s "${file}" "data/${name}" || changed=true
done
"${changed}" || fail "the watcher made no update to the data; it did not complete its check"

for name in "${NAMES[@]}"; do
  cp "${incoming}/${name}" "data/${name}"
done
