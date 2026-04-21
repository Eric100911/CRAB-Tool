#!/usr/bin/env python3
"""Collect machine-readable CRAB status into one authoritative state file."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

INCOMPATIBLE_STATUS_ARGS = {
    "--jobids",
    "--long",
    "--sort",
    "--summary",
    "--verboseErrors",
}
STATE_NAME = "latest_state.json"
SCHEMA_VERSION = 2
RECOVERY_SUFFIX = "recover"
STATUS_COLLECTION_OK = "ok_json"
STATUS_COLLECTION_HEADER_ONLY_KILLED = "header_only_killed"
STATUS_COLLECTION_FATAL_ERROR = "fatal_error"
STATUS_COLLECTION_NOT_COLLECTED = "not_collected"


class HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter
):
    """Help formatter with defaults and preserved line breaks."""


def ensure_cmssw_env() -> None:
    required = ("CMSSW_BASE", "CMSSW_RELEASE_BASE", "SCRAM_ARCH")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        missing_names = ", ".join(missing)
        raise RuntimeError(
            "CMSSW environment is not active. "
            f"Missing {missing_names}. Run 'cmsenv' first."
        )


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Collect machine-readable CRAB status snapshots and list failed jobs.",
        formatter_class=HelpFormatter,
        epilog=(
            "Examples:\n"
            "  crab_status_snapshot.py collect --cache-dir status_cache\n"
            "  crab_status_snapshot.py collect --state-file status_cache/latest_state.json -- --instance prod\n"
            "  crab_status_snapshot.py list-failed --state-file status_cache/latest_state.json\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser(
        "collect",
        help="Query crab status for all tracked tasks and save one state file.",
        description=(
            "Query 'crab status --json' for every root task in the manifest plus any "
            "already-recorded recovery attempts, then update one authoritative state file."
        ),
        formatter_class=HelpFormatter,
        epilog=(
            "Output files:\n"
            "  <cache-dir>/latest_state.json\n\n"
            "Extra arguments after '--' are forwarded to 'crab status --json'.\n"
            "Do not combine machine-readable mode with --long, --summary, --sort,\n"
            "--verboseErrors, or --jobids."
        ),
    )
    collect_parser.add_argument(
        "--manifest",
        default="generated_crab_configs.txt",
        help="Manifest that lists one CRAB config path per line.",
    )
    collect_parser.add_argument(
        "--cache-dir",
        default="status_cache",
        help="Directory where the authoritative latest_state.json file is written.",
    )
    collect_parser.add_argument(
        "--state-file",
        default=None,
        help="Explicit path for the authoritative state JSON file.",
    )

    list_failed_parser = subparsers.add_parser(
        "list-failed",
        help="List task directories that have failed jobs in the saved state file.",
        description=(
            "Read a saved latest_state.json file and print one tab-separated line for "
            "each task that currently contains failed CRAB jobs."
        ),
        formatter_class=HelpFormatter,
        epilog=(
            "Output columns:\n"
            "  task_dir<TAB>comma-separated job ids<TAB>failed job count"
        ),
    )
    list_failed_parser.add_argument(
        "--state-file",
        default=f"status_cache/{STATE_NAME}",
        help="Authoritative state file produced by the collect subcommand.",
    )
    list_failed_parser.add_argument(
        "--summary-file",
        default=None,
        help="Deprecated alias for --state-file.",
    )

    return parser.parse_known_args(argv)


def command_has_flag(args: list[str], flag: str) -> bool:
    return any(arg == flag or arg.startswith(f"{flag}=") for arg in args)


def ensure_compatible_status_args(extra_args: list[str]) -> None:
    for flag in INCOMPATIBLE_STATUS_ARGS:
        if command_has_flag(extra_args, flag):
            raise ValueError(
                f"{flag} is incompatible with machine-readable status collection. "
                "Use RAW_STATUS=1 ./status.sh for raw CRAB output."
            )


def read_manifest(manifest_path: Path) -> list[str]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest {manifest_path}. Run ./registerData.sh first.")
    return [line.strip() for line in manifest_path.read_text().splitlines() if line.strip()]


def resolve_state_file(args: argparse.Namespace) -> Path:
    if getattr(args, "summary_file", None):
        return Path(args.summary_file)
    if getattr(args, "state_file", None):
        return Path(args.state_file)
    return Path(args.cache_dir) / STATE_NAME


def task_dir_from_cfg(task_root: Path, cfg: str) -> Path:
    cfg_path = Path(cfg)
    task_name = f"crab_{cfg_path.stem}"
    return (task_root / task_name).resolve()


def extract_status_payload(stdout: str) -> dict[str, dict]:
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Could not locate JSON payload in `crab status --json` output.")
    return json.loads(stdout[start : end + 1])


def extract_header_value(stdout: str, label: str) -> str | None:
    prefix = f"{label}:"
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None


def summarize_jobs(payload: dict[str, dict]) -> tuple[dict[str, int], list[str]]:
    state_counts: collections.Counter[str] = collections.Counter()
    failed_job_ids: list[str] = []

    for crab_job_id, job in payload.items():
        state = str(job.get("State", "unknown"))
        state_counts[state] += 1
        if state == "failed":
            failed_job_ids.append(str(crab_job_id))

    failed_job_ids.sort(key=lambda value: int(value))
    return dict(sorted(state_counts.items())), failed_job_ids


def query_task_status(
    task_dir: Path, extra_args: list[str]
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    cmd = ["crab", "status", "-d", str(task_dir), "--json", *extra_args]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return completed, cmd


def build_task_summary(
    cfg: str, task_dir: Path, extra_args: list[str]
) -> tuple[dict[str, Any], dict[str, dict] | None, str, str, list[str]]:
    summary: dict[str, Any] = {
        "cfg": cfg,
        "task_dir": task_dir.name,
        "task_path": str(task_dir),
        "task_name": None,
        "server_status": None,
        "scheduler_status": None,
        "dashboard_url": None,
        "job_count": 0,
        "job_states": {},
        "failed_job_count": 0,
        "failed_job_ids": [],
        "status_collection_state": STATUS_COLLECTION_OK,
        "query_error": None,
        "query_warning": None,
    }

    if not task_dir.is_dir():
        summary["status_collection_state"] = STATUS_COLLECTION_FATAL_ERROR
        summary["query_error"] = f"Missing CRAB task directory {task_dir.name}."
        return summary, None, "", "", []

    completed, cmd = query_task_status(task_dir, extra_args)
    stdout = completed.stdout
    stderr = completed.stderr

    summary["task_name"] = extract_header_value(stdout, "Task name")
    summary["server_status"] = extract_header_value(stdout, "Status on the CRAB server")
    summary["scheduler_status"] = extract_header_value(stdout, "Status on the scheduler")
    summary["dashboard_url"] = extract_header_value(stdout, "Dashboard monitoring URL")

    if completed.returncode != 0:
        summary["status_collection_state"] = STATUS_COLLECTION_FATAL_ERROR
        message = stderr.strip() or stdout.strip() or "unknown CRAB status failure"
        summary["query_error"] = (
            f"`{' '.join(cmd)}` failed with exit code {completed.returncode}: {message}"
        )
        return summary, None, stdout, stderr, cmd

    try:
        payload = extract_status_payload(stdout)
        job_states, failed_job_ids = summarize_jobs(payload)
    except Exception as exc:
        if summary["server_status"] == "KILLED":
            summary["status_collection_state"] = STATUS_COLLECTION_HEADER_ONLY_KILLED
            summary["query_warning"] = f"Failed to parse status JSON after kill: {exc}"
            return summary, None, stdout, stderr, cmd
        summary["status_collection_state"] = STATUS_COLLECTION_FATAL_ERROR
        summary["query_error"] = f"Failed to parse status JSON: {exc}"
        return summary, None, stdout, stderr, cmd

    summary["job_count"] = len(payload)
    summary["job_states"] = job_states
    summary["failed_job_count"] = len(failed_job_ids)
    summary["failed_job_ids"] = failed_job_ids
    return summary, payload, stdout, stderr, cmd


def format_task_summary(summary: dict[str, Any]) -> str:
    if summary["query_error"]:
        return f"{summary['task_dir']} query_error={summary['query_error']}"
    if summary["query_warning"]:
        return (
            f"{summary['task_dir']} "
            f"server={summary['server_status'] or 'unknown'} "
            f"warning={summary['query_warning']}"
        )
    states = " ".join(
        f"{state}={count}" for state, count in summary["job_states"].items()
    )
    return (
        f"{summary['task_dir']} "
        f"server={summary['server_status'] or 'unknown'} "
        f"scheduler={summary['scheduler_status'] or 'unknown'} "
        f"failed={summary['failed_job_count']} "
        f"{states}"
    ).strip()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp_path, path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def empty_state(manifest_path: Path, task_root: Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": now_iso(),
        "manifest": str(manifest_path),
        "cwd": str(task_root),
        "status_args": [],
        "recovery_suffix": RECOVERY_SUFFIX,
        "families": {},
        "attempts": {},
        "query_failures": [],
        "header_only_killed_tasks": [],
        "task_count": 0,
    }


def ensure_state_shape(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("schema_version", SCHEMA_VERSION)
    state.setdefault("updated_at", now_iso())
    state.setdefault("manifest", "")
    state.setdefault("cwd", "")
    state.setdefault("status_args", [])
    state.setdefault("recovery_suffix", RECOVERY_SUFFIX)
    state.setdefault("families", {})
    state.setdefault("attempts", {})
    state.setdefault("query_failures", [])
    state.setdefault("header_only_killed_tasks", [])
    state.setdefault("task_count", 0)
    for attempt in state["attempts"].values():
        attempt.setdefault("family_id", attempt.get("task_dir"))
        attempt.setdefault("parent_attempt_id", None)
        attempt.setdefault("generation", 0)
        attempt.setdefault("planned_lumi_mask", None)
        attempt.setdefault("planned_lumi_source", None)
        attempt.setdefault("status_revision", None)
        attempt.setdefault("status", {"status_collection_state": STATUS_COLLECTION_NOT_COLLECTED})
        attempt.setdefault("recovery", {})
    return state


def infer_request_lineage(request_name: str, recovery_suffix: str) -> tuple[str, int]:
    import re

    numbered_pattern = re.compile(
        rf"^(?P<root>.+)__{re.escape(recovery_suffix)}(?P<generation>\d+)$"
    )
    match = numbered_pattern.match(request_name)
    if match:
        return match.group("root"), int(match.group("generation"))
    return request_name, 0


def rebuild_families(state: dict[str, Any]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for attempt_id, attempt in state["attempts"].items():
        attempt["task_dir"] = attempt_id
        family_id = str(attempt.get("family_id") or attempt_id)
        grouped.setdefault(family_id, []).append(attempt)

    families: dict[str, Any] = {}
    for family_id, attempts in grouped.items():
        ordered = sorted(
            attempts,
            key=lambda attempt: (
                int(attempt.get("generation", 0)),
                str(attempt.get("request_name") or ""),
                str(attempt.get("task_dir") or ""),
            ),
        )
        root_attempt = next(
            (attempt for attempt in ordered if int(attempt.get("generation", 0)) == 0),
            ordered[0],
        )
        canonical_family_id = str(root_attempt["task_dir"])
        for attempt in ordered:
            attempt["family_id"] = canonical_family_id
        families[canonical_family_id] = {
            "root_task_dir": canonical_family_id,
            "root_cfg": root_attempt.get("cfg"),
            "attempt_order": [str(attempt["task_dir"]) for attempt in ordered],
            "latest_attempt_id": str(ordered[-1]["task_dir"]),
        }
    state["families"] = families


def make_status_payload(
    summary: dict[str, Any],
    jobs: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    return {
        "collected_at": now_iso(),
        "task_name": summary.get("task_name"),
        "server_status": summary.get("server_status"),
        "scheduler_status": summary.get("scheduler_status"),
        "dashboard_url": summary.get("dashboard_url"),
        "status_collection_state": summary.get("status_collection_state"),
        "query_error": summary.get("query_error"),
        "query_warning": summary.get("query_warning"),
        "job_count": int(summary.get("job_count", 0)),
        "job_states": dict(summary.get("job_states", {})),
        "failed_job_count": int(summary.get("failed_job_count", 0)),
        "failed_job_ids": [str(job_id) for job_id in summary.get("failed_job_ids", [])],
        "jobs": jobs,
    }


def clear_stale_recovery(recovery: dict[str, Any]) -> dict[str, Any]:
    preserved = {
        "submitted_child_attempt_id": recovery.get("submitted_child_attempt_id"),
        "submitted_at": recovery.get("submitted_at"),
    }
    return {
        **preserved,
        "classification": recovery.get("classification", "no_action"),
        "recovery_job_ids": [],
        "recovery_state_counts": {},
        "blocking_job_ids": [],
        "blocking_state_counts": {},
        "skipped_jobs_without_time": [],
        "kill_required": False,
        "derived_from_revision": None,
        "resolved_lumi_action": None,
        "resolved_lumi_source": None,
        "resolved_lumi_mask": None,
    }


def merge_attempt_status(
    existing_attempt: dict[str, Any] | None,
    cfg: str,
    task_dir: Path,
    status: dict[str, Any],
) -> dict[str, Any]:
    existing_attempt = dict(existing_attempt or {})
    request_name = str(existing_attempt.get("request_name") or Path(cfg).stem)
    root_request_name, generation = infer_request_lineage(request_name, RECOVERY_SUFFIX)
    task_dir_name = task_dir.name
    family_id = str(existing_attempt.get("family_id") or (task_dir_name if generation == 0 else task_dir_name))
    status_revision = hash_payload(
        {key: value for key, value in status.items() if key != "collected_at"}
    )
    recovery = dict(existing_attempt.get("recovery", {}))
    if recovery.get("derived_from_revision") != status_revision:
        recovery = clear_stale_recovery(recovery)

    return {
        **existing_attempt,
        "task_dir": task_dir_name,
        "cfg": cfg,
        "cfg_path": str(Path(cfg).resolve() if Path(cfg).exists() else Path(cfg)),
        "task_path": str(task_dir.resolve()),
        "request_name": request_name,
        "family_id": family_id,
        "parent_attempt_id": existing_attempt.get("parent_attempt_id"),
        "generation": int(existing_attempt.get("generation", generation)),
        "planned_lumi_mask": existing_attempt.get("planned_lumi_mask"),
        "planned_lumi_source": existing_attempt.get("planned_lumi_source"),
        "status_revision": status_revision,
        "status": status,
        "recovery": recovery,
    }


def load_existing_state(state_path: Path, manifest_path: Path, task_root: Path) -> dict[str, Any]:
    if state_path.exists():
        return ensure_state_shape(load_json(state_path))
    return empty_state(manifest_path, task_root)


def query_entries(
    manifest_entries: list[str], task_root: Path, state: dict[str, Any]
) -> list[tuple[str, Path]]:
    entries: dict[str, tuple[str, Path]] = {}
    for cfg in manifest_entries:
        task_dir = task_dir_from_cfg(task_root, cfg)
        entries[task_dir.name] = (cfg, task_dir)
    for attempt in state.get("attempts", {}).values():
        cfg = str(attempt.get("cfg_path") or attempt.get("cfg") or "")
        task_path = Path(str(attempt.get("task_path") or (task_root / attempt["task_dir"])))
        if not cfg:
            continue
        entries.setdefault(task_path.name, (cfg, task_path))
    return list(entries.values())


def run_collect(args: argparse.Namespace, extra_args: list[str]) -> int:
    ensure_compatible_status_args(extra_args)

    manifest_path = Path(args.manifest).resolve()
    state_path = resolve_state_file(args).resolve()
    task_root = Path.cwd().resolve()
    state = load_existing_state(state_path, manifest_path, task_root)
    state["manifest"] = str(manifest_path)
    state["cwd"] = str(task_root)
    state["status_args"] = list(extra_args)

    query_failures: list[str] = []
    header_only_killed_tasks: list[str] = []

    for cfg, task_dir in query_entries(read_manifest(manifest_path), task_root, state):
        summary, payload, _stdout, _stderr, _cmd = build_task_summary(cfg, task_dir, extra_args)
        status = make_status_payload(summary, payload)
        task_dir_name = task_dir.name
        state["attempts"][task_dir_name] = merge_attempt_status(
            state["attempts"].get(task_dir_name),
            cfg,
            task_dir,
            status,
        )

        if status["status_collection_state"] == STATUS_COLLECTION_HEADER_ONLY_KILLED:
            header_only_killed_tasks.append(task_dir_name)
        if status["status_collection_state"] == STATUS_COLLECTION_FATAL_ERROR:
            query_failures.append(task_dir_name)
        print(format_task_summary(summary))

    rebuild_families(state)
    state["query_failures"] = sorted(query_failures)
    state["header_only_killed_tasks"] = sorted(header_only_killed_tasks)
    state["task_count"] = len(state["attempts"])
    state["updated_at"] = now_iso()
    write_json(state_path, state)
    return 1 if query_failures else 0


def run_list_failed(args: argparse.Namespace) -> int:
    state_path = resolve_state_file(args).resolve()
    if not state_path.exists():
        raise FileNotFoundError(
            f"Missing state file {state_path}. Run ./status.sh first."
        )

    state = ensure_state_shape(load_json(state_path))
    query_failures = state.get("query_failures", [])
    if query_failures:
        print(
            "Status snapshot contains query failures; refresh status before resubmitting: "
            + ", ".join(query_failures),
            file=sys.stderr,
        )
        return 1

    for attempt in state.get("attempts", {}).values():
        status = attempt.get("status", {})
        failed_job_ids = status.get("failed_job_ids", [])
        if not failed_job_ids:
            continue
        print(
            "\t".join(
                [
                    str(attempt["task_dir"]),
                    ",".join(str(job_id) for job_id in failed_job_ids),
                    str(status.get("failed_job_count", len(failed_job_ids))),
                ]
            )
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args, extra_args = parse_args(argv)
    ensure_cmssw_env()
    if args.command == "collect":
        return run_collect(args, extra_args)
    if extra_args:
        raise ValueError(f"Unexpected extra arguments for list-failed: {' '.join(extra_args)}")
    return run_list_failed(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI error reporting
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
