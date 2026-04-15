#!/usr/bin/env python3
"""Collect machine-readable CRAB status snapshots and list failed jobs."""

from __future__ import annotations

import argparse
import collections
import json
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


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Collect CRAB status snapshots and list tasks with failed jobs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser(
        "collect", help="Query crab status for all tasks and save JSON summaries."
    )
    collect_parser.add_argument("--manifest", default="generated_crab_configs.txt")
    collect_parser.add_argument("--cache-dir", default="status_cache")

    list_failed_parser = subparsers.add_parser(
        "list-failed", help="List task directories that have failed jobs in a saved summary."
    )
    list_failed_parser.add_argument(
        "--summary-file", default="status_cache/latest_summary.json"
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


def task_dir_from_cfg(cfg: str) -> str:
    return f"crab_{Path(cfg).stem}"


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


def build_task_summary(cfg: str, task_dir: Path, extra_args: list[str]) -> tuple[dict, dict | None]:
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
        "query_error": None,
    }

    if not task_dir.is_dir():
        summary["query_error"] = f"Missing CRAB task directory {task_dir.name}."
        return summary, None

    completed, cmd = query_task_status(task_dir, extra_args)
    stdout = completed.stdout
    stderr = completed.stderr

    summary["task_name"] = extract_header_value(stdout, "Task name")
    summary["server_status"] = extract_header_value(stdout, "Status on the CRAB server")
    summary["scheduler_status"] = extract_header_value(stdout, "Status on the scheduler")
    summary["dashboard_url"] = extract_header_value(stdout, "Dashboard monitoring URL")

    if completed.returncode != 0:
        message = stderr.strip() or stdout.strip() or "unknown CRAB status failure"
        summary["query_error"] = (
            f"`{' '.join(cmd)}` failed with exit code {completed.returncode}: {message}"
        )
        return summary, None

    try:
        payload = extract_status_payload(stdout)
        job_states, failed_job_ids = summarize_jobs(payload)
    except Exception as exc:
        summary["query_error"] = f"Failed to parse status JSON: {exc}"
        return summary, None

    summary["job_count"] = len(payload)
    summary["job_states"] = job_states
    summary["failed_job_count"] = len(failed_job_ids)
    summary["failed_job_ids"] = failed_job_ids
    return summary, payload


def format_task_summary(summary: dict) -> str:
    if summary["query_error"]:
        return f"{summary['task_dir']} query_error={summary['query_error']}"
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
    task_summaries: list[dict] = []

    for cfg in entries:
        task_dir = (task_root / task_dir_from_cfg(cfg)).resolve()
        summary, payload = build_task_summary(cfg, task_dir, extra_args)
        task_status_file = task_cache_dir / f"{summary['task_dir']}.json"
        summary["task_status_file"] = str(task_status_file.relative_to(cache_dir))

        if payload is not None:
            write_json(task_status_file, {"summary": summary, "jobs": payload})
        if summary["query_error"]:
            query_failures.append(summary["task_dir"])

        task_summaries.append(summary)
        print(format_task_summary(summary))

    latest_summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cwd": str(task_root),
        "manifest": str(manifest_path),
        "task_count": len(task_summaries),
        "query_failures": query_failures,
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
