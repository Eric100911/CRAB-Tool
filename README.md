# CRAB data submission helper

This directory contains a self-contained CRAB workflow for submitting
`MultiLepPAT` data jobs from 2022 through 2025.

## Preconditions

Every helper script in this directory expects:

```bash
cmsenv
export X509_USER_PROXY="$(voms-proxy-info -path)"
```

Use `--help` on any wrapper or Python CLI to see the full command reference.
Help output is always available even if `cmsenv` has not been set yet.

## What drives the configuration

- `crab3_template.py` is the base CRAB template.
- `crab3_recovery_template.py` is the user-editable recovery overlay template.
- `generate_crab_configs.py` expands the template using local `RundataList_*.txt`
  files.
- `registerData.sh` is a thin wrapper around `generate_crab_configs.py`.
- `../ConfFile_cfg.py` is the CMSSW config used by all generated CRAB jobs.
  Era-specific global-tag selection stays in `ConfFile_cfg.py`.
- `RundataList_*.txt` are the local dataset lists for 2022, 2023, 2024, and 2025.

The generated CRAB configs inject:

- `runOnMC=False`
- `era=<parsed from dataset path>`
- `outputFile=<campaign-specific ROOT filename>`
- `analysisMode=JpsiJpsiPhi`

## Quick start

Generate CRAB configs and refresh the manifest:

```bash
./registerData.sh
```

Print the submission commands without executing them:

```bash
./submit.sh
```

Submit for real:

```bash
./submit.sh --execute
```

Collect cached CRAB status snapshots:

```bash
./status.sh
```

Inspect raw CRAB status output instead of the cached JSON flow:

```bash
./status.sh --raw-status -- --verboseErrors
```

Resubmit only failed jobs:

```bash
./resubmit.sh --execute
```

Prepare recovery plans and render recovery configs:

```bash
./prepare_recovery_tasks.sh
```

Print the recovery report/preserve/kill/render/submit sequence without executing it:

```bash
./kill_unfinished_and_submit_recover.sh
```

Run the recovery sequence for real:

```bash
./kill_unfinished_and_submit_recover.sh --execute
```

Include mixed tasks in the recovery execution set:

```bash
./kill_unfinished_and_submit_recover.sh --execute --allow-mixed-tasks
```

Kill every generated task in the manifest:

```bash
./kill.sh --execute
```

## CLI reference

### `registerData.sh`

Generate CRAB configs from the local dataset lists.

```bash
./registerData.sh [generator options]
```

Notes:

- Forwards all non-help arguments to `generate_crab_configs.py`.
- Use `./generate_crab_configs.py --help` for the full generator option list.

### `submit.sh`

Submit every config listed in the manifest.

```bash
./submit.sh [options] [-- crab submit options]
```

Key options:

- `--dry-run`
- `--execute`
- `--manifest PATH`

### `status.sh`

Collect cached machine-readable status snapshots, or call `crab status` directly.

```bash
./status.sh [options] [-- crab status options]
```

Key options:

- `--cached-status`
- `--raw-status`
- `--manifest PATH`
- `--cache-dir PATH`

Outputs:

- `status_cache/latest_summary.json`
- `status_cache/tasks/*.json`

### `resubmit.sh`

Refresh or reuse cached task status, then resubmit only failed CRAB jobs.

```bash
./resubmit.sh [options] [-- crab resubmit options]
```

Key options:

- `--dry-run`
- `--execute`
- `--use-cached-status`
- `--refresh-status`
- `--status-cache-dir PATH`

### `prepare_recovery_tasks.sh`

Build a recovery plan and render recovery configs for stuck unfinished jobs.

```bash
./prepare_recovery_tasks.sh [options]
```

Key options:

- `--use-cached-status`
- `--refresh-status`
- `--status-cache-dir PATH`
- `--recovery-cache-dir PATH`
- `--stuck-hours HOURS`

Outputs:

- `recovery_cache/latest_recovery_plan.json`
- `recovery_cache/task_lineage.json`
- `recovery_cache/tracked_configs.txt`
- `recovery_cache/generated_recovery_configs.txt`
- `recovery_cache/configs/*.py`

Recovery overrides:

- Edit `crab3_recovery_template.py` when you need recovery-specific overrides
  such as `Data.unitsPerJob`, `Data.splitting`,
  `RECOVERY_PYCFG_PARAM_OVERRIDES`,
  `JobType.numCores`, `JobType.maxMemoryMB`, or other dotted `config.*` fields.
- Leave an override as `None` to keep the builder-provided default inherited
  from the original task.
- Re-run `./prepare_recovery_tasks.sh` or
  `./crab_recovery_task_builder.py render-all ...` after editing the template so
  the generated recovery configs under `recovery_cache/configs/` pick up the
  new overlay values.
- `RECOVERY_PYCFG_PARAM_OVERRIDES` merges into the original task
  `config.JobType.pyCfgParams`: existing keys are replaced in place and new keys
  are appended.
- If you truly need a full manual replacement for `JobType.pyCfgParams`, use the
  generic `RECOVERY_OVERRIDES` escape hatch with
  `"JobType.pyCfgParams": [...]`.
- During actual recovery execution, normal tasks preserve
  `results/notFinishedLumis.json` into `recovery_cache/reports/<task>/` before
  the original task is killed. The rendered recovery config then uses that
  preserved file as its lumi mask.

