# Research-data attribution and provenance — V10

V10 keeps the V9 public/reference calibration lineage. Raw external downloads are **not bundled** in the distributable ZIP; the normalized/locked reference files needed for the PoC are bundled so the first Docker run is reproducible.

## Mandatory empirical references used by the bundled lock

### Figshare — Datasets from IoT devices
- Record: `28667981`
- Repository license: CC0
- Role: high-frequency temperature, relative-humidity, light, pH and EC distribution/step/correlation calibration.

### KarLy soil-moisture reference
- DOI/record: `10.5281/zenodo.1227837`
- Repository: Zenodo
- Repository license: CC BY 4.0
- Role: soil-moisture anchor used by the current locked reference pack.

### NASA POWER
- Service: NASA POWER Hourly Point API
- Role: meteorological baseline for demo-farm coordinates.
- NASA rows remain climate reference data and are never relabeled as NextFarm sensor measurements.

## Optional supplemental references

### AgriDataValue — IoT Environmental Data
- Record/DOI: `10.5281/zenodo.18954708`
- Repository: Zenodo
- Repository license: CC BY 4.0
- Role: optional large environmental/soil-moisture reference.
- It is **not mandatory** for the bundled V10 first run. `NEXTFARM_DOWNLOAD_LARGE_REFERENCE=1` may be used by the preparation script when a fresh large download is desired.

### Parma tomato IoT — irrigation regimes
- DOI: `10.17632/35wh56287y.2`
- Repository: Mendeley Data
- License: CC BY 4.0
- Optional; API retrieval may require a Mendeley token.

### Parma evolving tomato testbed — 2023–2025
- DOI: `10.17632/h8sfcf9487.1`
- Repository: Mendeley Data
- License: CC BY 4.0
- Optional; API retrieval may require a Mendeley token.

## Separation rule

Reference rows stay under `research-data/reference/`. They are **not** inserted into `farm_db.sensor_readings` as if they were NextFarm telemetry.

Runtime simulator rows remain explicitly labeled:

```text
data_origin = simulated_device_calibrated_v9
```

The `v9` suffix is retained intentionally as a provenance identifier for the simulator lineage. V10 must not rename these rows to `nextfarm_api` or `nextfarm_mqtt` unless they actually came through an authenticated NextFarm connector.

The packaged ML suite is therefore a PoC/reference-trained suite. `production_ready=false` remains the correct statement until real NextFarm sandbox/field telemetry and confirmed incident labels are used for validation.
