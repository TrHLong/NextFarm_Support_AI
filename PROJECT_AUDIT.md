# Project Audit — AI Cleanup

- Created: `2026-09-27T18:30:11.595437+00:00`
- Scope: data/artifact inventory only; no deletion performed by the audit.

## Summary

| Classification | Files | Size (GB) | Meaning |
|---|---:|---:|---|
| `KEEP` | 30 | 0.005 | source, canonical data, operational fixtures |
| `REVIEW` | 718 | 0.289 | requires an explicit dependency before removal |
| `ARCHIVE` | 3159 | 13.697 | large generated data/model history moved outside active project |

## Active-runtime conclusion

The current `nextfarm_device.api.analytics_app` returns `NOT_VALIDATED` and an empty prediction list. It does not load the legacy shared/device joblib registries for farmer answers.

The legacy ten-model artifacts are therefore archival evidence, not production capabilities. The active product surface is deterministic data retrieval, temporal parsing, rule checks and authorization.

The complete machine-readable inventory is `docs/evidence/PROJECT_AUDIT.json`.
