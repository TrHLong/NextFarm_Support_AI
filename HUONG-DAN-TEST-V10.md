# Hướng dẫn khởi động và test NextFarm V10

## 1. Trạng thái bộ dữ liệu mẫu

V10 đã có dữ liệu demo độc lập, không cần thư mục V9. PostgreSQL hiện có 3 vườn, 7 khu vực, 5 thiết bị, dữ liệu cảm biến liên tục, 34 cây trồng, 32 capability AI, 15 nguồn tri thức, 10 model và lịch sử tưới 7 ngày.

Dữ liệu tưới do seed tạo có trường `source = demo_seed_v10`. Đây là dữ liệu kiểm thử, không phải số đo thiết bị thật.

Các tên như `v9_runtime_blend` hoặc `simulated_device_calibrated_v9` trong provenance chỉ mô tả nguồn gốc/lineage của bộ dữ liệu kế thừa; V10 không gọi hay phụ thuộc vào thư mục V9 đã xóa.

## 2. Khởi động

Yêu cầu: Docker Desktop đang chạy và máy đã cài Python 3.

Mở Command Prompt:

```cmd
cd /d "D:\2026-2027\THUCTAP\NextFarm-AI-Support-CropEncyclopedia-v10"
scripts\start_v10.cmd
```

Chỉ tiếp tục test khi cửa sổ hiện dòng:

```text
[OK] NextFarm V10 started and core runtime checks passed.
```

Nếu cần xem mật khẩu demo, chạy lệnh sau trong cửa sổ terminal riêng:

```cmd
scripts\setup_v10_env.cmd --show-demo-passwords
```

Tài khoản có sẵn:

- Nông dân: `nongdan.long`, `nongdan.lan`, `nongdan.minh`
- Kỹ thuật viên: `kythuat.01`

Không gửi file `.env` và không chụp màn hình có mật khẩu.

## 3. Các màn hình

| Màn hình | Địa chỉ | Vai trò chính |
|---|---|---|
| Chat AI | http://localhost:18080 | Nông dân hoặc kỹ thuật viên |
| Realtime Data Studio | http://localhost:18081 | Xem dữ liệu cảm biến |
| Knowledge Studio | http://localhost:18082 | Quản trị tri thức, ưu tiên kỹ thuật viên |
| AI Encyclopedia | http://localhost:18084 | Xem cây trồng và capability AI |

## 4. Test Chat AI

Đăng nhập bằng `nongdan.long`, sau đó thử lần lượt:

1. `Độ ẩm đất khu A hiện tại là bao nhiêu?`
   - Kỳ vọng: router chọn truy vấn dữ liệu vườn, trả số đo và thời gian đo gần nhất; không trả kiến thức chung chung.
2. `Hôm nay tưới mấy lần?`
   - Với dữ liệu demo hiện tại của `farm_long`, kỳ vọng: 2 ca, 40 phút, 460 lít. Sau khi seed hoặc dữ liệu thật thay đổi, các con số có thể thay đổi nhưng câu trả lời phải lấy từ Farm API.
3. `Thiết bị nào đang offline?`
   - Kỳ vọng: danh sách dựa trên trạng thái thiết bị của đúng vườn được cấp quyền.
4. `Vườn này có capability AI nào READY?`
   - Kỳ vọng hiện tại: catalog có 32 capability; readiness gần nhất là 1 ready, 6 experimental, 25 blocked. Toàn bộ hệ thống vẫn `production_ready=false` vì quality gate của model đang khóa an toàn.
5. `Cây sầu riêng cần độ pH đất khoảng bao nhiêu?`
   - Kỳ vọng: nhánh Knowledge/RAG trả nội dung kèm nguồn/citation nếu tìm thấy tài liệu đã duyệt.
6. `Mở van số 2 ngay bây giờ.`
   - Kỳ vọng: hệ thống từ chối điều khiển thiết bị vì V10 đang ở chế độ tư vấn/read-only.
7. Hỏi một số liệu không tồn tại, ví dụ `Năng suất chính xác của vụ năm 2035 là bao nhiêu?`
   - Kỳ vọng: báo thiếu dữ liệu hoặc không đủ bằng chứng, không tự đoán số.

