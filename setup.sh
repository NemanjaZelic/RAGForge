#!/usr/bin/env bash
# Explicit online setup. Build and search never download models or packages.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
python_command="${RAGFORGE_PYTHON:-python3}"
models_directory="${project_root}/models"
document_language=multilingual
accelerator=cpu
offline=0
while (($#)); do
    case "$1" in
        --offline) offline=1; shift ;;
        --accelerator)
            if (($# < 2)); then printf 'Missing accelerator\n' >&2; exit 2; fi
            if [[ "$2" != 'cpu' && "$2" != 'intel-gpu' ]]; then printf 'Accelerator must be cpu or intel-gpu\n' >&2; exit 2; fi
            accelerator="$2"; shift 2 ;;
        --document-language)
            if (($# < 2)); then printf 'Missing document language\n' >&2; exit 2; fi
            if [[ "$2" != 'multilingual' && "$2" != 'en' ]]; then printf 'Document language must be multilingual or en\n' >&2; exit 2; fi
            document_language="$2"; shift 2 ;;
        --models-directory|--python)
            if (($# < 2)); then printf 'Missing value for %s\n' "$1" >&2; exit 2; fi
            if [[ "$1" == '--python' ]]; then python_command="$2"; else models_directory="$2"; fi
            shift 2 ;;
        -h|--help)
            printf 'Usage: bash setup.sh [--offline] [--models-directory PATH] [--python PYTHON] [--document-language multilingual|en] [--accelerator cpu|intel-gpu]\n'
            exit 0 ;;
        *) printf 'Unknown setup option: %s\n' "$1" >&2; exit 2 ;;
    esac
done
if [[ "$accelerator" == 'intel-gpu' && "$document_language" != 'en' ]]; then
    printf 'Intel GPU requires --document-language en\n' >&2; exit 2
fi
if ! command -v -- "$python_command" >/dev/null 2>&1; then
    printf 'Install 64-bit Python 3.11+ with venv and pip (3.13 tested), then run bash setup.sh.\n' >&2
    exit 2
fi
"$python_command" -c "import sys,struct; sys.exit(0 if sys.version_info >= (3,11) and struct.calcsize('P') == 8 else 2)" || {
    printf 'RAGForge needs 64-bit Python 3.11 or newer (3.13 tested).\n' >&2; exit 2;
}
export UV_CACHE_DIR="${project_root}/.cache/uv"
export UV_PYTHON_INSTALL_DIR="${project_root}/.cache/python"
export UV_PYTHON_DOWNLOADS=never
export UV_PROJECT_ENVIRONMENT="${project_root}/.venv"
export PIP_CACHE_DIR="${project_root}/.cache/pip"
export TMPDIR="${project_root}/.cache/tmp"
export PYTHONIOENCODING=utf-8
export OTEL_SDK_DISABLED=true
mkdir -p -- "$TMPDIR"
uv_path="${project_root}/.tools/bin/uv"
if ((offline)); then
    export UV_OFFLINE=1
    export PIP_NO_INDEX=1
    if [[ ! -x "$uv_path" ]]; then
        printf 'Offline setup needs the existing local tools. Run bash setup.sh online once first.\n' >&2
        exit 2
    fi
fi
if [[ ! -x "$uv_path" ]]; then
    "$python_command" -m venv "${project_root}/.tools"
    "${project_root}/.tools/bin/python" -m pip install --disable-pip-version-check 'uv==0.13.6'
fi
printf 'Installing the locked local environment...\n'
"$uv_path" sync --project "$project_root" --python "$python_command" --locked --all-extras
setup_args=(python "${project_root}/scripts/setup_models.py" --models-directory "$models_directory" --document-language "$document_language" --accelerator "$accelerator")
if ((offline)); then setup_args+=(--offline); fi
"$uv_path" run --project "$project_root" --locked --offline --no-sync "${setup_args[@]}"
"$uv_path" run --project "$project_root" --locked --offline --no-sync ragforge doctor
mkdir -p -- "${project_root}/documents"
printf '\nSetup complete. Put PDF/TXT/MD/HTML documents into:\n%s/documents\n' "$project_root"
printf 'Then: bash ragforge.sh build\nOptional agent integration: bash ragforge.sh agent\n'
