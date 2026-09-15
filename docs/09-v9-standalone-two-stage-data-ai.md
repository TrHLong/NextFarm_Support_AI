# V9 standalone – two-stage data and AI

1. Mandatory static references (Figshare CC0 + AgriDataValue CC BY 4.0 + NASA POWER Hourly for farm-local climate baselines) are downloaded, normalized and SHA-256 locked before Docker services that consume them are built; CC BY Mendeley sources are optional supplements.
2. Static rows are reference/calibration material, not operational NextFarm telemetry.
3. A model-ready bootstrap set is derived from locked empirical distributions/temporal statistics and farm profiles.
4. AI trains 10 shared models in `bootstrap_reference` phase.
5. Only after bootstrap, the stateful simulator publishes `simulated_device_calibrated_v9` MQTT telemetry.
6. Runtime DB datasets filter strictly on that provenance.
7. At 50k runtime readings, AI retrains from V9 runtime telemetry with a bounded 25% reference anchor.
8. Simulator/reference-only V9 never declares itself production-ready.
