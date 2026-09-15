from __future__ import annotations

import base64
import copy
import hmac
import json
import asyncio
import logging
import io
import math
import os
import re
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import psycopg
import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error

from app.ml_pipeline import (
    FARM_PROFILES,
    FEATURES,
    MODEL_SPECS,
    MODEL_VERSION,
    farm_view_report,
    load_shared_model_report,
    load_shared_suite_report,
    profile_feature_values,
    shared_model_path,
    train_shared_suite,
)
from app.dataset_builder import (
    build_database_training_dataset,
    build_reference_bootstrap_dataset,
    build_v9_blended_training_dataset,
)
from app.runtime_export import export_customer_training_snapshot, export_runtime_snapshot
from app.customer_ml_automation import (
    GROUP_POLICIES,
    active_manifest_path,
    cleanup_legacy_shared_layout,
    list_customer_group_counts,
    load_active_manifest,
    load_shared_active_manifest,
    load_watermark,
    prepare_shared_customer_pool_dataset,
    prune_shared_history,
    publish_shared_candidate,
    train_customer_suite,
    training_decision,
    write_human_training_report,
)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DEFAULT_HOURS = int(os.getenv("AI_TRAINING_WINDOW_HOURS", "24"))
FORECAST_MINUTES = int(os.getenv("AI_FORECAST_MINUTES", "30"))
MIN_TRAINING_SAMPLES = int(os.getenv("AI_MIN_TRAINING_SAMPLES", "20"))
ARTIFACT_ROOT = Path(os.getenv("MODEL_ARTIFACT_DIR", "/models"))
DATA_EXPORT_ROOT = Path(os.getenv("ML_DATA_EXPORT_DIR", "/data/ml"))
RUNTIME_CSV_ROOT = Path(os.getenv("RUNTIME_CSV_EXPORT_DIR", "/data/runtime_csv"))
AUTO_TRAIN = os.getenv("AI_AUTO_TRAIN", "true").lower() in {"1", "true", "yes"}
TRAIN_DAYS = int(os.getenv("AI_TRAIN_DAYS", "14"))
TRAIN_ESTIMATORS = int(os.getenv("AI_TRAIN_ESTIMATORS", "90"))
FORCE_RETRAIN_ON_START = os.getenv("AI_FORCE_RETRAIN_ON_START", "false").lower() in {"1", "true", "yes"}
IDENTITY_URL = os.getenv("IDENTITY_URL", "http://localhost:8100")
INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")
INFERENCE_INTERVAL_SECONDS = max(60, int(os.getenv("AI_INFERENCE_INTERVAL_SECONDS", "120")))
AUTO_INFERENCE = os.getenv("AI_AUTO_INFERENCE", "true").lower() in {"1", "true", "yes"}
REFERENCE_BOOTSTRAP_PARQUET = Path(
    os.getenv(
        "AI_REFERENCE_BOOTSTRAP_PARQUET",
        os.getenv("AI_REFERENCE_BOOTSTRAP_CSV", "/research-data/reference/reference_bootstrap_training.parquet"),
    )
)
REFERENCE_LOCK_PATH = Path(os.getenv("AI_REFERENCE_LOCK_PATH", "/research-data/reference/reference_lock.json"))
TRAIN_RETRY_SECONDS = max(30, int(os.getenv("AI_TRAIN_RETRY_SECONDS", "60")))
RETRAIN_INTERVAL_HOURS = max(1, int(os.getenv("AI_RETRAIN_INTERVAL_HOURS", "6")))
RETRAIN_MIN_NEW_ROWS = max(1000, int(os.getenv("AI_RETRAIN_MIN_NEW_ROWS", "50000")))
RETRAIN_POLL_SECONDS = max(60, int(os.getenv("AI_RETRAIN_POLL_SECONDS", "120")))
REFERENCE_ANCHOR_RATIO = min(0.45, max(0.05, float(os.getenv("AI_REFERENCE_ANCHOR_RATIO", "0.25"))))
RUNTIME_ONLY_TRAINING = os.getenv("AI_RUNTIME_ONLY_TRAINING", "true").lower() in {"1", "true", "yes"}
# Legacy switch remains for migration only. The scalable default is one shared
# suite trained from isolated per-customer CSV snapshots.
PER_CUSTOMER_TRAINING = os.getenv("AI_PER_CUSTOMER_TRAINING", "false").lower() in {"1", "true", "yes"}
STARTUP_DELAY_SECONDS = max(0, int(os.getenv("AI_STARTUP_DELAY_SECONDS", "3")))
LOGGER = logging.getLogger("nextfarm.ai")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # The HTTP API must remain available even while model artifacts are not yet
    # writable/ready. Training state exposes the error instead of killing Uvicorn.
    try:
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        cleanup_legacy_shared_layout(ARTIFACT_ROOT)
        prune_shared_history(ARTIFACT_ROOT)
        start_auto_training()
        start_inference_worker()
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Không khởi tạo được worker AI: %s", exc)
        training_state.update({"running": False, "ready": False, "last_error": str(exc)})
    yield


app = FastAPI(title="NextFarm AI Analytics Service", version="10.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOW_ORIGINS",
            "http://localhost:8080,http://localhost:8081,http://localhost:8082",
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

METRIC_LABELS = {
    "soil_moisture": "Độ ẩm đất",
    "temperature": "Nhiệt độ",
    "air_humidity": "Độ ẩm không khí",
    "ec": "EC",
    "ph": "pH",
    "flow_rate": "Lưu lượng",
}


def _require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("Thiếu DATABASE_URL; hãy chạy dịch vụ qua Docker Compose sau scripts/setup_v9_env.cmd.")
    return DATABASE_URL


def conn():
    return psycopg.connect(_require_database_url(), row_factory=dict_row)


def _verify_api_user(request: Request) -> dict[str, Any] | None:
    authorization = request.headers.get("authorization")
    internal = request.headers.get("x-internal-service-key")
    # Ưu tiên token người dùng để giữ kiểm tra tenant xuyên suốt chuỗi service.
    if not authorization and INTERNAL_SERVICE_KEY and internal and hmac.compare_digest(internal, INTERNAL_SERVICE_KEY):
        return None
    if not authorization:
        raise HTTPException(status_code=401, detail="API AI yêu cầu đăng nhập.")
    try:
        with httpx.Client(timeout=8) as client:
            response = client.post(f"{IDENTITY_URL}/auth/verify", headers={"Authorization": authorization})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Không kết nối được dịch vụ xác thực.") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập không hợp lệ.")
    return response.json()["user"]


def _analytics_farm_id(request: Request) -> str | None:
    for pattern in (r"^/farms/([^/]+)", r"^/ml/predict/([^/]+)", r"^/ml/reports/([^/]+)", r"^/ml/charts/([^/]+)"):
        match = re.match(pattern, request.url.path)
        if match:
            return match.group(1)
    return request.query_params.get("farm_id")


def _can_read(user: dict[str, Any] | None, farm_id: str) -> bool:
    return user is None or any(x.get("farm_id") == farm_id and x.get("can_read") for x in user.get("farms", []))


