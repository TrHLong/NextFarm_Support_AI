# Cấu trúc thư mục và đường dẫn dẫn chứng v10.1

Tài liệu này là bản đồ chính thức của dự án `NextFarm-AI-Support-v10.1`. Khi trình bày, bắt đầu từ `model-artifacts/reports/LATEST_TRAINING_REPORT.md`, sau đó mở các CSV/JSON được báo cáo đó trỏ tới.

## 1. Thư mục gốc

| Đường dẫn | Chứa gì | Dẫn chứng cần dùng |
|---|---|---|
| `docker-compose.yml` | Cấu hình chạy toàn bộ dịch vụ, ngưỡng tự động train và volume model | `AI_PER_CUSTOMER_TRAINING=false`, `AI_SHARED_*`, cổng AI `18600`, web `18080` |
| `.env` | Giá trị môi trường của máy đang chạy | Không chụp/đưa mật khẩu hoặc service key vào báo cáo |
| `README.md` | Điểm bắt đầu và lệnh chạy dự án | Dùng để kiểm tra lệnh Docker |
| `HUONG-DAN-TEST-V10.md` | Các bài test chức năng v10 | Dùng cho phần nghiệm thu chức năng chung |
| `docs/` | Tài liệu giải thích, hướng dẫn test và bằng chứng tóm tắt | Mở hai tài liệu `CAU-TRUC...` và `HUONG-DAN-ML...` |
| `services/` | Mã nguồn 11 dịch vụ backend | Mỗi service có `Dockerfile`, `requirements.txt`, `app/` và có thể có `tests/` |
| `apps/` | Mã giao diện người dùng | Được nginx phục vụ tại `http://127.0.0.1:18080/` |
| `infra/database/` | Schema, seed và migration PostgreSQL | Migration mới nhất là `07_v10_1_customer_ml_evidence.sql` |
| `scripts/` | Script vận hành, kiểm tra và tái lập train | Hai script ML quan trọng ở mục 5 |
| `data/operational/` | Bộ Parquet vận hành đóng gói cùng dự án | Không phải CSV snapshot dùng trong phiên train mới nhất |
| `research-data/` | Dữ liệu nghiên cứu/tham chiếu và khóa provenance | Chỉ dùng khi báo cáo nguồn tham chiếu; pipeline runtime hiện dùng CSV theo khách hàng |
| `model-artifacts/` | Dữ liệu ML đã khóa, candidate model, biểu đồ và báo cáo train | Đây là thư mục bằng chứng ML chính |

## 2. Dữ liệu ML theo khách hàng

```text
model-artifacts/data/
├── training_policy.json
├── customers/
│   ├── customer_lan/
│   │   ├── CURRENT_SNAPSHOT.txt
│   │   ├── snapshots/runtime_.../snapshot_manifest.json
│   │   ├── snapshots/runtime_.../raw/*.csv
│   │   ├── datasets/*.parquet + *.json
│   │   └── processed/<dataset_version>/*.csv
│   ├── customer_long/...
│   └── customer_minh/...
└── shared/processed/<shared_dataset_version>/
    ├── 00_dataset_summary.csv
    ├── 01_processed_features_targets.csv
    ├── 02_train.csv
    ├── 03_validation.csv
    ├── 04_test.csv
    ├── 05_feature_catalog.csv
    ├── 06_target_catalog.csv
    ├── 07_model_metrics.csv
    ├── 08_candidate_validation.csv
    ├── 09_generalization_holdout.csv
    ├── 10_class_distribution.csv
    ├── 11_regression_target_summary.csv
    ├── 12_feature_importance.csv
    ├── 13_model_inventory.csv
    ├── 14_data_provenance.csv
    ├── predictions/<model_name>.csv
    └── evidence_manifest.json
```

Ý nghĩa các tầng:

1. `snapshots/.../raw/*.csv` là dữ liệu gốc đã tải từ PostgreSQL trong một transaction nhất quán. Mỗi dòng có `customer_id`.
2. `snapshot_manifest.json` ghi bảng nguồn, số dòng, SHA-256 và thời điểm khóa snapshot. Có thể dùng nó để chứng minh CSV không bị thay sau train.
3. `datasets/*.parquet` là dataset đã tạo feature/target và khóa theo `dataset_version`.
4. `processed/.../*.csv` là bằng chứng dễ mở bằng Excel. Bốn tệp `01` đến `04` cho thấy toàn bộ dữ liệu và ba phần train/validation/test.
5. `shared/processed/...` là bằng chứng của đúng phiên train 10 model nền; đây là nơi lấy số liệu cuối cùng.

Không dùng `customer_id`, `farm_id`, `farm_name`, `zone_id` hoặc `zone_code` làm feature định danh. Chúng được giữ để truy vết, phân quyền, tính metric theo nhóm và kiểm định leave-one-customer-out.

## 3. Model và kết quả train

```text
model-artifacts/
├── reports/
│   ├── LATEST_TRAINING_REPORT.md
│   └── <dataset_version>/TRAINING_REPORT.md
└── shared/
    ├── latest_training_report.json
    ├── active_models.json
    └── candidates/<dataset_version>/
        ├── suite_report.json
        └── shared/
            ├── training_dataset.parquet
            ├── suite_summary.png
            └── <model_name>/v2.1.0/
                ├── model.joblib
                ├── report.json
                ├── evaluation.png
                ├── feature_importance.png
                └── per_farm_evaluation.png
```

