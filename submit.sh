#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"
source "${SCRIPT_DIR}/crab_common.sh"

MANIFEST="${CRAB_MANIFEST:-generated_crab_configs.txt}"
CLI_DRY_RUN=""
SHOW_HELP=0
declare -a FORWARD_ARGS=()

show_help() {
    cat <<'EOF'
Usage: ./submit.sh [options] [-- crab submit options]

Submit every CRAB configuration listed in the manifest.

Options:
  -h, --help            Show this help text and exit.
  --manifest PATH       Manifest file to read. Falls back to CRAB_MANIFEST.
  --dry-run             Print the crab submit commands without executing them.
  --execute             Execute crab submit for each config in the manifest.
  --                    Stop parsing wrapper options and pass the rest to crab submit.

Environment fallback:
  CRAB_MANIFEST         Default manifest path.
  DRY_RUN               Default dry-run mode (accepted values: 0/1/true/false).

Preconditions:
  - Run 'cmsenv' in this CMSSW work area first.
  - Export X509_USER_PROXY before executing submissions.

Examples:
  ./submit.sh
  ./submit.sh --execute
  ./submit.sh --manifest my_configs.txt --execute -- --wait
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
        --dry-run)
            CLI_DRY_RUN=1
            shift
            ;;
        --execute)
            CLI_DRY_RUN=0
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

DRY_RUN="$(resolve_bool "DRY_RUN" "${CLI_DRY_RUN}" "${DRY_RUN:-}" "1")"

require_cmssw_env
require_manifest "${MANIFEST}"
require_proxy_env

while read -r cfg; do
    [[ -n "${cfg}" ]] || continue
    if [[ ! -f "${cfg}" ]]; then
        echo "Missing CRAB config ${cfg}. Regenerate with ./registerData.sh." >&2
        exit 1
    fi

    cmd=(crab submit -c "${cfg}")
    if ((${#FORWARD_ARGS[@]} > 0)); then
        cmd+=("${FORWARD_ARGS[@]}")
    fi

    if [[ "${DRY_RUN}" == "1" ]]; then
        printf '%q ' "${cmd[@]}"
        printf '\n'
    else
        "${cmd[@]}"
    fi
done < "${MANIFEST}"