@app.middleware("http")
async def analytics_auth_middleware(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    try:
        user = _verify_api_user(request)
        request.state.user = user
        farm_id = _analytics_farm_id(request)
        if farm_id and not _can_read(user, farm_id):
            raise HTTPException(status_code=403, detail="Tài khoản không có quyền truy cập AI của vườn này.")
        technician_only = request.url.path in {"/ml/train", "/ml/reports", "/ml/export-runtime-csv"} or (request.url.path == "/models/status" and not farm_id) or (request.url.path == "/ml/status" and not farm_id)
        if technician_only and user is not None and user.get("role") != "technician":
            raise HTTPException(status_code=403, detail="Chỉ kỹ thuật viên được thao tác phạm vi model toàn hệ thống.")
        return await call_next(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def safe_metric(metric: str) -> str:
    if metric not in METRIC_LABELS:
        raise HTTPException(status_code=400, detail="Chỉ số không được hỗ trợ.")
    return metric


def fetch_zone(cur, farm_id: str, zone: str | None) -> dict[str, Any] | None:
    if zone:
        cur.execute(
            "SELECT * FROM farm_db.zones WHERE farm_id=%s AND upper(zone_code)=upper(%s)",
            (farm_id, zone),
        )
    else:
        cur.execute("SELECT * FROM farm_db.zones WHERE farm_id=%s ORDER BY zone_code LIMIT 2", (farm_id,))
        rows = cur.fetchall()
        if len(rows) > 1:
            raise HTTPException(status_code=409, detail={"code": "ZONE_CONTEXT_REQUIRED", "message": "Vườn có nhiều khu; hãy chọn zone trước khi phân tích."})
        return rows[0] if rows else None
    return cur.fetchone()


def fetch_series(farm_id: str, metric: str, zone: str | None, hours: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metric = safe_metric(metric)
    hours = max(1, min(hours, 168))
    with conn() as db, db.cursor() as cur:
        zone_row = fetch_zone(cur, farm_id, zone)
        if not zone_row:
            raise HTTPException(status_code=404, detail="Không tìm thấy khu trong vườn.")
        cur.execute(
            """
            SELECT r.value,r.unit,r.quality,r.observed_at,s.sensor_name,r.data_origin,r.source_dataset,r.simulation_profile_version
            FROM farm_db.sensor_readings r
            JOIN farm_db.sensors s ON s.sensor_id=r.sensor_id
            WHERE r.farm_id=%s AND r.zone_id=%s AND r.metric_type=%s
              AND r.observed_at >= now() - (%s || ' hours')::interval
            ORDER BY r.observed_at
            """,
            (farm_id, zone_row["zone_id"], metric, hours),
        )
        rows = cur.fetchall()
    items = [
        {
            "value": float(r["value"]),
            "unit": r["unit"],
            "quality": r["quality"],
            "observed_at": r["observed_at"],
            "sensor_name": r["sensor_name"],
            "data_origin": r.get("data_origin"),
            "source_dataset": r.get("source_dataset"),
            "simulation_profile_version": r.get("simulation_profile_version"),
        }
        for r in rows
    ]
    return zone_row, items


def target_range(zone: dict[str, Any], metric: str) -> tuple[float | None, float | None]:
    if metric == "soil_moisture":
        return _float(zone.get("moisture_min")), _float(zone.get("moisture_max"))
    if metric == "ec":
        return _float(zone.get("ec_min")), _float(zone.get("ec_max"))
    if metric == "ph":
        return _float(zone.get("ph_min")), _float(zone.get("ph_max"))
    return None, None


def _float(value: Any) -> float | None:
    return float(value) if value is not None else None


def prepare_xy(items: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, datetime]:
    first = items[0]["observed_at"]
    x = np.array([[(p["observed_at"] - first).total_seconds() / 60.0] for p in items], dtype=float)
    y = np.array([p["value"] for p in items], dtype=float)
    return x, y, first


def train_models(farm_id: str, zone: dict[str, Any], metric: str, items: list[dict[str, Any]], hours: int) -> dict[str, Any]:
    """Phân tích online nhẹ, không lưu model riêng cho từng farm.

    10 model nghiệp vụ chính được train dùng chung ở pipeline /ml. Phần này chỉ
    tính xu hướng và điểm bất thường ngay trên cửa sổ dữ liệu mới nhất để vẽ chart.
    """
    if len(items) < MIN_TRAINING_SAMPLES:
        return {
            "ready": False,
            "reason": f"Cần tối thiểu {MIN_TRAINING_SAMPLES} mẫu, hiện có {len(items)} mẫu.",
            "sample_count": len(items),
        }

    x, y, _ = prepare_xy(items)
    regression = LinearRegression().fit(x, y)
    fitted = regression.predict(x)
    mae = float(mean_absolute_error(y, fitted))
    slope_per_hour = float(regression.coef_[0] * 60.0)

    delta = np.r_[0.0, np.diff(y)]
    features = np.column_stack([y, delta])
    contamination = min(0.08, max(0.02, 3 / max(len(y), 1)))
    detector = IsolationForest(n_estimators=120, contamination=contamination, random_state=42)
    labels = detector.fit_predict(features)
    scores = -detector.score_samples(features)
    anomalies = [
        {
            "index": int(i),
            "observed_at": items[i]["observed_at"],
            "value": float(y[i]),
            "score": float(scores[i]),
        }
        for i in range(len(y))
        if labels[i] == -1
    ]

    future_x = float(x[-1, 0] + FORECAST_MINUTES)
    forecast = float(regression.predict(np.array([[future_x]]))[0])
    latest = float(y[-1])
    confidence = max(0.35, min(0.97, 1.0 - mae / max(np.std(y) + 1e-6, 1.0)))
    return {
        "ready": True,
        "analyzer_id": "online_trend_anomaly_v1",
        "model_type": "Online statistical trend + Isolation Forest (không lưu artifact theo farm)",
        "scope_type": "request_window",
        "sample_count": len(items),
        "mae": round(mae, 3),
        "slope_per_hour": round(slope_per_hour, 3),
        "forecast_minutes": FORECAST_MINUTES,
        "forecast_value": round(forecast, 3),
        "latest_value": round(latest, 3),
        "confidence": round(confidence, 3),
        "anomalies": anomalies[-10:],
        "anomaly_count": len(anomalies),
    }

def device_context(farm_id: str) -> dict[str, Any]:
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT d.device_id,d.device_name,st.online,st.last_seen_at,st.observed_at
            FROM farm_db.devices d
            LEFT JOIN LATERAL (
              SELECT online,last_seen_at,observed_at FROM farm_db.device_status ds
              WHERE ds.device_id=d.device_id AND ds.port_id IS NULL
              ORDER BY observed_at DESC LIMIT 1
            ) st ON true
            WHERE d.farm_id=%s AND d.active=true
            ORDER BY d.device_name
            """,
            (farm_id,),
        )
        devices = cur.fetchall()
        cur.execute(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE result='failed') AS failed,
                   coalesce(sum(water_liters),0) AS liters
            FROM farm_db.irrigation_runs
            WHERE farm_id=%s AND started_at >= now()-interval '24 hours'
            """,
            (farm_id,),
        )
        irrigation = cur.fetchone()
    now = datetime.now(timezone.utc)
    offline = []
    for d in devices:
        observed = d.get("observed_at")
        stale = not observed or (now - observed).total_seconds() > 60
        if not d.get("online") or stale:
            offline.append({**d, "stale": stale})
    return {
        "devices": devices,
        "offline_devices": offline,
        "irrigation": {
            "total": irrigation["total"],
            "failed": irrigation["failed"],
            "liters": float(irrigation["liters"]),
        },
    }


def recommendation(zone: dict[str, Any], metric: str, model: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    latest = model.get("latest_value")
    forecast = model.get("forecast_value")
    low, high = target_range(zone, metric)
    offline = context["offline_devices"]
    anomaly_count = model.get("anomaly_count", 0)
    slope = model.get("slope_per_hour", 0.0)
    confidence = model.get("confidence", 0.0)

    if offline:
        names = ", ".join(d["device_name"] for d in offline)
        return {
            "severity": "urgent",
            "decision": "human_required",
            "title": "Cần kỹ thuật viên kiểm tra tại hiện trường",
            "summary": f"Thiết bị {names} đang offline hoặc không có bản tin mới. AI không thể xác nhận nguồn điện, dây mạng hay tình trạng vật lý từ xa.",
            "actions": [
                "Kiểm tra nguồn điện và đèn trạng thái thiết bị.",
                "Kiểm tra Wi‑Fi/Ethernet và gateway tại vườn.",
                "Sau khi có bản tin mới, AI sẽ tự phân tích lại dữ liệu.",
            ],
            "confidence": confidence,
        }

    if metric == "soil_moisture" and latest is not None and low is not None and latest < low:
        if forecast is not None and forecast < low and slope < 0:
            return {
                "severity": "high",
                "decision": "ai_can_handle",
                "title": "Độ ẩm thấp và còn xu hướng giảm",
                "summary": f"Giá trị hiện tại {latest:.1f}% thấp hơn ngưỡng {low:.1f}%; mô hình dự báo khoảng {forecast:.1f}% sau {FORECAST_MINUTES} phút.",
                "actions": [
                    "Đối chiếu ca tưới gần nhất và lưu lượng nước.",
                    "Theo dõi lại trong 15–30 phút sau ca tưới.",
                    "AI chỉ tạo ticket khi lưu lượng bằng 0, thiết bị offline hoặc độ ẩm không phục hồi.",
                ],
                "confidence": confidence,
            }
        return {
            "severity": "warning",
            "decision": "observe",
            "title": "Độ ẩm dưới ngưỡng",
            "summary": f"Giá trị hiện tại {latest:.1f}% thấp hơn ngưỡng {low:.1f}%, nhưng chưa đủ bằng chứng về lỗi vật lý.",
            "actions": ["Theo dõi xu hướng 30 phút.", "Kiểm tra lịch tưới và lưu lượng trước khi yêu cầu kỹ thuật viên."],
            "confidence": confidence,
        }

    if metric == "flow_rate" and latest is not None and latest < 0.5:
        return {
            "severity": "urgent",
            "decision": "human_required",
            "title": "Lưu lượng gần bằng 0",
            "summary": "AI phát hiện không có dòng nước đáng kể. Nguyên nhân có thể là bơm, nguồn nước, van cơ, đường ống hoặc cảm biến; cần người kiểm tra thực tế.",
            "actions": ["Dừng kéo dài ca tưới nếu hệ thống cho phép.", "Kiểm tra bơm, bể nước, van cơ, bộ lọc và đường ống."],
            "confidence": confidence,
        }

    if anomaly_count > max(3, int(model.get("sample_count", 0) * 0.06)):
        return {
            "severity": "warning",
            "decision": "observe",
            "title": "Dữ liệu có nhiều điểm bất thường",
            "summary": f"Mô hình phát hiện {anomaly_count} điểm lệch khỏi phân bố thường gặp trong cửa sổ phân tích.",
            "actions": ["So sánh với lịch tưới và thời tiết.", "Kiểm tra chất lượng cảm biến nếu bất thường lặp lại."],
            "confidence": confidence,
        }

    status = "ổn định"
    if high is not None and latest is not None and latest > high:
        status = "cao hơn ngưỡng"
    return {
        "severity": "info",
        "decision": "ai_can_handle",
        "title": "Dữ liệu đang được AI theo dõi",
        "summary": f"Chỉ số hiện {status}; mô hình chưa phát hiện tình huống cần chuyển ngay cho kỹ thuật viên.",
        "actions": ["Tiếp tục theo dõi tự động.", "AI sẽ cảnh báo khi xu hướng vượt ngưỡng hoặc xuất hiện bất thường."],
        "confidence": confidence,
    }


def persist_insight(farm_id: str, zone_id: str | None, metric: str, rec: dict[str, Any], model: dict[str, Any]) -> None:
    try:
        with conn() as db, db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO support_db.ai_insight_logs(
                  farm_id,zone_id,metric_type,insight_type,severity,summary,details,decision,confidence
                ) VALUES (%s,%s,%s,'smart_analysis',%s,%s,%s,%s,%s)
                """,
                (
                    farm_id, zone_id, metric, rec["severity"], rec["summary"],
                    Jsonb({"recommendation": rec, "model": model}), rec["decision"], rec.get("confidence"),
                ),
            )
            db.commit()
    except Exception:
        pass


def analyze(farm_id: str, metric: str, zone: str | None, hours: int) -> dict[str, Any]:
    zone_row, items = fetch_series(farm_id, metric, zone, hours)
    if not items:
        return {
            "available": False,
            "farm_id": farm_id,
            "zone_code": zone_row["zone_code"],
            "metric": metric,
            "reason": "Chưa có dữ liệu để huấn luyện mô hình.",
        }
    model = train_models(farm_id, zone_row, metric, items, hours)
    if not model.get("ready"):
        return {
            "available": True,
            "farm_id": farm_id,
            "zone_code": zone_row["zone_code"],
            "metric": metric,
            "unit": items[-1]["unit"],
            "model": model,
            "recommendation": {
                "severity": "info",
                "decision": "observe",
                "title": "Đang thu thập dữ liệu học",
                "summary": model["reason"],
                "actions": ["Tiếp tục để hệ thống sinh dữ liệu tự động."],
                "confidence": 0.0,
            },
        }
    context = device_context(farm_id)
    rec = recommendation(zone_row, metric, model, context)
    persist_insight(farm_id, zone_row["zone_id"], metric, rec, model)
    return {
        "available": True,
        "farm_id": farm_id,
        "zone_id": zone_row["zone_id"],
        "zone_code": zone_row["zone_code"],
        "zone_name": zone_row["zone_name"],
        "metric": metric,
        "metric_label": METRIC_LABELS[metric],
        "unit": items[-1]["unit"],
        "observed_at": items[-1]["observed_at"],
        "target_min": target_range(zone_row, metric)[0],
        "target_max": target_range(zone_row, metric)[1],
        "model": model,
        "recommendation": rec,
        "context": context,
    }


def chart_base64(farm_id: str, metric: str, zone: str | None, hours: int) -> dict[str, Any]:
    analysis = analyze(farm_id, metric, zone, hours)
    if not analysis.get("available"):
        raise HTTPException(status_code=404, detail=analysis.get("reason", "Không có dữ liệu."))
    zone_row, items = fetch_series(farm_id, metric, analysis["zone_code"], hours)
    times = [p["observed_at"] for p in items]
    values = [p["value"] for p in items]
    unit = items[-1]["unit"]

    fig, ax = plt.subplots(figsize=(10, 4.8), dpi=145)
    origins = {str(p.get("data_origin") or "missing_provenance") for p in items}
    simulated_only = bool(origins) and origins <= {"simulated_device_calibrated_v9"}
    series_label = "Telemetry thiết bị mô phỏng đã hiệu chỉnh" if simulated_only else "Dữ liệu có provenance"
    ax.plot(times, values, linewidth=2, label=series_label)
    low, high = target_range(zone_row, metric)
    if low is not None and high is not None:
        ax.axhspan(low, high, alpha=0.12, label=f"Ngưỡng mục tiêu {low:g}–{high:g}")
    model = analysis.get("model", {})
    if model.get("ready"):
        future_time = times[-1] + timedelta(minutes=model["forecast_minutes"])
        ax.plot(
            [times[-1], future_time],
            [values[-1], model["forecast_value"]],
            linestyle="--",
            linewidth=2,
            label=f"Dự báo {model['forecast_minutes']} phút",
        )
        anomaly_indexes = {a["index"] for a in model.get("anomalies", [])}
        anomaly_times = [times[i] for i in anomaly_indexes if 0 <= i < len(times)]
        anomaly_values = [values[i] for i in anomaly_indexes if 0 <= i < len(values)]
        if anomaly_times:
            ax.scatter(anomaly_times, anomaly_values, marker="x", s=45, label="Điểm bất thường")
    ax.set_title(f"{METRIC_LABELS[metric]} – Khu {analysis['zone_code']} ({hours} giờ)")
    ax.set_ylabel(unit)
    ax.set_xlabel("Thời gian")
    ax.grid(True, alpha=0.22)
    ax.legend(loc="best")
    fig.autofmt_xdate()
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    filename = f"nextfarm_{farm_id}_{analysis['zone_code']}_{metric}_{hours}h.png"
    return {
        "type": "image",
        "mime_type": "image/png",
        "base64": encoded,
        "filename": filename,
        "title": f"{METRIC_LABELS[metric]} khu {analysis['zone_code']} trong {hours} giờ",
        "analysis": analysis,
    }


@app.get("/health")
def health():
    suite = load_shared_suite_report(ARTIFACT_ROOT) or {}
    active = load_shared_active_manifest(ARTIFACT_ROOT)
    metadata = suite.get("dataset_metadata") or {}
    return {
        "service": "ai-analytics-service",
        "status": "ok",
        "models": ["10 shared RandomForest model families", "Online trend/anomaly analyzer"],
        "architecture": "shared_base_models_with_customer_calibration",
        "training_mode": "per-customer CSV snapshots -> temporal split -> shared RandomForest/ExtraTrees candidates -> quality gate -> active manifest",
        "training_phase": training_state.get("training_phase", "waiting_reference"),
        "dataset_source": suite.get("dataset_source") or training_state.get("dataset_source"),
        "dataset_version": suite.get("dataset_version") or training_state.get("dataset_version"),
        "candidate_model_count": len(suite.get("models") or []),
        "approved_model_count": int(suite.get("approved_model_count") or 0),
        "active_model_count": len(active.get("models") or {}),
        "production_ready": bool(suite.get("production_ready", False)),
        "customer_count": int(metadata.get("customer_count") or 0),
        "customer_id_used_as_feature": bool(metadata.get("customer_id_used_as_feature", False)),
        "chat_messages_used_for_training": bool(metadata.get("chat_messages_used_for_training", False)),
        "reference_bootstrap_ready": bool(training_state.get("reference_bootstrap_ready")),
        "runtime_reading_count": _db_training_reading_count_safe(),
        "runtime_retrain_threshold": RETRAIN_MIN_NEW_ROWS,
        "startup_delay_seconds": STARTUP_DELAY_SECONDS,
    }


@app.get("/farms/{farm_id}/series")
def series(
    farm_id: str,
    metric: str = Query("soil_moisture"),
    zone: str | None = Query(default=None),
    hours: int = Query(DEFAULT_HOURS, ge=1, le=168),
):
    zone_row, items = fetch_series(farm_id, metric, zone, hours)
    return {
        "farm_id": farm_id,
        "zone_code": zone_row["zone_code"],
        "metric": metric,
        "hours": hours,
        "items": items,
    }


@app.get("/farms/{farm_id}/analyze")
def analyze_endpoint(
    farm_id: str,
    metric: str = Query("soil_moisture"),
    zone: str | None = Query(default=None),
    hours: int = Query(DEFAULT_HOURS, ge=1, le=168),
):
    return analyze(farm_id, metric, zone, hours)


@app.get("/farms/{farm_id}/chart")
def chart_endpoint(
    farm_id: str,
    metric: str = Query("soil_moisture"),
    zone: str | None = Query(default=None),
    hours: int = Query(DEFAULT_HOURS, ge=1, le=168),
):
    return chart_base64(farm_id, metric, zone, hours)


@app.get("/farms/{farm_id}/smart-summary")
def smart_summary(farm_id: str):
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT zone_code FROM farm_db.zones WHERE farm_id=%s ORDER BY zone_code", (farm_id,))
        zones = [r["zone_code"] for r in cur.fetchall()]
    results = []
    for zone in zones:
        try:
            results.append(analyze(farm_id, "soil_moisture", zone, DEFAULT_HOURS))
        except Exception as exc:  # noqa: BLE001
            results.append({"zone_code": zone, "available": False, "reason": str(exc)})
    priority = {"urgent": 4, "high": 3, "warning": 2, "info": 1}
    results.sort(key=lambda r: priority.get(r.get("recommendation", {}).get("severity", "info"), 0), reverse=True)
    human_required = [r for r in results if r.get("recommendation", {}).get("decision") == "human_required"]
    top = results[0] if results else None
    return {
        "farm_id": farm_id,
        "generated_at": datetime.now(timezone.utc),
        "zone_results": results,
        "human_required_count": len(human_required),
        "top_recommendation": top.get("recommendation") if top else None,
        "ai_scope": {
            "can_handle": [
                "Phân tích xu hướng và bất thường",
                "Dự báo ngắn hạn",
                "Vẽ và xuất biểu đồ",
                "So sánh ngưỡng theo từng khu",
                "Đề xuất kiểm tra và tự theo dõi lại",
            ],
            "requires_human": [
                "Mất điện hoặc nguồn thiết bị",
                "Đứt dây, hỏng van, hỏng bơm",
                "Rò rỉ, tắc đường ống hoặc thiếu nước thực tế",
                "Tình trạng hiện trường không có cảm biến xác nhận",
            ],
        },
    }


@app.get("/models/status")
def model_status(farm_id: str | None = None):
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM knowledge_db.model_registry
            WHERE scope_type='global'
            ORDER BY model_family,trained_at DESC
            """
        )
        items = cur.fetchall()
        calibrations = []
        if farm_id:
            cur.execute(
                """
                SELECT * FROM farm_db.farm_model_calibrations
                WHERE farm_id=%s ORDER BY model_family
                """,
                (farm_id,),
            )
            calibrations = cur.fetchall()
    return {
        "architecture": "multi_tenant_shared_models",
        "items": items,
        "total": len(items),
        "farm_specific_model_count": 0,
        "farm_id": farm_id,
        "calibrations": calibrations,
    }


# ============================================================
# TRAIN/TEST LAB V10.1 SHARED CUSTOMER MODELS
# Stage 1: downloaded static reference -> bootstrap model suite.
# Stage 2: V9-only device-simulated telemetry -> retrain after threshold,
#          retaining a bounded reference anchor to reduce drift.
# No previous-project database is read by this service.
# ============================================================
training_state: dict[str, Any] = {
    "running": False,
    "ready": False,
    "reference_bootstrap_ready": False,
    "training_phase": "waiting_reference",
    "last_started_at": None,
    "last_finished_at": None,
    "last_error": None,
    "total_model_artifacts": 0,
    "architecture": "shared_base_models_with_customer_calibration",
    "customers": {},
    "dataset_source": None,
    "dataset_version": None,
    "approved_model_count": 0,
    "experimental_model_count": 0,
    "production_ready": False,
    "origin_mix": {},
    "source_reading_count": 0,
    "runtime_reading_count": 0,
    "retrain_reason": None,
}
training_lock = threading.Lock()
artifact_lock = threading.RLock()


def _production_ready(_report: dict[str, Any] | None) -> bool:
    # Simulated telemetry must never self-certify as production-ready without
    # later validation against actual NextFarm hardware/field telemetry.
    return False


def _training_phase(report: dict[str, Any] | None) -> str:
    if not report:
        return "waiting_reference"
    return str(report.get("training_phase") or (report.get("dataset_metadata") or {}).get("training_phase") or "unknown")


def _db_training_reading_count() -> int:
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """SELECT count(*) AS n
               FROM farm_db.sensor_readings
               WHERE data_origin='simulated_device_calibrated_v9'
                 AND observed_at >= now()-(%s || ' days')::interval""",
            (TRAIN_DAYS,),
        )
        row = cur.fetchone()
    return int((row or {}).get("n") or 0)


def _db_training_reading_count_safe() -> int:
    try:
        return _db_training_reading_count()
    except Exception:
        return 0


def _rewrite_artifact_paths(report: dict[str, Any], staging_root: Path) -> dict[str, Any]:
    final = copy.deepcopy(report)
    staging_prefix = str(staging_root)
    final_prefix = str(ARTIFACT_ROOT)
    for model in final.get("models", []):
        for key in ("artifact_path", "evaluation_chart", "importance_chart", "per_farm_chart"):
            value = model.get(key)
            if isinstance(value, str) and value.startswith(staging_prefix):
                model[key] = final_prefix + value[len(staging_prefix):]
    return final


def _publish_trained_suite(staging_root: Path, report: dict[str, Any]) -> dict[str, Any]:
    staged_shared = staging_root / "shared"
    if not staged_shared.exists():
        raise RuntimeError("Phiên train không tạo thư mục shared hoàn chỉnh.")
    final_report = _rewrite_artifact_paths(report, staging_root)
    (staged_shared / "suite_report.json").write_text(json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8")
    for model in final_report.get("models", []):
        report_path = staged_shared / model["model_name"] / f"v{model['model_version']}" / "report.json"
        report_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")

    final_shared = ARTIFACT_ROOT / "shared"
    backup = ARTIFACT_ROOT / f".shared-backup-{uuid.uuid4().hex}"
    with artifact_lock:
        had_previous = final_shared.exists()
        if had_previous:
            final_shared.rename(backup)
        try:
            staged_shared.rename(final_shared)
            tmp_report = ARTIFACT_ROOT / ".shared_models_report.json.tmp"
            tmp_report.write_text(json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_report.replace(ARTIFACT_ROOT / "shared_models_report.json")
        except Exception:
            if final_shared.exists():
                shutil.rmtree(final_shared, ignore_errors=True)
            if had_previous and backup.exists():
                backup.rename(final_shared)
            raise
        else:
            shutil.rmtree(backup, ignore_errors=True)
    return final_report


def _persist_training_report(report: dict[str, Any]) -> None:
    phase = _training_phase(report)
    with conn() as db, db.cursor() as cur:
        cur.execute("DELETE FROM knowledge_db.model_registry WHERE scope_type='global'")
        for model in report.get("models", []):
            cur.execute(
                """
                INSERT INTO knowledge_db.model_registry(
                  model_id,farm_id,zone_id,metric_type,model_type,trained_at,sample_count,
                  training_window_hours,metrics,status,artifact_path,dataset_version,
                  train_count,test_count,split_strategy,feature_names,model_family,
                  model_version,scope_type,scope_key,task,artifact_uri,training_origin_mix,training_phase
                ) VALUES (%s,NULL,NULL,%s,%s,now(),%s,%s,%s,'ready',%s,%s,%s,%s,%s,%s,%s,%s,'global','all_farms',%s,%s,%s,%s)
                ON CONFLICT (model_id) DO UPDATE SET
                  trained_at=EXCLUDED.trained_at,sample_count=EXCLUDED.sample_count,
                  metrics=EXCLUDED.metrics,status='ready',artifact_path=EXCLUDED.artifact_path,
                  dataset_version=EXCLUDED.dataset_version,train_count=EXCLUDED.train_count,
                  test_count=EXCLUDED.test_count,split_strategy=EXCLUDED.split_strategy,
                  feature_names=EXCLUDED.feature_names,model_version=EXCLUDED.model_version,
                  scope_type='global',scope_key='all_farms',task=EXCLUDED.task,artifact_uri=EXCLUDED.artifact_uri,
                  training_origin_mix=EXCLUDED.training_origin_mix,training_phase=EXCLUDED.training_phase
                """,
                (
                    model["model_id"], model["model_name"], model["task"],
                    model["train_count"] + model["validation_count"] + model["test_count"],
                    TRAIN_DAYS * 24, Jsonb(model["test_metrics"]), model["artifact_path"],
                    model["dataset_version"], model["train_count"], model["test_count"], model["split_strategy"],
                    Jsonb(FEATURES), model["model_name"], model["model_version"], model["task"], model["artifact_path"],
                    Jsonb((report.get("dataset_metadata") or {}).get("origin_mix", {})), phase,
                ),
            )
            cur.execute(
                """UPDATE knowledge_db.model_registry
                   SET status=%s,deployment_status=%s,quality_gate=%s,dataset_source=%s
                   WHERE model_id=%s""",
                (model.get("deployment_status", "experimental"), model.get("deployment_status", "experimental"),
                 Jsonb(model.get("quality_gate", {})), report.get("dataset_source", "unknown"), model["model_id"]),
            )
            cur.execute(
                """
                INSERT INTO knowledge_db.model_evaluations(
                  model_id,farm_id,model_name,task,dataset_version,train_count,test_count,
                  split_time,metrics,evaluation_chart,importance_chart,evaluated_at,
                  evaluation_scope,evaluation_key,validation_count,lofo_metrics
                ) VALUES (%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),'global','all_farms',%s,%s)
                ON CONFLICT (model_id) DO UPDATE SET
                  dataset_version=EXCLUDED.dataset_version,train_count=EXCLUDED.train_count,
                  test_count=EXCLUDED.test_count,split_time=EXCLUDED.split_time,
                  metrics=EXCLUDED.metrics,evaluation_chart=EXCLUDED.evaluation_chart,
                  importance_chart=EXCLUDED.importance_chart,evaluated_at=now(),
                  evaluation_scope='global',evaluation_key='all_farms',
                  validation_count=EXCLUDED.validation_count,lofo_metrics=EXCLUDED.lofo_metrics
                """,
                (model["model_id"], model["model_name"], model["task"], model["dataset_version"],
                 model["train_count"], model["test_count"], model["validation_end"], Jsonb(model["test_metrics"]),
                 model["evaluation_chart"], model["importance_chart"], model["validation_count"],
                 Jsonb(model.get("leave_one_farm_out", {}))),
            )
            for farm_id, calibration in model.get("farm_calibrations", {}).items():
                cur.execute(
                    """
                    INSERT INTO farm_db.farm_model_calibrations(
                      farm_id,model_family,model_version,bias,scale,sample_count,metrics,updated_at
                    ) VALUES (%s,%s,%s,%s,1.0,%s,%s,now())
                    ON CONFLICT (farm_id,model_family,model_version) DO UPDATE SET
                      bias=EXCLUDED.bias,scale=EXCLUDED.scale,sample_count=EXCLUDED.sample_count,
                      metrics=EXCLUDED.metrics,updated_at=now()
                    """,
                    (farm_id, model["model_name"], model["model_version"], calibration.get("bias", 0.0),
                     calibration.get("sample_count", 0), Jsonb(calibration)),
                )
        cur.execute(
            """
            INSERT INTO farm_db.ai_training_runs(
              farm_id,dataset_version,model_count,train_count,test_count,status,detail,finished_at
            ) VALUES (NULL,%s,%s,%s,%s,'success',%s,now())
            """,
            (report["dataset_version"], report["model_count"], report["train_count"], report["test_count"],
             Jsonb({
                 "architecture": "shared_base_models_with_customer_calibration",
                 "training_phase": phase,
                 "validation_count": report["validation_count"],
                 "generalization_test": report["generalization_test"],
                 "shared_artifacts": report["total_model_artifacts"],
                 "approved_model_count": report.get("approved_model_count", 0),
                 "experimental_model_count": report.get("experimental_model_count", 0),
                 "production_ready": False,
                 "origin_mix": (report.get("dataset_metadata") or {}).get("origin_mix", {}),
                 "raw_reading_count": (report.get("dataset_metadata") or {}).get("raw_reading_count", 0),
             })),
        )
        db.commit()


def _mark_shared_customer_watermarks(report: dict[str, Any]) -> None:
    """Ghi mốc dữ liệu từng khách sau khi một bộ 10 model nền train thành công."""
    sources = (report.get("dataset_metadata") or {}).get("customer_sources", [])
    if not sources:
        return
    active_count = len(load_shared_active_manifest(ARTIFACT_ROOT).get("models", {}))
    with conn() as db, db.cursor() as cur:
        for source in sources:
            cur.execute(
                """INSERT INTO knowledge_db.customer_ml_watermarks(
                     customer_id,last_snapshot_id,last_dataset_version,last_group_counts,
                     last_training_status,last_finished_at,last_error,active_model_count,updated_at
                   ) VALUES (%s,%s,%s,%s,'success',now(),NULL,%s,now())
                   ON CONFLICT(customer_id) DO UPDATE SET
                     last_snapshot_id=EXCLUDED.last_snapshot_id,
                     last_dataset_version=EXCLUDED.last_dataset_version,
                     last_group_counts=EXCLUDED.last_group_counts,
                     last_training_status='success',last_finished_at=now(),last_error=NULL,
                     active_model_count=EXCLUDED.active_model_count,updated_at=now()""",
                (
                    source["customer_id"], source.get("snapshot_id"), report["dataset_version"],
                    Jsonb(source.get("raw_group_counts", {})), active_count,
                ),
            )
        db.commit()


def _choose_training_phase(force_phase: str | None = None) -> str:
    if force_phase in {"bootstrap_reference", "runtime_retrain"}:
        return force_phase
    suite = load_shared_suite_report(ARTIFACT_ROOT)
    if not suite or not _artifacts_ready():
        return "runtime_retrain" if _db_training_reading_count_safe() >= RETRAIN_MIN_NEW_ROWS else "bootstrap_reference"
    if _db_training_reading_count_safe() >= RETRAIN_MIN_NEW_ROWS:
        return "runtime_retrain"
    return "bootstrap_reference"


def _run_training(_requested_farm_id: str | None = None, force_phase: str | None = None) -> None:
    if not training_lock.acquire(blocking=False):
        return
    try:
        phase = _choose_training_phase(force_phase)
        training_state.update({
            "running": True, "ready": False, "training_phase": phase,
            "last_started_at": datetime.now(timezone.utc).isoformat(), "last_error": None,
            "runtime_reading_count": _db_training_reading_count_safe(),
        })
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        staging_root = ARTIFACT_ROOT / ".training" / uuid.uuid4().hex
        try:
            if phase == "bootstrap_reference":
                dataset_meta = build_reference_bootstrap_dataset(
                    _require_database_url(), ARTIFACT_ROOT, REFERENCE_BOOTSTRAP_PARQUET, REFERENCE_LOCK_PATH
                )
                training_frame = dataset_meta.pop("frame")
                dataset_source = "reference_bootstrap"
            else:
                if _db_training_reading_count() < RETRAIN_MIN_NEW_ROWS:
                    raise RuntimeError(
                        f"Telemetry runtime chưa đủ ngưỡng retrain: cần {RETRAIN_MIN_NEW_ROWS} readings."
                    )
                if RUNTIME_ONLY_TRAINING:
                    counts_by_customer = list_customer_group_counts(_require_database_url())
                    dataset_meta = prepare_shared_customer_pool_dataset(
                        _require_database_url(), ARTIFACT_ROOT, counts_by_customer,
                        days=TRAIN_DAYS, freq_minutes=15,
                    )
                    dataset_source = "v10_per_customer_csv_pool"
                else:
                    dataset_meta = build_v9_blended_training_dataset(
                        _require_database_url(), ARTIFACT_ROOT, REFERENCE_BOOTSTRAP_PARQUET, REFERENCE_LOCK_PATH,
                        lookback_days=TRAIN_DAYS, freq_minutes=15, reference_anchor_ratio=REFERENCE_ANCHOR_RATIO,
                    )
                    dataset_source = "v9_runtime_blend"
                training_frame = dataset_meta.pop("frame")
            dataset_meta["training_phase"] = phase
            report = train_shared_suite(
                staging_root, days=TRAIN_DAYS, estimators=TRAIN_ESTIMATORS, run_lofo=True,
                training_frame=training_frame, dataset_version=dataset_meta.get("dataset_version"),
                dataset_source=dataset_source, dataset_metadata=dataset_meta,
                evidence_root=ARTIFACT_ROOT / "data" / "shared" / "processed",
                published_artifact_root=(
                    ARTIFACT_ROOT / "shared" / "candidates" / dataset_meta.get("dataset_version", "pending")
                ),
                scope_type="global",
                scope_key="all_customers",
                generalization_column=("customer_id" if dataset_source == "v10_per_customer_csv_pool" else "farm_id"),
                generalization_label=("khách hàng" if dataset_source == "v10_per_customer_csv_pool" else "vườn"),
                minimum_generalization_groups=3,
            )
            report["training_phase"] = phase
            report["production_ready"] = False
            report = publish_shared_candidate(ARTIFACT_ROOT, staging_root, report)
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)
        _persist_training_report(report)
        _mark_shared_customer_watermarks(report)
        write_human_training_report(ARTIFACT_ROOT, report)
        training_state.update({
            "running": False, "ready": True, "reference_bootstrap_ready": True,
            "training_phase": phase, "last_finished_at": datetime.now(timezone.utc).isoformat(),
            "total_model_artifacts": report["total_model_artifacts"], "last_error": None,
            "dataset_source": report.get("dataset_source"), "dataset_version": report.get("dataset_version"),
            "approved_model_count": report.get("approved_model_count", 0),
            "experimental_model_count": report.get("experimental_model_count", 0), "production_ready": False,
            "origin_mix": (report.get("dataset_metadata") or {}).get("origin_mix", {}),
            "source_reading_count": int((report.get("dataset_metadata") or {}).get("raw_reading_count", 0) or 0),
            "runtime_reading_count": _db_training_reading_count_safe(),
        })
    except Exception as exc:  # noqa: BLE001
        training_state.update({
            "running": False, "ready": bool(load_shared_suite_report(ARTIFACT_ROOT)),
            "last_finished_at": datetime.now(timezone.utc).isoformat(), "last_error": str(exc),
        })
        LOGGER.exception("V9 training failed: %s", exc)
    finally:
        training_lock.release()


def _artifacts_ready() -> bool:
    with artifact_lock:
        suite = load_shared_suite_report(ARTIFACT_ROOT)
        if not suite:
            return False
        if suite.get("dataset_source") not in {
            "reference_bootstrap", "v9_runtime_blend", "v10_runtime_database",
            "v10_per_customer_csv_pool",
        }:
            return False
        if _training_phase(suite) not in {"bootstrap_reference", "runtime_retrain"}:
            return False
        active = load_shared_active_manifest(ARTIFACT_ROOT)
        active_paths_ok = all(
            Path(item.get("artifact_path", "__missing__")).exists()
            for item in active.get("models", {}).values()
        )
        candidate_paths_ok = suite.get("model_count") == len(MODEL_SPECS) and all(
            Path(item.get("artifact_path", "__missing__")).exists()
            for item in suite.get("models", [])
        )
        # Một phiên train hoàn tất nhưng 0 candidate đạt gate vẫn là trạng thái
        # hợp lệ; inference sẽ không dùng model nào và scheduler chờ dữ liệu mới.
        return active_paths_ok and candidate_paths_ok


def _training_scheduler_loop() -> None:
    if STARTUP_DELAY_SECONDS:
        threading.Event().wait(STARTUP_DELAY_SECONDS)
    force_once = FORCE_RETRAIN_ON_START
    while True:
        try:
            runtime_count = _db_training_reading_count()
            training_state["runtime_reading_count"] = runtime_count
            suite = load_shared_suite_report(ARTIFACT_ROOT) if _artifacts_ready() else None
            counts_by_customer = list_customer_group_counts(_require_database_url())
            decisions = {
                customer_id: training_decision(
                    counts, load_watermark(_require_database_url(), customer_id)
                )
                for customer_id, counts in counts_by_customer.items()
            }
            eligible_customers = sorted(
                customer_id for customer_id, decision in decisions.items()
                if decision["eligible"]
            )
            training_state["customer_thresholds"] = decisions
            reason = None
            target_phase = None
            if not suite and runtime_count >= RETRAIN_MIN_NEW_ROWS:
                reason, target_phase = "initial_per_customer_csv_pool", "runtime_retrain"
            elif not suite:
                reason, target_phase = "initial_static_reference_bootstrap", "bootstrap_reference"
            elif force_once:
                target_phase = "runtime_retrain" if runtime_count >= RETRAIN_MIN_NEW_ROWS else "bootstrap_reference"
                reason = "force_retrain_on_start"
            elif eligible_customers:
                reason = "customer_group_threshold:" + ",".join(eligible_customers)
                target_phase = "runtime_retrain"
            if reason and target_phase:
                force_once = False
                training_state["retrain_reason"] = reason
                _run_training(force_phase=target_phase)
                if not _artifacts_ready():
                    threading.Event().wait(TRAIN_RETRY_SECONDS)
                    continue
        except Exception as exc:  # noqa: BLE001
            training_state["last_error"] = f"Scheduler: {exc}"
        threading.Event().wait(RETRAIN_POLL_SECONDS)


def start_auto_training() -> None:
    if PER_CUSTOMER_TRAINING:
        if AUTO_TRAIN:
            threading.Thread(
                target=_customer_training_scheduler_loop,
                daemon=True,
                name="nextfarm-per-customer-training",
            ).start()
        return
    suite = load_shared_suite_report(ARTIFACT_ROOT)
    if _artifacts_ready() and not FORCE_RETRAIN_ON_START:
        try:
            _persist_training_report(suite)
            training_state.update({
                "ready": True, "reference_bootstrap_ready": True, "training_phase": _training_phase(suite),
                "total_model_artifacts": suite["total_model_artifacts"], "last_finished_at": suite.get("trained_at"),
                "last_error": None, "dataset_source": suite.get("dataset_source"), "dataset_version": suite.get("dataset_version"),
                "approved_model_count": suite.get("approved_model_count", 0),
                "experimental_model_count": suite.get("experimental_model_count", 0), "production_ready": False,
                "origin_mix": (suite.get("dataset_metadata") or {}).get("origin_mix", {}),
                "source_reading_count": int((suite.get("dataset_metadata") or {}).get("raw_reading_count", 0) or 0),
                "runtime_reading_count": _db_training_reading_count_safe(),
            })
        except Exception as exc:  # noqa: BLE001
            training_state["last_error"] = f"Không đăng ký được artifact có sẵn: {exc}"
    if AUTO_TRAIN:
        threading.Thread(target=_training_scheduler_loop, daemon=True, name="nextfarm-v9-two-stage-training").start()


def _customer_id_for_farm(farm_id: str) -> str:
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT customer_id FROM farm_db.farms WHERE farm_id=%s", (farm_id,))
        row = cur.fetchone()
    if not row or not row.get("customer_id"):
        raise HTTPException(status_code=404, detail="Không tìm thấy khách hàng sở hữu vườn.")
    return str(row["customer_id"])


def _run_one_customer_training(customer_id: str, counts: dict[str, int], reason: str) -> None:
    customer_state = training_state.setdefault("customers", {}).setdefault(customer_id, {})
    customer_state.update({
        "running": True,
        "reason": reason,
        "last_started_at": datetime.now(timezone.utc).isoformat(),
        "last_error": None,
    })
    training_state["running"] = True
    try:
        report = train_customer_suite(
            _require_database_url(), ARTIFACT_ROOT, customer_id, counts,
            days=TRAIN_DAYS, estimators=TRAIN_ESTIMATORS,
        )
        customer_state.update({
            "running": False,
            "ready": report.get("total_active_model_count", 0) > 0,
            "dataset_version": report["dataset_version"],
            "snapshot_id": (report.get("dataset_metadata") or {}).get("runtime_snapshot_id"),
            "approved_candidate_count": report.get("approved_model_count", 0),
            "active_model_count": report.get("total_active_model_count", 0),
            "last_finished_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None,
        })
    except Exception as exc:  # noqa: BLE001
        customer_state.update({
            "running": False,
            "last_finished_at": datetime.now(timezone.utc).isoformat(),
            "last_error": str(exc),
        })
        LOGGER.exception("Customer ML training failed for %s: %s", customer_id, exc)
    finally:
        training_state["running"] = any(
            bool(item.get("running")) for item in training_state.get("customers", {}).values()
        )


def _customer_training_cycle(force_customer_id: str | None = None) -> dict[str, Any]:
    all_counts = list_customer_group_counts(_require_database_url())
    decisions: dict[str, Any] = {}
    for customer_id, counts in all_counts.items():
        if force_customer_id and customer_id != force_customer_id:
            continue
        watermark = load_watermark(_require_database_url(), customer_id)
        decision = training_decision(counts, watermark)
        decisions[customer_id] = decision
        customer_state = training_state.setdefault("customers", {}).setdefault(customer_id, {})
        customer_state.update({
            "group_counts": counts,
            "threshold_decision": decision,
            "active_model_count": int(watermark.get("active_model_count") or 0),
            "last_dataset_version": watermark.get("last_dataset_version"),
            "last_snapshot_id": watermark.get("last_snapshot_id"),
        })
        if decision["eligible"]:
            reason = "initial_minimum_reached" if decision["first_run"] else "new_group_rows_reached"
            _run_one_customer_training(customer_id, counts, reason)
    return decisions


def _customer_training_scheduler_loop() -> None:
    if STARTUP_DELAY_SECONDS:
        threading.Event().wait(STARTUP_DELAY_SECONDS)
    while True:
        try:
            _customer_training_cycle()
        except Exception as exc:  # noqa: BLE001
            training_state["last_error"] = f"Per-customer scheduler: {exc}"
            LOGGER.exception("Per-customer scheduler failed: %s", exc)
        threading.Event().wait(RETRAIN_POLL_SECONDS)


@app.get("/ml/status")
def ml_status(farm_id: str | None = Query(default=None)):
    if PER_CUSTOMER_TRAINING:
        all_counts = list_customer_group_counts(_require_database_url())
        selected_customer = _customer_id_for_farm(farm_id) if farm_id else None
        customers: dict[str, Any] = {}
        for customer_id, counts in all_counts.items():
            if selected_customer and customer_id != selected_customer:
                continue
            watermark = load_watermark(_require_database_url(), customer_id)
            active = load_active_manifest(ARTIFACT_ROOT, customer_id)
            customers[customer_id] = {
                "group_counts": counts,
                "threshold_decision": training_decision(counts, watermark),
                "last_snapshot_id": watermark.get("last_snapshot_id"),
                "last_dataset_version": watermark.get("last_dataset_version"),
                "last_training_status": watermark.get("last_training_status", "never"),
                "last_started_at": watermark.get("last_started_at"),
                "last_finished_at": watermark.get("last_finished_at"),
                "last_error": watermark.get("last_error"),
                "active_model_count": len(active.get("models", {})),
                "active_manifest": str(active_manifest_path(ARTIFACT_ROOT, customer_id)),
            }
        return {
            "architecture": "per_customer_automatic_ml_pipeline",
            "scope": "customer",
            "auto_train": AUTO_TRAIN,
            "pipeline": "database -> immutable per-customer CSV snapshot -> clean/features -> chronological 70/15/15 -> validation selection -> test/zone holdout -> candidate -> quality-gated activation",
            "model_data_root": str(ARTIFACT_ROOT / "data" / "customers"),
            "candidate_root": str(ARTIFACT_ROOT / "customers"),
            "group_policies": GROUP_POLICIES,
            "training_days": TRAIN_DAYS,
            "estimators": TRAIN_ESTIMATORS,
            "retrain_poll_seconds": RETRAIN_POLL_SECONDS,
            "customers": customers,
        }
    suite = load_shared_suite_report(ARTIFACT_ROOT)
    if suite and not _artifacts_ready():
        suite = None
    runtime_count = _db_training_reading_count_safe()
    farm_views: dict[str, Any] = {}
    if suite:
        selected_farms = [farm_id] if farm_id else list(FARM_PROFILES)
        for selected_farm_id in selected_farms:
            profile = FARM_PROFILES.get(selected_farm_id, {"name": selected_farm_id})
            farm_views[selected_farm_id] = {
                "farm_name": profile["name"], "model_count": suite["model_count"],
                "train_count": suite["train_count"], "validation_count": suite["validation_count"],
                "test_count": suite["test_count"], "trained_at": suite["trained_at"], "uses_shared_models": True,
                "approved_model_count": suite.get("approved_model_count", 0),
                "experimental_model_count": suite.get("experimental_model_count", 0),
                "production_ready": False, "training_phase": _training_phase(suite),
            }
    return {
        **training_state,
        "ready": bool(suite) or training_state["ready"],
        "reference_bootstrap_ready": bool(suite) or bool(training_state.get("reference_bootstrap_ready")),
        "training_phase": _training_phase(suite) if suite else training_state.get("training_phase"),
        "total_model_artifacts": suite["total_model_artifacts"] if suite else training_state["total_model_artifacts"],
        "auto_train": AUTO_TRAIN, "force_retrain_on_start": FORCE_RETRAIN_ON_START,
        "training_days": TRAIN_DAYS, "estimators": TRAIN_ESTIMATORS,
        "architecture": "shared_base_models_with_customer_calibration",
        "training_policy": "CSV snapshots stay isolated by customer; eligible snapshots are pooled to train exactly 10 shared base models",
        "shared_model_count": len(load_shared_active_manifest(ARTIFACT_ROOT).get("models", {})),
        "farm_specific_model_count": 0,
        "expected_shared_models": len(MODEL_SPECS), "generalization_test": "leave_one_customer_out",
        "active_manifest": str(ARTIFACT_ROOT / "shared" / "active_models.json"),
        "human_training_report": str(ARTIFACT_ROOT / "reports" / "LATEST_TRAINING_REPORT.md"),
        "dataset_source": suite.get("dataset_source") if suite else training_state.get("dataset_source"),
        "dataset_version": suite.get("dataset_version") if suite else training_state.get("dataset_version"),
        "approved_model_count": suite.get("approved_model_count", 0) if suite else training_state.get("approved_model_count", 0),
        "experimental_model_count": suite.get("experimental_model_count", 0) if suite else training_state.get("experimental_model_count", 0),
        "production_ready": False,
        "production_ready_policy": "disabled in simulator/reference-only V9; requires later validation on actual NextFarm hardware telemetry",
        "origin_mix": (suite.get("dataset_metadata") or {}).get("origin_mix", {}) if suite else training_state.get("origin_mix", {}),
        "runtime_reading_count": runtime_count,
        "runtime_retrain_threshold": RETRAIN_MIN_NEW_ROWS,
        "runtime_rows_until_retrain": max(0, RETRAIN_MIN_NEW_ROWS - runtime_count),
        "reference_anchor_ratio": REFERENCE_ANCHOR_RATIO,
        "runtime_only_training": RUNTIME_ONLY_TRAINING,
        "retrain_poll_seconds": RETRAIN_POLL_SECONDS, "retrain_interval_hours": RETRAIN_INTERVAL_HOURS,
        "auto_inference": AUTO_INFERENCE, "inference_interval_seconds": INFERENCE_INTERVAL_SECONDS,
        "worker": inference_worker_state, "farms": farm_views,
    }


@app.post("/ml/train")
def ml_train(
    farm_id: str | None = Query(default=None),
    customer_id: str | None = Query(default=None),
):
    if PER_CUSTOMER_TRAINING:
        selected_customer = customer_id or (_customer_id_for_farm(farm_id) if farm_id else None)
        if not selected_customer:
            raise HTTPException(status_code=400, detail="Cần customer_id hoặc farm_id để train đúng tenant.")
        if training_state.get("running"):
            raise HTTPException(status_code=409, detail="Một phiên train theo khách hàng đang chạy.")
        all_counts = list_customer_group_counts(_require_database_url())
        if selected_customer not in all_counts:
            raise HTTPException(status_code=404, detail="Khách hàng chưa có vườn hoặc dữ liệu vận hành.")
        decision = training_decision(all_counts[selected_customer], load_watermark(_require_database_url(), selected_customer))
        if decision["missing_minimum"]:
            raise HTTPException(status_code=409, detail={
                "message": "Chưa đủ lịch sử tối thiểu để tránh train model kém tin cậy.",
                "decision": decision,
            })
        threading.Thread(
            target=_run_one_customer_training,
            args=(selected_customer, all_counts[selected_customer], "manual_authorized"),
            daemon=True,
            name=f"nextfarm-customer-train-{selected_customer}",
        ).start()
        return {
            "accepted": True,
            "customer_id": selected_customer,
            "scope": "customer",
            "decision": decision,
            "message": "Đã bắt đầu pipeline tự động từ snapshot CSV riêng của khách hàng.",
        }
    if training_state["running"]:
        raise HTTPException(status_code=409, detail="Một phiên train/test model dùng chung đang chạy.")
    phase = "runtime_retrain" if _db_training_reading_count_safe() >= RETRAIN_MIN_NEW_ROWS else "bootstrap_reference"
    threading.Thread(target=_run_training, kwargs={"_requested_farm_id": farm_id, "force_phase": phase}, daemon=True, name="nextfarm-v9-manual-train").start()
    return {
        "accepted": True, "requested_farm_id": farm_id, "scope": "global", "training_phase": phase,
        "message": "Đã bắt đầu train 10 model V9 theo chính sách hai giai đoạn; không đọc dữ liệu từ dự án cũ.",
    }


@app.post("/ml/export-runtime-csv")
def ml_export_runtime_csv(customer_id: str | None = Query(default=None)):
    """Create a repeatable-read CSV snapshot of the current operational database."""
    if customer_id:
        return export_customer_training_snapshot(_require_database_url(), ARTIFACT_ROOT / "data", customer_id)
    return export_runtime_snapshot(_require_database_url(), RUNTIME_CSV_ROOT)


@app.get("/ml/reports")
def ml_reports():
    if PER_CUSTOMER_TRAINING:
        items = []
        customer_root = ARTIFACT_ROOT / "customers"
        if customer_root.exists():
            for path in customer_root.glob("*/latest_training_report.json"):
                report = json.loads(path.read_text(encoding="utf-8"))
                items.append({
                    "customer_id": report.get("scope_key"),
                    "dataset_version": report.get("dataset_version"),
                    "model_count": report.get("model_count", 0),
                    "approved_candidate_count": report.get("approved_model_count", 0),
                    "active_model_count": report.get("total_active_model_count", 0),
                    "trained_at": report.get("trained_at"),
                    "models": report.get("models", []),
                })
        return {"architecture": "per_customer_automatic_ml_pipeline", "customer_count": len(items), "items": items}
    suite = load_shared_suite_report(ARTIFACT_ROOT)
    if suite and not _artifacts_ready():
        suite = None
    if not suite:
        return {"architecture": "multi_tenant_shared_models", "total_models": 0, "items": []}
    return {
        "architecture": "multi_tenant_shared_models",
        "total_models": suite["model_count"],
        "farm_specific_model_count": 0,
        "items": suite["models"],
    }


@app.get("/ml/reports/{farm_id}")
def ml_farm_report(farm_id: str):
    if PER_CUSTOMER_TRAINING:
        customer_id = _customer_id_for_farm(farm_id)
        path = ARTIFACT_ROOT / "customers" / customer_id / "latest_training_report.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Khách hàng chưa có báo cáo train.")
        return json.loads(path.read_text(encoding="utf-8"))
    report = farm_view_report(ARTIFACT_ROOT, farm_id)
    if report:
        return report
    suite = load_shared_suite_report(ARTIFACT_ROOT)
    if not suite:
        raise HTTPException(status_code=404, detail="Chưa có báo cáo model dùng chung.")
    profile = _load_farm_ai_profile(farm_id)
    return {
        "architecture": "multi_tenant_shared_models",
        "farm_id": farm_id,
        "farm_name": profile.get("name", farm_id),
        "profile": profile,
        "model_count": suite["model_count"],
        "shared_artifact_count": suite["total_model_artifacts"],
        "train_count": suite["train_count"],
        "validation_count": suite["validation_count"],
        "test_count": suite["test_count"],
        "split_strategy": suite["split_strategy"],
        "generalization_test": suite["generalization_test"],
        "models": suite["models"],
        "note": "Farm mới dùng global metrics cho đến khi có đủ dữ liệu để đánh giá/calibration riêng; vẫn không tạo model binary riêng.",
    }


@app.get("/ml/reports/{farm_id}/{model_name}")
def ml_model_report(farm_id: str, model_name: str):
    if PER_CUSTOMER_TRAINING:
        customer_id = _customer_id_for_farm(farm_id)
        report_path = ARTIFACT_ROOT / "customers" / customer_id / "latest_training_report.json"
        if not report_path.exists():
            raise HTTPException(status_code=404, detail="Khách hàng chưa có báo cáo train/test.")
        suite = json.loads(report_path.read_text(encoding="utf-8"))
        report = next((item for item in suite.get("models", []) if item.get("model_name") == model_name), None)
        if not report:
            raise HTTPException(status_code=404, detail="Không có model trong candidate mới nhất của khách hàng.")
        result = dict(report)
        result["customer_id"] = customer_id
        result["farm_id"] = farm_id
        result["active"] = model_name in load_active_manifest(ARTIFACT_ROOT, customer_id).get("models", {})
        result["uses_customer_artifact"] = True
        return result
    report = load_shared_model_report(ARTIFACT_ROOT, model_name)
    if not report:
        raise HTTPException(status_code=404, detail="Model dùng chung chưa có báo cáo train/test.")
    profile = _load_farm_ai_profile(farm_id)
    result = dict(report)
    result["farm_id"] = farm_id
    result["farm_profile"] = profile
    result["farm_metrics"] = report.get("per_farm_metrics", {}).get(farm_id)
    result["calibration"] = report.get("farm_calibrations", {}).get(farm_id)
    result["uses_shared_artifact"] = True
    result["is_unseen_farm"] = farm_id not in report.get("per_farm_metrics", {})
    return result


@app.get("/ml/charts/{farm_id}/summary")
def ml_summary_chart(farm_id: str):
    _load_farm_ai_profile(farm_id)
    if PER_CUSTOMER_TRAINING:
        customer_id = _customer_id_for_farm(farm_id)
        report_path = ARTIFACT_ROOT / "customers" / customer_id / "latest_training_report.json"
        if not report_path.exists():
            raise HTTPException(status_code=404, detail="Khách hàng chưa có biểu đồ tổng hợp.")
        suite = json.loads(report_path.read_text(encoding="utf-8"))
        models = suite.get("models", [])
        if not models:
            raise HTTPException(status_code=404, detail="Khách hàng chưa có biểu đồ tổng hợp.")
        path = Path(models[0]["artifact_path"]).parents[2] / "suite_summary.png"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Chưa có biểu đồ tổng hợp candidate của khách hàng.")
        return FileResponse(path, media_type="image/png", filename=f"{customer_id}_models_summary.png")
    suite = load_shared_suite_report(ARTIFACT_ROOT) or {}
    path = Path(suite.get("suite_summary_chart", "__missing__"))
    if not path.exists():
        raise HTTPException(status_code=404, detail="Chưa có biểu đồ tổng hợp model dùng chung.")
    return FileResponse(path, media_type="image/png", filename="shared_models_train_test_summary.png")


@app.get("/ml/charts/{farm_id}/{model_name}/{chart_kind}")
def ml_model_chart(farm_id: str, model_name: str, chart_kind: str):
    _load_farm_ai_profile(farm_id)
    filename_by_kind = {
        "evaluation": "evaluation.png",
        "importance": "feature_importance.png",
        "per-farm": "per_farm_evaluation.png",
    }
    filename = filename_by_kind.get(chart_kind)
    if not filename:
        raise HTTPException(status_code=400, detail="chart_kind nhận evaluation, importance hoặc per-farm.")
    if PER_CUSTOMER_TRAINING:
        customer_id = _customer_id_for_farm(farm_id)
        report_path = ARTIFACT_ROOT / "customers" / customer_id / "latest_training_report.json"
        if not report_path.exists():
            raise HTTPException(status_code=404, detail="Khách hàng chưa có báo cáo model.")
        suite = json.loads(report_path.read_text(encoding="utf-8"))
        model = next((item for item in suite.get("models", []) if item.get("model_name") == model_name), None)
        key_by_kind = {"evaluation": "evaluation_chart", "importance": "importance_chart", "per-farm": "per_farm_chart"}
        path = Path(model[key_by_kind[chart_kind]]) if model else Path("__missing__")
        if not path.exists():
            raise HTTPException(status_code=404, detail="Chưa có biểu đồ candidate của khách hàng.")
        return FileResponse(path, media_type="image/png", filename=f"{customer_id}_{model_name}_{chart_kind}.png")
    report = load_shared_model_report(ARTIFACT_ROOT, model_name)
    key_by_kind = {
        "evaluation": "evaluation_chart",
        "importance": "importance_chart",
        "per-farm": "per_farm_chart",
    }
    path = Path((report or {}).get(key_by_kind[chart_kind], "__missing__"))
    if not path.exists():
        raise HTTPException(status_code=404, detail="Chưa có biểu đồ của model dùng chung.")
    return FileResponse(path, media_type="image/png", filename=f"shared_{model_name}_{chart_kind}.png")

CLASS_LABELS = {
    "anomaly_multisensor": {0: "Bình thường", 1: "Bất thường"},
    "flow_fault": {0: "Bình thường", 1: "Không có dòng", 2: "Có dấu hiệu rò rỉ"},
    "irrigation_failure": {0: "Ca tưới bình thường", 1: "Ca tưới có nguy cơ thất bại"},
    "irrigation_need": {0: "Chưa cần tưới", 1: "Có nhu cầu tưới"},
    "device_health": {0: "Tốt", 1: "Cần theo dõi", 2: "Nguy cơ lỗi"},
    "farm_health": {0: "Tốt", 1: "Cảnh báo", 2: "Nghiêm trọng"},
}


def _training_medians(customer_id: str | None = None) -> dict[str, float]:
    if PER_CUSTOMER_TRAINING and customer_id:
        active = load_active_manifest(ARTIFACT_ROOT, customer_id)
        first = next(iter((active.get("models") or {}).values()), None)
        parquet_path = Path(first["artifact_path"]).parents[2] / "training_dataset.parquet" if first else Path("__missing__")
    else:
        active = load_shared_active_manifest(ARTIFACT_ROOT)
        first = next(iter((active.get("models") or {}).values()), None)
        parquet_path = (
            Path(first["artifact_path"]).parents[2] / "training_dataset.parquet"
            if first else Path("__missing__")
        )
    if not parquet_path.exists():
        return {}
    try:
        import pandas as pd
        frame = pd.read_parquet(parquet_path, columns=FEATURES, engine="pyarrow")
        return {name: float(frame[name].median()) for name in FEATURES}
    except Exception:
        return {}


def _load_farm_ai_profile(farm_id: str) -> dict[str, Any]:
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT p.*,f.farm_name,f.crop_name,f.region,f.area_ha,f.cultivation_type,f.soil_texture
            FROM farm_db.farms f
            LEFT JOIN farm_db.farm_ai_profiles p ON p.farm_id=f.farm_id
            WHERE f.farm_id=%s
            """,
            (farm_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy vườn.")
    if farm_id in FARM_PROFILES:
        profile = dict(FARM_PROFILES[farm_id])
    else:
        crop_name = str(row.get("crop_name") or "").lower()
        crop = "tomato" if "cà chua" in crop_name else "durian" if "sầu riêng" in crop_name else "leafy_vegetable" if "rau" in crop_name else "other"
        profile = {
            "name": row.get("farm_name") or farm_id,
            "crop": crop,
            "cultivation_type": row.get("cultivation_type") or "other",
            "climate_region": row.get("climate_region") or "other",
            "soil_type": row.get("soil_type") or row.get("soil_texture") or "other",
            "area_ha": float(row.get("area_ha") or 1.0),
            "moisture_min": float(row.get("target_moisture_min") or 50.0),
            "moisture_max": float(row.get("target_moisture_max") or 75.0),
            "ec_min": float(row.get("target_ec_min") or 1.0),
            "ec_max": float(row.get("target_ec_max") or 2.5),
            "ph_min": float(row.get("target_ph_min") or 5.5),
            "ph_max": float(row.get("target_ph_max") or 7.0),
        }
    # DB profile có quyền ghi đè cấu hình demo.
    mappings = {
        "crop": "crop_code",
        "cultivation_type": "cultivation_type",
        "climate_region": "climate_region",
        "soil_type": "soil_type",
        "area_ha": "area_ha",
        "moisture_min": "target_moisture_min",
        "moisture_max": "target_moisture_max",
        "ec_min": "target_ec_min",
        "ec_max": "target_ec_max",
        "ph_min": "target_ph_min",
        "ph_max": "target_ph_max",
    }
    for key, column in mappings.items():
        value = row.get(column)
        if value is not None:
            profile[key] = float(value) if key in {"area_ha","moisture_min","moisture_max","ec_min","ec_max","ph_min","ph_max"} else value
    return profile


def _farm_calibration(farm_id: str, model_family: str, bundle: dict[str, Any]) -> dict[str, float]:
    if PER_CUSTOMER_TRAINING:
        own = bundle.get("farm_calibrations", {}).get(farm_id, {})
        return {"bias": float(own.get("bias", 0.0)), "scale": 1.0}
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT bias,scale FROM farm_db.farm_model_calibrations
            WHERE farm_id=%s AND model_family=%s AND model_version=%s
            """,
            (farm_id, model_family, bundle.get("model_version", MODEL_VERSION)),
        )
        row = cur.fetchone()
    if row:
        return {"bias": float(row.get("bias") or 0.0), "scale": float(row.get("scale") or 1.0)}
    fallback = bundle.get("farm_calibrations", {}).get(farm_id, {})
    return {"bias": float(fallback.get("bias", 0.0)), "scale": 1.0}


