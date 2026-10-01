# Cleanup report — reset and model cleanup 2026-09-28

## Created

- `data/canonical_reset/`: reproducible canonical JSONL data and manifest.
- `benchmarks/golden_questions_reset.jsonl`: 168 parser/query regression cases.
- `D:\2026-2027\THUCTAP\NextFarm-AI-Support-v10.1_ARCHIVE_20260928\backup\`: one rollback snapshot of existing data and model artifacts.
- `PROJECT_AUDIT.md` and `docs/evidence/PROJECT_AUDIT.json`: hashed inventory before cleanup.
- `docs/evidence/AI_CLEANUP_MOVE.json`: reversible archive move manifest.

## Replaced in the active chat path

- Multi-field irrigation logs are kept as one query plan.
- List requests return event rows, not only an aggregate.
- Fertilizer totals query `fertilizer_ml` and channel breakdowns.
- Noon resolves to a deterministic 11:00–13:30 local interval.
- Sensor max/min and open-valve count are deterministic operations.

## Retained

Existing source, migrations, tests and operational datasets remain until a verified migration/import is completed. Legacy model artifacts are not promoted or used to invent farmer answers.

The 14.71 GB backup and generated model history were moved to:
`D:\2026-2027\THUCTAP\NextFarm-AI-Support-v10.1_ARCHIVE_20260928`

The active project keeps only the canonical/operational data, source code,
tests, query/rule pipeline and small training policy metadata. Empty artifact
directories may be recreated by Docker without restoring any model.

## Model decision

| Capability | Decision | Reason |
|---|---|---|
| Moisture forecast | Keep as blocked/experimental | useful agronomic horizon; no real-data gate yet |
| Early flow failure | Keep as blocked/experimental | useful before irrigation action; independent incidents required |
| Sensor anomaly | Keep rule baseline; ML blocked | missing/stale/range are deterministic rules |
| Temperature/EC/pH forecast | Remove from active runtime | current values/trends are queryable; no validated forecast |
| Leak/irrigation-need/device-health/farm-health | Remove from active runtime | legacy synthetic or weak-label classifiers |
| Power-loss/MQTT-loss forecast | Remove from active runtime | current connectivity is a rule/observer question |

## Not claimed

No synthetic model is marked production-ready; no accuracy metric has been fabricated.
