#!/usr/bin/env python3
"""Unit tests for crab_status_snapshot.py."""

from __future__ import annotations

import json
import importlib.util
import tempfile
import unittest
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
            summary_path = Path(tmpdir) / "latest_summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "query_failures": ["crab_task_a"],
                        "tasks": [],
                    }
                )
            )
            args = type("Args", (), {"summary_file": str(summary_path)})
            self.assertEqual(snapshot.run_list_failed(args), 1)


if __name__ == "__main__":
    unittest.main()
