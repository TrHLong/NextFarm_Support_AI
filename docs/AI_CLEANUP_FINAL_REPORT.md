# AI Cleanup Final Report — 2026-09-28

## Outcome

The active project was reduced from a model-heavy demo package into a lightweight source project. Generated model history and rollback data were moved outside the shareable project folder.

## Size

- Before cleanup: about 14 GB from `backup/` and `model-artifacts/` alone.
- After cleanup: active `model-artifacts/` contains only `training_policy.json` and `problem-b/collection_state.json`.
- Archive: `D:\2026-2027\THUCTAP\NextFarm-AI-Support-v10.1_ARCHIVE_20260928`.

## Moved To Archive

- `backup/` rollback snapshot: 7.51 GB.
- `model-artifacts/data/customers/`: 5.86 GB.
- `model-artifacts/shared/`: 117.82 MB.
- `model-artifacts/benchmark-retrain/`: 115.91 MB.
- `model-artifacts/device-v11/`: 839.15 MB.
- `model-artifacts/device-v11-candidate-b/`: 263.00 MB.
- generated reports, farmer-v13 artifacts, historical-customer artifacts, device/runtime datasets and shared summaries.

Total moved across both cleanup passes: about 15.01 GB.

## Models Kept Eligible

These are not production-ready; they are only eligible for future evidence collection:

- `moisture_forecast`
- `flow_fault_forecast`
- `sensor_fault_forecast`

## Removed From Active Runtime

- `temperature_forecast`
- `ec_forecast`
- `ph_forecast`
- `leak_forecast`
- `irrigation_failure_forecast`
- `irrigation_need`
- `device_health`
- `farm_health`
- `power_loss_forecast`
- `mqtt_loss_forecast`

## Production Logic Kept

- deterministic sensor/device/irrigation/fertilizer/command/alert queries;
- Vietnamese time resolver;
- authorization and cross-farm protection;
- missing/stale/out-of-range rules;
- fertilizer and irrigation aggregation.

## Runtime Policy

- Docker default: `DEVICE_AUTO_TRAIN=false`.
- Farmer forecast endpoint: fail-closed `NOT_VALIDATED` until a real validation gate exists.
- Runtime training code now uses `ACTIVE_SPECS`, so it only considers the 3 eligible model families.

## Verification

- `docker compose config --quiet`: passed, with only Docker config-file access warning from Windows.
- Static syntax check with `ast.parse`: passed for cleanup scripts, `contracts.py`, `api.py`, and `runtime_training.py`.
- Full pytest could not be run from the bundled Python because `pytest` is not installed in that runtime.

## Re-run Commands

```cmd
cd /d "D:\2026-2027\THUCTAP\NextFarm-AI-Support-v10.1"
python scripts\audit_ai_cleanup.py --project-root .
python scripts\cleanup_ai_models.py --project-root . --archive-root "D:\2026-2027\THUCTAP\NextFarm-AI-Support-v10.1_ARCHIVE_20260928" --apply
docker compose config --quiet
docker compose up -d --build
```

For this machine, if `python` is not available in PATH, use the Codex bundled Python shown in the session logs.