def _current_feature_vector(farm_id: str, zone_code: str | None) -> tuple[str, list[float], dict[str, Any]]:
    from app.ml_pipeline import FEATURES
    medians = _training_medians(_customer_id_for_farm(farm_id) if PER_CUSTOMER_TRAINING else None)
    now = datetime.now(timezone.utc)
    with conn() as db, db.cursor() as cur:
        zone_row = fetch_zone(cur, farm_id, zone_code)
        if not zone_row:
            raise HTTPException(status_code=404, detail="Không tìm thấy khu để suy luận AI.")
        zone_code = zone_row["zone_code"]
        values: dict[str, float] = {}
        deltas: dict[str, float] = {}
        rolling: dict[str, tuple[float, float]] = {}
        latest_times = []
        for metric in METRIC_LABELS:
            cur.execute(
                """
                SELECT value,observed_at FROM farm_db.sensor_readings
                WHERE farm_id=%s AND zone_id=%s AND metric_type=%s
                ORDER BY observed_at DESC LIMIT 8
                """,
                (farm_id, zone_row["zone_id"], metric),
            )
            rows = cur.fetchall()
            if rows:
                series = [float(r["value"]) for r in rows]
                values[metric] = series[0]
                deltas[metric] = series[0] - series[1] if len(series) > 1 else 0.0
                rolling[metric] = (float(np.mean(series)), float(np.std(series)))
                latest_times.append(rows[0]["observed_at"])
        cur.execute(
            """
            SELECT online,running,observed_at FROM farm_db.device_status ds
            JOIN farm_db.devices d ON d.device_id=ds.device_id
            WHERE d.farm_id=%s ORDER BY ds.observed_at DESC LIMIT 60
            """,
            (farm_id,),
        )
        statuses = cur.fetchall()
        latest_status = statuses[0] if statuses else {}
        packet_loss = sum(1 for s in statuses if not s.get("online")) / max(len(statuses), 1)
        cur.execute(
            """
            SELECT result,started_at FROM farm_db.irrigation_runs
            WHERE farm_id=%s AND (zone_id=%s OR zone_id IS NULL)
            ORDER BY started_at DESC LIMIT 30
            """,
            (farm_id, zone_row["zone_id"]),
        )
        runs = cur.fetchall()
        command_failure = sum(1 for r in runs if r["result"] == "failed") / max(len(runs), 1)
        last_irrigation = runs[0]["started_at"] if runs else now - timedelta(hours=12)
    minute = now.hour * 60 + now.minute
    latest_observed = max(latest_times) if latest_times else now - timedelta(hours=1)
    farm_profile = _load_farm_ai_profile(farm_id)
    feature_values = {
        **profile_feature_values(farm_profile),
        "zone_index": {"A": 0, "B": 1, "C": 2}.get(str(zone_code).upper(), 0),
        "minute_sin": math.sin(2 * math.pi * minute / 1440),
        "minute_cos": math.cos(2 * math.pi * minute / 1440),
        "day_sin": math.sin(2 * math.pi * now.weekday() / 7),
        "day_cos": math.cos(2 * math.pi * now.weekday() / 7),
        "soil_moisture": values.get("soil_moisture"),
        "temperature": values.get("temperature"),
        "air_humidity": values.get("air_humidity"),
        "ec": values.get("ec"),
        "ph": values.get("ph"),
        "flow_rate": values.get("flow_rate"),
        "soil_moisture_missing": int("soil_moisture" not in values),
        "temperature_missing": int("temperature" not in values),
        "air_humidity_missing": int("air_humidity" not in values),
        "ec_missing": int("ec" not in values),
        "ph_missing": int("ph" not in values),
        "flow_rate_missing": int("flow_rate" not in values),
        "valve_running": int(bool(latest_status.get("running"))),
        "pump_running": int(bool(latest_status.get("running"))),
        "device_online": int(bool(latest_status.get("online", False))),
        "scheduled_irrigation": int(bool(latest_status.get("running"))),
        "minutes_since_irrigation": max(0.0, (now - last_irrigation).total_seconds() / 60),
        "sensor_age_seconds": max(0.0, (now - latest_observed).total_seconds()),
        "packet_loss_rate": packet_loss,
        "command_failure_rate": command_failure,
        "moisture_delta": deltas.get("soil_moisture", 0.0),
        "temperature_delta": deltas.get("temperature", 0.0),
        "humidity_delta": deltas.get("air_humidity", 0.0),
        "ec_delta": deltas.get("ec", 0.0),
        "ph_delta": deltas.get("ph", 0.0),
        "flow_delta": deltas.get("flow_rate", 0.0),
        "moisture_roll_mean": rolling.get("soil_moisture", (None, None))[0],
        "moisture_roll_std": rolling.get("soil_moisture", (None, None))[1],
        "flow_roll_mean": rolling.get("flow_rate", (None, None))[0],
        "flow_roll_std": rolling.get("flow_rate", (None, None))[1],
    }
    vector = [float(feature_values.get(name) if feature_values.get(name) is not None else medians.get(name, 0.0)) for name in FEATURES]
    return str(zone_code), vector, feature_values






