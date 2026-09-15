from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
checks: list[tuple[str, bool, str]] = []


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


def check(name: str, ok: bool, detail: str) -> None:
    checks.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


check("Version standalone", text("VERSION").strip() == "9.0.1", "VERSION=9.0.1")
manifest = json.loads(text("research-data/source_manifest.json"))
policy = manifest.get("policy", {})
check("Không dùng dữ liệu dự án trước", policy.get("uses_prior_project_data") is False, "policy uses_prior_project_data=false")
check("Static reference bắt buộc", policy.get("static_reference_required_before_start") is True and policy.get("no_silent_fake_reference_fallback") is True, "Thiếu reference thì dừng, không bịa fallback")
source_ids = {x.get("id") for x in manifest.get("sources", [])}
check("Catalog nguồn công khai có provenance", {"figshare_iot_28667981", "karly_soil_moisture_1227837", "agridatavalue_iot_18954708", "parma_tomato_35wh56287y_2", "parma_evolving_h8sfcf9487_1", "nasa_power_2025"}.issubset(source_ids), f"declared_sources={len(source_ids)}")
mandatory_ids = {x.get("id") for x in manifest.get("sources", []) if x.get("mandatory")}
check("Ba reference bắt buộc", mandatory_ids == {"figshare_iot_28667981", "karly_soil_moisture_1227837", "nasa_power_2025"}, "Figshare + KarLy soil moisture + climate-by-location đều bắt buộc")
reference_lock = json.loads(text("research-data/reference/reference_lock.json"))
actual_ids = {x.get("id") for x in reference_lock.get("sources", [])}
actual_counts = reference_lock.get("reference_source_counts", {})
check(
    "Nguồn đã tải thực tế khớp lock",
    len(actual_ids) == len(actual_counts) and sum(int(x) for x in actual_counts.values()) == int(reference_lock.get("normalized_reference_rows", 0)),
    f"actual_sources={len(actual_ids)}, normalized_rows={reference_lock.get('normalized_reference_rows', 0)}",
)
check(
    "Nguồn tùy chọn không bị gọi là bắt buộc",
    "agridatavalue_iot_18954708" not in mandatory_ids and "OPTIONAL_LARGE_ZENODO_RECORD_IDS = [18954708]" in text("scripts/prepare_v9_reference_data.py"),
    "Zenodo 18954708 là nguồn bổ sung tùy chọn; KarLy mới là soil-moisture anchor bắt buộc",
)

prep = text("scripts/prepare_v9_reference_data.py")
check("Downloader public reference", all(x in prep for x in ["api.figshare.com", "raw.githubusercontent.com/felixriese", "zenodo.org/api/records", "power.larc.nasa.gov", "api.data.mendeley.com"]), "Figshare + KarLy + Zenodo tùy chọn + NASA POWER + Mendeley tùy chọn")
check("NASA fail closed", "Không tải được NASA POWER bắt buộc" in prep and "return 2" in prep, "Không có climate reference theo vị trí thì V9 dừng")
check("Reference có SHA-256 lock", all(x in prep for x in ["normalized_sha256", "calibration_sha256", "bootstrap_sha256", "reference_lock.json"]), "Raw/normalized/calibration/bootstrap được khóa checksum")
check("Không silent random static fallback", "V9 dừng; không có random fallback" in prep and "V9 dừng thay vì tự bịa static reference" in prep, "Fail closed nếu nguồn bắt buộc/coverage không đủ")
check("Coverage tối thiểu", '"temperature":5000' in prep and '"air_humidity":5000' in prep and '"soil_moisture":500' in prep and '"ec":5000' in prep and '"ph":5000' in prep in prep, "Static reference cần đủ mẫu khí hậu + soil moisture + EC/pH")
check("Bootstrap tách khỏi telemetry", "derived_reference_training_not_device_telemetry" in prep, "Static-derived bootstrap không insert sensor_readings")

profiles = json.loads(text("research-data/calibration/v9_profiles.json"))
check("Ba vườn có profile độc lập", set(profiles.get("farms", {})) == {"farm_long", "farm_lan", "farm_minh"}, "3 farm V9 fresh")
check("Cadence vật lý chậm hơn MQTT", profiles.get("principles", {}).get("mqtt_publish_seconds") == 2 and profiles.get("principles", {}).get("physical_state_minimum_step_seconds", 0) >= 30, "Publish nhanh nhưng trạng thái vật lý có quán tính")
check("Fault theo episode", profiles.get("principles", {}).get("faults_are_episodes") is True, "Offline/no-flow/leak/drift/stuck không random từng packet")

