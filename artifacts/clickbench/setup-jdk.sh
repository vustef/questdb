#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/_env.sh"

archive="${CLICKBENCH_DIR}/toolchains/jdk25.tar.gz"
install_dir="${CLICKBENCH_DIR}/toolchains/jdk25"
url="https://api.adoptium.net/v3/binary/latest/25/ga/mac/aarch64/jdk/hotspot/normal/eclipse?project=jdk"

if [[ -x "${install_dir}/Contents/Home/bin/java" ]]; then
    "${install_dir}/Contents/Home/bin/java" -version
    exit 0
fi

mkdir -p "${CLICKBENCH_DIR}/toolchains" "${install_dir}"
curl --fail --location --continue-at - --output "${archive}" "${url}"
tar -xzf "${archive}" -C "${install_dir}" --strip-components=1
"${install_dir}/Contents/Home/bin/java" -version

