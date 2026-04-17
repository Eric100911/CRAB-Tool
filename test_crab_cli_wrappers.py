#!/usr/bin/env python3
"""CLI regression tests for the crabData shell wrappers and Python helpers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SUBMIT_SH = SCRIPT_DIR / "submit.sh"
RESUBMIT_SH = SCRIPT_DIR / "resubmit.sh"
PREPARE_RECOVERY_SH = SCRIPT_DIR / "prepare_recovery_tasks.sh"
KILL_RECOVER_SH = SCRIPT_DIR / "kill_unfinished_and_submit_recover.sh"
STATUS_SNAPSHOT_PY = SCRIPT_DIR / "crab_status_snapshot.py"
RECOVERY_BUILDER_PY = SCRIPT_DIR / "crab_recovery_task_builder.py"


def make_fake_tools(root: Path) -> tuple[Path, Path]:
    fake_bin = root / "bin"
    fake_bin.mkdir()
    proxy_path = root / "x509up_u_test"
    proxy_path.write_text("proxy\n")
    crab_log = root / "fake_crab.log"

    crab_script = fake_bin / "crab"
    crab_script.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"${FAKE_CRAB_LOG}\"\n"
        "exit 0\n"
    )
    crab_script.chmod(0o755)

    proxy_script = fake_bin / "voms-proxy-info"
    proxy_script.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == \"-path\" ]]; then\n"
        "  printf '%s\\n' \"${FAKE_PROXY_PATH}\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    proxy_script.chmod(0o755)
    return proxy_path, crab_log


class CrabCliWrapperTest(unittest.TestCase):
    maxDiff = None

    def base_env(self) -> dict[str, str]:
        env = os.environ.copy()
        for key in ("CMSSW_BASE", "CMSSW_RELEASE_BASE", "SCRAM_ARCH", "X509_USER_PROXY"):
            env.pop(key, None)
        return env

    def run_command(
        self, command: list[str], *, env: dict[str, str], cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=cwd or SCRIPT_DIR,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_submit_help_short_circuits_preflight(self) -> None:
        env = self.base_env()
        completed = self.run_command(["bash", str(SUBMIT_SH), "--help"], env=env)
        self.assertEqual(completed.returncode, 0)
        self.assertIn("Usage: ./submit.sh", completed.stdout)
        self.assertNotIn("CMSSW environment is not active", completed.stderr)

    def test_prepare_recovery_help_short_circuits_preflight(self) -> None:
        env = self.base_env()
        completed = self.run_command(
            ["bash", str(PREPARE_RECOVERY_SH), "--help"], env=env
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("Usage: ./prepare_recovery_tasks.sh", completed.stdout)
        self.assertNotIn("CMSSW environment is not active", completed.stderr)

    def test_submit_requires_cmssw_before_normal_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# config\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                }
            )

            completed = self.run_command(
                ["bash", str(SUBMIT_SH), "--dry-run", "--manifest", str(manifest_path)],
                env=env,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("CMSSW environment is not active", completed.stderr)

    def test_submit_execute_cli_overrides_dry_run_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# config\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                    "CMSSW_BASE": "/tmp/cmssw",
                    "CMSSW_RELEASE_BASE": "/tmp/cmssw_release",
                    "SCRAM_ARCH": "el9_amd64_gcc13",
                    "DRY_RUN": "1",
                }
            )

            completed = self.run_command(
                ["bash", str(SUBMIT_SH), "--execute", "--manifest", str(manifest_path)],
                env=env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertTrue(crab_log.exists())
            self.assertIn(f"submit -c {cfg_path}", crab_log.read_text())

    def test_submit_dry_run_cli_overrides_execute_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# config\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                    "CMSSW_BASE": "/tmp/cmssw",
                    "CMSSW_RELEASE_BASE": "/tmp/cmssw_release",
                    "SCRAM_ARCH": "el9_amd64_gcc13",
                    "DRY_RUN": "0",
                }
            )

            completed = self.run_command(
                ["bash", str(SUBMIT_SH), "--dry-run", "--manifest", str(manifest_path)],
                env=env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn(f"crab submit -c {cfg_path}", completed.stdout)
            self.assertFalse(crab_log.exists(), msg=crab_log.read_text() if crab_log.exists() else "")

    def test_resubmit_use_cached_status_cli_overrides_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# config\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")
            task_dir = tmp / "crab_sample_cfg"
            status_cache_dir = tmp / "status_cache"
            status_cache_dir.mkdir()
            summary_path = status_cache_dir / "latest_summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "query_failures": [],
                        "tasks": [
                            {
                                "task_dir": str(task_dir),
                                "failed_job_ids": ["7", "9"],
                                "failed_job_count": 2,
                            }
                        ],
                    }
                )
            )

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                    "CMSSW_BASE": "/tmp/cmssw",
                    "CMSSW_RELEASE_BASE": "/tmp/cmssw_release",
                    "SCRAM_ARCH": "el9_amd64_gcc13",
                    "USE_CACHED_STATUS": "0",
                }
            )

            completed = self.run_command(
                [
                    "bash",
                    str(RESUBMIT_SH),
                    "--dry-run",
                    "--use-cached-status",
                    "--manifest",
                    str(manifest_path),
                    "--status-cache-dir",
                    str(status_cache_dir),
                ],
                env=env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn(f"crab resubmit -d {task_dir} --jobids", completed.stdout)
            self.assertIn("7\\,9", completed.stdout)

    def test_python_help_outputs_do_not_require_cmssw(self) -> None:
        env = self.base_env()
        status_help = self.run_command(
            [sys.executable, str(STATUS_SNAPSHOT_PY), "collect", "--help"], env=env
        )
        self.assertEqual(status_help.returncode, 0)
        self.assertIn("Output files:", status_help.stdout)
        self.assertIn("--cache-dir", status_help.stdout)

        recovery_help = self.run_command(
            [sys.executable, str(RECOVERY_BUILDER_PY), "plan", "--help"], env=env
        )
        self.assertEqual(recovery_help.returncode, 0)
        self.assertIn("Output files:", recovery_help.stdout)
        self.assertIn("--stuck-hours", recovery_help.stdout)

    def test_kill_recover_dry_run_reports_before_kill_for_normal_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# config\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")
            recovery_cache_dir = tmp / "recovery_cache"
            recovery_cache_dir.mkdir()
            task_path = tmp / "crab_sample_cfg"
            plan_path = recovery_cache_dir / "latest_recovery_plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "task_dir": "crab_sample_cfg",
                                "task_path": str(task_path),
                                "report_dir": str(recovery_cache_dir / "reports" / "crab_sample_cfg"),
                                "preserved_not_finished_lumis": str(
                                    recovery_cache_dir / "reports" / "crab_sample_cfg" / "notFinishedLumis.json"
                                ),
                                "recover_cfg": str(recovery_cache_dir / "configs" / "sample__recover1.py"),
                                "classification": "recovery_candidate",
                            }
                        ]
                    }
                )
            )

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                    "CMSSW_BASE": "/tmp/cmssw",
                    "CMSSW_RELEASE_BASE": "/tmp/cmssw_release",
                    "SCRAM_ARCH": "el9_amd64_gcc13",
                }
            )

            completed = self.run_command(
                [
                    "bash",
                    str(KILL_RECOVER_SH),
                    "--dry-run",
                    "--use-prepared-plan",
                    "--manifest",
                    str(manifest_path),
                    "--recovery-cache-dir",
                    str(recovery_cache_dir),
                ],
                env=env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            lines = [line for line in completed.stdout.splitlines() if line.startswith("[")]
            self.assertGreaterEqual(len(lines), 6)
            self.assertIn("crab report -d", lines[0])
            self.assertIn("cp -f", lines[1])
            self.assertIn("crab kill -d", lines[2])

    def test_kill_recover_dry_run_skips_kill_for_killed_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# config\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")
            recovery_cache_dir = tmp / "recovery_cache"
            recovery_cache_dir.mkdir()
            task_path = tmp / "crab_sample_cfg"
            plan_path = recovery_cache_dir / "latest_recovery_plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "task_dir": "crab_sample_cfg",
                                "task_path": str(task_path),
                                "report_dir": str(recovery_cache_dir / "reports" / "crab_sample_cfg"),
                                "preserved_not_finished_lumis": str(
                                    recovery_cache_dir / "reports" / "crab_sample_cfg" / "notFinishedLumis.json"
                                ),
                                "recover_cfg": str(recovery_cache_dir / "configs" / "sample__recover1.py"),
                                "classification": "killed_recovery_candidate",
                            }
                        ]
                    }
                )
            )

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                    "CMSSW_BASE": "/tmp/cmssw",
                    "CMSSW_RELEASE_BASE": "/tmp/cmssw_release",
                    "SCRAM_ARCH": "el9_amd64_gcc13",
                }
            )

            completed = self.run_command(
                [
                    "bash",
                    str(KILL_RECOVER_SH),
                    "--dry-run",
                    "--use-prepared-plan",
                    "--manifest",
                    str(manifest_path),
                    "--recovery-cache-dir",
                    str(recovery_cache_dir),
                ],
                env=env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            lines = [line for line in completed.stdout.splitlines() if line.startswith("[")]
            self.assertGreaterEqual(len(lines), 5)
            self.assertIn("preserve-if-present", lines[0])
            self.assertNotIn("crab kill -d", completed.stdout)


if __name__ == "__main__":
    unittest.main()
