# Current Data Readiness - v10.2

Kiểm tra trên `data/canonical_reset` bằng pipeline production-safe mới:

- Dataset manifest: `PIPELINE_TEST_ONLY`.
- Sau chuẩn hóa wide → long: 15,552 sensor metric rows.
- `real_device/field_device/verified_import`: 0 rows.
- Non-production rows: 15,552.
- Timestamp validity: 100%.
- Duplicate fraction: 0%.
- Invalid physical fraction: 0%.
- Irrigation events: 18, thấp hơn readiness target 100.
- Irrigation events có soil moisture before/after chuẩn hóa: 0, thấp hơn target 80.
- Soil Moisture Forecast production readiness: **FAIL** vì không có telemetry thật và lịch sử thật đủ dài.
- Nutrient Recommendation: **NOT_READY** vì thiếu expert/outcome labels.
- Leak/Valve: **RULE_READY_ML_NOT_READY**.
- Smart Irrigation Scheduling: **NOT_READY** với dữ liệu hiện tại.
- Predictive Maintenance: **NOT_READY** vì thiếu failure episodes thật.

Kết luận: dữ liệu hiện tại phù hợp cho pipeline/demo QA, không phù hợp để tuyên bố model production đã được train/validated. v10.2 cố ý chặn việc tạo production model từ tập này.