def _prediction_requires_human(item: dict[str, Any]) -> bool:
    return (
        (item.get("model_name") in {"device_health", "farm_health"} and item.get("prediction") == 2)
        or (item.get("model_name") == "flow_fault" and item.get("prediction") in {1, 2})
        or (item.get("model_name") == "irrigation_failure" and item.get("prediction") == 1)
    )

inference_worker_state: dict[str, Any] = {
    "running": False, "last_cycle_at": None, "last_success_at": None,
    "last_error": None, "predictions_written": 0, "alerts_written": 0,
}

def _upsert_prediction_alerts(result: dict[str, Any]) -> int:
    if result.get("decision") != "human_required":
        return 0
    farm_id = result["farm_id"]
    zone_code = result["zone_code"]
    risky = [
        p for p in result.get("predictions", [])
        if p.get("deployment_status") == "approved"
        and _prediction_requires_human(p)
        and (p.get("probability") or 0) >= 0.72
    ]
    written = 0
    with conn() as db, db.cursor() as cur:
        for item in risky:
            alert_id = f"ai_{farm_id}_{zone_code}_{item['model_name']}"
            cur.execute(
                """INSERT INTO farm_db.alerts(alert_id,farm_id,zone_id,alert_type,severity,title,message,status,detected_at)
                   VALUES (%s,%s,(SELECT zone_id FROM farm_db.zones WHERE farm_id=%s AND upper(zone_code)=upper(%s) LIMIT 1),
                           %s,'high',%s,%s,'open',now())
                   ON CONFLICT (alert_id) DO UPDATE SET message=EXCLUDED.message,severity=EXCLUDED.severity,detected_at=now(),status='open',resolved_at=NULL""",
                (alert_id,farm_id,farm_id,zone_code,item["model_name"],f"AI: {item['display_name']}",f"Khu {zone_code}: {item['label']} (confidence {item.get('probability')})."),
            )
            written += 1
        db.commit()
    return written

