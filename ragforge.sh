#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
python_path="${project_root}/.venv/bin/python"
if [[ ! -x "$python_path" ]]; then
    printf 'Run bash setup.sh first.\n' >&2
    exit 2
fi
export PYTHONIOENCODING=utf-8
export OTEL_SDK_DISABLED=true
exec "$python_path" -m ragforge.quickstart --project "$project_root" "$@"