Ba tệp phải phân biệt rõ:

| Tệp | Mục đích |
|---|---|
| `reports/LATEST_TRAINING_REPORT.md` | Báo cáo cho người đọc: CSV nào được dùng, xử lý gì, chia dữ liệu ra sao, từng metric có ý nghĩa gì và kết luận đạt/chưa đạt |
| `shared/latest_training_report.json` | Cùng kết quả ở dạng máy đọc; API `/ml/status` và `/ml/reports` dùng tệp này |
| `shared/active_models.json` | Danh sách model được phép suy luận. Candidate không qua quality gate không xuất hiện trong `models` |

`model.joblib` trong `candidates` chứng minh quá trình đã xuất model, nhưng không đồng nghĩa model được phép sử dụng. Phải đối chiếu `deployment_status` và `active_models.json`.

## 4. Mã nguồn tạo ra bằng chứng

| Tệp mã nguồn | Trách nhiệm |
|---|---|
| `services/ai-analytics-service/app/runtime_export.py` | Xuất snapshot CSV riêng theo `customer_id`, tạo SHA-256 manifest |
| `services/ai-analytics-service/app/dataset_builder.py` | Làm sạch theo thời gian, forward-fill giới hạn, tạo 44 feature và 10 target, xuất dataset khóa |
| `services/ai-analytics-service/app/ml_pipeline.py` | Chia train/validation/test, chọn thuật toán, tính metric, LOCO, biểu đồ và `model.joblib` |
| `services/ai-analytics-service/app/customer_ml_automation.py` | Kiểm tra ngưỡng từng nhóm dữ liệu, gộp các CSV khách hàng đủ điều kiện, publish candidate, quality gate, active manifest và báo cáo Markdown |
| `services/ai-analytics-service/app/main.py` | Scheduler tự động, API báo cáo, nạp active model và áp dụng calibration theo vườn |
| `services/chatbot-service/app/main.py` | Grounding, phân quyền dữ liệu vườn và chặn dự báo định lượng không có model/dữ liệu phù hợp |

## 5. Script quan trọng

| Script | Khi nào dùng |
|---|---|
| `scripts/train_shared_from_customer_csv.py` | Tái lập một phiên train từ các CSV đã có mà không cần tải lại DB; dùng cho kiểm tra/báo cáo |
| `scripts/cleanup_generated_artifacts.py` | Dọn cache/artifact cũ bằng danh sách cố định, kiểm tra đường dẫn và ghi báo cáo xóa |

Hai bằng chứng dọn dẹp:

- `docs/evidence/cleanup-pretrain-latest.json`
- `docs/evidence/cleanup-posttrain-latest.json`

## 6. Dịch vụ

| Thư mục | Chức năng chính |
|---|---|
| `identity-service` | Đăng nhập, token, người dùng và quyền |
| `farm-data-service` | Vườn, khu, cảm biến, thiết bị, lịch tưới và dữ liệu vận hành |
| `telemetry-ingestion-service` | Nhận telemetry/MQTT và chống trùng |
| `data-simulator-service` | Sinh dữ liệu thiết bị mô phỏng đã hiệu chỉnh |
| `ai-analytics-service` | Dataset, train, model registry, inference và metric |
| `knowledge-service` | Kho tri thức có nguồn và truy hồi tài liệu |
| `truth-guard-service` | Kiểm tra căn cứ, mức tin cậy và yêu cầu con người |
| `crop-router-service` | Điều phối câu hỏi theo cây trồng/ngữ cảnh |
| `llm-gateway-service` | Cổng LLM có kiểm soát |
| `chatbot-service` | Luồng chat, grounding, feedback và từ chối khi thiếu căn cứ |
| `ticket-service` | Chuyển chuyên gia/ticket khi AI không nên tự xử lý |

## 7. Trạng thái phiên train hiện tại

- Dataset: `nextfarm-v10.1-shared-customers-20260908T083303Z-cbd0f593ec9b`.
- Nguồn: 287 dòng của `customer_lan`, 574 dòng của `customer_long`, 40 dòng của `customer_minh`; tổng 901 dòng.
- Split theo mốc thời gian: train 684, validation 147, test 70. Tỷ lệ theo số dòng không đúng tuyệt đối 70/15/15 vì ranh giới được tính theo timestamp duy nhất và số khách hàng có dữ liệu tại mỗi timestamp khác nhau.
- Đã tạo 10 candidate `model.joblib`.
- 0/10 candidate qua toàn bộ quality gate, nên `active_models.json` có 0 model. Hệ thống phải chờ dữ liệu đa dạng hơn và không được công bố độ chính xác đạt chuẩn.
- `production_ready=false` vì dữ liệu hiện nay là mô phỏng đã hiệu chỉnh và nhãn phân loại là weak label.

Kết quả 0/10 là một kết luận kiểm định có giá trị: test thông thường có thể rất đẹp, ví dụ dự báo nhiệt độ R² = 0,97723 và EC R² = 0,97151, nhưng R² thấp nhất khi bỏ hẳn một khách hàng lần lượt là -2,288 và -324,734. Điều đó cho thấy model đang học đặc điểm của các khách đã thấy và chưa tổng quát tốt sang khách mới.
