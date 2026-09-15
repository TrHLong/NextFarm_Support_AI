# Hướng dẫn kiểm tra dữ liệu, train 10 model và ghi báo cáo

## 1. Kiến trúc cần trình bày trước

Dữ liệu tách riêng theo khách hàng, nhưng model nền không tách thành một bộ 10 model cho mỗi khách hàng.

```text
PostgreSQL
  -> snapshot CSV riêng customer_lan/customer_long/customer_minh/...
  -> làm sạch + feature/target riêng, giữ customer_id để truy vết
  -> gộp các tập đủ điều kiện, cân bằng số dòng theo khách hàng
  -> chia thời gian 70/15/15
  -> train đúng 10 model nền dùng chung
  -> leave-one-customer-out
  -> quality gate -> active_models.json
  -> suy luận + calibration nhỏ theo vườn
```

Nếu có 500 khách hàng, hệ thống có 500 vùng snapshot/watermark tách biệt, đúng 10 model nền và các bản ghi calibration nhỏ `bias/scale` theo vườn. Chỉ tạo model riêng trong trường hợp ngoại lệ, sau khi đủ dữ liệu thật và A/B test chứng minh model riêng tốt hơn rõ ràng.

Không tạo mặc định 5.000 model. Cách đó tốn CPU/RAM/dung lượng, nhiều khách không đủ nhãn, khó giám sát và dễ cho ra model “đẹp giả” do dữ liệu ít.

## 2. Khởi động đúng bản mã mới

```powershell
cd D:\2026-2027\THUCTAP\NextFarm-AI-Support-v10.1
docker compose up -d --build ai-analytics-service chatbot-service
docker compose up -d
docker compose ps
```

Mở `http://127.0.0.1:18080/`, rồi kiểm tra API:

```powershell
Invoke-RestMethod http://127.0.0.1:18600/health
Invoke-RestMethod http://127.0.0.1:18600/ml/status | ConvertTo-Json -Depth 10
Invoke-RestMethod http://127.0.0.1:18600/ml/reports | ConvertTo-Json -Depth 10
```

Sau khi rebuild, service mới tự xóa layout `model-artifacts/shared/<model_name>` cũ khi đã có candidate mới. Layout chuẩn chỉ còn `shared/candidates`, `latest_training_report.json` và `active_models.json`.

## 3. Kiểm tra CSV riêng từng khách hàng

