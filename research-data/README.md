# V9 Research Reference Data

V9 uses public static datasets only as a **reference/calibration layer**. They are downloaded on the target machine during first startup and stored under `reference/raw/` with metadata/checksums.

Generated operational rows are always labeled:

```text
simulated_device_calibrated_v9
```

Static reference rows are never inserted into `farm_db.sensor_readings` and are never presented as measurements from NextFarm hardware.

The simulator uses locked empirical quantiles, step sizes/correlations and farm-specific agronomic state dynamics. AI first learns a locked reference-derived bootstrap set, then retrains only after enough new V9 runtime telemetry has accumulated.
