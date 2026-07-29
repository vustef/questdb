#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/_env.sh"

exec "${CLICKBENCH_DIR}/run.sh" \
    start \
    -d "${CLICKBENCH_ROOT}" \
    -t "${CLICKBENCH_TAG}" \
    "$@"
