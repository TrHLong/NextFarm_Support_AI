# NextFarm AI Support V10.1 — Acceptance Hardening

V10.1 là baseline hợp nhất sau feedback công ty. Bản này giữ kiến trúc crop-aware
của V10 và bổ sung: chọn farm/zone bắt buộc khi mơ hồ, planner đa nguồn, API lịch
tưới/command log, `measured_at` + `received_at`, RAG có ngưỡng phiên bản hóa,
Truth Guard kiểm tra quality/no-data, benchmark 260 câu và dữ liệu vận hành giả lập
40 farm. Xem báo cáo tại `docs/V10.1-COMPANY-REMEDIATION.md`.

Hệ thống là PoC **crop-aware, evidence-first**: tài khoản → vườn/thửa → nông sản (`crop_key`) → bộ capability/model phù hợp. Hệ thống không tạo một thư mục model cho từng nông dân và cũng không gọi 10 model dùng chung là “model chuyên cây” khi chưa có validation theo cây.

## Báo cáo Word dùng để trình bày

- `docs/BAO-CAO-THUC-NGHIEM-10-MODEL-VA-32-NANG-LUC.docx`: bảng dữ liệu, split, chỉ số, kết quả 10 model, 32 capability và phương án 500 khách hàng.
- `docs/BAO-CAO-KIEN-TRUC-LLM-VA-LUONG-XU-LY-CAU-HOI.docx`: provider LLM đang hoạt động, API được hỗ trợ, luồng câu hỏi và chính sách dữ liệu chat.

Trạng thái cấu hình hiện tại là `LLM_PROVIDER=deterministic`: không gửi câu hỏi tới OpenAI/ChatGPT hoặc Gemini. Mã nguồn có hỗ trợ OpenAI Responses API với model cấu hình `gpt-5.6-luna` khi đổi provider sang `openai`; Gemini chưa được tích hợp.

## V10 có gì mới

- **LLM Gateway thật**: chế độ `deterministic` chạy không cần API; chế độ `openai` dùng Responses API cho planner và grounded verbalizer. LLM không có DB credentials và không tự chọn vườn ngoài danh sách đã phân quyền.
- **Crop Router**: chuẩn hóa tên nông sản tiếng Việt thành `crop_key`, ánh xạ từng vườn/khu sang capability trong AI Encyclopedia.
- **AI Encyclopedia**: 34 khóa nông sản và 32 capability ở các nhóm sensor quality, irrigation/water, soil/nutrition, disease/pest, yield/growth, satellite và computer vision.
- **10 ML artifacts V2.1**: pipeline thử Random Forest và Extra Trees, chọn thuật toán bằng validation theo thời gian, sau đó chạy test + Leave-One-Farm-Out và quality gate.
- **Truth Guard V10**: kiểm tra số liệu/nguồn/confidence, tenant evidence, freshness và trạng thái experimental/blocked sau bước LLM verbalization.
- **UI thứ tư**: `http://localhost:18084` để xem trực tiếp vườn → nông sản → capability → READY/EXPERIMENTAL/BLOCKED.
- **Không đóng gói `.env` hay raw dataset lớn**.

## Trạng thái dữ liệu trung thực

Telemetry demo vẫn có provenance:

```text
data_origin = simulated_device_calibrated_v9
```

Đây là simulator đã hiệu chỉnh bằng reference công khai, **không phải dữ liệu production NextFarm**. Các capability yêu cầu ảnh drone/satellite, dữ liệu bệnh, radiation/wind hoặc nhãn sự cố thật sẽ bị BLOCKED/EXPERIMENTAL thay vì sinh kết quả giả.

## Cài mới trên Windows

Yêu cầu: Docker Desktop đang chạy + Python 3.

```cmd
cd /d "D:\2026-2027\THUCTAP\NextFarm-AI-Support-v10.1"
scripts\setup_v10_env.cmd
scripts\start_v10.cmd
```

`setup_v10_env.cmd` sinh/bổ sung secret ngẫu nhiên và in tên tài khoản demo nhưng không ghi password ra log. Khi thật sự cần xem password trên terminal riêng, chạy `scripts\setup_v10_env.cmd --show-demo-passwords`. Không chia sẻ file `.env`.
`start_v10.cmd` build container, chạy unit test của các dịch vụ AI, chờ healthcheck rồi tự kiểm tra luồng đăng nhập → Crop Router → capability readiness → LLM planner → Farm Data → chatbot → Truth Guard. Nếu bất kỳ bước nào không đạt, script trả exit code khác 0.

V10 mặc định dùng dải cổng `18xxx` để có thể chạy song song với V9 mà không dừng hoặc ghi đè project cũ. Tất cả host bind đều nằm trong `.env` và có thể đổi khi cần.

### Bật LLM OpenAI

Sau khi chạy setup, mở `.env` và đổi:

```text
LLM_PROVIDER=openai
OPENAI_API_KEY=<API_KEY_CUA_BAN>
OPENAI_MODEL=gpt-5.6-luna
```