sim = text("services/data-simulator-service/app/calibrated_model.py")
sim_main = text("services/data-simulator-service/app/main.py")
check("Simulator bắt buộc calibration", "reference_calibration.json" in sim_main and "reference_calibration_required" in text("research-data/calibration/v9_profiles.json"), "Runtime cần calibration từ static reference")
check("Simulator dùng empirical step/correlation", all(x in sim for x in ["reference_step", "reference_corr", "reference_median"]), "Noise/inertia bám thống kê reference")
check("Runtime provenance riêng", 'DATA_ORIGIN = "simulated_device_calibrated_v9"' in sim_main, "Không gắn nhãn dữ liệu thiết bị thật")
check("Backfill cũng có provenance", "historical_backfill" in sim_main and "reference_calibration_sha256" in sim_main, "Lịch sử mô phỏng có checksum calibration")

telemetry = text("services/telemetry-ingestion-service/app/main.py")
check("Ingestion từ chối packet thiếu provenance", 'allowed_origins or {"simulated_device_calibrated_v9"}' in telemetry and "packet_origin not in accepted_origins" in telemetry, "MQTT demo chỉ nhận origin mô phỏng; API chỉ nhận origin NextFarm đã định nghĩa")

schema = text("infra/database/01_schema.sql")
seed = text("infra/database/02_seed_demo.sql")
check("Schema provenance hữu hạn", all(x in schema for x in ["simulated_device_calibrated_v9", "nextfarm_api", "nextfarm_mqtt", "manual_import", "partner_api"]), "DB chỉ nhận các provenance đã định nghĩa; MQTT demo vẫn fail-closed")
check("Schema reference registry", "research_db.reference_datasets" in schema and "training_phase" in schema, "DB lưu reference lock + phase model")
check("Schema Data Operations", all(x in schema for x in ["ops_db.daily_data_reports", "ops_db.ingest_attempts", "ops_db.backup_runs", "farm_db.control_commands", "user_db.external_identities"]), "Có nhóm dữ liệu, audit ingest/lệnh và backup registry")
check("Seed không nhét telemetry giả cũ", "INSERT INTO farm_db.sensor_readings" not in seed and "INSERT INTO farm_db.device_status" not in seed and "INSERT INTO farm_db.irrigation_runs" not in seed, "Operational telemetry bắt đầu rỗng")
check("Seed không nhét alert/ticket runtime", "INSERT INTO farm_db.alerts" not in seed and "TKT-DEMO" not in seed, "Ticket/cảnh báo phát sinh từ runtime/người dùng")

builder = text("services/ai-analytics-service/app/dataset_builder.py")
ai = text("services/ai-analytics-service/app/main.py")
pipeline = text("services/ai-analytics-service/app/ml_pipeline.py")
check("AI bootstrap từ locked reference", "build_reference_bootstrap_dataset" in ai and "reference_bootstrap" in builder, "Giai đoạn 1 không đọc sensor DB")
check("AI runtime chỉ V9", "data_origin='simulated_device_calibrated_v9'" in builder, "Dataset runtime lọc provenance V9")
check("Retrain có reference anchor", "build_v9_blended_training_dataset" in ai and "REFERENCE_ANCHOR_RATIO" in ai, "Runtime + static anchor chống drift")
check("Ngưỡng retrain 50k", 'AI_RETRAIN_MIN_NEW_ROWS: "50000"' in text("docker-compose.yml") and '"50000"' in ai, "Không train lại theo từng packet")
check("Hai phase rõ ràng", all(x in ai for x in ["bootstrap_reference", "runtime_retrain", "v9_standalone_two_stage_learning"]), "Static bootstrap -> runtime retrain")
check("Không synthetic fallback trong production", "explicit locked dataset frame; no internal synthetic fallback" in pipeline, "Internal generator chỉ còn test_fixture")
check("Không tự nhận production", "def _production_ready" in ai and "return False" in ai and "actual NextFarm hardware" in ai, "Reference/simulator-only luôn production_ready=false")