def _run_inference_cycle() -> None:
    inference_worker_state.update({"running": True, "last_cycle_at": datetime.now(timezone.utc).isoformat(), "last_error": None})
    predictions_written = alerts_written = 0
    try:
        with conn() as db, db.cursor() as cur:
            cur.execute("SELECT farm_id,zone_code FROM farm_db.zones ORDER BY farm_id,zone_code")
            targets = cur.fetchall()
        target_errors: list[str] = []
        for target in targets:
            try:
                result = _predict_and_persist(target["farm_id"], target["zone_code"], trigger="scheduled_worker")
                predictions_written += len(result.get("predictions", []))
                alerts_written += _upsert_prediction_alerts(result)
            except Exception as exc:  # noqa: BLE001
                target_errors.append(f"{target['farm_id']}/{target['zone_code']}: {exc}")
        inference_worker_state.update({
            "last_success_at": datetime.now(timezone.utc).isoformat(),
            "predictions_written": inference_worker_state["predictions_written"] + predictions_written,
            "alerts_written": inference_worker_state["alerts_written"] + alerts_written,
            "last_error": "; ".join(target_errors[-10:]) if target_errors else None,
        })
    except Exception as exc:  # noqa: BLE001
        inference_worker_state["last_error"] = str(exc)
    finally:
        inference_worker_state["running"] = False

