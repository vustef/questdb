#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/_env.sh"

if [[ "$(java -version 2>&1 | head -n 1)" != *'"25.'* ]]; then
    echo "QuestDB requires JDK 25. Run ${CLICKBENCH_DIR}/setup-jdk.sh first." >&2
    exit 1
fi

cd "${QUESTDB_DIR}"
mvn -P local-client -pl core -am \
    -Dtest=ClickBenchTest \
    -Dsurefire.failIfNoSpecifiedTests=false \
    test