### `kill_unfinished_and_submit_recover.sh`

Execute the recovery flow selected by the recovery plan.

```bash
./kill_unfinished_and_submit_recover.sh [options]
```

Key options:

- `--dry-run`
- `--execute`
- `--use-prepared-plan`
- `--rebuild-plan`
- `--use-cached-status`
- `--refresh-status`
- `--allow-mixed-tasks`
- `--skip-mixed-tasks`

### `kill.sh`

Kill every task listed in the manifest.

```bash
./kill.sh [options] [-- crab kill options]
```

Key options:

- `--dry-run`
- `--execute`
- `--manifest PATH`

## Python CLI reference

### `generate_crab_configs.py`

Generate CRAB config files from the local dataset lists.

```bash
./generate_crab_configs.py --help
```

### `crab_status_snapshot.py`

Collect cached CRAB status JSON payloads or list failed jobs from a saved
summary.

```bash
./crab_status_snapshot.py --help
./crab_status_snapshot.py collect --help
./crab_status_snapshot.py list-failed --help
```

`list-failed` prints one tab-separated line per task:

```text
task_dir<TAB>comma-separated job ids<TAB>failed job count
```

### `crab_recovery_task_builder.py`

Build recovery plans, keep recovery lineage metadata, resolve lumi-mask
fallbacks, render recovery configs, or list executable recovery tasks.

```bash
./crab_recovery_task_builder.py --help
./crab_recovery_task_builder.py plan --help
./crab_recovery_task_builder.py render-all --help
./crab_recovery_task_builder.py resolve-lumi-mask --help
```

`list-executable` prints:

```text
task_dir<TAB>task_path<TAB>report_dir<TAB>report_lumi_mask<TAB>recover_cfg<TAB>classification
```

## Recovery classification

`prepare_recovery_tasks.sh` reads `status_cache/latest_summary.json` and
classifies tasks into:

- `recovery_candidate`: tasks whose `unsubmitted` jobs or sufficiently old
  `idle` / `cooloff` jobs should move to a recovery task immediately.
- `killed_recovery_candidate`: tasks whose `crab status --json` output contains
  only the CRAB header, with `Status on the CRAB server: KILLED`, so the task
  should still move into the recovery flow even without per-job JSON.
- `mixed`: tasks that have recovery-candidate jobs but also still contain other
  non-finished jobs such as `running`, `transferring`, `failed`, or fresher
  `idle` / `cooloff` jobs.
- `failed_only`: tasks that only need the existing `./resubmit.sh` flow.

Mixed tasks are excluded from recovery execution by default. Add
`--allow-mixed-tasks` when you want to include them.

## Environment variable compatibility

The preferred interface is the command line. The wrappers still accept the old
environment variables as fallbacks:

- `CRAB_MANIFEST`
- `STATUS_CACHE_DIR`
- `RECOVERY_CACHE_DIR`
- `DRY_RUN`
- `RAW_STATUS`
- `USE_CACHED_STATUS`
- `USE_PREPARED_PLAN`
- `ALLOW_MIXED_TASKS`
- `STUCK_HOURS`

Precedence is:

1. command-line flag
2. environment variable
3. built-in default

Examples:

```bash
# Preferred
./submit.sh --execute

# Still supported
DRY_RUN=0 ./submit.sh
```

## Notes

- The dataset lists are copied locally into this directory so `crabData` remains
  self-contained.
- The generator removes previously generated CRAB configs listed in
  `generated_crab_configs.txt` before writing a fresh set.
- Generated request names encode the stream index and the processed campaign so
  distinct prompt-reco versions do not collide.
- `crab status --json` still prints a human-readable header before the JSON
  payload, so `crab_status_snapshot.py` extracts the final JSON object from
  stdout before summarizing job states.
- A killed task may return only the CRAB header with `Status on the CRAB
  server: KILLED` and no JSON payload. The cached status flow now records that
  as a non-fatal `header_only_killed` state instead of aborting recovery
  planning.
- Normal recovery tasks now follow the CRAB flow of `crab report` on the
  original task, preserving `results/notFinishedLumis.json` into
  `recovery_cache/reports/<task>/`, then `crab kill`, and finally `crab submit`
  of a new config that reuses the original task settings with a new request
  name and the preserved not-finished lumi mask.
- The generated recovery config is now rendered through
  `crab3_recovery_template.py`, which acts as the supported overlay layer for
  recovery-only changes. That template can override the default inherited
  `unitsPerJob`, splitting mode, CRAB job resources, keyed `pyCfgParams`, and
  arbitrary dotted `config.*` assignments without modifying either
  `crab3_template.py` or the original task config.
- `lumisToProcess.json` is informational and is not used as the recovery lumi
  mask. The normal recovery source is `notFinishedLumis.json`.
- If an already-killed task has no preserved or existing
  `results/notFinishedLumis.json`, the recovery flow falls back to the original
  task lumi mask and resubmits the full lumi set.
- Recovery ancestry is tracked in `recovery_cache/task_lineage.json`. Generated
  recovery request names use numbered descendants such as
  `...__recover1`, `...__recover2`, and the lineage-aware manifest
  `recovery_cache/tracked_configs.txt` is available for future status or
  recovery passes that need to include submitted recovery configs.
