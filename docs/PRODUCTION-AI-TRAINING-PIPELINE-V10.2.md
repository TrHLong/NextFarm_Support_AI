# NextFarm Production-safe AI Training Pipeline v10.2

## Mục tiêu
Không train model production bằng dữ liệu giả. Mọi run đi qua: Ingestion → Audit/Cleaning → Feature Engineering → Data Readiness Gate → Temporal Split → Candidate Training → Validation Selection → Locked Test → Model Acceptance → REPORT.docx.

## Nguồn dữ liệu
Production chỉ chấp nhận `data_origin`: `real_device`, `field_device`, `verified_import`. `synthetic`, `simulation`, `pipeline_test`, `demo`, `generated` bị loại khỏi production training.

## Chạy audit dữ liệu hiện có
```bat
python scripts\train_production_safe.py --dataset data\operational --audit-only
```
Nếu dataset không có schema tối thiểu (`customer_id,farm_id,zone_id,device_id,observed_at,metric_type,value,data_origin`) pipeline sẽ dừng và báo lỗi thay vì tự đoán schema.

## Chạy train khi dữ liệu thật đủ readiness
```bat
python scripts\train_production_safe.py --dataset D:\NEXTFARM_REAL_DATA
```
Nếu readiness FAIL, lệnh vẫn tạo báo cáo audit nhưng không tạo model production candidate.

## Output
Mỗi run nằm tại `model-artifacts/production-safe/runs/prod-.../` và có:
- `data_audit.json`
- `data_readiness.json`
- `cleaned_sensor_readings.parquet`
- `moisture_features.parquet`
- `training_report.json`
- `REPORT.docx`
- `charts/`
- model `.joblib` và predictions CSV chỉ khi readiness đủ và training thực sự chạy.

## 5 model sản phẩm
1. Soil Moisture Forecast: trainer production-safe đã có, multi-horizon 1h/3h/6h/12h.
2. Nutrient Recommendation: NOT_READY cho đến khi có expert/outcome labels.
3. Leak/Valve Anomaly: rule-first; ML chỉ train khi có incident ground truth thật.
4. Smart Irrigation Scheduling: forecast + optimization trước RL; readiness phụ thuộc ca tưới thật before/after.
5. Predictive Maintenance: NOT_READY cho đến khi có failure episodes thật và telemetry thiết bị phù hợp.

## Quy tắc chống leakage
- Split theo thời gian 70/15/15, không random row.
- Horizon purge: label của Train/Validation không được vượt biên split.
- Imputer/scaler chỉ fit Train.
- Chọn model bằng Validation.
- Test chỉ đánh giá một lần sau khi chọn model.
