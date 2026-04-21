#!/usr/bin/env python3
"""Unit tests for the unified-state recovery builder."""

from __future__ import annotations

import importlib.util
import json
import re
import runpy
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("crab_recovery_state_builder.py")
MODULE_SPEC = importlib.util.spec_from_file_location(
    "crab_recovery_state_builder", MODULE_PATH
)
builder = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(builder)

TEMPLATE_PATH = Path(__file__).with_name("crab3_recovery_template.py")


def write_original_cfg(path: Path, *, lumi_mask: str = "/tmp/chiw/original_lumi_mask.json") -> None:
    path.write_text(
        "from WMCore.Configuration import Configuration\n"
        "config = Configuration()\n"
        "config.section_('General')\n"
        f"config.General.requestName = '{path.stem}'\n"
        "config.section_('JobType')\n"
        "config.JobType.outputFiles = ['mymultilep_Run2024Hv1.root']\n"
        "config.JobType.pyCfgParams = [\n"
        "    'runOnMC=False',\n"
        "    'era=Run2024H',\n"
        "    'outputFile=mymultilep_Run2024Hv1.root',\n"
        "    'analysisMode=JpsiJpsiPhi',\n"
        "    'numThreads=4',\n"
        "    'numStreams=4',\n"
        "]\n"
        "config.JobType.numCores = 1\n"
        "config.JobType.maxMemoryMB = 2000\n"
        "config.section_('Data')\n"
        "config.Data.splitting = 'LumiBased'\n"
        "config.Data.unitsPerJob = 40\n"
        "config.Data.publication = False\n"
        "config.Data.outputDatasetTag = 'sample'\n"
        f"config.Data.lumiMask = '{lumi_mask}'\n"
        "config.section_('Site')\n"
        "config.Site.storageSite = 'T2_TEST_SITE'\n"
    )


def install_fake_wmcore(tmp: Path) -> None:
    wmcore_dir = tmp / "WMCore"
    wmcore_dir.mkdir()
    (wmcore_dir / "__init__.py").write_text("")
    (wmcore_dir / "Configuration.py").write_text(
        "from types import SimpleNamespace\n"
        "\n"
        "class Configuration:\n"
        "    def section_(self, name):\n"
        "        section = SimpleNamespace()\n"
        "        setattr(self, name, section)\n"
        "        return section\n"
    )


@contextmanager
def prepend_sys_path(path: Path):
    sys.path.insert(0, str(path))
    try:
        yield
    finally:
        sys.path = [entry for entry in sys.path if entry != str(path)]


def render_template_with_attempt(
    tmp: Path, attempt: dict[str, object], template_text: str
) -> object:
    install_fake_wmcore(tmp)
    template_copy = tmp / "crab3_recovery_template.py"
    template_copy.write_text(template_text)
    rendered_path = builder.render_recovery_config(attempt, template_copy)
    with prepend_sys_path(tmp):
        namespace = runpy.run_path(str(rendered_path))
    return namespace["config"]


def reset_template_overrides(template_text: str) -> str:
    normalized = template_text
    replacements = [
        (r"^RECOVERY_UNITS_PER_JOB = .*$", "RECOVERY_UNITS_PER_JOB = None"),
        (r"^RECOVERY_SPLITTING = .*$", "RECOVERY_SPLITTING = None"),
        (r"^RECOVERY_NUM_CORES = .*$", "RECOVERY_NUM_CORES = None"),
        (r"^RECOVERY_MAX_MEMORY_MB = .*$", "RECOVERY_MAX_MEMORY_MB = None"),
    ]
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized, flags=re.MULTILINE)
    normalized = re.sub(
        r"RECOVERY_PYCFG_PARAM_OVERRIDES = \{\n(?:.*\n)*?\}",
        'RECOVERY_PYCFG_PARAM_OVERRIDES = {\n    "numThreads": 1,\n    "numStreams": 0,\n}',
        normalized,
        flags=re.MULTILINE,
    )
    return normalized


