#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/_env.sh"

url="https://datasets.clickhouse.com/hits_compatible/hits.parquet"
file="${CLICKBENCH_IMPORT}/hits.parquet"
expected_size=14779976446

mkdir -p "${CLICKBENCH_IMPORT}"

if [[ -f "${file}" ]] && [[ "$(wc -c < "${file}")" -eq "${expected_size}" ]]; then
    echo "ClickBench dataset is already complete: ${file}"
    exit 0
fi

curl --fail --location --continue-at - --output "${file}" "${url}"
actual_size=$(wc -c < "${file}")
if [[ "${actual_size}" -ne "${expected_size}" ]]; then
    echo "Incomplete dataset: expected ${expected_size} bytes, got ${actual_size}" >&2
    exit 1
fi

echo "Downloaded the official 99,997,497-row ClickBench dataset to ${file}"

