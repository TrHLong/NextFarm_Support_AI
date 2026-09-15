# Research basis for the V10 AI Encyclopedia

Catalog V10 là danh sách **capability nghiên cứu/triển khai**, không phải tuyên bố rằng mọi capability đã có trained model.

## 1. Irrigation and crop-water models

FAO-56 cung cấp nền tảng Penman–Monteith cho reference evapotranspiration (ETo) và crop coefficient để chuyển ETo thành crop evapotranspiration/water requirement. Vì các phép tính này cần dữ liệu khí tượng phù hợp, V10 đánh capability BLOCKED khi thiếu input thay vì tạo ETo giả.

Sources:
- https://www.fao.org/4/X0490E/x0490e00.htm
- https://www.fao.org/4/X0490E/x0490e0b.htm

Capabilities: `eto_fao56`, `crop_water_requirement`, `water_stress_risk`, `irrigation_efficiency`.

## 2. Remote sensing / satellite crop-health models

NASA Harmonized Landsat Sentinel-2 vegetation-index products support indices such as NDVI/EVI and moisture-related indices such as NDMI/NDWI. V10 therefore catalogs vegetation health, water stress and canopy/biomass capabilities, but leaves them BLOCKED until farm geometry + imagery/time series are actually connected.

Sources:
- https://science.nasa.gov/mission/landsat/hls-vegetation-indices/
- https://www.earthdata.nasa.gov/data/catalog/lpcloud-hlsl30-002

Capabilities: `ndvi_health`, `ndmi_water_stress`, `canopy_biomass`.

## 3. Yield, growth and phenology

Precision-agriculture literature repeatedly evaluates ML/ensemble/deep-learning approaches using weather, soil, management and remote-sensing features for crop yield and growth-related prediction. V10 catalogs these as separate capabilities because their labels and horizon differ from sensor anomaly detection.

Representative research:
- https://doi.org/10.1016/j.atech.2024.100718

Capabilities: `yield_forecast`, `growth_stage_detection`, `harvest_date_forecast`, `crop_environment_fit`.

## 4. Disease, pest, weed and quality computer vision

Modern smart-farm research uses CNN/transformer/YOLO-family vision models for plant disease, pest/weed detection, fruit maturity and quality grading. These cannot be trained honestly from V10 numeric IoT data, so the Encyclopedia records them while the runtime status remains BLOCKED until a labeled image dataset/camera pipeline exists.

Capabilities: `disease_vision`, `pest_vision`, `weed_vision`, `ripeness_vision`, `fruit_quality_grading`.

## 5. Core IoT/time-series models

V10 retains the ten V9 ML families for moisture/temperature/EC/pH forecast, anomaly, flow/irrigation faults/need and health scores. The V2.1 trainer performs temporal train/validation/test and Leave-One-Farm-Out quality gates. Models that fail cross-farm or class-coverage gates remain EXPERIMENTAL even when test metrics look high.

## 6. Governance rule

The Encyclopedia has three states:

- `READY`: implementation exists, required data exists and quality/domain gate is passed.
- `EXPERIMENTAL`: implementation/model exists but field/crop validation is insufficient.
- `BLOCKED`: required data, artifact or validated method is missing.

This state machine is intentional: “knowing that an AI method exists” is not the same as claiming NextFarm already has a reliable production model for that crop.
