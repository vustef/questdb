#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/_env.sh"

launcher="${CLICKBENCH_BIN}/questdb.sh"
if [[ ! -x "${launcher}" ]]; then
    echo "Staged QuestDB launcher not found. Run ${CLICKBENCH_DIR}/build.sh first." >&2
    exit 1
fi

mkdir -p "${CLICKBENCH_ROOT}" "${CLICKBENCH_IMPORT}"
export QDB_CAIRO_SQL_COPY_ROOT="${CLICKBENCH_IMPORT}"
export QDB_HTTP_MIN_NET_BIND_TO="127.0.0.1:19003"

exec "${launcher}" "$@"
