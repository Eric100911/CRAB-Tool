#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"
source "${SCRIPT_DIR}/crab_common.sh"

MANIFEST="${CRAB_MANIFEST:-generated_crab_configs.txt}"
STATUS_CACHE_DIR="${STATUS_CACHE_DIR:-status_cache}"
STATE_FILE="${STATUS_CACHE_DIR}/latest_state.json"
CLI_RAW_STATUS=""
SHOW_HELP=0
declare -a FORWARD_ARGS=()

show_help() {
    cat <<'EOF'
Usage: ./status.sh [options] [-- crab status options]

Query CRAB status for every task in the manifest.

By default this wrapper uses crab_status_snapshot.py collect to create a cached,
machine-readable state file under status_cache/latest_state.json. Use
--raw-status to call
"crab status" directly for each task instead.

Options:
  -h, --help            Show this help text and exit.
  --manifest PATH       Manifest file to read. Falls back to CRAB_MANIFEST.
  --cache-dir PATH      Status cache directory. Falls back to STATUS_CACHE_DIR.
  --raw-status          Bypass the JSON cache flow and call crab status directly.
  --cached-status       Force the JSON cache flow even if RAW_STATUS is set.
  --                    Stop parsing wrapper options and pass the rest through.

Environment fallback:
  CRAB_MANIFEST         Default manifest path.
  STATUS_CACHE_DIR      Default status cache directory.
  RAW_STATUS            Default raw-vs-cached mode (accepted values: 0/1/true/false).

Preconditions:
  - Run 'cmsenv' in this CMSSW work area first.
  - Export X509_USER_PROXY before querying CRAB.

Passthrough:
  - In cached mode, extra arguments are forwarded to crab_status_snapshot.py collect.
  - In raw mode, extra arguments are forwarded to crab status for each task.
  - Use '--' to disambiguate wrapper options from passthrough options when needed.

Examples:
  ./status.sh
  ./status.sh --cache-dir custom_status_cache
  ./status.sh --raw-status -- --verboseErrors
EOF
}

while (($#)); do
    case "$1" in
        -h|--help)
            SHOW_HELP=1
            shift
            ;;
        --manifest)
            require_option_value "$1" "${2:-}"
            MANIFEST="$2"
            shift 2
            ;;
        --cache-dir)
            require_option_value "$1" "${2:-}"
            STATUS_CACHE_DIR="$2"
            shift 2
            ;;
        --raw-status)
            CLI_RAW_STATUS=1
            shift
            ;;
        --cached-status)
            CLI_RAW_STATUS=0
            shift
            ;;
        --)
            shift
            FORWARD_ARGS=("$@")
            break
            ;;
        *)
            FORWARD_ARGS+=("$1")
            shift
            ;;
    esac
done

if [[ "${SHOW_HELP}" == "1" ]]; then
    show_help
    exit 0
fi

RAW_STATUS="$(resolve_bool "RAW_STATUS" "${CLI_RAW_STATUS}" "${RAW_STATUS:-}" "0")"

require_cmssw_env
require_manifest "${MANIFEST}"
require_proxy_env

if [[ "${RAW_STATUS}" == "1" ]]; then
    while read -r cfg; do
        [[ -n "${cfg}" ]] || continue
        task_dir="$(cfg_to_task_dir "${cfg}")"
        cmd=(crab status -d "${task_dir}")
        if ((${#FORWARD_ARGS[@]} > 0)); then
            cmd+=("${FORWARD_ARGS[@]}")
        fi
        "${cmd[@]}"
    done < "${MANIFEST}"
    exit 0
fi

exec python3 crab_status_snapshot.py collect \
    --manifest "${MANIFEST}" \
    --state-file "${STATE_FILE}" \
    "${FORWARD_ARGS[@]}"