def _inference_worker_loop() -> None:
    if STARTUP_DELAY_SECONDS:
        threading.Event().wait(STARTUP_DELAY_SECONDS)
    while True:
        customer_models_ready = PER_CUSTOMER_TRAINING and (ARTIFACT_ROOT / "customers").exists()
        if (customer_models_ready or _artifacts_ready()) and not training_state.get("running"):
            _run_inference_cycle()
        threading.Event().wait(INFERENCE_INTERVAL_SECONDS)

def start_inference_worker() -> None:
    if AUTO_INFERENCE:
        threading.Thread(target=_inference_worker_loop, daemon=True, name="nextfarm-scheduled-inference").start()


def _predict_and_persist(farm_id: str, zone: str | None = None, trigger: str = "api"):

    import joblib

    farm_profile = _load_farm_ai_profile(farm_id)
    customer_id = _customer_id_for_farm(farm_id)
    zone_code, vector, feature_values = _current_feature_vector(farm_id, zone)
    predictions = []
    with artifact_lock:
        loaded_bundles = []
        if PER_CUSTOMER_TRAINING:
            active = load_active_manifest(ARTIFACT_ROOT, customer_id)
            for spec in MODEL_SPECS:
                item = (active.get("models") or {}).get(spec.name)
                path = Path(item["artifact_path"]) if item and item.get("artifact_path") else None
                if path and path.exists():
                    loaded_bundles.append((spec, joblib.load(path)))
        else:
            for spec in MODEL_SPECS:
                path = shared_model_path(ARTIFACT_ROOT, spec.name)
                if path.exists():
                    bundle = joblib.load(path)
                    if bundle.get("deployment_status") == "approved":
                        loaded_bundles.append((spec, bundle))
    for spec, bundle in loaded_bundles:
        model = bundle["model"]
        bundle_medians = bundle.get("feature_medians", {})
        model_vector = np.asarray([[
            float(feature_values.get(name))
            if feature_values.get(name) is not None
            else float(bundle_medians.get(name, 0.0))
            for name in FEATURES
        ]], dtype=float)
        raw_prediction = model.predict(model_vector)[0]
        item: dict[str, Any] = {
            "model_name": spec.name,
            "display_name": spec.display_name,
            "task": spec.task,
            "model_version": bundle.get("model_version", MODEL_VERSION),
            "scope_type": "customer" if PER_CUSTOMER_TRAINING else "global",
            "scope_key": customer_id if PER_CUSTOMER_TRAINING else "all_farms",
            "artifact_scope": "customer" if PER_CUSTOMER_TRAINING else "shared",
            "deployment_status": bundle.get("deployment_status", "experimental"),
            "quality_gate": bundle.get("quality_gate", {}),
        }
        if spec.task == "regression":
            calibration = _farm_calibration(farm_id, spec.name, bundle)
            calibrated = float(raw_prediction) * calibration["scale"] + calibration["bias"]
            item.update({
                "raw_prediction": round(float(raw_prediction), 4),
                "prediction": round(calibrated, 4),
                "label": f"{calibrated:.2f}",
                "calibration": calibration,
            })
        else:
            class_value = int(raw_prediction)
            probability = None
            if hasattr(model, "predict_proba"):
                probs = model.predict_proba(model_vector)[0]
                class_index = list(model.classes_).index(raw_prediction)
                probability = float(probs[class_index])
            item.update({
                "prediction": class_value,
                "label": CLASS_LABELS.get(spec.name, {}).get(class_value, str(class_value)),
                "probability": round(probability, 4) if probability is not None else None,
            })
        predictions.append(item)

    if not predictions:
        raise HTTPException(
            status_code=409,
            detail=(
                "Khách hàng chưa có model vượt quality gate; hệ thống chỉ dùng dữ liệu trực tiếp/quy tắc an toàn "
                "và không lấy model của khách hàng khác."
                if PER_CUSTOMER_TRAINING else "10 model dùng chung chưa train xong."
            ),
        )
    approved_predictions = [p for p in predictions if p.get("deployment_status") == "approved"]
    human_required = any(
        _prediction_requires_human(p)
        for p in predictions if p.get("deployment_status") == "approved"
    )

    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO farm_db.farm_feature_snapshots(farm_id,zone_id,features,observed_at)
            VALUES (%s,(SELECT zone_id FROM farm_db.zones WHERE farm_id=%s AND upper(zone_code)=upper(%s) LIMIT 1),%s,now())
            """,
            (farm_id, farm_id, zone_code, Jsonb(feature_values)),
        )
        for item in predictions:
            cur.execute(
                """
                INSERT INTO farm_db.farm_predictions(
                  farm_id,zone_id,model_family,model_version,prediction,confidence,decision,trigger_source,deployment_status,created_at
                ) VALUES (
                  %s,(SELECT zone_id FROM farm_db.zones WHERE farm_id=%s AND upper(zone_code)=upper(%s) LIMIT 1),
                  %s,%s,%s,%s,%s,%s,%s,now()
                )
                """,
                (
                    farm_id, farm_id, zone_code, item["model_name"], item.get("model_version", MODEL_VERSION),
                    Jsonb(item), item.get("probability"),
                    "human_required" if human_required else ("ai_can_handle" if approved_predictions else "observe"),
                    trigger, item.get("deployment_status", "experimental"),
                ),
            )
        db.commit()

    return {
        "architecture": "per_customer_models" if PER_CUSTOMER_TRAINING else "shared_base_models_with_customer_calibration",
        "customer_id": customer_id,
        "farm_id": farm_id,
        "farm_profile": farm_profile,
        "zone_code": zone_code,
        "generated_at": datetime.now(timezone.utc),
        "feature_snapshot": feature_values,
        "shared_model_count": len(predictions),
        "farm_specific_model_count": 0,
        "predictions": predictions,
        "decision": "human_required" if human_required else ("ai_can_handle" if approved_predictions else "observe"),
        "trigger": trigger,
        "note": (
            "Chỉ suy luận bằng model đã vượt quality gate và được kích hoạt cho đúng customer_id. "
            "Candidate không đạt không thay thế model đang hoạt động."
            if PER_CUSTOMER_TRAINING else
            "Suy luận chỉ bằng model nền dùng chung có tên trong active manifest. Mỗi vườn áp dụng calibration nhỏ; candidate không đạt giữ nguyên model active trước đó."
        ),
    }


@app.get("/ml/predict/{farm_id}")
def ml_predict(farm_id: str, zone: str | None = Query(default=None)):
    return _predict_and_persist(farm_id, zone, trigger="api")
