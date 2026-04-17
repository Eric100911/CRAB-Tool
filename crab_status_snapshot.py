#!/usr/bin/env python3
"""Collect machine-readable CRAB status snapshots and list failed jobs."""

from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

INCOMPATIBLE_STATUS_ARGS = {
    "--jobids",
    "--long",
    "--sort",
    "--summary",
    "--verboseErrors",
}
STATUS_COLLECTION_OK = "ok_json"
STATUS_COLLECTION_HEADER_ONLY_KILLED = "header_only_killed"
STATUS_COLLECTION_FATAL_ERROR = "fatal_error"


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
            "  crab_status_snapshot.py collect --cache-dir status_cache -- --instance prod\n"
            "  crab_status_snapshot.py list-failed --summary-file status_cache/latest_summary.json\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser(
        "collect",
        help="Query crab status for all tasks and save JSON summaries.",
        description=(
            "Query 'crab status --json' for every task listed in a manifest, write a "
            "summary file, and store one per-task JSON payload under the cache directory."
        ),
        formatter_class=HelpFormatter,
        epilog=(
            "Output files:\n"
            "  <cache-dir>/latest_summary.json\n"
            "  <cache-dir>/tasks/<task-dir>.json\n\n"
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
        help="Directory where the summary and per-task JSON payloads are written.",
    )

    list_failed_parser = subparsers.add_parser(
        "list-failed",
        help="List task directories that have failed jobs in a saved summary.",
        description=(
            "Read a saved latest_summary.json file and print one tab-separated line for "
            "each task that currently contains failed CRAB jobs."
        ),
        formatter_class=HelpFormatter,
        epilog=(
            "Output columns:\n"
            "  task_dir<TAB>comma-separated job ids<TAB>failed job count"
        ),
    )
    list_failed_parser.add_argument(
        "--summary-file",
        default="status_cache/latest_summary.json",
        help="Status summary file produced by the collect subcommand.",
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


def query_task_status(task_dir: Path, extra_args: list[str]) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    cmd = ["crab", "status", "-d", str(task_dir), "--json", *extra_args]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return completed, cmd


def build_task_summary(
    cfg: str, task_dir: Path, extra_args: list[str]
) -> tuple[dict, dict | None, str, str, list[str]]:
    summary = {
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


def format_task_summary(summary: dict) -> str:
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


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def run_collect(args: argparse.Namespace, extra_args: list[str]) -> int:
    ensure_compatible_status_args(extra_args)

    manifest_path = Path(args.manifest)
    cache_dir = Path(args.cache_dir)
    task_cache_dir = cache_dir / "tasks"

    entries = read_manifest(manifest_path)
    task_root = Path.cwd()
    query_failures: list[str] = []
    header_only_killed_tasks: list[str] = []
    task_summaries: list[dict] = []

    for cfg in entries:
        task_dir = task_dir_from_cfg(task_root, cfg)
        summary, payload, stdout, stderr, cmd = build_task_summary(cfg, task_dir, extra_args)
        task_status_file = task_cache_dir / f"{summary['task_dir']}.json"
        summary["task_status_file"] = str(task_status_file.relative_to(cache_dir))

        task_payload = {
            "summary": summary,
            "jobs": payload,
        }
        if summary["status_collection_state"] != STATUS_COLLECTION_OK:
            task_payload["command"] = cmd
            task_payload["stdout"] = stdout
            task_payload["stderr"] = stderr
        write_json(task_status_file, task_payload)

        if summary["status_collection_state"] == STATUS_COLLECTION_HEADER_ONLY_KILLED:
            header_only_killed_tasks.append(summary["task_dir"])
        if summary["status_collection_state"] == STATUS_COLLECTION_FATAL_ERROR:
            query_failures.append(summary["task_dir"])

        task_summaries.append(summary)
        print(format_task_summary(summary))

    latest_summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cwd": str(task_root),
        "manifest": str(manifest_path),
        "task_count": len(task_summaries),
        "query_failures": query_failures,
        "header_only_killed_tasks": header_only_killed_tasks,
        "tasks": task_summaries,
    }
    write_json(cache_dir / "latest_summary.json", latest_summary)
    return 1 if query_failures else 0


def run_list_failed(args: argparse.Namespace) -> int:
    summary_path = Path(args.summary_file)
    if not summary_path.exists():
        raise FileNotFoundError(
            f"Missing summary file {summary_path}. Run ./status.sh first."
        )

    summary = json.loads(summary_path.read_text())
    query_failures = summary.get("query_failures", [])
    if query_failures:
        print(
            "Status snapshot contains query failures; refresh status before resubmitting: "
            + ", ".join(query_failures),
            file=sys.stderr,
        )
        return 1

    for task in summary.get("tasks", []):
        failed_job_ids = task.get("failed_job_ids", [])
        if not failed_job_ids:
            continue
        print(
            "\t".join(
                [
                    task["task_dir"],
                    ",".join(str(job_id) for job_id in failed_job_ids),
                    str(task.get("failed_job_count", len(failed_job_ids))),
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
