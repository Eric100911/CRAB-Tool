#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

MANIFEST="${CRAB_MANIFEST:-generated_crab_configs.txt}"
DRY_RUN="${DRY_RUN:-1}"

declare -a failed_tasks=()

is_no_jobs_to_resubmit_output() {
    local output="$1"
    local normalized
    normalized="$(printf '%s' "${output}" | tr '[:upper:]' '[:lower:]')"
    [[ "${normalized}" == *"no jobs to resubmit"* ]] ||
        [[ "${normalized}" == *"nothing to resubmit"* ]] ||
        [[ "${normalized}" == *"don't have jobs to resubmit"* ]] ||
        [[ "${normalized}" == *"doesn't have jobs to resubmit"* ]]
}

if [[ ! -f "${MANIFEST}" ]]; then
    echo "Missing ${MANIFEST}. Run ./registerData.sh first." >&2
    exit 1
fi

while read -r cfg; do
    [[ -n "${cfg}" ]] || continue
    task_dir="crab_${cfg%.py}"
    if [[ ! -d "${task_dir}" ]]; then
        echo "Missing CRAB task directory ${task_dir}." >&2
        failed_tasks+=("${task_dir}")
        continue
    fi

    cmd=(crab resubmit -d "${task_dir}")
    #if [[ -n "${X509_USER_PROXY:-}" ]]; then
    #    cmd+=(--proxy "${X509_USER_PROXY}")
    #fi

    if [[ "${DRY_RUN}" == "1" ]]; then
        printf '%q ' "${cmd[@]}" "$@"
        printf '\n'
    else
        if output="$("${cmd[@]}" "$@" 2>&1)"; then
            printf '%s\n' "${output}"
        else
            if is_no_jobs_to_resubmit_output "${output}"; then
                printf '%s\n' "${output}"
                echo "Skipping ${task_dir}: no jobs to resubmit."
                continue
            fi

            printf '%s\n' "${output}" >&2
            echo "Resubmit failed for ${task_dir}." >&2
            failed_tasks+=("${task_dir}")
        fi
    fi
done < "${MANIFEST}"

if (( ${#failed_tasks[@]} > 0 )); then
    printf 'Resubmit failures in %d task(s):\n' "${#failed_tasks[@]}" >&2
    printf '  %s\n' "${failed_tasks[@]}" >&2
    exit 1
fi
