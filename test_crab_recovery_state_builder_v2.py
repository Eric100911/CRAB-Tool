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
sys.path.insert(0, str(MODULE_PATH.parent))
MODULE_SPEC.loader.exec_module(builder)

TEMPLATE_PATH = Path(__file__).with_name("crab3_recovery_template.py")
ROOT_COMPACT_MASK = {"1": [[1, 5]]}
CHILD_COMPACT_MASK = {"1": [[6, 9]]}


def write_original_cfg(
    path: Path,
    *,
    lumi_mask: str = "/tmp/chiw/original_lumi_mask.json",
    units_per_job: int = 40,
    publication: bool = False,
    output_dataset_tag_expr: str = "'sample'",
    preamble: str = "",
) -> None:
    path.write_text(
        preamble
        +
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
        f"config.Data.unitsPerJob = {units_per_job}\n"
        f"config.Data.publication = {publication!r}\n"
        f"config.Data.outputDatasetTag = {output_dataset_tag_expr}\n"
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
            original_lumi_mask = tmp / "original_lumi_mask.json"
            original_lumi_mask.write_text(json.dumps(ROOT_COMPACT_MASK) + "\n")
            write_original_cfg(cfg_path, lumi_mask=str(original_lumi_mask))
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
            with prepend_sys_path(tmp):
                self.assertEqual(builder.refresh_recovery_state(args), 0)
            state = json.loads(state_path.read_text())
            attempt = state["attempts"]["crab_sample_cfg"]
            self.assertEqual(attempt["planned_lumi_mask"], ROOT_COMPACT_MASK)
            self.assertEqual(
                attempt["planned_lumi_source"], "original_task_lumi_mask"
            )
            self.assertEqual(
                attempt["config_metadata"],
                {
                    "units_per_job": 40,
                    "publication_enabled": False,
                    "output_dataset_tag": "sample",
                },
            )
            self.assertIn("next_recover_cfg", attempt["artifacts"])
            self.assertIn("next_planned_lumi_mask_file", attempt["artifacts"])

    def test_record_submission_appends_linear_family_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            install_fake_wmcore(tmp)
            parent_cfg = tmp / "parent.py"
            original_lumi_mask = tmp / "original_lumi_mask.json"
            original_lumi_mask.write_text(json.dumps(ROOT_COMPACT_MASK) + "\n")
            write_original_cfg(parent_cfg, lumi_mask=str(original_lumi_mask))
            state_path = tmp / builder.STATE_NAME
            state_path.write_text(
                json.dumps(
                    {
                        "cwd": str(tmp),
                        "families": {
                            "crab_parent": {
                                "root_task_dir": "crab_parent",
                                "root_cfg": str(parent_cfg),
                                "attempt_order": ["crab_parent"],
                                "latest_attempt_id": "crab_parent",
                            }
                        },
                        "attempts": {
                            "crab_parent": {
                                "task_dir": "crab_parent",
                                "cfg": str(parent_cfg),
                                "cfg_path": str(parent_cfg),
                                "task_path": str(tmp / "crab_parent"),
                                "request_name": "parent",
                                "family_id": "crab_parent",
                                "generation": 0,
                                "planned_lumi_mask": ROOT_COMPACT_MASK,
                                "original_lumi_mask": ROOT_COMPACT_MASK,
                                "config_metadata": {
                                    "units_per_job": 40,
                                    "publication_enabled": False,
                                    "output_dataset_tag": "sample",
                                },
                                "original_units_per_job": 40,
                                "publication_enabled": False,
                                "original_output_dataset_tag": "sample",
                                "status_revision": "sha256:test",
                                "status": {"status_collection_state": "ok_json"},
                                "recovery": {
                                    "derived_from_revision": "sha256:test",
                                    "classification": "killed_recovery_candidate",
                                    "executable": True,
                                    "resolved_lumi_action": "submit",
                                    "resolved_lumi_source": "parent_planned_lumi_mask_killed",
                                    "resolved_lumi_mask": ROOT_COMPACT_MASK,
                                },
                                "artifacts": {
                                    "next_child_task_dir": "crab_parent__recover1",
                                    "next_child_task_path": str(tmp / "crab_parent__recover1"),
                                    "next_recover_cfg": str(tmp / "recovery_cache" / "configs" / "parent__recover1.py"),
                                    "next_recover_request_name": "parent__recover1",
                                    "next_planned_lumi_mask_file": str(
                                        tmp
                                        / "recovery_cache"
                                        / "lumimasks"
                                        / "parent__recover1.json"
                                    ),
                                    "preserved_not_finished_lumis": str(
                                        tmp / "report" / "notFinishedLumis.json"
                                    ),
                                },
                            }
                        },
                    }
                )
            )
            state = json.loads(state_path.read_text())
            with prepend_sys_path(tmp):
                builder.render_recovery_config(
                    state["attempts"]["crab_parent"],
                    TEMPLATE_PATH,
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
            with prepend_sys_path(tmp):
                self.assertEqual(builder.record_submission(args), 0)
            state = json.loads(state_path.read_text())
            self.assertEqual(
                state["families"]["crab_parent"]["attempt_order"],
                ["crab_parent", "crab_parent__recover1"],
            )
            child = state["attempts"]["crab_parent__recover1"]
            self.assertEqual(child["parent_attempt_id"], "crab_parent")
            self.assertEqual(child["planned_lumi_mask"], ROOT_COMPACT_MASK)
            self.assertEqual(
                child["config_metadata"],
                {
                    "units_per_job": 100,
                    "publication_enabled": False,
                    "output_dataset_tag": "parent__recover1",
                },
            )

    def test_render_recovery_config_uses_default_recovery_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cfg_path = tmp / "parent.py"
            original_lumi_mask = tmp / "original_lumi_mask.json"
            original_lumi_mask.write_text(json.dumps(ROOT_COMPACT_MASK) + "\n")
            write_original_cfg(cfg_path, lumi_mask=str(original_lumi_mask))

            attempt = {
                "cfg_path": str(cfg_path),
                "request_name": "parent",
                "config_metadata": {
                    "units_per_job": 40,
                    "publication_enabled": False,
                    "output_dataset_tag": "sample",
                },
                "recovery": {"resolved_lumi_mask": ROOT_COMPACT_MASK},
                "artifacts": {
                    "preserved_not_finished_lumis": str(tmp / "report" / "notFinishedLumis.json"),
                    "next_recover_cfg": str(tmp / "recovery_cache" / "configs" / "child.py"),
                    "next_recover_request_name": "parent__recover1",
                    "next_planned_lumi_mask_file": str(
                        tmp / "recovery_cache" / "lumimasks" / "parent__recover1.json"
                    ),
                },
            }

            config = render_template_with_attempt(
                tmp, attempt, reset_template_overrides(TEMPLATE_PATH.read_text())
            )
            self.assertEqual(config.General.requestName, "parent__recover1")
            expected_lumi_mask_path = (
                tmp / "recovery_cache" / "lumimasks" / "parent__recover1.json"
            )
            self.assertEqual(config.Data.lumiMask, str(expected_lumi_mask_path))
            self.assertEqual(
                json.loads(expected_lumi_mask_path.read_text()), ROOT_COMPACT_MASK
            )
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
                    "planned_lumi_mask": ROOT_COMPACT_MASK,
                    "recovery": {"classification": "recovery_candidate"},
                    "artifacts": {
                        "preserved_not_finished_lumis": str(preserved),
                        "task_not_finished_lumis": str(task_results),
                    },
                }
            )
            self.assertEqual(
                (action, source, path),
                ("submit", "preserved_not_finished", ROOT_COMPACT_MASK),
            )

    def test_resolve_lumi_falls_back_to_parent_planned_mask_when_no_jobs_finished(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            action, source, path = builder.resolve_lumi_for_attempt(
                {
                    "planned_lumi_mask": ROOT_COMPACT_MASK,
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
                ("submit", "parent_planned_lumi_mask_no_finished_jobs", ROOT_COMPACT_MASK),
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
                    "planned_lumi_mask": ROOT_COMPACT_MASK,
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

    def test_add_to_chain_registers_existing_child_after_exact_lumi_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            state_path = tmp / builder.STATE_NAME
            child_task_dir = "crab_parent__recover1"
            child_task_path = tmp / child_task_dir
            child_cfg_path = tmp / "parent__recover1.py"
            child_lumi_mask = tmp / "child_lumi_mask.json"
            child_lumi_mask.write_text(json.dumps(ROOT_COMPACT_MASK) + "\n")
            install_fake_wmcore(tmp)
            write_original_cfg(child_cfg_path, lumi_mask=str(child_lumi_mask))

            state_path.write_text(
                json.dumps(
                    {
                        "cwd": str(tmp),
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
                                "planned_lumi_mask": ROOT_COMPACT_MASK,
                                "planned_lumi_source": "original_task_lumi_mask",
                                "original_lumi_mask": ROOT_COMPACT_MASK,
                                "status_revision": "sha256:test",
                                "status": {"status_collection_state": "ok_json", "job_states": {"idle": 10}},
                                "recovery": {
                                    "derived_from_revision": "sha256:test",
                                    "classification": "killed_recovery_candidate",
                                    "executable": True,
                                },
                                "artifacts": {},
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
                    "parent_task": "crab_parent",
                    "child_task_dir": child_task_dir,
                    "child_cfg": str(child_cfg_path),
                    "child_task_path": str(child_task_path),
                },
            )
            with prepend_sys_path(tmp):
                self.assertEqual(builder.add_to_chain(args), 0)
            state = json.loads(state_path.read_text())
            self.assertEqual(
                state["families"]["crab_parent"]["attempt_order"],
                ["crab_parent", child_task_dir],
            )
            child = state["attempts"][child_task_dir]
            self.assertEqual(child["parent_attempt_id"], "crab_parent")
            self.assertEqual(child["planned_lumi_mask"], ROOT_COMPACT_MASK)
            self.assertEqual(
                child["planned_lumi_source"], "parent_planned_lumi_mask_fallback"
            )
            self.assertEqual(
                child["config_metadata"],
                {
                    "units_per_job": 40,
                    "publication_enabled": False,
                    "output_dataset_tag": "sample",
                },
            )

    def test_refresh_recovery_uses_persisted_child_config_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            install_fake_wmcore(tmp)
            parent_cfg = tmp / "parent.py"
            child_cfg = tmp / "parent__recover1.py"
            original_lumi_mask = tmp / "original_lumi_mask.json"
            child_lumi_mask = tmp / "child_lumi_mask.json"
            original_lumi_mask.write_text(json.dumps(ROOT_COMPACT_MASK) + "\n")
            child_lumi_mask.write_text(json.dumps(ROOT_COMPACT_MASK) + "\n")
            write_original_cfg(parent_cfg, lumi_mask=str(original_lumi_mask))
            write_original_cfg(
                child_cfg,
                lumi_mask=str(child_lumi_mask),
                units_per_job=10,
                output_dataset_tag_expr="DEFAULT_OUTPUT_DATASET_TAG",
                preamble="DEFAULT_OUTPUT_DATASET_TAG = 'parent__recover1'\n",
            )

            state_path = tmp / builder.STATE_NAME
            state_path.write_text(
                json.dumps(
                    {
                        "cwd": str(tmp),
                        "families": {
                            "crab_parent": {
                                "root_task_dir": "crab_parent",
                                "root_cfg": str(parent_cfg),
                                "attempt_order": ["crab_parent"],
                                "latest_attempt_id": "crab_parent",
                            }
                        },
                        "attempts": {
                            "crab_parent": {
                                "task_dir": "crab_parent",
                                "cfg": str(parent_cfg),
                                "cfg_path": str(parent_cfg),
                                "task_path": str(tmp / "crab_parent"),
                                "request_name": "parent",
                                "family_id": "crab_parent",
                                "generation": 0,
                                "planned_lumi_mask": ROOT_COMPACT_MASK,
                                "planned_lumi_source": "original_task_lumi_mask",
                                "original_lumi_mask": ROOT_COMPACT_MASK,
                                "config_metadata": {
                                    "units_per_job": 40,
                                    "publication_enabled": False,
                                    "output_dataset_tag": "sample",
                                },
                                "original_units_per_job": 40,
                                "publication_enabled": False,
                                "original_output_dataset_tag": "sample",
                                "status_revision": "sha256:root",
                                "status": {
                                    "collected_at": "2026-04-20T10:00:00+00:00",
                                    "status_collection_state": "ok_json",
                                    "server_status": "KILLED",
                                    "job_states": {"idle": 2},
                                    "failed_job_count": 0,
                                    "failed_job_ids": [],
                                    "jobs": {
                                        "1": {"State": "idle", "SubmitTimes": [1]},
                                        "2": {"State": "idle", "SubmitTimes": [1]},
                                    },
                                },
                                "recovery": {"derived_from_revision": "sha256:root"},
                                "artifacts": {
                                    "preserved_not_finished_lumis": str(tmp / "report" / "notFinishedLumis.json"),
                                    "task_not_finished_lumis": str(tmp / "task_results" / "notFinishedLumis.json"),
                                    "task_processed_lumis": str(tmp / "task_results" / "processedLumis.json"),
                                    "task_lumis_to_process": str(tmp / "task_results" / "lumisToProcess.json"),
                                },
                            }
                        },
                    }
                )
            )
            add_args = type(
                "Args",
                (),
                {
                    "state_file": str(state_path),
                    "plan_file": None,
                    "summary_file": None,
                    "parent_task": "crab_parent",
                    "child_task_dir": "crab_parent__recover1",
                    "child_cfg": str(child_cfg),
                    "child_task_path": str(tmp / "crab_parent__recover1"),
                },
            )
            with prepend_sys_path(tmp):
                self.assertEqual(builder.add_to_chain(add_args), 0)

            refresh_args = type(
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
            with prepend_sys_path(tmp):
                self.assertEqual(builder.refresh_recovery_state(refresh_args), 0)

            state = json.loads(state_path.read_text())
            child = state["attempts"]["crab_parent__recover1"]
            self.assertEqual(
                child["config_metadata"],
                {
                    "units_per_job": 10,
                    "publication_enabled": False,
                    "output_dataset_tag": "parent__recover1",
                },
            )

    def test_render_recovery_config_inherits_child_effective_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cfg_path = tmp / "parent__recover1.py"
            child_lumi_mask = tmp / "child_lumi_mask.json"
            child_lumi_mask.write_text(json.dumps(CHILD_COMPACT_MASK) + "\n")
            write_original_cfg(
                cfg_path,
                lumi_mask=str(child_lumi_mask),
                units_per_job=10,
                output_dataset_tag_expr="DEFAULT_OUTPUT_DATASET_TAG",
                preamble="DEFAULT_OUTPUT_DATASET_TAG = 'parent__recover1'\n",
            )

            attempt = {
                "cfg_path": str(cfg_path),
                "request_name": "parent__recover1",
                "config_metadata": {
                    "units_per_job": 10,
                    "publication_enabled": False,
                    "output_dataset_tag": "parent__recover1",
                },
                "recovery": {"resolved_lumi_mask": CHILD_COMPACT_MASK},
                "artifacts": {
                    "preserved_not_finished_lumis": str(tmp / "report" / "notFinishedLumis.json"),
                    "next_recover_cfg": str(tmp / "recovery_cache" / "configs" / "grandchild.py"),
                    "next_recover_request_name": "parent__recover2",
                    "next_planned_lumi_mask_file": str(
                        tmp / "recovery_cache" / "lumimasks" / "parent__recover2.json"
                    ),
                },
            }

            config = render_template_with_attempt(
                tmp, attempt, reset_template_overrides(TEMPLATE_PATH.read_text())
            )
            self.assertEqual(config.Data.unitsPerJob, 10)


if __name__ == "__main__":
    unittest.main()
