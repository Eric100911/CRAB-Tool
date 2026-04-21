from __future__ import annotations

import runpy

namespace = runpy.run_path(__ORIGINAL_CONFIG__)
config = namespace["config"]

ORIGINAL_CONFIG = __ORIGINAL_CONFIG__
ORIGINAL_REQUEST_NAME = __ORIGINAL_REQUEST_NAME__
RECOVERY_REQUEST_NAME = __REQUEST_NAME__

DEFAULT_RECOVERY_LUMI_MASK = __LUMI_MASK__
DEFAULT_UNITS_PER_JOB = __UNITS_PER_JOB__
DEFAULT_OUTPUT_DATASET_TAG = __DEFAULT_OUTPUT_DATASET_TAG__

# User-editable recovery overrides.
#
# Leave a value as None to keep the builder-provided default inherited from the
# original task. Replace it with a concrete value to override the recovery
# submission without modifying the original CRAB config.
RECOVERY_UNITS_PER_JOB = 100
RECOVERY_SPLITTING = None
RECOVERY_NUM_CORES = 1
RECOVERY_MAX_MEMORY_MB = 2000
RECOVERY_PYCFG_PARAM_OVERRIDES = {
    "numThreads": 1,
    "numStreams": 0,
}
RECOVERY_OVERRIDES = {
    # "Site.storageSite": "T2_CH_CERN",
    # "Data.publication": False,
    # "JobType.pyCfgParams": [
    #     "runOnMC=False",
    #     "era=Run2022E",
    #     "outputFile=mymultilep_Run2022Ev1.root",
    #     "analysisMode=JpsiJpsiPhi",
    # ],
}


def apply_dotted_override(config_obj, dotted_path, value):
    target = config_obj
    parts = dotted_path.split(".")
    if parts and parts[0] == "config":
        parts = parts[1:]
    for part in parts[:-1]:
        target = getattr(target, part)
    setattr(target, parts[-1], value)


def merge_pycfg_params(base_params, overrides):
    override_map = {str(key): str(value) for key, value in overrides.items()}
    remaining = dict(override_map)
    merged = []

    for item in base_params:
        if isinstance(item, str) and "=" in item:
            key, _value = item.split("=", 1)
            if key in override_map:
                merged.append(f"{key}={override_map[key]}")
                remaining.pop(key, None)
            else:
                merged.append(item)
        else:
            merged.append(item)

    for key, value in override_map.items():
        if key in remaining:
            merged.append(f"{key}={value}")

    return merged


config.General.requestName = RECOVERY_REQUEST_NAME
config.Data.lumiMask = DEFAULT_RECOVERY_LUMI_MASK
config.Data.outputDatasetTag = DEFAULT_OUTPUT_DATASET_TAG
config.Data.unitsPerJob = (
    DEFAULT_UNITS_PER_JOB
    if RECOVERY_UNITS_PER_JOB is None
    else RECOVERY_UNITS_PER_JOB
)

if RECOVERY_SPLITTING is not None:
    config.Data.splitting = RECOVERY_SPLITTING
if RECOVERY_NUM_CORES is not None:
    config.JobType.numCores = RECOVERY_NUM_CORES
if RECOVERY_MAX_MEMORY_MB is not None:
    config.JobType.maxMemoryMB = RECOVERY_MAX_MEMORY_MB
if RECOVERY_PYCFG_PARAM_OVERRIDES:
    base = list(getattr(config.JobType, "pyCfgParams", []))
    config.JobType.pyCfgParams = merge_pycfg_params(
        base, RECOVERY_PYCFG_PARAM_OVERRIDES
    )

for dotted_path, value in RECOVERY_OVERRIDES.items():
    apply_dotted_override(config, dotted_path, value)
