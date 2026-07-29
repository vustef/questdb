#!/usr/bin/env bash

set -euo pipefail
script_dir=$(cd "$(dirname "$0")" && pwd)

"${script_dir}/stop.sh"
"${script_dir}/build.sh"
"${script_dir}/start.sh"
python3 "${script_dir}/bench.py" q10 "$@"
