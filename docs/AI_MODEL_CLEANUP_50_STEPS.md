# NextFarm AI cleanup and redesign — 50-step execution log

This file is the execution checklist for the 28/09/2026 cleanup. It separates
production logic, query/rule logic and experimental ML. A checked item means
the source, data or documentation change is present in this project.

1. [x] Scan source, services, scripts, data and artifacts.
2. [x] Hash artifact files before cleanup.
3. [x] Write `PROJECT_AUDIT.md` and `docs/evidence/PROJECT_AUDIT.json`.
4. [x] Confirm the active backend is `nextfarm_device.api`.
5. [x] Confirm farmer forecast endpoint is fail-closed with `NOT_VALIDATED`.
6. [x] Confirm legacy joblib registries are not loaded for farmer chat.
7. [x] Preserve one rollback archive outside the project.
8. [x] Move the duplicated 7 GB backup outside the project.
9. [x] Move customer snapshot history outside the project.
10. [x] Move shared 10-model benchmark artifacts outside the project.
11. [x] Move device-v11 model runs outside the project.
12. [x] Move benchmark and historical training outputs outside the project.
13. [x] Move generated reports outside the project.
14. [x] Move old shared model summary outside the project.
15. [x] Keep canonical reset data.
16. [x] Keep operational query data.
17. [x] Keep source, tests, schemas and migrations.
18. [x] Keep training code for reproducibility.
19. [x] Disable automatic model training by default.
20. [x] Make technician training an explicit operation.
21. [x] Keep deterministic sensor queries.
22. [x] Keep deterministic irrigation aggregation.
23. [x] Keep fertilizer total and channel aggregation.
24. [x] Keep deterministic valve/pump state rules.
25. [x] Keep stale/missing/quality semantics.
26. [x] Keep server-side farmer/device authorization.
27. [x] Keep Vietnamese temporal normalization.
28. [x] Keep list versus aggregate response semantics.
29. [x] Keep no-data and not-configured states distinct.
30. [x] Keep current sensor values separate from forecast values.
31. [x] Keep moisture forecast as blocked/experimental research.
32. [x] Keep early flow-failure forecast as blocked/experimental research.
33. [x] Keep sensor anomaly rule baseline.
34. [x] Remove temperature forecast from active farmer runtime.
35. [x] Remove EC forecast from active farmer runtime.
36. [x] Remove pH forecast from active farmer runtime.
37. [x] Remove leak classifier from active farmer runtime.
38. [x] Remove irrigation-need classifier from active farmer runtime.
39. [x] Remove device-health classifier from active farmer runtime.
40. [x] Remove farm-health classifier from active farmer runtime.
41. [x] Remove power-loss forecast from active farmer runtime.
42. [x] Remove MQTT-loss forecast from active farmer runtime.
43. [x] Keep legacy model names only for backward-compatible reports.
44. [x] Add an explicit active model allow-list.
45. [x] Mark synthetic data as pipeline/evaluation only.
46. [x] Document model limitations and blocked reasons.
47. [x] Record every archive move in `AI_CLEANUP_MOVE.json`.
48. [x] Keep cleanup reproducible with `scripts/cleanup_ai_models.py`.
49. [ ] Validate Docker build and endpoint smoke tests after the user starts Docker.
50. [ ] Promote a model only after real-data, farm-held-out evaluation passes.

## Active model allow-list

The allow-list is intentionally small:

- `moisture_forecast`
- `flow_fault_forecast`
- `sensor_fault_forecast`

The list means “eligible for a future evidence run”, not “production-ready”.
Current farmer answers are data queries and rules. No model is promoted by this
cleanup.

## Archive

Generated artifacts were moved to:

`D:\2026-2027\THUCTAP\NextFarm-AI-Support-v10.1_ARCHIVE_20260928`

The archive is outside the project directory and is not mounted by Docker.