Không có API key thì để `LLM_PROVIDER=deterministic`; toàn bộ tool/data/RAG/Truth Guard vẫn chạy để demo kiến trúc.

## Giao diện

```text
http://localhost:18080   Chat AI / SupportOps
http://localhost:18081   Realtime Data Studio
http://localhost:18082   Knowledge Studio
http://localhost:18084   AI Encyclopedia
```

Mở cùng lúc:

```cmd
scripts\open_studios.cmd
```

## API V10 mới

```text
GET  http://localhost:18900/health
GET  http://localhost:18900/me/crops
GET  http://localhost:18900/farms/{farm_id}/capabilities
GET  http://localhost:18950/health
POST http://localhost:18950/plan
POST http://localhost:18950/verbalize
```

Các endpoint có dữ liệu khách hàng yêu cầu token/tenant authorization; internal service key chỉ dành cho giao tiếp service-to-service.

Trạng thái `READY` trên dữ liệu mô phỏng được hiển thị là `demo_ready`; chỉ dữ liệu có provenance NextFarm thật mới được đánh dấu `production_candidate`. `production_ready` vẫn luôn false cho tới khi có nghiệm thu sandbox/field, security và chuyên gia nông học độc lập.

## Model artifacts

V10 đóng gói đúng 10 artifact ở:

```text
model-artifacts/shared/<model_family>/v2.1.0/model.joblib
```

Không có `farm_long/model.joblib`, `farm_lan/model.joblib`... Bách khoa AI có nhiều capability hơn 10 artifact vì một capability có thể là rule, công thức FAO, remote sensing, CV hoặc LLM/RAG; V10 không tạo file model giả cho những phần chưa được train.

Xem báo cáo train/test mới nhất, có CSV nguồn và giải thích chỉ số tại:

```text
model-artifacts/reports/LATEST_TRAINING_REPORT.md
```

Model chỉ được dùng như READY khi quality gate và crop/data-domain cho phép. Các model chưa generalize tốt được giữ `EXPERIMENTAL`.

## Kiểm tra

```cmd
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_v10_completion.ps1
```

Hoặc:

```cmd
python scripts\check_v10_static.py
```

Kiểm tra cả runtime sau khi container đã chạy:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_v10_completion.ps1 -Runtime
```

Evidence test và runtime mới nhất được ghi tại `docs/evidence/v10.1-unit-test-summary.json` và `docs/evidence/v10.1-runtime-validation-latest.json`; cả hai không chứa password/token.

Hướng dẫn kiểm tra từng feedback và mẫu ghi báo cáo:

```text
docs/V10.1-FEEDBACK-MANUAL-TEST-GUIDE.md
docs/V10.1-FEEDBACK-REPORT-TEMPLATE.md
```

Ma trận câu hỏi kiểm tra thủ công qua API localhost:

```cmd
py -3 scripts\manual_feedback_probe.py "." "docs\evidence\v10.1-manual-feedback-probe.json"
```

Sau khi Docker chạy:

```cmd
docker compose ps -a
curl http://localhost:18900/health
curl http://localhost:18950/health
curl http://localhost:18600/ml/status
curl http://localhost:18800/stats
```

## Dừng nhưng giữ dữ liệu

```cmd
docker compose down
```

Không dùng `docker compose down -v` trừ khi chủ động muốn xóa volume PostgreSQL V10.

## Production override

Tạo đầy đủ secret riêng cho HTTP ingest/MQTT, Mosquitto password file và HTTPS origin:

```cmd
scripts\setup_v10_production.cmd https://ai.example.vn
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
```

Production override chỉ public các frontend trên địa chỉ bind đã cấu hình; database, MQTT và API nội bộ không publish ra host. TLS phải được kết thúc tại reverse proxy/load balancer của môi trường triển khai.

## Tài liệu chính

- `docs/14-v10-crop-aware-ai-encyclopedia.md`
- `docs/15-v10-install-run.md`
- `docs/16-v10-research-model-catalog.md`
- `docs/CAU-TRUC-THU-MUC-VA-DAN-CHUNG.md`
- `docs/HUONG-DAN-ML-THEO-KHACH-HANG.md`
- `docs/evidence/shared-ml-latest.json`
- `docs/evidence/v10.1-static-validation.json`

## ML dùng chung, dữ liệu tách theo khách hàng

Pipeline v10.1 tách snapshot CSV theo `customer_id`, gộp các tập đủ điều kiện để train đúng 10 model nền, kiểm định leave-one-customer-out và chỉ kích hoạt candidate qua quality gate. Với 500 khách hàng vẫn dùng 10 model nền cùng calibration nhỏ theo vườn. Xem [`docs/HUONG-DAN-ML-THEO-KHACH-HANG.md`](docs/HUONG-DAN-ML-THEO-KHACH-HANG.md) và [`docs/CAU-TRUC-THU-MUC-VA-DAN-CHUNG.md`](docs/CAU-TRUC-THU-MUC-VA-DAN-CHUNG.md).
