# Cài đặt và chạy NextFarm V10

## 1. Giải nén

Ví dụ:

```text
D:\2026-2027\THUCTAP\NextFarm-AI-Support-CropEncyclopedia-v10
```

## 2. Dừng đúng project Docker cũ nếu bị trùng cổng

Không dừng toàn bộ container trên máy. Tại đúng thư mục project cũ, dùng `docker compose down`, hoặc đổi port/bind của project đang gây xung đột.

## 3. Tạo local secrets

```cmd
cd /d "D:\2026-2027\THUCTAP\NextFarm-AI-Support-CropEncyclopedia-v10"
scripts\setup_v10_env.cmd
```

Script tạo/nâng cấp `.env` nhưng mặc định không in password ra log. Chỉ dùng `scripts\setup_v10_env.cmd --show-demo-passwords` trên terminal riêng khi cần đăng nhập demo. File `.env` không được commit hoặc chia sẻ.

V10 mặc định dùng dải cổng `18xxx`, PostgreSQL `15432` và MQTT `11883` để chạy song song với V9. Có thể đổi từng biến `NEXTFARM_*_BIND` trong `.env` nếu máy đã dùng các cổng này.

## 4. Chọn LLM

### Offline/deterministic

```text
LLM_PROVIDER=deterministic
```

### OpenAI

Sửa `.env`:

```text
LLM_PROVIDER=openai
OPENAI_API_KEY=<key>
OPENAI_MODEL=gpt-5.6-luna
```

Không ghi API key vào source code, HTML hoặc Git.

## 5. Khởi động

```cmd
scripts\start_v10.cmd
```

Script chỉ báo thành công sau khi unit/endpoint test, healthcheck và smoke test các luồng cốt lõi V10.1 đều đạt. Evidence được ghi vào `docs/evidence/v10.1-unit-test-summary.json` và `docs/evidence/v10.1-runtime-validation-latest.json`.

Hoặc:

```cmd
docker compose up -d --build
```

## 6. Kiểm tra

```cmd
docker compose ps -a
curl http://localhost:18100/health
curl http://localhost:18200/health
curl http://localhost:18300/health
curl http://localhost:18400/health
curl http://localhost:18600/health
curl http://localhost:18700/health
curl http://localhost:18800/stats
curl http://localhost:18900/health
curl http://localhost:18950/health
```

Expected V10 crop-router health có `crop_count=34`, `capability_count=32`.

Kiểm tra lại cả runtime bất kỳ lúc nào:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_v10_completion.ps1 -Runtime
```

## 7. Mở UI

```cmd
scripts\open_studios.cmd
```

- 18080 Chat
- 18081 Data Studio
- 18082 Knowledge Studio
- 18084 AI Encyclopedia

## 8. Kiểm tra model

```cmd
dir /s /b model-artifacts\shared\v2.1.0\model.joblib
```

Do version nằm dưới từng model family, lệnh dễ dùng hơn là:

```cmd
for /r model-artifacts\shared %f in (model.joblib) do @echo %f
```

V10 package có 10 `v2.1.0/model.joblib`.

## 9. Dừng dự án

```cmd
docker compose down
```

Không thêm `-v` nếu muốn giữ database.

## 10. Chuẩn bị production override

```cmd
scripts\setup_v10_production.cmd https://ai.example.vn
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
```

Lệnh setup production tạo riêng HTTP ingest key, hai MQTT password và `.secrets/mosquitto.passwords`. Không dùng origin HTTP/localhost khi triển khai thật. TLS được cấu hình tại reverse proxy/load balancer phía trước các frontend.