class CrabRecoveryStateBuilderTest(unittest.TestCase):
    def test_refresh_recovery_populates_root_planned_mask_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cfg_path = tmp / "sample_cfg.py"
            write_original_cfg(cfg_path)
            state_path = tmp / "status_cache" / builder.STATE_NAME
            state_path.parent.mkdir()
            state_path.write_text(
                json.dumps(
                    {
                        "cwd": str(tmp),
                        "families": {
                            "crab_sample_cfg": {
                                "root_task_dir": "crab_sample_cfg",
                                "root_cfg": str(cfg_path),
                                "attempt_order": ["crab_sample_cfg"],
                                "latest_attempt_id": "crab_sample_cfg",
                            }
                        },
                        "attempts": {
                            "crab_sample_cfg": {
                                "task_dir": "crab_sample_cfg",
                                "task_path": str(tmp / "crab_sample_cfg"),
                                "cfg": str(cfg_path),
                                "cfg_path": str(cfg_path),
                                "request_name": "sample_cfg",
                                "family_id": "crab_sample_cfg",
                                "generation": 0,
                                "status_revision": "sha256:test",
                                "status": {
                                    "collected_at": "2026-04-20T10:00:00+00:00",
                                    "status_collection_state": "ok_json",
                                    "server_status": "SUBMITTED",
                                    "job_states": {"idle": 2},
                                    "failed_job_count": 0,
                                    "failed_job_ids": [],
                                    "jobs": {
                                        "1": {"State": "idle", "SubmitTimes": [1]},
                                        "2": {"State": "idle", "SubmitTimes": [1]},
                                    },
                                },
                                "recovery": {"derived_from_revision": "sha256:test"},
                            }
                        },
                    }
                )
            )

            args = type(
                "Args",
                (),
                {
                    "state_file": str(state_path),
                    "plan_file": None,
                    "summary_file": None,
                    "output_dir": str(tmp / "recovery_cache"),
                    "stuck_hours": 48.0,
                    "recovery_suffix": "recover",
                },
            )
            self.assertEqual(builder.refresh_recovery_state(args), 0)
            state = json.loads(state_path.read_text())
            attempt = state["attempts"]["crab_sample_cfg"]
            self.assertEqual(
                attempt["planned_lumi_mask"], "/tmp/chiw/original_lumi_mask.json"
            )
            self.assertEqual(
                attempt["planned_lumi_source"], "original_task_lumi_mask"
            )
            self.assertIn("next_recover_cfg", attempt["artifacts"])

    def test_record_submission_appends_linear_family_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            state_path = tmp / builder.STATE_NAME
            state_path.write_text(
                json.dumps(
                    {
                        "families": {
                            "crab_parent": {
                                "root_task_dir": "crab_parent",
                                "root_cfg": str(tmp / "parent.py"),
                                "attempt_order": ["crab_parent"],
                                "latest_attempt_id": "crab_parent",
                            }
                        },
                        "attempts": {
                            "crab_parent": {
                                "task_dir": "crab_parent",
                                "cfg": str(tmp / "parent.py"),
                                "cfg_path": str(tmp / "parent.py"),
                                "task_path": str(tmp / "crab_parent"),
                                "request_name": "parent",
                                "family_id": "crab_parent",
                                "generation": 0,
                                "planned_lumi_mask": "/tmp/chiw/original.json",
                                "status_revision": "sha256:test",
                                "status": {"status_collection_state": "ok_json"},
                                "recovery": {
                                    "derived_from_revision": "sha256:test",
                                    "classification": "killed_recovery_candidate",
                                    "executable": True,
                                    "resolved_lumi_action": "submit",
                                    "resolved_lumi_source": "parent_planned_lumi_mask_killed",
                                    "resolved_lumi_mask": "/tmp/chiw/original.json",
                                },
                                "artifacts": {
                                    "next_child_task_dir": "crab_parent__recover1",
                                    "next_child_task_path": str(tmp / "crab_parent__recover1"),
                                    "next_recover_cfg": str(tmp / "recovery_cache" / "configs" / "parent__recover1.py"),
                                    "next_recover_request_name": "parent__recover1",
                                },
                            }
                        },
                    }
                )
            )
            args = type(
                "Args",
                (),
                {
                    "state_file": str(state_path),
                    "plan_file": None,
                    "summary_file": None,
                    "task": "crab_parent",
                },
            )
            self.assertEqual(builder.record_submission(args), 0)
            state = json.loads(state_path.read_text())
            self.assertEqual(
                state["families"]["crab_parent"]["attempt_order"],
                ["crab_parent", "crab_parent__recover1"],
            )
            child = state["attempts"]["crab_parent__recover1"]
            self.assertEqual(child["parent_attempt_id"], "crab_parent")
            self.assertEqual(child["planned_lumi_mask"], "/tmp/chiw/original.json")

    def test_render_recovery_config_uses_default_recovery_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cfg_path = tmp / "parent.py"
            write_original_cfg(cfg_path)

            attempt = {
                "cfg_path": str(cfg_path),
                "request_name": "parent",
                "recovery": {"resolved_lumi_mask": "/tmp/chiw/missing.json"},
                "artifacts": {
                    "preserved_not_finished_lumis": str(tmp / "report" / "notFinishedLumis.json"),
                    "next_recover_cfg": str(tmp / "recovery_cache" / "configs" / "child.py"),
                    "next_recover_request_name": "parent__recover1",
                },
            }

            config = render_template_with_attempt(
                tmp, attempt, reset_template_overrides(TEMPLATE_PATH.read_text())
            )
            self.assertEqual(config.General.requestName, "parent__recover1")
            self.assertEqual(config.Data.lumiMask, "/tmp/chiw/missing.json")
            self.assertEqual(config.Data.unitsPerJob, 40)
            self.assertEqual(
                config.JobType.pyCfgParams,
                [
                    "runOnMC=False",
                    "era=Run2024H",
                    "outputFile=mymultilep_Run2024Hv1.root",
                    "analysisMode=JpsiJpsiPhi",
                    "numThreads=1",
                    "numStreams=0",
                ],
            )

    def test_resolve_lumi_prefers_preserved_not_finished(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            preserved = tmp / "report" / "notFinishedLumis.json"
            preserved.parent.mkdir(parents=True)
            preserved.write_text(json.dumps({"1": [[1, 5]]}))
            task_results = tmp / "task_results" / "notFinishedLumis.json"
            task_results.parent.mkdir(parents=True)
            task_results.write_text(json.dumps({"1": [[6, 9]]}))
            action, source, path = builder.resolve_lumi_for_attempt(
                {
                    "planned_lumi_mask": "/tmp/chiw/original.json",
                    "recovery": {"classification": "recovery_candidate"},
                    "artifacts": {
                        "preserved_not_finished_lumis": str(preserved),
                        "task_not_finished_lumis": str(task_results),
                    },
                }
            )
            self.assertEqual(
                (action, source, path),
                ("submit", "preserved_not_finished", str(preserved)),
            )

    def test_resolve_lumi_falls_back_to_parent_planned_mask_when_no_jobs_finished(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            action, source, path = builder.resolve_lumi_for_attempt(
                {
                    "planned_lumi_mask": "/tmp/chiw/original.json",
                    "status": {"job_states": {"idle": 10}},
                    "recovery": {"classification": "recovery_candidate"},
                    "artifacts": {
                        "preserved_not_finished_lumis": str(tmp / "report" / "notFinishedLumis.json"),
                        "task_not_finished_lumis": str(tmp / "task_results" / "notFinishedLumis.json"),
                        "task_processed_lumis": str(tmp / "task_results" / "processedLumis.json"),
                        "task_lumis_to_process": str(tmp / "task_results" / "lumisToProcess.json"),
                    },
                }
            )
            self.assertEqual(
                (action, source, path),
                ("submit", "parent_planned_lumi_mask_no_finished_jobs", "/tmp/chiw/original.json"),
            )

    def test_resolve_lumi_skips_complete_when_processed_equals_planned(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            results = tmp / "task_results"
            results.mkdir()
            content = json.dumps({"1": [[1, 5]]})
            (results / "processedLumis.json").write_text(content)
            (results / "lumisToProcess.json").write_text(content)
            action, source, path = builder.resolve_lumi_for_attempt(
                {
                    "planned_lumi_mask": "/tmp/chiw/original.json",
                    "status": {"job_states": {"finished": 10}},
                    "recovery": {"classification": "recovery_candidate"},
                    "artifacts": {
                        "preserved_not_finished_lumis": str(tmp / "report" / "notFinishedLumis.json"),
                        "task_not_finished_lumis": str(results / "notFinishedLumis.json"),
                        "task_processed_lumis": str(results / "processedLumis.json"),
                        "task_lumis_to_process": str(results / "lumisToProcess.json"),
                    },
                }
            )
            self.assertEqual((action, source, path), ("skip", "complete", ""))


if __name__ == "__main__":
    unittest.main()
