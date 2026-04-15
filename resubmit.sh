#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

MANIFEST="${CRAB_MANIFEST:-generated_crab_configs.txt}"
DRY_RUN="${DRY_RUN:-1}"
USE_CACHED_STATUS="${USE_CACHED_STATUS:-0}"
STATUS_CACHE_DIR="${STATUS_CACHE_DIR:-status_cache}"
SUMMARY_FILE="${STATUS_CACHE_DIR}/latest_summary.json"

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

if [[ "${USE_CACHED_STATUS}" != "1" || ! -f "${SUMMARY_FILE}" ]]; then
    STATUS_CACHE_DIR="${STATUS_CACHE_DIR}" CRAB_MANIFEST="${MANIFEST}" ./status.sh
fi

if ! failed_output="$(
    python3 crab_status_snapshot.py list-failed --summary-file "${SUMMARY_FILE}"
)"; then
    exit 1
fi

if [[ -z "${failed_output}" ]]; then
    echo "No failed jobs found in status snapshot."
    exit 0
fi

mapfile -t failed_entries < <(printf '%s\n' "${failed_output}")

for entry in "${failed_entries[@]}"; do
    IFS=$'\t' read -r task_dir failed_job_ids failed_count <<< "${entry}"
    [[ -n "${task_dir}" ]] || continue

    cmd=(crab resubmit -d "${task_dir}" --jobids "${failed_job_ids}")

    if [[ "${DRY_RUN}" == "1" ]]; then
        printf '[failed=%s] ' "${failed_count}"
        printf '%q ' "${cmd[@]}" "$@"
        printf '\n'
        continue
    fi

    if output="$("${cmd[@]}" "$@" 2>&1)"; then
        printf '%s\n' "${output}"
        continue
    fi

    if is_no_jobs_to_resubmit_output "${output}"; then
        printf '%s\n' "${output}"
        echo "Skipping ${task_dir}: no jobs to resubmit."
        continue
    fi

    printf '%s\n' "${output}" >&2
    echo "Resubmit failed for ${task_dir}." >&2
    failed_tasks+=("${task_dir}")
done

if (( ${#failed_tasks[@]} > 0 )); then
    printf 'Resubmit failures in %d task(s):\n' "${#failed_tasks[@]}" >&2
    printf '  %s\n' "${failed_tasks[@]}" >&2
    exit 1
fi
