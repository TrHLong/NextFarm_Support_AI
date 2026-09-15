# NextFarm — Bài toán B / dữ liệu thiết bị

> **Bản GitHub gọn:** đọc [GITHUB-PACKAGE.md](GITHUB-PACKAGE.md) để biết dữ liệu/model được giữ, phần raw lưu riêng và lệnh tái train trên máy clone. Báo cáo gốc giữ nguyên; gói này không phải backup toàn bộ 7 GB.

Bản cập nhật 14/09/2026 tập trung chat dữ liệu của tủ được cấp quyền. Chat hiện dùng định tuyến quy tắc, API và mẫu có bằng chứng; không gọi ChatGPT/OpenAI/Gemini. Kỹ thuật viên chỉ duyệt tri thức và xem dữ liệu theo quyền; luồng ticket đã ngừng sử dụng.

## Báo cáo hiện hành

Đọc **[báo cáo nông dân V13 và đầy đủ 130 câu trả lời](docs/farmer-v13/BAO-CAO-NONG-DAN-V13.html)** hoặc [PDF 8 trang](docs/farmer-v13/BAO-CAO-NONG-DAN-V13.pdf). Có bảng nguồn dữ liệu, cải tiến huấn luyện, dung sai đề xuất, so sánh baseline, 25 đáp án đối chiếu và các bước tự kiểm tra. Báo cáo trước ngày 13/09 lưu tại [retraining-20260913](docs/retraining-20260913/BAO-CAO-TRAIN-LAI.html), không thay thế kết quả V13.

- 243/243 kiểm thử code qua, gồm 130 câu mẫu định tuyến/công cụ và 25 đối chiếu số liệu; có 14 cảnh báo hiệu năng DataFrame. Bộ câu dùng để phát triển, không chứng minh hiểu mọi câu hỏi hay độ chính xác thực địa.
- Mã V13 có `chat_contract=farmer_v13` trong health; cần build lại container. Lần kiểm tra 14/09 Docker Engine chưa kết nối được, chưa xác minh web sau build.
- Đã train lại 4 dự báo từ CSV lịch sử bằng cách học mức thay đổi. Tỷ lệ trong dung sai đề xuất trên mọi mẫu có nhãn: 95,59%; tính cả từ chối vì thiếu đầu vào. Tập kiểm tra mô phỏng đã dùng ở lần trước; chưa phải test mù mới. Nhiệt độ và pH chưa thắng baseline MAE trên cùng dòng hợp lệ. Xem `model-artifacts/farmer-v13/latest_report.json`.
- Sáu model sự cố được đối chiếu lại ngưỡng balanced accuracy/F1 macro/recall ≥80% từ benchmark mô phỏng 42 ngày đã train ngày 13/09; 6/6 qua trên bộ đó. Không gọi là kết quả từ CSV 3 khách hoặc kết quả fit mới của lượt V13.
- Chưa có kết quả train/test từ bộ CSV vận hành đủ hợp đồng 72 giờ mới. 0 model được nghiệm thu để phát hành dự báo. Kết quả lịch sử không thay cho điều kiện thu 72 giờ.
- Các chỉ số 10/10 trong `docs/device-v11` và `model-artifacts/device-v11` là thí nghiệm lịch sử, không dùng để nghiệm thu bản này.
- 32 năng lực là truy vấn/kiểm tra, không phải 32 model ML. AVAILABLE chỉ nói nhóm dữ liệu khả dụng.

## Khởi chạy

Mở Docker Desktop, chờ Engine running, rồi chạy trong CMD tại thư mục dự án:

```cmd
scripts\start_v11.cmd
docker compose ps
```

Tên script giữ để tương thích; `start_v10.cmd` chuyển tiếp vào script này. Script kiểm tra Engine, build, nhập tài liệu công ty dạng draft rồi chạy kiểm thử. Web chính http://127.0.0.1:18080; dữ liệu 18081; Knowledge 18082; model 18084. `/api/farm/health` phải có `chat_contract=farmer_v13` mới xác nhận mã chat V13.

## Dữ liệu và huấn luyện tự động

