#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/_env.sh"

if [[ "$(java -version 2>&1 | head -n 1)" != *'"25.'* ]]; then
    echo "QuestDB requires JDK 25. Run ${CLICKBENCH_DIR}/setup-jdk.sh first." >&2
    exit 1
fi

profiles="local-client"
web_console_zip="${QUESTDB_DIR}/core/src/main/resources/io/questdb/site/public.zip"
if [[ ! -f "${web_console_zip}" ]]; then
    profiles="${profiles},build-web-console"
    echo "Web console bundle is missing; downloading it for this build."
fi

cd "${QUESTDB_DIR}"
mvn -P "${profiles}" -pl core -am package \
    -Dmaven.test.skip=true \
    -Dcheckstyle.skip \
    -Dspotless.check.skip=true

jar=$(find "${QUESTDB_DIR}/core/target" -maxdepth 1 -name 'questdb-*-SNAPSHOT.jar' -print -quit)
if [[ -z "${jar}" ]]; then
    echo "QuestDB JAR was not produced by the build." >&2
    exit 1
fi

runtime_lib="${CLICKBENCH_RUNTIME}/lib"
mkdir -p "${CLICKBENCH_BIN}" "${runtime_lib}"
cp "${QUESTDB_DIR}"/core/src/main/bin/*.sh "${CLICKBENCH_BIN}/"
cp "${jar}" "${CLICKBENCH_BIN}/questdb.jar"
chmod +x "${CLICKBENCH_BIN}"/*.sh

case "$(uname -s)-$(uname -m)" in
    Darwin-arm64)
        platform="darwin-aarch64"
        ;;
    Darwin-x86_64)
        platform="darwin-x86-64"
        ;;
    Linux-aarch64|Linux-arm64)
        platform="linux-aarch64"
        ;;
    Linux-x86_64)
        platform="linux-x86-64"
        ;;
    *)
        platform=""
        ;;
esac

if [[ -n "${platform}" ]]; then
    native_dir="${QUESTDB_DIR}/core/src/main/resources/io/questdb/bin/${platform}"
    if [[ -d "${native_dir}" ]]; then
        cp "${native_dir}"/* "${runtime_lib}/"
    fi

    if [[ "${platform}" == darwin-* ]]; then
        async_profiler_version="4.5"
        async_profiler_name="async-profiler-${async_profiler_version}-macos"
        async_profiler_archive="${CLICKBENCH_DIR}/toolchains/${async_profiler_name}.zip"
        async_profiler_home="${CLICKBENCH_DIR}/toolchains/${async_profiler_name}"
        async_profiler_url="https://github.com/async-profiler/async-profiler/releases/download/v${async_profiler_version}/${async_profiler_name}.zip"
        async_profiler_sha256="46d04ef81f532a065a0b3877e488aa706afa14aa2ea14433b323db9e6fda76dc"

        if [[ ! -x "${async_profiler_home}/bin/asprof" ||
              ! -f "${async_profiler_home}/lib/libasyncProfiler.dylib" ]]; then
            mkdir -p "${CLICKBENCH_DIR}/toolchains"
            if [[ ! -f "${async_profiler_archive}" ]]; then
                echo "Downloading async-profiler ${async_profiler_version} for macOS."
                curl --fail --location \
                    --output "${async_profiler_archive}" \
                    "${async_profiler_url}"
            fi

            actual_sha256=$(shasum -a 256 "${async_profiler_archive}" | awk '{print $1}')
            if [[ "${actual_sha256}" != "${async_profiler_sha256}" ]]; then
                echo "async-profiler archive checksum mismatch." >&2
                exit 1
            fi
            unzip -q -o "${async_profiler_archive}" -d "${CLICKBENCH_DIR}/toolchains"
        fi

        cp "${async_profiler_home}/bin/asprof" "${runtime_lib}/"
        cp "${async_profiler_home}/bin/jfrconv" "${runtime_lib}/"
        cp "${async_profiler_home}/lib/libasyncProfiler.dylib" "${runtime_lib}/"
        ln -sfn "libasyncProfiler.dylib" "${runtime_lib}/libasyncProfiler.so"
        chmod +x "${runtime_lib}/asprof" "${runtime_lib}/jfrconv"
    else
        profiler_dir="${QUESTDB_DIR}/core/src/main/bin/${platform}"
        if [[ -d "${profiler_dir}" ]]; then
            for profiler_file in asprof jfrconv libasyncProfiler.so libjemalloc.so; do
                if [[ -f "${profiler_dir}/${profiler_file}" ]]; then
                    cp "${profiler_dir}/${profiler_file}" "${runtime_lib}/"
                fi
            done
            chmod +x "${runtime_lib}/asprof" "${runtime_lib}/jfrconv" 2>/dev/null || true
        fi
    fi
fi

echo "Staged QuestDB launcher: ${CLICKBENCH_BIN}/questdb.sh"
