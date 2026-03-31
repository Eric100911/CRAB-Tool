#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

MANIFEST="${CRAB_MANIFEST:-generated_crab_configs.txt}"
DRY_RUN="${DRY_RUN:-1}"

if [[ ! -f "${MANIFEST}" ]]; then
    echo "Missing ${MANIFEST}. Run ./registerData.sh first." >&2
    exit 1
fi

while read -r cfg; do
    [[ -n "${cfg}" ]] || continue
    if [[ ! -f "${cfg}" ]]; then
        echo "Missing CRAB config ${cfg}. Regenerate with ./registerData.sh." >&2
        exit 1
    fi

    cmd=(crab submit -c "${cfg}")
    if [[ -n "${X509_USER_PROXY:-}" ]]; then
        cmd+=(--proxy "${X509_USER_PROXY}")
    fi

    if [[ "${DRY_RUN}" == "1" ]]; then
        printf '%q ' "${cmd[@]}"
        printf '\n'
    else
        "${cmd[@]}"
    fi
done < "${MANIFEST}"