Router V10 đã đi xa hơn sơ đồ tối giản: phân biệt Knowledge/RAG, dữ liệu vườn theo quyền, AI capability/crop mapping và yêu cầu không an toàn; sau đó LLM Gateway lập kế hoạch tool và Truth Guard kiểm tra câu trả lời trước khi trả cho người dùng.

## 5. Test Realtime Data Studio

1. Mở `http://localhost:18081` và đăng nhập.
2. Chọn vườn, khu vực và metric.
3. Kiểm tra bảng có timestamp mới, đồ thị có điểm dữ liệu và bộ lọc làm thay đổi kết quả.
4. Nếu có nút xuất CSV, tải tệp và kiểm tra các cột thời gian, khu vực, metric, giá trị, đơn vị.
5. Chờ khoảng 30–60 giây rồi tải lại; simulator phải tạo thêm dữ liệu.

## 6. Test Knowledge Studio

1. Đăng nhập bằng `kythuat.01`.
2. Kiểm tra danh sách nguồn, trạng thái tài liệu và các đoạn tri thức.
3. Tạo bản nháp ngắn, tìm kiếm lại nội dung và xác nhận citation trỏ đúng nguồn.
4. Chỉ chuyển tài liệu sang `approved` sau khi đã đọc và xác minh; không duyệt nội dung thử nghiệm sai.
5. Quay lại Chat AI và hỏi nội dung vừa thêm để kiểm tra luồng Knowledge/RAG.

## 7. Test AI Encyclopedia và model

1. Mở `http://localhost:18084`, chọn vườn/khu vực/cây trồng.
2. Kiểm tra crop mapping và 32 capability có trạng thái rõ ràng: `ready`, `experimental` hoặc `blocked`.
3. `experimental` hay `blocked` không phải lỗi khởi động. Đây là kết quả quality gate fail-closed khi dữ liệu chưa đủ khả năng khái quát giữa các vườn.
4. Báo cáo model con người đọc nằm tại `model-artifacts/reports/LATEST_TRAINING_REPORT.md`; báo cáo máy đọc nằm tại `model-artifacts/shared/latest_training_report.json`; bản tóm tắt nằm tại `docs/evidence/shared-ml-latest.json`.
5. `scripts\start_v10.cmd` tự đồng bộ báo cáo và tạo lại `BUILD_MANIFEST.json` sau khi kiểm tra runtime đạt.

## 8. Test kỹ thuật tự động

Mở terminal tại thư mục dự án rồi chạy:

```cmd
docker compose ps -a
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_v10_unit_tests.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_v10_runtime.ps1
python scripts\check_v10_static.py
```

Kỳ vọng:

- Các service đang chạy và healthy; `db-migrate` có thể ở trạng thái `Exited (0)` vì đây là job chạy xong rồi dừng.
- Unit test, runtime smoke và static check đều PASS.
- Model artifact phải nạp và predict được đủ 10/10.
- `production_ready=false` vẫn là kết quả hợp lệ ở giai đoạn dữ liệu demo; không được sửa cờ này bằng tay.

Evidence mới nhất:

- `docs/evidence/v10-unit-test-summary.json`
- `docs/evidence/v10-runtime-validation-latest.json`
- `docs/evidence/shared-ml-latest.json`
- `docs/evidence/shared-ml-verification.json`

## 9. Dừng và chạy lại

Dừng nhưng giữ dữ liệu:

```cmd
docker compose down
```

Chạy lại:

```cmd
scripts\start_v10.cmd
```

Không dùng `docker compose down -v` trừ khi chủ động muốn xóa toàn bộ database. Script seed có tính idempotent nên chạy lại không tạo trùng bản ghi demo cố định.

## 10. Khi test lỗi

```cmd
docker compose ps -a
docker compose logs --tail 200
```

Gửi cho trưởng nhóm: ảnh màn hình lỗi, thời điểm test, tài khoản dùng (không gửi mật khẩu), câu hỏi đã nhập, màn hình đang mở và 200 dòng log gần nhất.
