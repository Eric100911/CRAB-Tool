#!/usr/bin/env python3
"""Unit tests for crab_status_snapshot.py."""

from __future__ import annotations

import json
import importlib.util
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("crab_status_snapshot.py")
MODULE_SPEC = importlib.util.spec_from_file_location("crab_status_snapshot", MODULE_PATH)
snapshot = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(snapshot)


SAMPLE_STATUS_OUTPUT = """Rucio client intialized for account chiw
CRAB project directory:\t\t/path/to/crab_task
Task name:\t\t\t260411_080042:chiw_crab_task
Status on the CRAB server:\tSUBMITTED
Status on the scheduler:\tSUBMITTED

{"1": {"State": "finished", "Error": [0, "OK", {}], "JobIds": ["144836102.0"]}, "2": {"State": "failed", "Error": [8020, "File open error", {}], "JobIds": ["144836103.0"]}, "3": {"State": "transferring", "Error": [0, "OK", {}], "JobIds": ["144836104.0"]}}
Log file is /path/to/crab.log
"""

KILLED_STATUS_OUTPUT = """Rucio client intialized for account chiw
CRAB project directory:\t\t/path/to/crab_task
Task name:\t\t\t260411_080042:chiw_crab_task
Status on the CRAB server:\tKILLED

Log file is /path/to/crab.log
"""


class CrabStatusSnapshotTest(unittest.TestCase):
    def test_extract_status_payload_ignores_text_wrapper(self) -> None:
        payload = snapshot.extract_status_payload(SAMPLE_STATUS_OUTPUT)
        self.assertEqual(sorted(payload), ["1", "2", "3"])
        self.assertEqual(payload["2"]["State"], "failed")

    def test_summarize_jobs_tracks_failed_job_ids(self) -> None:
        payload = snapshot.extract_status_payload(SAMPLE_STATUS_OUTPUT)
        job_states, failed_job_ids = snapshot.summarize_jobs(payload)
        self.assertEqual(
            job_states, {"failed": 1, "finished": 1, "transferring": 1}
        )
        self.assertEqual(failed_job_ids, ["2"])

    def test_list_failed_rejects_query_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "latest_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "query_failures": ["crab_task_a"],
                        "families": {
                            "crab_task_a": {
                                "root_task_dir": "crab_task_a",
                                "attempt_order": ["crab_task_a"],
                                "latest_attempt_id": "crab_task_a",
                            }
                        },
                        "attempts": {
                            "crab_task_a": {
                                "task_dir": "crab_task_a",
                                "status": {
                                    "failed_job_ids": ["7"],
                                    "failed_job_count": 1,
                                },
                            }
                        },
                    }
                )
            )
            args = type("Args", (), {"state_file": str(state_path), "summary_file": None})
            self.assertEqual(snapshot.run_list_failed(args), 1)

    def test_list_failed_reads_failed_jobs_from_state_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "latest_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "query_failures": [],
                        "attempts": {
                            "crab_task": {
                                "task_dir": "crab_task",
                                "status": {
                                    "failed_job_ids": ["7", "9"],
                                    "failed_job_count": 2,
                                },
                            }
                        },
                    }
                )
            )
            args = type("Args", (), {"state_file": str(state_path), "summary_file": None})
            with tempfile.TemporaryDirectory() as _:
                self.assertEqual(snapshot.run_list_failed(args), 0)

    def test_list_failed_only_emits_latest_chain_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "latest_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "query_failures": ["crab_task"],
                        "families": {
                            "crab_task": {
                                "root_task_dir": "crab_task",
                                "attempt_order": ["crab_task", "crab_task__recover1"],
                                "latest_attempt_id": "crab_task__recover1",
                            }
                        },
                        "attempts": {
                            "crab_task": {
                                "task_dir": "crab_task",
                                "status": {
                                    "failed_job_ids": ["3"],
                                    "failed_job_count": 1,
                                },
                            },
                            "crab_task__recover1": {
                                "task_dir": "crab_task__recover1",
                                "status": {
                                    "failed_job_ids": ["7", "9"],
                                    "failed_job_count": 2,
                                },
                            },
                        },
                    }
                )
            )
            args = type("Args", (), {"state_file": str(state_path), "summary_file": None})
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(snapshot.run_list_failed(args), 0)
            self.assertEqual(stdout.getvalue().strip(), "crab_task__recover1\t7,9\t2")

    def test_build_task_summary_treats_killed_without_json_as_header_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "crab_task"
            task_dir.mkdir()
            original_query = snapshot.query_task_status
            try:
                snapshot.query_task_status = lambda *_args, **_kwargs: (
                    subprocess.CompletedProcess(
                        args=["crab", "status"],
                        returncode=0,
                        stdout=KILLED_STATUS_OUTPUT,
                        stderr="",
                    ),
                    ["crab", "status", "-d", str(task_dir), "--json"],
                )
                summary, payload, stdout, stderr, cmd = snapshot.build_task_summary(
                    "sample.py", task_dir, []
                )
            finally:
                snapshot.query_task_status = original_query

            self.assertIsNone(payload)
            self.assertEqual(stdout, KILLED_STATUS_OUTPUT)
            self.assertEqual(stderr, "")
            self.assertIn("--json", cmd)
            self.assertEqual(
                summary["status_collection_state"],
                snapshot.STATUS_COLLECTION_HEADER_ONLY_KILLED,
            )
            self.assertIsNone(summary["query_error"])
            self.assertIn("Failed to parse status JSON", summary["query_warning"])

    def test_task_dir_from_cfg_uses_task_root_even_for_absolute_cfg(self) -> None:
        task_root = Path("/tmp/work")
        cfg = "/tmp/somewhere/configs/sample.py"
        self.assertEqual(
            snapshot.task_dir_from_cfg(task_root, cfg),
            task_root / "crab_sample",
        )

    def test_merge_attempt_status_clears_stale_resolved_lumi_mask(self) -> None:
        summary, payload, *_rest = (
            {
                "cfg": "sample.py",
                "task_dir": "crab_sample",
                "task_path": "/tmp/crab_sample",
                "task_name": "task",
                "server_status": "SUBMITTED",
                "scheduler_status": "SUBMITTED",
                "dashboard_url": None,
                "job_count": 1,
                "job_states": {"finished": 1},
                "failed_job_count": 0,
                "failed_job_ids": [],
                "status_collection_state": snapshot.STATUS_COLLECTION_OK,
                "query_error": None,
                "query_warning": None,
            },
            {"1": {"State": "finished"}},
            "",
            "",
            [],
        )
        status = snapshot.make_status_payload(summary, payload)
        attempt = snapshot.merge_attempt_status(
            {
                "request_name": "sample",
                "recovery": {
                    "derived_from_revision": "sha256:stale",
                    "resolved_lumi_action": "submit",
                    "resolved_lumi_source": "preserved_not_finished",
                    "resolved_lumi_mask": "/tmp/chiw/mask.json",
                },
            },
            "sample.py",
            Path("/tmp/crab_sample"),
            status,
        )
        self.assertIsNone(attempt["recovery"]["resolved_lumi_mask"])


if __name__ == "__main__":
    unittest.main()
