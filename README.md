# CRAB data submission helper

This directory contains a self-contained CRAB workflow for submitting `MultiLepPAT`
data jobs from 2022 through 2025.

## What drives the configuration

- `crab3_template.py` is the single CRAB template.
- `generate_crab_configs.py` expands the template using local `RundataList_*.txt`
  files.
- `../ConfFile_cfg.py` is the CMSSW config used by all generated CRAB jobs.
  Era-specific global-tag selection stays in `ConfFile_cfg.py`.
- `RundataList_*.txt` are the local dataset lists for 2022, 2023, 2024, and 2025.

The generated CRAB configs inject:

- `runOnMC=False`
- `era=<parsed from dataset path>`
- `outputFile=<campaign-specific ROOT filename>`
- `analysisMode=JpsiJpsiPhi`

## Workflow

From this directory:

```bash
./registerData.sh
```

This generates one CRAB config per dataset and records the list in
`generated_crab_configs.txt`.

Dry-run the submission commands:

```bash
./submit.sh
```

Actually submit:

```bash
DRY_RUN=0 ./submit.sh
```

Check status for all generated tasks:

```bash
./status.sh
```

Dry-run resubmission commands:

```bash
./resubmit.sh
```

Actually resubmit:

```bash
DRY_RUN=0 ./resubmit.sh
```

Kill generated tasks:

```bash
DRY_RUN=0 ./kill.sh
```

If you have an explicit proxy, the helper scripts will append
`--proxy ${X509_USER_PROXY}` automatically.

## Custom generation

You can override defaults when generating CRAB configs:

```bash
./registerData.sh \
  --lists RundataList_2025.txt \
  --analysis-mode JpsiJpsiPhi \
  --prefix crab3_refactor \
  --units-per-job 20 \
  --storage-site T3_CH_CERNBOX \
  --outlfn /store/user/chiw/JpsiJpsiPhi/rootNtuple/
```

## Notes

- The dataset lists are copied locally into this directory so `crabData` remains
  self-contained.
- The generator removes previously generated CRAB configs listed in
  `generated_crab_configs.txt` before writing a fresh set.
- Generated request names encode the stream index and the processed campaign so
  distinct prompt-reco versions do not collide.