compose = text("docker-compose.yml")
check("Volume V9 riêng", "nextfarm_v9_fresh_pg" in compose and "COMPOSE_PROJECT_NAME" in text("scripts/setup_v9_env.py"), "Không nối volume dự án khác")
service_mains = "\n".join(text(str(p.relative_to(ROOT)).replace("\\", "/")) for p in ROOT.glob("services/*/app/main.py"))
check("Không fallback mật khẩu DB cố định", "nextfarm_demo" not in service_mains and 'postgresql://nextfarm:' not in service_mains, "DATABASE_URL bắt buộc từ Compose/.env; source chạy ngoài Compose fail closed")
check("AI bootstrap trước simulator trong start", text("scripts/start_v9.cmd").find("wait_v9_bootstrap.py") < text("scripts/start_v9.cmd").find("telemetry moi"), "Static AI bootstrap hoàn tất trước runtime stream")
check("AI image có static reference", "COPY research-data /research-data" in text("services/ai-analytics-service/Dockerfile"), "Reference pack tải trước build được đóng vào image AI")
check("Simulator image có static reference", "COPY research-data ./research-data" in text("services/data-simulator-service/Dockerfile"), "Calibration tải trước build được đóng vào simulator")

ui = text("apps/web/app.js")
check("UI nhận diện simulator V9", "simulated_device_calibrated_v9" in ui, "Người dùng thấy provenance mô phỏng hiệu chỉnh")
chatbot = text("services/chatbot-service/app/main.py")
farm_service = text("services/farm-data-service/app/main.py")
check("Chat fail-safe và có history", "strict=True" in chatbot and "/conversations/current/messages" in chatbot and "CHAT_PERSISTENCE_FAILED" in chatbot, "Không nuốt lỗi ghi chat; mở máy lại tải từ PostgreSQL")
check("Báo cáo nhóm dữ liệu realtime", "/studio/data-groups" in farm_service and "/studio/daily-report" in farm_service and "/studio/daily-report/snapshot" in farm_service, "Data Studio có row count, freshness và báo cáo ngày")
check("Migration chạy với volume cũ", "db-migrate:" in compose and "03_v10_ops_migration.sql" in compose, "Không phụ thuộc docker-entrypoint-initdb.d của volume mới")
check("Backup/restore có chốt an toàn", "pg_dump" in text("scripts/backup_v10.ps1") and "ConfirmRestore" in text("scripts/restore_v10.ps1"), "Backup checksum/verify và restore bắt buộc xác nhận")
check("MQTT production không anonymous", "allow_anonymous false" in text("infra/mosquitto/mosquitto.prod.conf") and "mosquitto.passwords" in text("docker-compose.production.yml"), "Production override bật password + ACL + persistence")
identity = text("services/identity-service/app/main.py")
check("Ánh xạ danh tính ngoài có revoke/resolve", all(x in identity for x in ["/external-identities", "/resolve", "/revoke", "revoked_at IS NULL"]), "Zalo OA/NextFarm chỉ resolve ánh xạ đã xác minh và chưa thu hồi")
check("NextFarm API ingest có idempotency/audit", all(x in telemetry for x in ["/integrations/nextfarm/ingest", "INGEST_API_KEY", "ops_db.ingest_attempts", "sensor_id không thuộc farm/zone"]), "API read-only kiểm tra key, mapping tenant, packet_id và provenance")

syntax_errors = []
for path in ROOT.rglob("*.py"):
    if "reference/raw" in str(path).replace("\\", "/"):
        continue
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        syntax_errors.append(f"{path.relative_to(ROOT)}:{exc.lineno}:{exc.msg}")
check("Python syntax", not syntax_errors, "; ".join(syntax_errors) if syntax_errors else "all parsed")

passed = sum(1 for _, ok, _ in checks if ok)
report = {"version": "9.0.1", "architecture": "standalone_static_reference_then_v9_runtime", "passed": passed, "total": len(checks), "checks": [{"name": n, "passed": ok, "detail": d} for n, ok, d in checks]}
out = ROOT / "docs" / "evidence" / "v9-standalone-contract-report.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nKết quả V9 standalone: {passed}/{len(checks)}")
raise SystemExit(0 if passed == len(checks) else 1)
