#!/usr/bin/env bash
# Run shellcheck on every file under rootfs/ and tests/ whose first line is a
# bash, sh or bashio shebang. execline scripts (s6 "up" files) are skipped.
set -euo pipefail
cd "$(dirname "$0")/.."

files=()
while IFS= read -r -d '' f; do
  if head -n 1 "$f" | grep -qE '^#!.*[/ ](bash|sh|bashio)([[:space:]]|$)'; then
    files+=("$f")
  fi
done < <(find pecron_monitor_ha_app/rootfs tests -type f -print0 2>/dev/null)

if [[ ${#files[@]} -eq 0 ]]; then
  echo "No shell scripts found."
  exit 0
fi

printf 'shellcheck: %s\n' "${files[@]}"
shellcheck "${files[@]}"
