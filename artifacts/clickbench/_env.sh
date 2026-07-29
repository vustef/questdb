#!/usr/bin/env bash

set -euo pipefail

CLICKBENCH_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
QUESTDB_DIR=$(cd "${CLICKBENCH_DIR}/../.." && pwd)
CLICKBENCH_ROOT=${CLICKBENCH_ROOT:-"${CLICKBENCH_DIR}/root"}
CLICKBENCH_IMPORT=${CLICKBENCH_IMPORT:-"${CLICKBENCH_DIR}/import"}
CLICKBENCH_RUNTIME=${CLICKBENCH_RUNTIME:-"${CLICKBENCH_DIR}/runtime"}
CLICKBENCH_BIN=${CLICKBENCH_BIN:-"${CLICKBENCH_RUNTIME}/bin"}
CLICKBENCH_TAG=${CLICKBENCH_TAG:-"clickbench"}
CLICKBENCH_JDK_HOME=${CLICKBENCH_JDK_HOME:-"${CLICKBENCH_DIR}/toolchains/jdk25/Contents/Home"}
CLICKBENCH_URL=${CLICKBENCH_URL:-"http://127.0.0.1:9000"}
CLICKBENCH_WORKER_COUNT=${CLICKBENCH_WORKER_COUNT:-8}

# This Mac has eight performance cores and two efficiency cores. Keep the
# benchmark's network, query, and write pools at eight workers by default.
# Setting QDB_SHARED_WORKER_COUNT directly still takes precedence.
export QDB_SHARED_WORKER_COUNT="${QDB_SHARED_WORKER_COUNT:-${CLICKBENCH_WORKER_COUNT}}"

if [[ -x "${CLICKBENCH_JDK_HOME}/bin/java" ]]; then
    export JAVA_HOME="${CLICKBENCH_JDK_HOME}"
    export PATH="${JAVA_HOME}/bin:${PATH}"
fi