`nextfarm_device/collection_worker.py` chạy trong ML service. Cứ 5 phút kiểm tra hợp đồng thu dữ liệu mới. Mỗi tủ phải đủ ít nhất 72 giờ theo thời gian server nhận, độ phủ sensor và status ít nhất 90%, điểm cuối còn mới. Backfill hoặc lịch sử chưa có nhãn `problem_b_v12` không được tính. Thu mô phỏng theo thời gian thật vẫn là dữ liệu mô phỏng.

Khi đủ điều kiện, worker xuất CSV tối đa mỗi 24 giờ vào `model-artifacts/data/problem-b-runtime/capture-.../`. Làm sạch cố định, tạo đặc trưng quá khứ, chia theo thời gian và giữ riêng khách test; fit các phép biến đổi trên train rồi mới fit model. Thiếu nhãn/lớp/sự cố hoặc chưa đủ mẫu thì BLOCKED.

| Nơi xem | Nội dung |
| --- | --- |
| `model-artifacts/problem-b/collection_state.json` | Số giờ, độ phủ từng tủ, lý do chờ/chặn, snapshot gần nhất; chỉ xuất hiện khi worker chạy |
| `model-artifacts/data/problem-b-runtime/capture-.../manifest.json` | Danh sách CSV, customer_id/device_id, số dòng, SHA256, nguồn và cửa sổ thu |
| Cùng snapshot: `cleaning_report.json`, `raw/`, `cleaned/` | Dòng trước/sau xử lý và nguyên nhân loại/giữ trống |
| `model-artifacts/problem-b/runs/capture-.../training_report.html` | Bảng kết quả train đọc trực tiếp; file chỉ có khi chạy thật với snapshot đủ điều kiện |
| Cùng run: `*_report.json`, `*_test_predictions.csv`, `*_failure_cases.csv`, `features_and_splits.csv`, `training_code/` | Kết quả từng model, đối chiếu từng dự đoán, lỗi, cách chia và mã nguồn tái lập |
| `docs/problem-b/unit-tests.xml`, `verification.json` | Kết quả kiểm thử phần mềm, tách khỏi kết quả model vận hành |

Ba ngày là điều kiện khởi đầu, chưa đủ bảo đảm model tốt trên mọi khách/mùa hoặc dự báo được sự cố đột ngột. Bản này tự động xuất ứng viên thí nghiệm và báo lý do chưa đạt; chưa có phát hành dự báo đã được nghiệm thu thực địa. Chưa triển khai tích hợp Zalo OA thật hoặc load test 500 khách.

## Lần train trên dữ liệu đã có ngày 13/09

| Nơi xem | Nội dung |
| --- | --- |
| `model-artifacts/historical-customer/latest_report.json` | Trỏ tới run hoàn chỉnh từ ba khách: 4 forecast đã fit, 6 classifier chưa có nhãn sự cố độc lập trong nguồn này |
| `model-artifacts/data/historical-customer/` | CSV sạch theo khách, nguồn/hash, thống kê làm sạch, lưới thời gian có chỗ trống, features và split |
| `model-artifacts/benchmark-retrain/latest_report.json` | Trỏ tới run 10 model từ benchmark mô phỏng có nhãn; toàn bộ EXPERIMENTAL |
| `model-artifacts/data/benchmark-retrain/` | Dữ liệu benchmark đã chuẩn hóa; nguồn gốc vẫn là mô phỏng |
| `docs/retraining-20260913/storage_compression.json` | Nén 273 CSV: khoảng 5.45 GiB xuống 1.48 GiB trên đĩa; SHA-256 giữ nguyên |

Tái lập trong Python đã cài `services/ai-analytics-service/requirements.txt`, từ gốc dự án:

```cmd
python -m nextfarm_device.historical_training --project .
python -m nextfarm_device.benchmark_training --project . --source model-artifacts/data/device-v11-validation-b-20260910
```

Mỗi lệnh tạo run mới và lưu mã nguồn cùng kết quả, không sửa registry đang phục vụ. Đây là tái lập thí nghiệm từ CSV có sẵn; pipeline thu vận hành vẫn do worker thực hiện tự động. Nén NTFS giữ nguyên dung lượng logic hiển thị ở mục Size; dung lượng thực giảm ở mục Size on disk.

Dữ liệu của mỗi khách được lưu riêng để truy vết; huấn luyện bộ model dùng chung theo bài toán, không nhân 10 model cho mỗi người dùng. Mã khách/tủ không đi vào đặc trưng.
