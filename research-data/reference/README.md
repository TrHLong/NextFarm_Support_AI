# NextFarm V9 static reference pack

This directory is created by `scripts\prepare_v9_research_data.cmd` on the first clean V9 start.

The downloader retrieves public research/reference data, normalizes useful sensor columns, locks checksums, derives calibration statistics, and then creates `reference_bootstrap_training.parquet`.

`reference_bootstrap_training.parquet` is **derived from downloaded references**. It is not claimed to be observed NextFarm hardware telemetry.

Runtime telemetry produced later by the simulator is stored separately as `simulated_device_calibrated_v9`.
