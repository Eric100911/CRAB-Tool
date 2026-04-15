#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

MANIFEST="${CRAB_MANIFEST:-generated_crab_configs.txt}"
STATUS_CACHE_DIR="${STATUS_CACHE_DIR:-status_cache}"
RAW_STATUS="${RAW_STATUS:-0}"

if [[ ! -f "${MANIFEST}" ]]; then
    echo "Missing ${MANIFEST}. Run ./registerData.sh first." >&2
    exit 1
fi

if [[ "${RAW_STATUS}" == "1" ]]; then
    while read -r cfg; do
        [[ -n "${cfg}" ]] || continue
        task_dir="crab_${cfg%.py}"
        cmd=(crab status -d "${task_dir}")
        "${cmd[@]}" "$@"
    done < "${MANIFEST}"
    exit 0
fi

exec python3 crab_status_snapshot.py collect \
    --manifest "${MANIFEST}" \
    --cache-dir "${STATUS_CACHE_DIR}" \
    "$@"
