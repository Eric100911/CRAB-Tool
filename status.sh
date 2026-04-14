#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

MANIFEST="${CRAB_MANIFEST:-generated_crab_configs.txt}"

if [[ ! -f "${MANIFEST}" ]]; then
    echo "Missing ${MANIFEST}. Run ./registerData.sh first." >&2
    exit 1
fi

while read -r cfg; do
    [[ -n "${cfg}" ]] || continue
    task_dir="crab_${cfg%.py}"
    cmd=(crab status -d "${task_dir}")
    # if [[ -n "${X509_USER_PROXY:-}" ]]; then
    #    cmd+=(--proxy "${X509_USER_PROXY}")
    # fi
    "${cmd[@]}" "$@"
done < "${MANIFEST}"
