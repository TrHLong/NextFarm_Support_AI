# NextFarm AI Support v10.2

- Added production-safe data ingestion/audit/cleaning/readiness pipeline.
- Synthetic/simulation/demo data are forbidden from production model training.
- Added multi-horizon soil-moisture feature/target preparation for 1h/3h/6h/12h.
- Added horizon-purged chronological 70/15/15 split and train-only preprocessing.
- Added baseline comparison and acceptance gate.
- Added automatic Vietnamese `REPORT.docx` with charts and explanations per run.
- Added readiness statuses for all five farmer-facing AI groups; unsupported models remain NOT_READY instead of being trained on fabricated labels.
- Preserved legacy simulation benchmark code for QA/research only.
