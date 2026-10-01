# NextFarm AI Support v10.4

Nền tảng hỗ trợ nông nghiệp NextFarm kết hợp dữ liệu IoT, truy vấn theo quyền, tri thức nông học, chatbot có kiểm soát bằng chứng và pipeline AI mô phỏng.

## Trạng thái phiên bản

- Phiên bản đóng gói: `10.4`
- Nguồn nâng cấp: `NextFarm-AI-Support-v10.1`
- Phạm vi AI v10.4: `SYNTHETIC_SIMULATION_ONLY`
- Chế độ mặc định: tư vấn và đọc dữ liệu; không tự động điều khiển thiết bị
- `DEVICE_AUTO_TRAIN=false` là mặc định để tránh huấn luyện ngoài ý muốn trong runtime

Các kết quả mô phỏng và model artifact trong repository dùng cho đồ án, benchmark và shadow test. Chúng không thay thế nghiệm thu trên dữ liệu vận hành thực tế.

## Tính năng chính

- Web UI cho nông dân và kỹ thuật viên
- Chat dữ liệu thiết bị theo quyền truy cập
- Realtime Data Studio cho cảm biến, thiết bị và lịch tưới
- Knowledge Studio cho nguồn tri thức, bản nháp và citation
- AI Encyclopedia cho crop mapping và trạng thái capability
- Telemetry ingestion qua MQTT
- PostgreSQL với schema và dữ liệu demo
- Truth Guard kiểm tra độ tin cậy câu trả lời
- Crop router và LLM gateway deterministic
- Năm pipeline AI mô phỏng:
  - dự báo độ ẩm đất
  - khuyến nghị dinh dưỡng
  - phát hiện bất thường
  - lập lịch tưới
  - predictive maintenance

## Kiến trúc thư mục

| Thư mục | Nội dung |
| --- | --- |
| `apps/` | Các giao diện web |
| `services/` | Các microservice FastAPI |
| `infra/` | PostgreSQL, MQTT và Nginx |
| `data/` | Dữ liệu mô phỏng và dữ liệu demo |
| `model-artifacts/` | Kết quả training và inference mô phỏng |
| `nextfarm_device/` | Logic runtime, kiểm tra dữ liệu và training |
| `scripts/` | Script thiết lập, khởi chạy và kiểm thử |
| `tests_device/` | Bộ kiểm thử hợp đồng và acceptance |
| `docs/` | Báo cáo, hướng dẫn và evidence |

## Yêu cầu

- Windows 10/11
- Docker Desktop đang chạy và Docker Engine ở trạng thái running
- Docker Compose v2+
- Ít nhất 8 GB RAM trống cho toàn bộ stack
- Python 3 nếu muốn chạy các kiểm thử hoặc pipeline offline ngoài container

## Khởi động

Mở Command Prompt hoặc PowerShell:

```powershell
cd /d "D:\2026-2027\THUCTAP\NextFarm_Support_AI"
scripts\start_v11.cmd  (Nếu cần hãy chỉnh sửa start_v11.cmd cho phù hợp với dòng máy ) 
```

`start_v10.cmd` là alias tương thích và chuyển tiếp sang `start_v11.cmd`.

Nếu chỉ muốn tạo cấu hình local trước:

```powershell
scripts\setup_v10_env.cmd
```

Script này dùng PowerShell có sẵn trên Windows để tạo secret, không bắt buộc
phải cài Python. Có thể chạy lại nhiều lần; các secret hiện có được giữ nguyên.

File `.env` chứa secret local và không được commit. Repository đã cung cấp `.env.example` để tham khảo.

## Các địa chỉ sau khi chạy

| Thành phần | URL |
| --- | --- |
| Web chính / Chat AI | http://127.0.0.1:18080 |
| Data Studio | http://127.0.0.1:18081 |
| Knowledge Studio | http://127.0.0.1:18082 |
| AI Encyclopedia | http://127.0.0.1:18084 |
| Identity API | http://127.0.0.1:18100 |
| Farm Data API | http://127.0.0.1:18300 |
| Chatbot API | http://127.0.0.1:18000 |

Kiểm tra container:

```powershell
docker compose ps
docker compose logs --tail 200
```

## Tài khoản demo

Tên người dùng demo được seed trong database:

- Farmer: `nongdan.long`, `nongdan.lan`, `nongdan.minh`
- Technician: `kythuat.01`

Mật khẩu được sinh trong `.env` local. Không đưa mật khẩu lên GitHub hoặc chia sẻ trong issue/log.

## Smoke test thủ công

1. Đăng nhập bằng tài khoản farmer.
2. Hỏi độ ẩm đất hiện tại của một khu vực.
3. Hỏi số lần tưới trong ngày.
4. Hỏi thiết bị nào đang offline.
5. Hỏi capability AI nào đang `READY`, `EXPERIMENTAL` hoặc `BLOCKED`.
6. Hỏi kiến thức về pH hoặc cây trồng để kiểm tra citation.
7. Thử yêu cầu mở van; runtime read-only phải từ chối.
8. Hỏi một số liệu không tồn tại; hệ thống phải báo thiếu dữ liệu thay vì đoán.

## Kiểm thử tự động

Khi Docker Engine đã hoạt động:

```powershell
docker compose ps -a
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_v10_unit_tests.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_v10_runtime.ps1
python scripts\check_v10_static.py
```

Kiểm tra offline:

```powershell
python -m pytest tests_device -q
```

## Dừng hệ thống

Giữ lại volume database:

```powershell
docker compose down
```

Chỉ dùng lệnh sau khi chủ động muốn xóa dữ liệu database demo:

```powershell
docker compose down -v
```

## Giới hạn an toàn

- Dữ liệu v10.4 là dữ liệu mô phỏng, không phải telemetry production.
- Model chưa được xem là nghiệm thu production chỉ vì benchmark mô phỏng đạt.
- Chưa bật tích hợp Zalo OA thật.
- Không commit `.env`, API key, token, password hoặc dữ liệu vận hành riêng tư.

## Tài liệu

- [Hướng dẫn test v10](HUONG-DAN-TEST-V10.md)
- [Release notes v10.4](RELEASE-NOTES-V10.4.md)
- [Báo cáo training và mô phỏng](docs/)
- [Manifest đóng gói](PACKAGING_MANIFEST.md)

## License

Chưa khai báo license công khai. Vui lòng bổ sung license trước khi phát hành package cho bên thứ ba.
