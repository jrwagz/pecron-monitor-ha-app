#!/usr/bin/env bash
# Install the pinned pecron-monitor library into the current Python
# environment. The Dockerfile is the only place the commit is written.
set -euo pipefail
cd "$(dirname "$0")/.."

sha=$(sed -n 's/^ARG PECRON_MONITOR_SHA=//p' pecron_monitor_ha_app/Dockerfile)
if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Could not read PECRON_MONITOR_SHA from the Dockerfile" >&2
  exit 1
fi
python3 -m pip install --no-deps \
  "https://github.com/attractify-logan/pecron-monitor/archive/${sha}.tar.gz"