Mở `model-artifacts\data\customers\<customer_id>\snapshots\<snapshot_id>\` và kiểm tra:

1. `snapshot_manifest.json`: `customer_id`, thời điểm khóa DB, tên CSV, số dòng và SHA-256.
2. `raw/customer.csv`: chỉ có khách hàng tương ứng.
3. `raw/farms.csv`: mọi dòng có cùng `customer_id`.
4. `raw/sensor_readings.csv`: cảm biến, vườn, khu, thời gian và provenance.
5. `raw/device_status.csv`: trạng thái online/running.
6. `raw/telemetry_ingest_events.csv`: trạng thái gói telemetry.
7. `raw/irrigation_runs.csv`: lịch sử ca tưới.
8. `raw/alerts.csv`, `raw/control_commands.csv`: sự cố/lệnh, có thể ít hoặc bằng 0.

Snapshot thay đổi sau mỗi lần retrain tự động. Không chép một bảng số đếm cũ vào báo cáo mới. Hãy lấy `dataset_version`, `trained_at`, danh sách `customer_sources` và đường dẫn CSV từ `model-artifacts\shared\latest_training_report.json`, rồi khóa báo cáo theo đúng `dataset_version` đó. Báo cáo Word đã tạo thực hiện cách khóa này tại `docs\BAO-CAO-THUC-NGHIEM-10-MODEL-VA-32-NANG-LUC.docx`.

Số đếm trực tiếp từ DB là số tích lũy dùng để so ngưỡng scheduler và có thể tăng khi simulator chạy. Số `raw_reading_count` trong báo cáo dataset là dữ liệu thuộc cửa sổ train; `row_count` là số mẫu hoàn chỉnh sau khi ghép thời gian, tạo feature/target và loại dòng thiếu.

## 4. Ngưỡng tự động xét retrain

| Nhóm dữ liệu | Tối thiểu lần đầu | Dòng mới để xét retrain |
|---|---:|---:|
| `sensor_readings` | 20.000 | 5.000 |
| `device_status` | 5.000 | 2.000 |
| `telemetry_ingest_events` | 2.000 | 1.000 |
| `irrigation_runs` | 3 | 2 |
| `alerts` | không bắt buộc | 5 |
| `control_commands` | không bắt buộc | 5 |

Sau xử lý, mỗi khách cần tối thiểu 40 mẫu để tham gia pool hiện tại; pool cần ít nhất 3 khách hàng để chạy leave-one-customer-out. Mỗi khách được lấy tối đa 5.000 mẫu mới nhất trong một phiên để khách hàng lớn không lấn át khách nhỏ.

Scheduler kiểm tra hai phút một lần. Sau train thành công, `knowledge_db.customer_ml_watermarks` ghi số dòng từng nhóm đã sử dụng. Lần sau chỉ khi một nhóm đạt delta thì hệ thống mới tạo snapshot và train lại bộ dùng chung.

## 5. Kiểm tra làm sạch và chống nhìn thấy tương lai

Mở `services/ai-analytics-service/app/dataset_builder.py` và đối chiếu:

1. Dữ liệu được bucket theo 15 phút.
2. Nhóm xử lý là `customer_id + farm_id + zone_id`.
3. Chỉ dùng `ffill(limit=2)` cho cảm biến thiếu.
4. Không dùng `bfill`; dữ liệu tương lai không lấp ngược về quá khứ.
5. Target 30 phút dùng `shift(-horizon_steps)` rồi loại dòng không có tương lai thật.
6. Sau khi tạo target mới chia theo timestamp; không random split.

Mở thư mục bằng chứng:

```text
model-artifacts\data\shared\processed\nextfarm-v10.1-shared-customers-20260908T083303Z-cbd0f593ec9b\
```

- `01_processed_features_targets.csv`: 901 dòng, có `customer_id` để truy vết.
- `02_train.csv`: 684 dòng.
- `03_validation.csv`: 147 dòng.
- `04_test.csv`: 70 dòng.
- timestamp lớn nhất train phải nhỏ hơn timestamp nhỏ nhất validation;
- timestamp lớn nhất validation phải nhỏ hơn timestamp nhỏ nhất test.

Tỷ lệ số dòng không đúng tuyệt đối 70/15/15 vì code chia trên timestamp duy nhất. Tại một timestamp có thể có một hoặc nhiều khách hàng/khu. Cách này giữ mọi dòng cùng thời điểm trong cùng một split.

## 6. 44 feature và 10 target

Danh sách đầy đủ nằm trong `05_feature_catalog.csv` và `06_target_catalog.csv`.

Feature gồm cảm biến hiện tại; delta và rolling từ quá khứ; cờ missing; trạng thái thiết bị/van/bơm; packet loss; lịch sử tưới; thời gian; cây trồng, kiểu canh tác, khí hậu, đất và ngưỡng mục tiêu.

| Model | Bài toán | Target |
|---|---|---|
| `moisture_forecast` | hồi quy | độ ẩm đất sau 30 phút |
| `temperature_forecast` | hồi quy | nhiệt độ sau 30 phút |
| `ec_forecast` | hồi quy | EC sau 30 phút |
| `ph_forecast` | hồi quy | pH sau 30 phút |
| `anomaly_multisensor` | phân loại | bất thường đa cảm biến |
| `flow_fault` | phân loại 3 lớp | bình thường/mất dòng/rò rỉ |
| `irrigation_failure` | phân loại | nguy cơ ca tưới thất bại |
| `irrigation_need` | phân loại | có cần tưới không |
| `device_health` | phân loại 3 mức | sức khỏe thiết bị |
| `farm_health` | phân loại 3 mức | sức khỏe tổng hợp vườn |

Các nhãn phân loại là weak label từ quy tắc quan sát được. Chúng kiểm tra pipeline nhưng chưa thay nhãn sự cố thật do kỹ sư/người dùng xác nhận.

## 7. Quá trình train và chỉ số

Mỗi model có Random Forest và Extra Trees. Hồi quy chọn candidate bằng R² validation; phân loại chọn bằng F1-macro validation. Sau đó fit lại trên train + validation và đánh giá một lần trên test.

- MAE: sai số tuyệt đối trung bình, cùng đơn vị target.
- RMSE: phạt mạnh lỗi lớn.
- R²: khả năng giải thích biến thiên; âm là kém hơn dự báo trung bình.
- Accuracy: tổng tỷ lệ đúng, dễ đẹp giả khi một lớp chiếm đa số.
- F1-macro/Recall-macro: tính đều cho từng lớp.
- Recall lớp rủi ro: phần sự cố thật được phát hiện.
- Confusion matrix: lớp nào bị nhầm thành lớp nào.

Leave-one-customer-out lần lượt bỏ toàn bộ Lan, Long rồi Minh khỏi train để test khả năng sang khách chưa thấy. `customer_id` là khóa holdout, không nằm trong 44 feature.

## 8. Đọc kết quả hiện tại

Mở theo thứ tự:

```text
model-artifacts\reports\LATEST_TRAINING_REPORT.md
docs\evidence\shared-ml-latest.json
model-artifacts\shared\latest_training_report.json
model-artifacts\shared\active_models.json
model-artifacts\data\shared\processed\...\07_model_metrics.csv
model-artifacts\data\shared\processed\...\09_generalization_holdout.csv
model-artifacts\data\shared\processed\...\10_class_distribution.csv
```

Kết quả: 901 mẫu; train 684, validation 147, test 70; tạo đủ 10 candidate; 0/10 qua toàn bộ quality gate; 0 model active; `production_ready=false`.

Ví dụ để trình bày:

- `temperature_forecast`: test R² 0,97723 nhưng LOCO R² thấp nhất -2,288, nên chưa tổng quát sang khách mới.
- `ec_forecast`: test R² 0,97151 nhưng LOCO thấp nhất -324,734, cho thấy phân phối EC giữa khách khác mạnh hoặc một khách gần như không có phương sai.
- `irrigation_need`: accuracy 0,97143, F1-macro 0,92944 nhưng LOCO F1 thấp nhất 0,370 và một khách thiếu lớp cần tưới.
- `flow_fault`: accuracy 0,95714 nhưng recall lớp mất dòng bằng 0 trên test; model bỏ sót sự cố nên gate chặn.

Không báo cáo “model chính xác 97%” chỉ từ accuracy/R² đẹp. Kết luận đúng: pipeline hoạt động, dữ liệu hiện tại chưa chứng minh 10 model đủ tin cậy để triển khai.

## 9. Cách cải thiện lần train sau

1. Chạy simulator/thiết bị lâu hơn để mỗi khách có nhiều timestamp và khu.
2. Bảo đảm từng khách có đủ lớp mất dòng, rò rỉ, tưới thất bại, thiết bị tốt/cảnh báo/lỗi.
3. Giảm weak label bằng phản hồi đã duyệt của kỹ sư/người vận hành.
4. Thêm khách/vườn có cây, đất, khí hậu và ngưỡng EC/pH khác nhau.
5. Xem `10_class_distribution.csv` và `11_regression_target_summary.csv` trước train.
6. Không hạ quality gate chỉ để có số đẹp.

## 10. Chat có tự quay về model để học không?

Không. Tin nhắn chat không được đưa trực tiếp vào 10 model cảm biến.

Luồng trả lời: xác thực quyền vườn; lấy dữ liệu/tri thức có nguồn; câu hỏi định lượng chỉ dùng active model phù hợp; thiếu model/dữ liệu thì nói chưa đủ căn cứ hoặc chuyển chuyên gia. Feedback chat vào hàng đợi duyệt; chỉ dữ liệu đã duyệt và đúng schema mới có thể tham gia phiên train sau.

Vì `active_models.json` đang rỗng, chatbot không được bịa năng suất, doanh thu, ngày thu hoạch hay con số dự báo từ candidate experimental. Nó vẫn có thể trả lời số đo trực tiếp có timestamp/nguồn và hướng dẫn nông học có tài liệu.

## 11. Mẫu ghi báo cáo cho từng model

```text
Tên model và target:
CSV nguồn theo customer_id:
Số dòng raw và sau xử lý:
Feature và cách tạo target/nhãn:
Ranh giới train-validation-test:
Hai thuật toán candidate:
Chỉ số validation dùng để chọn:
Kết quả test:
Kết quả leave-one-customer-out:
Quality gate đạt/chưa đạt và lý do:
Đường dẫn model.joblib:
Có trong active_models.json hay không:
Giới hạn dữ liệu và việc cần bổ sung:
```

## 12. Kiểm tra sau rebuild

```powershell
cd D:\2026-2027\THUCTAP\NextFarm-AI-Support-v10.1
docker compose up -d --build ai-analytics-service chatbot-service
docker compose ps
Invoke-RestMethod http://127.0.0.1:18600/ml/status | ConvertTo-Json -Depth 10
Get-Content .\model-artifacts\reports\LATEST_TRAINING_REPORT.md
Get-Content .\model-artifacts\shared\active_models.json
```

Kỳ vọng: `architecture=shared_base_models_with_customer_calibration`; `dataset_source=v10_per_customer_csv_pool`; `generalization_test=leave_one_customer_out`; có 10 candidate và 0 active ở dữ liệu hiện tại; chatbot từ chối dự báo định lượng khi thiếu active model; `model-artifacts/customers` không được tạo lại.
