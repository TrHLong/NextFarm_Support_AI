# V10.1.1 — Independent Feedback Audit Hardening

- Thay benchmark lặp mẫu bằng 260 ca đúng taxonomy phản biện và oracle đọc từ Parquet.
- Bổ sung provenance từng dòng, ACL/control fields, crop/soil/growth context, device freshness và data invariants.
- Không nhận zone/metric do planner tự đề xuất; zone hội thoại chỉ kế thừa từ một kết quả tool đã xác nhận.
- Truth Guard mất kết nối, dữ liệu stale/no-data/suspect/bad và tư vấn số thiếu ngữ cảnh đều fail closed.
- Sửa router để phân biệt câu hỏi kiến thức với truy vấn vận hành; thêm bảng và source-version metadata cho RAG.
- Tách rõ `offline_passed` với hai cổng runtime Docker và duyệt nông học NextFarm.

# V10.1.0 — Company Feedback Acceptance Hardening

- Hợp nhất source V10 mới nhất, phục hồi `apps/web/app.js` bị thiếu trong gói text-only.
- Không tự chọn farm/zone/metric khi ngữ cảnh mơ hồ; mọi truy cập chéo farm bị chặn.
- Planner hỗ trợ 1–4 tool và kết hợp operational evidence với Knowledge/RAG.
- Bổ sung API farms/zones, lịch tưới, lịch sử tưới và command log read-only.
- Sensor trả `measured_at`, `received_at`, age, freshness và quality.
- Truth Guard fail-closed với stale, suspect/bad quality và no-data.
- RAG dùng structure-aware chunks, reader authentication và threshold phiên bản hóa.
- Thêm 11 bảng Parquet vận hành: 40 farm, 120 zone, 80 user, 725.760 readings/14 ngày.
- Thêm benchmark 260 câu, 10 model V2.1 đồng bộ trên một dataset và acceptance report.
- Thêm rate limit tại Nginx, request ID, timeout/retry và JSON access log.

# V10.0.0 — Crop-aware AI Encyclopedia

- Added crop-aware AI routing: customer/farm/zone → crop_key → capability/model status.
- Added 34-crop catalog and 32-capability AI Encyclopedia with READY/EXPERIMENTAL/BLOCKED governance.
- Added `crop-router-service` and AI Encyclopedia UI on port 8084.
- Added `llm-gateway-service` with deterministic fallback and optional OpenAI Responses API planner/verbalizer.
- Truth Guard now validates LLM output after verbalization and adds tenant/freshness/model-status checks.
- ML pipeline V2.1 compares Random Forest vs Extra Trees on validation, then preserves test/LOFO quality gates.
- Bundles exactly 10 V2.1 ML artifacts; inherited V2.0 artifacts and prior runtime/blend demo datasets removed.
- Raw external reference downloads and `.env` secrets are excluded from the distribution package.
- Added V10 install, architecture, research-catalog and validation evidence docs.
- Stabilized first-run execution: fixed missing Crop Router authorization/catalog helpers, zone validation and database-backed healthchecks.
- Capability readiness now gates executable implementation, model registry, crop mapping, fresh farm/zone inputs, history length and data provenance separately.
- Internal LLM/Truth Guard endpoints require a service key; production MQTT/HTTP ingest use dedicated generated credentials and internal APIs bind to loopback only.
- Startup now runs container endpoint tests plus an authenticated end-to-end smoke flow and writes fresh, non-secret evidence instead of reusing V9 validation claims.
- `production_candidate` is separated from `production_ready`; V10 remains non-production until independent field/security/agronomy acceptance exists.

# Changelog

## V9 Completion Pack – 2026-08-15

- Thêm migration idempotent cho volume V9 đang dùng và schema Data Operations.
- Lưu chat fail-safe trong PostgreSQL, history API, khôi phục UI sau restart và idempotency theo hội thoại.
- Thêm Data Operations Center: 9 nhóm dữ liệu, provenance/freshness, audit accepted/duplicate/rejected/error và báo cáo ngày.
- Thêm ánh xạ danh tính Zalo OA/NextFarm có verify/revoke/resolve và tenant guard.
- Thêm NextFarm read-only ingest API có integration key, packet idempotency, sensor/device mapping validation và audit.
- Thêm command audit foundation; PoC vẫn không thực thi van/bơm.
- Thêm backup/restore checksum + verify, Adminer profile localhost và production override cho CORS/MQTT ACL/persistence.
- Sửa mô tả nguồn: KarLy là soil-moisture anchor bắt buộc; Zenodo AgriDataValue là tùy chọn; lock hiện có 3 nguồn/147.919 dòng và flow-rate external coverage bằng 0.
- Kiểm tra tĩnh 47/47 và smoke test Docker cô lập gồm migration, ingest, tenant, chat restart, Data Studio, backup/restore.

## V9.0.1 Standalone Reference Fix – 2026-08-11

- Sửa lỗi first-run dừng ở `soil_moisture=0`: AgriDataValue có schema theo pilot không khớp bộ parser wide-column V9.0.0.
- Thêm KarLy/Zenodo soil-moisture dataset làm compact mandatory anchor (CC BY 4.0, cột `soil_moisture` rõ ràng).
- AgriDataValue chuyển thành large optional reference; bật bằng `NEXTFARM_DOWNLOAD_LARGE_REFERENCE=1`.
- Bỏ qua raw AgriDataValue khổng lồ trong normalization mặc định; bật bằng `NEXTFARM_USE_LARGE_ZENODO_REFERENCE=1` sau khi có parser/schema audit phù hợp.
- Downloader hiển thị MB/phần trăm và checksum thay vì đứng im nhiều phút.
- Không thay đổi nguyên tắc fail-closed: thiếu Figshare/KarLy/NASA POWER hoặc coverage cốt lõi vẫn dừng, không fake fallback.

## V9.0.0 Standalone – 2026-08-11

- Tách V9 thành bản cài mới hoàn toàn, không migrate/đọc/train database dự án trước.
- Thêm first-run downloader cho static public reference (Figshare, Zenodo, NASA POWER; Mendeley tùy chọn).
- Fail closed nếu static reference bắt buộc không tải được hoặc coverage biến cốt lõi không đủ.
- Khóa normalized reference, calibration và bootstrap training bằng SHA-256.
- AI hai giai đoạn: `bootstrap_reference` trước, `runtime_retrain` sau ngưỡng 50.000 readings V9.
- Runtime retrain giữ reference anchor mặc định 25% để giảm distribution drift.
- Simulator stateful dùng empirical quantiles, step sizes và correlations từ reference calibration.
- Runtime provenance duy nhất: `simulated_device_calibrated_v9`.
- Fresh seed không còn sensor readings, device status, irrigation run, alert hoặc ticket giả lịch sử.
- `production_ready=false` bắt buộc trong V9 simulator/reference-only.
