from __future__ import annotations

import os
import hmac
import re
from datetime import datetime, timezone
from typing import Any

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SENSOR_FRESH_MINUTES = int(os.getenv("SENSOR_FRESH_MINUTES", "30"))
DEVICE_FRESH_SECONDS = int(os.getenv("DEVICE_FRESH_SECONDS", "30"))
IDENTITY_URL = os.getenv("IDENTITY_URL", "http://localhost:8100")
INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")

app = FastAPI(title="NextFarm Farm DB Service", version="10.1.0")
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


def _require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("Thiếu DATABASE_URL; hãy chạy dịch vụ qua Docker Compose sau scripts/setup_v9_env.cmd.")
    return DATABASE_URL


def conn():
    return psycopg.connect(_require_database_url(), row_factory=dict_row)


def _verify_request_user(request: Request) -> dict[str, Any] | None:
    authorization = request.headers.get("authorization")
    supplied_internal = request.headers.get("x-internal-service-key")
    # Khi có token người dùng, luôn kiểm tra tenant của token; service key không được phép ghi đè.
    if not authorization and INTERNAL_SERVICE_KEY and supplied_internal and hmac.compare_digest(supplied_internal, INTERNAL_SERVICE_KEY):
        return None
    if not authorization:
        raise HTTPException(status_code=401, detail="API dữ liệu yêu cầu đăng nhập.")
    try:
        with httpx.Client(timeout=8) as client:
            response = client.post(f"{IDENTITY_URL}/auth/verify", headers={"Authorization": authorization})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Không kết nối được dịch vụ xác thực.") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập không hợp lệ hoặc đã hết hạn.")
    return response.json()["user"]


def _farm_from_request(request: Request) -> str | None:
    match = re.match(r"^/farms/([^/]+)", request.url.path)
    if match:
        return match.group(1)
    return request.query_params.get("farm_id")


def _has_read_access(user: dict[str, Any] | None, farm_id: str) -> bool:
    if user is None:
        return True
    return any(item.get("farm_id") == farm_id and item.get("can_read") for item in user.get("farms", []))


def require_farm_access(request: Request, farm_id: str) -> None:
    if not _has_read_access(getattr(request.state, "user", None), farm_id):
        raise_api_error(403, "FORBIDDEN", "Tài khoản không có quyền truy cập vườn này.", {"farm_id": farm_id})


def error_payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message, "details": details or {}}}


def raise_api_error(status_code: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message, "details": details or {}})


@app.exception_handler(HTTPException)
async def structured_http_error(_request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict) and exc.detail.get("code"):
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.detail["code"], exc.detail["message"], exc.detail.get("details")),
        )
    return JSONResponse(status_code=exc.status_code, content=error_payload("REQUEST_REJECTED", str(exc.detail)))


@app.middleware("http")
async def tenant_auth_middleware(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    try:
        user = _verify_request_user(request)
        request.state.user = user
        farm_id = _farm_from_request(request)
        if farm_id and not _has_read_access(user, farm_id):
            raise_api_error(403, "FORBIDDEN", "Tài khoản không có quyền truy cập vườn này.", {"farm_id": farm_id})
        if request.url.path.startswith("/studio/") and request.url.path != "/studio/catalog" and request.method == "GET" and not farm_id:
            raise_api_error(400, "FARM_CONTEXT_REQUIRED", "Thiếu farm_id; API Studio không được phép trả dữ liệu toàn hệ thống.")
        return await call_next(request)
    except HTTPException as exc:
        if isinstance(exc.detail, dict) and exc.detail.get("code"):
            return JSONResponse(status_code=exc.status_code, content=error_payload(exc.detail["code"], exc.detail["message"], exc.detail.get("details")))
        return JSONResponse(status_code=exc.status_code, content=error_payload("REQUEST_REJECTED", str(exc.detail)))


def age_seconds(ts: datetime | None) -> float | None:
    if not ts:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())


def freshness(ts: datetime | None, threshold_seconds: int) -> dict[str, Any]:
    age = age_seconds(ts)
    if age is None:
        return {"fresh": False, "age_seconds": None, "freshness": "missing"}
    return {
        "fresh": age <= threshold_seconds,
        "age_seconds": round(age, 1),
        "freshness": "fresh" if age <= threshold_seconds else "stale",
    }


def zone_row(cur, farm_id: str, zone_code: str | None):
    if not zone_code:
        cur.execute("SELECT * FROM farm_db.zones WHERE farm_id=%s ORDER BY zone_code LIMIT 2", (farm_id,))
        rows = cur.fetchall()
        if not rows:
            return None
        if len(rows) > 1:
            raise_api_error(
                409,
                "ZONE_CONTEXT_REQUIRED",
                "Vườn có nhiều khu; phải chọn rõ khu trước khi đọc số liệu hoặc đưa khuyến nghị.",
                {"farm_id": farm_id},
            )
        return rows[0]
    else:
        cur.execute(
            "SELECT * FROM farm_db.zones WHERE farm_id=%s AND upper(zone_code)=upper(%s)",
            (farm_id, zone_code),
        )
    return cur.fetchone()


@app.get("/health")
def health():
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM farm_db.farms")
        farms = int(cur.fetchone()["n"])
    return {"service": "farm-data-service", "status": "ok", "database": "farm_db", "farm_count": farms}


@app.get("/farms")
def farms(request: Request):
    user = getattr(request.state, "user", None)
    if user is None:
        raise_api_error(403, "FORBIDDEN", "Danh sách vườn chỉ trả cho phiên người dùng đã xác thực.")
    allowed = [str(item["farm_id"]) for item in user.get("farms", []) if item.get("can_read")]
    if not allowed:
        return {"items": [], "total": 0}
    with conn() as db, db.cursor() as cur:
        cur.execute(
            "SELECT farm_id,farm_name,crop_name,region,address,area_ha FROM farm_db.farms WHERE farm_id=ANY(%s) ORDER BY farm_name",
            (allowed,),
        )
        rows = cur.fetchall()
    return {"items": rows, "total": len(rows)}


@app.get("/farms/{farm_id}/zones")
def zones(farm_id: str):
    with conn() as db, db.cursor() as cur:
        cur.execute(
            "SELECT zone_id,zone_code,zone_name,crop_name,area_ha,moisture_min,moisture_max,ec_min,ec_max,ph_min,ph_max FROM farm_db.zones WHERE farm_id=%s ORDER BY zone_code",
            (farm_id,),
        )
        rows = cur.fetchall()
    return {"farm_id": farm_id, "items": rows, "total": len(rows)}


@app.get("/farms/{farm_id}/overview")
def overview(farm_id: str):
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT * FROM farm_db.farms WHERE farm_id=%s", (farm_id,))
        farm = cur.fetchone()
        if not farm:
            raise HTTPException(status_code=404, detail="Không tìm thấy vườn.")
        cur.execute(
            "SELECT zone_id,zone_code,zone_name,crop_name,area_ha,moisture_min,moisture_max FROM farm_db.zones WHERE farm_id=%s ORDER BY zone_code",
            (farm_id,),
        )
        zones = cur.fetchall()
        cur.execute("SELECT count(*) AS total FROM farm_db.devices WHERE farm_id=%s AND active=true", (farm_id,))
        device_count = cur.fetchone()["total"]
        cur.execute("SELECT count(*) AS total FROM farm_db.alerts WHERE farm_id=%s AND status='open'", (farm_id,))
        open_alerts = cur.fetchone()["total"]
    return {**farm, "zones": zones, "device_count": device_count, "open_alerts": open_alerts}


@app.get("/farms/{farm_id}/metrics/latest")
def latest_metric(
    farm_id: str,
    metric: str = Query(...),
    zone: str | None = Query(default=None),
):
    allowed = {"soil_moisture", "air_humidity", "temperature", "ec", "ph", "flow_rate"}
    if metric not in allowed:
        raise HTTPException(status_code=400, detail="Loại số đo không được hỗ trợ.")
    with conn() as db, db.cursor() as cur:
        z = zone_row(cur, farm_id, zone)
        if not z:
            return {"available": False, "error_code": "NOT_FOUND", "reason": "Không tìm thấy khu được yêu cầu.", "farm_id": farm_id, "zone": zone, "metric": metric}
        cur.execute(
            """
            SELECT r.*,s.sensor_name
            FROM farm_db.sensor_readings r
            JOIN farm_db.sensors s ON s.sensor_id=r.sensor_id
            WHERE r.farm_id=%s AND r.zone_id=%s AND r.metric_type=%s
            ORDER BY r.observed_at DESC LIMIT 1
            """,
            (farm_id, z["zone_id"], metric),
        )
        row = cur.fetchone()
    if not row:
        return {
            "available": False,
            "error_code": "NO_DATA",
            "reason": "Khu này chưa có số đo cho chỉ số được yêu cầu.",
            "farm_id": farm_id,
            "zone_code": z["zone_code"],
            "metric": metric,
        }
    fresh = freshness(row["observed_at"], SENSOR_FRESH_MINUTES * 60)
    value = float(row["value"])
    status = "unknown"
    target_min = target_max = None
    if metric == "soil_moisture":
        target_min = float(z["moisture_min"]) if z["moisture_min"] is not None else None
        target_max = float(z["moisture_max"]) if z["moisture_max"] is not None else None
    elif metric == "ec":
        target_min = float(z["ec_min"]) if z["ec_min"] is not None else None
        target_max = float(z["ec_max"]) if z["ec_max"] is not None else None
    elif metric == "ph":
        target_min = float(z["ph_min"]) if z["ph_min"] is not None else None
        target_max = float(z["ph_max"]) if z["ph_max"] is not None else None
    if target_min is not None and target_max is not None:
        status = "low" if value < target_min else "high" if value > target_max else "normal"
    return {
        "available": True,
        "farm_id": farm_id,
        "zone_id": z["zone_id"],
        "zone_code": z["zone_code"],
        "zone_name": z["zone_name"],
        "metric": metric,
        "sensor_name": row["sensor_name"],
        "value": value,
        "unit": row["unit"],
        "quality": row["quality"],
        "observed_at": row["observed_at"],
        "measured_at": row["observed_at"],
        "received_at": row.get("received_at") or row.get("created_at"),
        "target_min": target_min,
        "target_max": target_max,
        "status": status,
        **fresh,
    }


@app.get("/farms/{farm_id}/devices")
def devices(farm_id: str, zone: str | None = None):
    with conn() as db, db.cursor() as cur:
        params: list[Any] = [farm_id]
        where = "d.farm_id=%s"
        if zone:
            where += " AND (upper(z.zone_code)=upper(%s) OR z.zone_code IS NULL)"
            params.append(zone)
        cur.execute(
            f"""
            SELECT d.device_id,d.device_name,d.device_type,d.model_name,d.firmware_version,d.connectivity,
                   z.zone_code,
                   st.online,st.last_seen_at,st.observed_at
            FROM farm_db.devices d
            LEFT JOIN farm_db.zones z ON z.zone_id=d.zone_id
            LEFT JOIN LATERAL (
              SELECT online,last_seen_at,observed_at FROM farm_db.device_status ds
              WHERE ds.device_id=d.device_id AND ds.port_id IS NULL
              ORDER BY observed_at DESC LIMIT 1
            ) st ON true
            WHERE {where} AND d.active=true
            ORDER BY d.device_name
            """,
            params,
        )
        rows = cur.fetchall()
    items = []
    for row in rows:
        f = freshness(row["observed_at"], DEVICE_FRESH_SECONDS)
        effective_online = bool(row["online"]) and f["fresh"]
        items.append({**row, **f, "effective_online": effective_online})
    return {"items": items, "total": len(items)}


@app.get("/farms/{farm_id}/ports/{port_number}")
def port_status(farm_id: str, port_number: int, zone: str | None = None):
    with conn() as db, db.cursor() as cur:
        params: list[Any] = [farm_id, port_number]
        where_zone = ""
        if zone:
            where_zone = " AND upper(z.zone_code)=upper(%s)"
            params.append(zone)
        cur.execute(
            f"""
            SELECT p.port_id,p.port_number,p.port_name,p.port_type,z.zone_code,
                   d.device_id,d.device_name,
                   st.online,st.running,st.last_seen_at,st.observed_at
            FROM farm_db.device_ports p
            JOIN farm_db.devices d ON d.device_id=p.device_id
            LEFT JOIN farm_db.zones z ON z.zone_id=p.zone_id
            LEFT JOIN LATERAL (
              SELECT online,running,last_seen_at,observed_at FROM farm_db.device_status ds
              WHERE ds.port_id=p.port_id ORDER BY observed_at DESC LIMIT 1
            ) st ON true
            WHERE d.farm_id=%s AND p.port_number=%s {where_zone}
            ORDER BY d.device_id,p.port_id
            """,
            params,
        )
        rows = cur.fetchall()
    items = []
    for row in rows:
        f = freshness(row["observed_at"], DEVICE_FRESH_SECONDS)
        items.append({**row, **f, "effective_online": bool(row["online"]) and f["fresh"]})
    return {"configured": bool(items), "ambiguous": len(items) > 1, "items": items}


@app.get("/farms/{farm_id}/irrigation/summary")
def irrigation_summary(farm_id: str, zone: str | None = None, period: str = "today"):
    periods = {
        "today": "date_trunc('day', now())",
        "yesterday": "date_trunc('day', now()) - interval '1 day'",
        "week": "date_trunc('week', now())",
    }
    if period not in periods:
        raise HTTPException(status_code=400, detail="period chỉ nhận today, yesterday hoặc week")
    start_sql = periods[period]
    end_sql = "date_trunc('day', now())" if period == "yesterday" else "now() + interval '1 day'"
    with conn() as db, db.cursor() as cur:
        params: list[Any] = [farm_id]
        zone_filter = ""
        if zone:
            zone_filter = " AND upper(z.zone_code)=upper(%s)"
            params.append(zone)
        cur.execute(
            f"""
            SELECT count(*) AS run_count,
                   coalesce(sum(r.duration_minutes),0) AS total_minutes,
                   coalesce(sum(r.water_liters),0) AS total_liters,
                   count(*) FILTER (WHERE r.result='failed') AS failed_count,
                   count(*) FILTER (WHERE r.result='running') AS running_count
            FROM farm_db.irrigation_runs r
            LEFT JOIN farm_db.zones z ON z.zone_id=r.zone_id
            WHERE r.farm_id=%s AND r.started_at >= {start_sql} AND r.started_at < {end_sql} {zone_filter}
            """,
            params,
        )
        row = cur.fetchone()
        cur.execute(
            f"""
            SELECT r.run_id,z.zone_code,r.started_at,r.ended_at,r.duration_minutes,r.water_liters,r.result,r.source
            FROM farm_db.irrigation_runs r
            LEFT JOIN farm_db.zones z ON z.zone_id=r.zone_id
            WHERE r.farm_id=%s AND r.started_at >= {start_sql} AND r.started_at < {end_sql} {zone_filter}
            ORDER BY r.started_at DESC LIMIT 10
            """,
            params,
        )
        items = cur.fetchall()
    return {
        "farm_id": farm_id,
        "zone": zone,
        "period": period,
        "run_count": row["run_count"],
        "total_minutes": float(row["total_minutes"]),
        "total_liters": float(row["total_liters"]),
        "failed_count": row["failed_count"],
        "running_count": row["running_count"],
        "items": items,
    }


@app.get("/farms/{farm_id}/irrigation/history")
def irrigation_history(
    farm_id: str,
    zone: str | None = None,
    hours: int = Query(168, ge=1, le=2160),
    limit: int = Query(100, ge=1, le=500),
):
    with conn() as db, db.cursor() as cur:
        params: list[Any] = [farm_id, hours]
        zone_filter = ""
        if zone:
            zone_filter = " AND upper(z.zone_code)=upper(%s)"
            params.append(zone)
        params.append(limit)
        cur.execute(
            f"""
            SELECT r.run_id,r.farm_id,z.zone_code,r.started_at,r.ended_at,
                   r.duration_minutes,r.water_liters,r.result,r.source
            FROM farm_db.irrigation_runs r
            LEFT JOIN farm_db.zones z ON z.zone_id=r.zone_id
            WHERE r.farm_id=%s AND r.started_at >= now()-(%s * interval '1 hour') {zone_filter}
            ORDER BY r.started_at DESC LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()
    return {"farm_id": farm_id, "zone": zone, "hours": hours, "items": rows, "total": len(rows)}


@app.get("/farms/{farm_id}/irrigation/schedules")
def irrigation_schedules(farm_id: str, zone: str | None = None):
    with conn() as db, db.cursor() as cur:
        params: list[Any] = [farm_id]
        zone_filter = ""
        if zone:
            zone_filter = " AND upper(z.zone_code)=upper(%s)"
            params.append(zone)
        cur.execute(
            f"""
            SELECT s.schedule_id,s.farm_id,z.zone_code,p.port_number,s.schedule_name,
                   s.start_time,s.duration_minutes,s.days_of_week,s.enabled
            FROM farm_db.irrigation_schedules s
            LEFT JOIN farm_db.zones z ON z.zone_id=s.zone_id
            LEFT JOIN farm_db.device_ports p ON p.port_id=s.port_id
            WHERE s.farm_id=%s {zone_filter}
            ORDER BY s.enabled DESC,s.start_time,z.zone_code
            """,
            params,
        )
        rows = cur.fetchall()
    return {"farm_id": farm_id, "zone": zone, "items": rows, "total": len(rows)}


@app.get("/farms/{farm_id}/commands")
def command_logs(
    farm_id: str,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    with conn() as db, db.cursor() as cur:
        params: list[Any] = [farm_id]
        status_filter = ""
        if status:
            status_filter = " AND c.status=%s"
            params.append(status)
        params.append(limit)
        cur.execute(
            f"""
            SELECT c.command_id,c.idempotency_key,c.requested_by,c.farm_id,z.zone_code,
                   d.device_name,p.port_number,c.command_type,c.parameters,c.source_channel,
                   c.status,c.confirmation_required,c.requested_at,c.confirmed_at,c.executed_at,
                   c.result,c.error_message,c.correlation_id
            FROM farm_db.control_commands c
            LEFT JOIN farm_db.zones z ON z.zone_id=c.zone_id
            LEFT JOIN farm_db.devices d ON d.device_id=c.device_id
            LEFT JOIN farm_db.device_ports p ON p.port_id=c.port_id
            WHERE c.farm_id=%s {status_filter}
            ORDER BY c.requested_at DESC LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()
    return {"farm_id": farm_id, "status": status, "items": rows, "total": len(rows)}


@app.get("/farms/{farm_id}/alerts")
def alerts(farm_id: str, zone: str | None = None, status: str = "open", limit: int = 20):
    with conn() as db, db.cursor() as cur:
        params: list[Any] = [farm_id, status]
        where = "a.farm_id=%s AND a.status=%s"
        if zone:
            where += " AND upper(z.zone_code)=upper(%s)"
            params.append(zone)
        params.append(limit)
        cur.execute(
            f"""
            SELECT a.*,z.zone_code,z.zone_name
            FROM farm_db.alerts a
            LEFT JOIN farm_db.zones z ON z.zone_id=a.zone_id
            WHERE {where}
            ORDER BY CASE a.severity WHEN 'urgent' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC,
                     a.detected_at DESC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()
    return {"items": rows, "total": len(rows)}

@app.get("/farms/{farm_id}/climate-summary")
def climate_summary(farm_id: str, zone: str | None = None, hours: int = Query(24, ge=1, le=2160)):
    metrics = ["temperature", "air_humidity", "soil_moisture", "ph", "ec"]
    with conn() as db, db.cursor() as cur:
        z = zone_row(cur, farm_id, zone)
        if not z:
            raise HTTPException(status_code=404, detail="Không tìm thấy khu được yêu cầu.")
        cur.execute(
            """
            SELECT metric_type,
                   avg(value)::float AS mean,
                   min(value)::float AS min,
                   max(value)::float AS max,
                   count(*) AS sample_count,
                   max(observed_at) AS latest_at
            FROM farm_db.sensor_readings
            WHERE farm_id=%s AND zone_id=%s AND observed_at >= now()-(%s * interval '1 hour')
                  AND metric_type = ANY(%s)
            GROUP BY metric_type
            """,
            (farm_id, z["zone_id"], hours, metrics),
        )
        rows = cur.fetchall()
    by_metric = {row["metric_type"]: row for row in rows}
    return {
        "farm_id": farm_id,
        "zone_id": z["zone_id"],
        "zone_code": z["zone_code"],
        "hours": hours,
        "metrics": by_metric,
        "data_completeness": round(len(by_metric) / len(metrics), 3),
    }



def _ensemble_daily_series(daily: dict[str, Any], base_key: str) -> list[float]:
    direct = daily.get(base_key)
    if isinstance(direct, list):
        return [float(v) for v in direct if v is not None]
    candidate_keys = [key for key in daily if key == base_key or key.startswith(base_key + "_")]
    series_list = [daily[key] for key in candidate_keys if isinstance(daily.get(key), list)]
    if not series_list:
        return []
    result: list[float] = []
    for index in range(max(len(values) for values in series_list)):
        values = [float(series[index]) for series in series_list if index < len(series) and series[index] is not None]
        if values:
            result.append(sum(values) / len(values))
    return result


@app.get("/farms/{farm_id}/seasonal-outlook")
def seasonal_outlook(farm_id: str, forecast_days: int = Query(90, ge=30, le=210)):
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT farm_id,farm_name,latitude,longitude,region FROM farm_db.farms WHERE farm_id=%s", (farm_id,))
        farm = cur.fetchone()
        if not farm:
            raise HTTPException(status_code=404, detail="Không tìm thấy vườn.")
        if farm["latitude"] is None or farm["longitude"] is None:
            return {"available": False, "reason": "Vườn chưa có tọa độ để lấy dự báo mùa vụ.", "farm_id": farm_id}

    endpoint = "https://seasonal-api.open-meteo.com/v1/seasonal"
    params = {
        "latitude": float(farm["latitude"]),
        "longitude": float(farm["longitude"]),
        "daily": "temperature_2m_mean,temperature_2m_max,temperature_2m_min,relative_humidity_2m_mean,precipitation_sum",
        "forecast_days": forecast_days,
        "timezone": "Asia/Ho_Chi_Minh",
    }
    try:
        response = httpx.get(endpoint, params=params, timeout=25, follow_redirects=True)
        response.raise_for_status()
        body = response.json()
        daily = body.get("daily") or {}
        temperature_mean = _ensemble_daily_series(daily, "temperature_2m_mean")
        temperature_max = _ensemble_daily_series(daily, "temperature_2m_max")
        temperature_min = _ensemble_daily_series(daily, "temperature_2m_min")
        humidity = _ensemble_daily_series(daily, "relative_humidity_2m_mean")
        precipitation = _ensemble_daily_series(daily, "precipitation_sum")
        if not temperature_mean:
            raise ValueError("Nhà cung cấp không trả chuỗi nhiệt độ mùa vụ.")
        summary = {
            "available": True,
            "farm_id": farm_id,
            "farm_name": farm["farm_name"],
            "region": farm["region"],
            "forecast_days": len(temperature_mean),
            "temperature_mean": round(sum(temperature_mean) / len(temperature_mean), 2),
            "temperature_min": round(min(temperature_min or temperature_mean), 2),
            "temperature_max": round(max(temperature_max or temperature_mean), 2),
            "air_humidity_mean": round(sum(humidity) / len(humidity), 2) if humidity else None,
            "precipitation_total_mm": round(sum(precipitation), 2) if precipitation else None,
            "provider": "Open-Meteo Seasonal Forecast (ECMWF)",
            "source_url": str(response.url),
            "limitations": [
                "Dự báo mùa vụ có độ phân giải khu vực, không thay thế trạm đo tại vườn.",
                "Dữ liệu mùa vụ chưa hiệu chỉnh sai lệch cục bộ; cần kết hợp IoT và chuyên gia nông học.",
                "Không dùng riêng dự báo này để cam kết năng suất hoặc lợi nhuận.",
            ],
        }
        try:
            from psycopg.types.json import Jsonb
            with conn() as db, db.cursor() as cur:
                cur.execute(
                    "INSERT INTO farm_db.external_climate_snapshots(farm_id,provider,horizon_days,source_url,payload) VALUES (%s,%s,%s,%s,%s)",
                    (farm_id, summary["provider"], summary["forecast_days"], summary["source_url"], Jsonb(summary)),
                )
                db.commit()
        except Exception:
            pass
        return summary
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return {
            "available": False,
            "farm_id": farm_id,
            "reason": f"Chưa lấy được dự báo mùa vụ: {exc}",
            "provider": "Open-Meteo Seasonal Forecast (ECMWF)",
            "source_url": "https://open-meteo.com/en/docs/seasonal-forecast-api",
        }

# ============================================================
# V9 - Realtime Data Studio API
# ============================================================
import asyncio
import csv
import io
import json
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb


class StudioQueryRequest(BaseModel):
    farm_id: str
    zone: str | None = None
    metric: str = "soil_moisture"
    hours: int = Field(default=1, ge=1, le=168)
    bucket_seconds: int = Field(default=10, ge=1, le=3600)
    aggregate: str = "avg"


def _studio_zone_id(cur, farm_id: str, zone: str | None) -> str | None:
    if not zone:
        return None
    cur.execute("SELECT zone_id FROM farm_db.zones WHERE farm_id=%s AND upper(zone_code)=upper(%s)", (farm_id, zone))
    row = cur.fetchone()
    return row["zone_id"] if row else "__missing__"


@app.get("/studio/catalog")
def studio_catalog(request: Request):
    with conn() as db, db.cursor() as cur:
        user = getattr(request.state, "user", None)
        allowed_ids = None if user is None else [x["farm_id"] for x in user.get("farms", []) if x.get("can_read")]
        if allowed_ids is None:
            cur.execute("SELECT farm_id,farm_name,crop_name,region FROM farm_db.farms ORDER BY farm_name")
            farms = cur.fetchall()
            cur.execute("SELECT zone_id,farm_id,zone_code,zone_name,crop_name FROM farm_db.zones ORDER BY farm_id,zone_code")
            zones = cur.fetchall()
        elif not allowed_ids:
            farms, zones = [], []
        else:
            cur.execute("SELECT farm_id,farm_name,crop_name,region FROM farm_db.farms WHERE farm_id=ANY(%s) ORDER BY farm_name", (allowed_ids,))
            farms = cur.fetchall()
            cur.execute("SELECT zone_id,farm_id,zone_code,zone_name,crop_name FROM farm_db.zones WHERE farm_id=ANY(%s) ORDER BY farm_id,zone_code", (allowed_ids,))
            zones = cur.fetchall()
        cur.execute("SELECT DISTINCT metric_type,unit FROM farm_db.sensors WHERE active=true ORDER BY metric_type,unit")
        metrics = cur.fetchall()
        cur.execute("SELECT * FROM farm_db.metric_rules WHERE enabled=true ORDER BY metric_type,rule_name")
        rules = cur.fetchall()
    return {"farms": farms, "zones": zones, "metrics": metrics, "evaluation_rules": rules}


@app.get("/studio/stats")
def studio_stats(farm_id: str | None = None):
    with conn() as db, db.cursor() as cur:
        params: list[Any] = []
        farm_filter = ""
        if farm_id:
            farm_filter = " WHERE farm_id=%s"
            params.append(farm_id)
        cur.execute(f"SELECT count(*) AS total_rows,max(observed_at) AS latest_observed_at FROM farm_db.sensor_readings{farm_filter}", params)
        readings = cur.fetchone()
        cur.execute(
            """
            SELECT count(*) FILTER (WHERE received_at >= now()-interval '1 minute') AS packets_last_minute,
                   coalesce(sum(inserted_readings) FILTER (WHERE received_at >= now()-interval '1 minute'),0) AS readings_last_minute,
                   round(avg(insert_latency_ms) FILTER (WHERE received_at >= now()-interval '1 minute'),2) AS avg_ingest_latency_ms,
                   max(received_at) AS latest_packet_at
            FROM farm_db.telemetry_ingest_events
            WHERE farm_id=%s
            """,
            (farm_id,),
        )
        ingest = cur.fetchone()
        cur.execute("SELECT count(*) AS total_models FROM knowledge_db.model_registry WHERE status IN ('ready','approved','experimental')")
        models = cur.fetchone()
        cur.execute("SELECT count(*) AS predictions_last_hour FROM farm_db.farm_predictions WHERE farm_id=%s AND created_at >= now()-interval '1 hour'", (farm_id,))
        predictions = cur.fetchone()
    return {**readings, **ingest, **models, **predictions}


DATA_GROUP_SPECS: list[dict[str, Any]] = [
    {
        "code": "sensor_readings",
        "label": "Số đo cảm biến",
        "fresh_seconds": 1800,
        "query": """
            SELECT count(*)::bigint AS row_count,min(observed_at) AS oldest_at,max(observed_at) AS newest_at,
                   jsonb_build_object('good',count(*) FILTER (WHERE quality='good'),'suspect',count(*) FILTER (WHERE quality='suspect'),'bad',count(*) FILTER (WHERE quality='bad')) AS details
            FROM farm_db.sensor_readings WHERE farm_id=%s
        """,
    },
    {
        "code": "device_status",
        "label": "Trạng thái thiết bị",
        "fresh_seconds": 30,
        "query": """
            SELECT count(*)::bigint AS row_count,min(ds.observed_at) AS oldest_at,max(ds.observed_at) AS newest_at,
                   jsonb_build_object('online',count(*) FILTER (WHERE ds.online),'offline',count(*) FILTER (WHERE NOT ds.online)) AS details
            FROM farm_db.device_status ds JOIN farm_db.devices d ON d.device_id=ds.device_id WHERE d.farm_id=%s
        """,
    },
    {
        "code": "irrigation_schedules",
        "label": "Lịch tưới",
        "fresh_seconds": None,
        "query": """
            SELECT count(*)::bigint AS row_count,NULL::timestamptz AS oldest_at,NULL::timestamptz AS newest_at,
                   jsonb_build_object('enabled',count(*) FILTER (WHERE enabled),'disabled',count(*) FILTER (WHERE NOT enabled)) AS details
            FROM farm_db.irrigation_schedules WHERE farm_id=%s
        """,
    },
    {
        "code": "irrigation_runs",
        "label": "Lịch sử tưới",
        "fresh_seconds": 86400,
        "query": """
            SELECT count(*)::bigint AS row_count,min(started_at) AS oldest_at,max(started_at) AS newest_at,
                   jsonb_build_object('success',count(*) FILTER (WHERE result='success'),'failed',count(*) FILTER (WHERE result='failed'),'running',count(*) FILTER (WHERE result='running')) AS details
            FROM farm_db.irrigation_runs WHERE farm_id=%s
        """,
    },
    {
        "code": "control_commands",
        "label": "Nhật ký lệnh điều khiển",
        "fresh_seconds": 86400,
        "query": """
            SELECT count(*)::bigint AS row_count,min(requested_at) AS oldest_at,max(requested_at) AS newest_at,
                   jsonb_build_object('pending_confirmation',count(*) FILTER (WHERE status='pending_confirmation'),'executed',count(*) FILTER (WHERE status='executed'),'failed',count(*) FILTER (WHERE status='failed')) AS details
            FROM farm_db.control_commands WHERE farm_id=%s
        """,
    },
    {
        "code": "alerts",
        "label": "Cảnh báo",
        "fresh_seconds": 86400,
        "query": """
            SELECT count(*)::bigint AS row_count,min(detected_at) AS oldest_at,max(detected_at) AS newest_at,
                   jsonb_build_object('open',count(*) FILTER (WHERE status='open'),'resolved',count(*) FILTER (WHERE status='resolved'),'urgent',count(*) FILTER (WHERE severity='urgent')) AS details
            FROM farm_db.alerts WHERE farm_id=%s
        """,
    },
    {
        "code": "farm_profile",
        "label": "Hồ sơ khách hàng / vườn",
        "fresh_seconds": None,
        "query": """
            SELECT (1+(SELECT count(*) FROM farm_db.zones WHERE farm_id=f.farm_id)+(SELECT count(*) FROM farm_db.devices WHERE farm_id=f.farm_id)+(SELECT count(*) FROM farm_db.sensors WHERE farm_id=f.farm_id))::bigint AS row_count,
                   f.created_at AS oldest_at,f.created_at AS newest_at,
                   jsonb_build_object('farms',1,'zones',(SELECT count(*) FROM farm_db.zones WHERE farm_id=f.farm_id),'devices',(SELECT count(*) FROM farm_db.devices WHERE farm_id=f.farm_id),'sensors',(SELECT count(*) FROM farm_db.sensors WHERE farm_id=f.farm_id)) AS details
            FROM farm_db.farms f WHERE f.farm_id=%s
        """,
    },
    {
        "code": "chat_messages",
        "label": "Hội thoại chatbot",
        "fresh_seconds": None,
        "query": """
            SELECT count(m.message_id)::bigint AS row_count,min(m.created_at) AS oldest_at,max(m.created_at) AS newest_at,
                   jsonb_build_object('farmer',count(*) FILTER (WHERE m.sender_type='farmer'),'bot',count(*) FILTER (WHERE m.sender_type='bot')) AS details
            FROM support_db.conversations c LEFT JOIN support_db.chat_messages m ON m.conversation_id=c.conversation_id
            WHERE c.farm_id=%s
        """,
    },
    {
        "code": "ingest_attempts",
        "label": "Nhật ký tiếp nhận dữ liệu",
        "fresh_seconds": 60,
        "query": """
            SELECT count(*)::bigint AS row_count,min(received_at) AS oldest_at,max(received_at) AS newest_at,
                   jsonb_build_object('accepted',count(*) FILTER (WHERE status='accepted'),'duplicate',count(*) FILTER (WHERE status='duplicate'),'rejected',count(*) FILTER (WHERE status='rejected'),'error',count(*) FILTER (WHERE status='error')) AS details
            FROM ops_db.ingest_attempts WHERE farm_id=%s
        """,
    },
]


@app.get("/studio/data-groups")
def studio_data_groups(farm_id: str):
    items: list[dict[str, Any]] = []
    with conn() as db, db.cursor() as cur:
        for spec in DATA_GROUP_SPECS:
            cur.execute(spec["query"], (farm_id,))
            row = cur.fetchone() or {"row_count": 0, "oldest_at": None, "newest_at": None, "details": {}}
            count = int(row.get("row_count") or 0)
            newest = row.get("newest_at")
            age = age_seconds(newest)
            threshold = spec["fresh_seconds"]
            if count == 0:
                status = "missing"
            elif threshold is None:
                status = "available"
            else:
                status = "fresh" if age is not None and age <= threshold else "stale"
            items.append(
                {
                    "data_group": spec["code"],
                    "label": spec["label"],
                    "row_count": count,
                    "oldest_at": row.get("oldest_at"),
                    "newest_at": newest,
                    "freshness_seconds": round(age, 1) if age is not None else None,
                    "status": status,
                    "details": row.get("details") or {},
                }
            )
        cur.execute(
            """
            SELECT data_origin,count(*)::bigint AS row_count,max(observed_at) AS newest_at
            FROM farm_db.sensor_readings WHERE farm_id=%s
            GROUP BY data_origin ORDER BY data_origin
            """,
            (farm_id,),
        )
        origins = cur.fetchall()
    return {
        "farm_id": farm_id,
        "generated_at": datetime.now(timezone.utc),
        "items": items,
        "sensor_origins": origins,
        "policy": {
            "missing": "Nhóm chưa có dữ liệu, chatbot không được suy đoán.",
            "stale": "Nhóm có dữ liệu nhưng đã quá ngưỡng freshness; câu trả lời phải kèm cảnh báo trễ.",
            "provenance_required": True,
        },
    }


@app.get("/studio/daily-report")
def studio_daily_report(farm_id: str, days: int = Query(default=7, ge=1, le=90)):
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            WITH args AS (SELECT %s::text AS farm_id,%s::int AS days),
            dates AS (
              SELECT generate_series(current_date-((SELECT days FROM args)-1),current_date,interval '1 day')::date AS report_date
            ),
            groups(data_group) AS (VALUES
              ('sensor_readings'),('device_status'),('irrigation_runs'),('control_commands'),('alerts'),('chat_messages'),('ingest_attempts')
            ),
            events AS (
              SELECT timezone('Asia/Ho_Chi_Minh',observed_at)::date AS report_date,'sensor_readings'::text AS data_group,observed_at AS event_at,'accepted'::text AS status
              FROM farm_db.sensor_readings WHERE farm_id=(SELECT farm_id FROM args)
              UNION ALL
              SELECT timezone('Asia/Ho_Chi_Minh',ds.observed_at)::date,'device_status',ds.observed_at,'accepted'
              FROM farm_db.device_status ds JOIN farm_db.devices d ON d.device_id=ds.device_id WHERE d.farm_id=(SELECT farm_id FROM args)
              UNION ALL
              SELECT timezone('Asia/Ho_Chi_Minh',started_at)::date,'irrigation_runs',started_at,'accepted'
              FROM farm_db.irrigation_runs WHERE farm_id=(SELECT farm_id FROM args)
              UNION ALL
              SELECT timezone('Asia/Ho_Chi_Minh',requested_at)::date,'control_commands',requested_at,CASE WHEN status='failed' THEN 'error' ELSE 'accepted' END
              FROM farm_db.control_commands WHERE farm_id=(SELECT farm_id FROM args)
              UNION ALL
              SELECT timezone('Asia/Ho_Chi_Minh',detected_at)::date,'alerts',detected_at,'accepted'
              FROM farm_db.alerts WHERE farm_id=(SELECT farm_id FROM args)
              UNION ALL
              SELECT timezone('Asia/Ho_Chi_Minh',m.created_at)::date,'chat_messages',m.created_at,'accepted'
              FROM support_db.chat_messages m JOIN support_db.conversations c ON c.conversation_id=m.conversation_id WHERE c.farm_id=(SELECT farm_id FROM args)
              UNION ALL
              SELECT timezone('Asia/Ho_Chi_Minh',received_at)::date,'ingest_attempts',received_at,status
              FROM ops_db.ingest_attempts WHERE farm_id=(SELECT farm_id FROM args)
            ),
            totals AS (
              SELECT report_date,data_group,count(*)::bigint AS row_count,min(event_at) AS oldest_at,max(event_at) AS newest_at,
                     count(*) FILTER (WHERE status='accepted')::bigint AS accepted_count,
                     count(*) FILTER (WHERE status='duplicate')::bigint AS duplicate_count,
                     count(*) FILTER (WHERE status='rejected')::bigint AS rejected_count,
                     count(*) FILTER (WHERE status='error')::bigint AS error_count
              FROM events
              WHERE report_date >= current_date-((SELECT days FROM args)-1)
              GROUP BY report_date,data_group
            )
            SELECT d.report_date,g.data_group,coalesce(t.row_count,0)::bigint AS row_count,
                   coalesce(t.accepted_count,0)::bigint AS accepted_count,
                   coalesce(t.duplicate_count,0)::bigint AS duplicate_count,
                   coalesce(t.rejected_count,0)::bigint AS rejected_count,
                   coalesce(t.error_count,0)::bigint AS error_count,t.oldest_at,t.newest_at,
                   CASE WHEN t.newest_at IS NULL THEN NULL ELSE round(extract(epoch FROM (now()-t.newest_at))::numeric,1) END AS freshness_seconds
            FROM dates d CROSS JOIN groups g
            LEFT JOIN totals t ON t.report_date=d.report_date AND t.data_group=g.data_group
            ORDER BY d.report_date DESC,g.data_group
            """,
            (farm_id, days),
        )
        rows = cur.fetchall()
    return {"farm_id": farm_id, "days": days, "generated_at": datetime.now(timezone.utc), "items": rows}


@app.post("/studio/daily-report/snapshot")
def snapshot_daily_report(farm_id: str, request: Request, days: int = Query(default=7, ge=1, le=90)):
    user = getattr(request.state, "user", None)
    if user is not None and user.get("role") != "technician":
        raise HTTPException(status_code=403, detail="Chỉ kỹ thuật viên được chốt snapshot báo cáo.")
    report = studio_daily_report(farm_id=farm_id, days=days)
    with conn() as db, db.cursor() as cur:
        for row in report["items"]:
            cur.execute(
                """
                INSERT INTO ops_db.daily_data_reports(
                  report_date,farm_id,data_group,row_count,accepted_count,duplicate_count,rejected_count,
                  oldest_observed_at,newest_observed_at,freshness_seconds,metadata,generated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (report_date,farm_id,data_group) DO UPDATE SET
                  row_count=excluded.row_count,accepted_count=excluded.accepted_count,
                  duplicate_count=excluded.duplicate_count,rejected_count=excluded.rejected_count,
                  oldest_observed_at=excluded.oldest_observed_at,newest_observed_at=excluded.newest_observed_at,
                  freshness_seconds=excluded.freshness_seconds,metadata=excluded.metadata,generated_at=now()
                """,
                (
                    row["report_date"],farm_id,row["data_group"],row["row_count"],row["accepted_count"],
                    row["duplicate_count"],row["rejected_count"],row["oldest_at"],row["newest_at"],
                    row["freshness_seconds"],Jsonb({"source": "live_query", "error_count": row["error_count"]}),
                ),
            )
        db.commit()
    return {"saved": True, "farm_id": farm_id, "rows": len(report["items"]), "generated_at": datetime.now(timezone.utc)}


@app.get("/studio/grid")
def studio_grid(
    farm_id: str | None = None,
    zone: str | None = None,
    minutes: int = Query(default=10, ge=1, le=10080),
    limit: int = Query(default=200, ge=10, le=2000),
):
    with conn() as db, db.cursor() as cur:
        params: list[Any] = [minutes]
        filters = ["r.observed_at >= now()-(%s || ' minutes')::interval"]
        if farm_id:
            filters.append("r.farm_id=%s")
            params.append(farm_id)
        if zone:
            filters.append("upper(z.zone_code)=upper(%s)")
            params.append(zone)
        params.append(limit)
        cur.execute(
            f"""
            SELECT date_trunc('second',r.observed_at) AS observed_at,r.farm_id,f.farm_name,
                   r.zone_id,z.zone_code,z.zone_name,
                   max(r.value) FILTER (WHERE r.metric_type='soil_moisture')::float8 AS soil_moisture,
                   max(r.value) FILTER (WHERE r.metric_type='air_humidity')::float8 AS air_humidity,
                   max(r.value) FILTER (WHERE r.metric_type='temperature')::float8 AS temperature,
                   max(r.value) FILTER (WHERE r.metric_type='ec')::float8 AS ec,
                   max(r.value) FILTER (WHERE r.metric_type='ph')::float8 AS ph,
                   max(r.value) FILTER (WHERE r.metric_type='flow_rate')::float8 AS flow_rate,
                   string_agg(DISTINCT r.quality, ',') AS quality,
                   string_agg(DISTINCT r.data_origin, ',') AS data_origin,
                   string_agg(DISTINCT coalesce(r.simulation_profile_version,''), ',') AS simulation_profile_version
            FROM farm_db.sensor_readings r
            JOIN farm_db.farms f ON f.farm_id=r.farm_id
            LEFT JOIN farm_db.zones z ON z.zone_id=r.zone_id
            WHERE {' AND '.join(filters)}
            GROUP BY date_trunc('second',r.observed_at),r.farm_id,f.farm_name,r.zone_id,z.zone_code,z.zone_name
            ORDER BY observed_at DESC LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()
    return {"items": rows, "total": len(rows), "columns": ["observed_at","farm_name","zone_code","soil_moisture","air_humidity","temperature","ec","ph","flow_rate","quality","data_origin","simulation_profile_version"]}


@app.get("/studio/ingest-events")
def studio_ingest_events(farm_id: str | None = None, limit: int = Query(default=50, ge=1, le=500)):
    with conn() as db, db.cursor() as cur:
        if farm_id:
            cur.execute(
                """SELECT event_id,packet_id,mqtt_topic,farm_id,zone_id,message_type,sent_at,received_at,
                          inserted_readings,insert_latency_ms,status,error_message
                   FROM farm_db.telemetry_ingest_events WHERE farm_id=%s ORDER BY received_at DESC LIMIT %s""",
                (farm_id, limit),
            )
        else:
            cur.execute(
                """SELECT event_id,packet_id,mqtt_topic,farm_id,zone_id,message_type,sent_at,received_at,
                          inserted_readings,insert_latency_ms,status,error_message
                   FROM farm_db.telemetry_ingest_events ORDER BY received_at DESC LIMIT %s""",
                (limit,),
            )
        rows = cur.fetchall()
    return {"items": rows, "total": len(rows)}


@app.get("/studio/series")
def studio_series(
    farm_id: str,
    metric: str = "soil_moisture",
    zone: str | None = None,
    hours: int = Query(default=1, ge=1, le=168),
    bucket_seconds: int = Query(default=10, ge=1, le=3600),
):
    with conn() as db, db.cursor() as cur:
        zone_id = _studio_zone_id(cur, farm_id, zone)
        if zone_id == "__missing__":
            raise HTTPException(status_code=404, detail="Không tìm thấy khu.")
        params: list[Any] = [bucket_seconds, farm_id, metric, hours]
        zone_filter = ""
        if zone_id:
            zone_filter = " AND r.zone_id=%s"
            params.append(zone_id)
        cur.execute(
            f"""
            SELECT date_bin((%s || ' seconds')::interval,r.observed_at,timestamptz '2000-01-01') AS bucket,
                   avg(r.value)::float8 AS avg_value,min(r.value)::float8 AS min_value,max(r.value)::float8 AS max_value,
                   stddev_pop(r.value)::float8 AS stddev,count(*) AS samples,
                   string_agg(DISTINCT r.data_origin, ',') AS data_origin,
                   string_agg(DISTINCT coalesce(r.simulation_profile_version,''), ',') AS simulation_profile_version
            FROM farm_db.sensor_readings r
            WHERE r.farm_id=%s AND r.metric_type=%s AND r.observed_at >= now()-(%s || ' hours')::interval {zone_filter}
            GROUP BY bucket ORDER BY bucket
            """,
            params,
        )
        rows = cur.fetchall()
    return {"farm_id": farm_id, "zone": zone, "metric": metric, "bucket_seconds": bucket_seconds, "items": rows}


@app.post("/studio/query")
def studio_query(payload: StudioQueryRequest, request: Request):
    require_farm_access(request, payload.farm_id)
    allowed_aggregates = {
        "avg": "avg(r.value)", "min": "min(r.value)", "max": "max(r.value)",
        "stddev": "stddev_pop(r.value)", "count": "count(*)::float8",
    }
    if payload.aggregate not in allowed_aggregates:
        raise HTTPException(status_code=400, detail="aggregate chỉ nhận avg, min, max, stddev hoặc count")
    with conn() as db, db.cursor() as cur:
        zone_id = _studio_zone_id(cur, payload.farm_id, payload.zone)
        if zone_id == "__missing__":
            raise HTTPException(status_code=404, detail="Không tìm thấy khu.")
        params: list[Any] = [payload.bucket_seconds, payload.farm_id, payload.metric, payload.hours]
        zone_filter = ""
        if zone_id and zone_id != "__missing__":
            zone_filter = " AND r.zone_id=%s"
            params.append(zone_id)
        cur.execute(
            f"""
            SELECT date_bin((%s || ' seconds')::interval,r.observed_at,timestamptz '2000-01-01') AS bucket,
                   {allowed_aggregates[payload.aggregate]}::float8 AS value,count(*) AS samples
            FROM farm_db.sensor_readings r
            WHERE r.farm_id=%s AND r.metric_type=%s AND r.observed_at >= now()-(%s || ' hours')::interval {zone_filter}
            GROUP BY bucket ORDER BY bucket
            """,
            params,
        )
        rows = cur.fetchall()
    return {"query": payload.model_dump(), "sql_semantics": "time bucket + safe aggregate", "items": rows}


@app.get("/studio/evaluate")
def studio_evaluate(
    farm_id: str,
    metric: str = "soil_moisture",
    zone: str | None = None,
    minutes: int = Query(default=60, ge=5, le=10080),
    expected_interval_seconds: int = Query(default=2, ge=1, le=3600),
):
    with conn() as db, db.cursor() as cur:
        zone_id = _studio_zone_id(cur, farm_id, zone)
        if zone_id == "__missing__":
            raise HTTPException(status_code=404, detail="Không tìm thấy khu.")
        params: list[Any] = [farm_id, metric, minutes]
        zone_filter = ""
        if zone_id:
            zone_filter = " AND r.zone_id=%s"
            params.append(zone_id)
        cur.execute(
            f"""
            SELECT count(*) AS sample_count,min(observed_at) AS first_at,max(observed_at) AS last_at,
                   avg(value)::float8 AS avg_value,min(value)::float8 AS min_value,max(value)::float8 AS max_value,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY value)::float8 AS median_value,
                   stddev_pop(value)::float8 AS stddev_value,
                   regr_slope(value::float8,extract(epoch FROM observed_at)) * 3600 AS slope_per_hour,
                   count(*) FILTER (WHERE quality='suspect') AS suspect_count,
                   count(*) FILTER (WHERE quality='bad') AS bad_count
            FROM farm_db.sensor_readings r
            WHERE r.farm_id=%s AND r.metric_type=%s AND r.observed_at >= now()-(%s || ' minutes')::interval {zone_filter}
            """,
            params,
        )
        stats = cur.fetchone()
        sample_count = int(stats["sample_count"] or 0)
        expected_count = max(1, int(minutes * 60 / expected_interval_seconds))
        completeness = min(1.0, sample_count / expected_count)
        latest_age = age_seconds(stats.get("last_at"))

        target_min = target_max = None
        if zone_id:
            cur.execute("SELECT moisture_min,moisture_max,ec_min,ec_max,ph_min,ph_max FROM farm_db.zones WHERE zone_id=%s", (zone_id,))
            z = cur.fetchone()
            if metric == "soil_moisture": target_min,target_max = z["moisture_min"],z["moisture_max"]
            elif metric == "ec": target_min,target_max = z["ec_min"],z["ec_max"]
            elif metric == "ph": target_min,target_max = z["ph_min"],z["ph_max"]
        threshold = {"available": target_min is not None and target_max is not None}
        if threshold["available"]:
            threshold_params = [farm_id, metric, minutes]
            if zone_id: threshold_params.append(zone_id)
            cur.execute(
                f"""
                SELECT count(*) FILTER (WHERE value BETWEEN %s AND %s) AS inside,
                       count(*) FILTER (WHERE value < %s) AS below,
                       count(*) FILTER (WHERE value > %s) AS above,count(*) AS total
                FROM farm_db.sensor_readings r
                WHERE r.farm_id=%s AND r.metric_type=%s AND r.observed_at >= now()-(%s || ' minutes')::interval {zone_filter}
                """,
                [target_min,target_max,target_min,target_max,*threshold_params],
            )
            th = cur.fetchone(); total = max(1,int(th["total"] or 0))
            threshold.update({"target_min": float(target_min),"target_max": float(target_max),"inside_percent": round(int(th["inside"] or 0)*100/total,2),"below_seconds": int(th["below"] or 0)*expected_interval_seconds,"above_seconds": int(th["above"] or 0)*expected_interval_seconds})

        cur.execute(
            """SELECT count(*) AS total,count(*) FILTER (WHERE online=true) AS online
               FROM farm_db.device_status ds JOIN farm_db.devices d ON d.device_id=ds.device_id
               WHERE d.farm_id=%s AND ds.observed_at >= now()-(%s || ' minutes')::interval""",
            (farm_id, minutes),
        )
        uptime = cur.fetchone(); uptime_total=max(1,int(uptime["total"] or 0))
        cur.execute(
            """SELECT count(*) AS total,count(*) FILTER (WHERE result='success') AS success,
                      coalesce(sum(water_liters),0)::float8 AS total_liters
               FROM farm_db.irrigation_runs WHERE farm_id=%s AND started_at >= now()-(%s || ' minutes')::interval""",
            (farm_id, minutes),
        )
        irrigation = cur.fetchone(); irr_total=max(1,int(irrigation["total"] or 0))

        irrigation_response: dict[str, Any] = {"available": False}
        if metric == "soil_moisture" and zone_id:
            cur.execute("SELECT started_at,ended_at FROM farm_db.irrigation_runs WHERE farm_id=%s AND zone_id=%s AND result='success' ORDER BY started_at DESC LIMIT 1", (farm_id,zone_id))
            run = cur.fetchone()
            if run:
                end_at = run["ended_at"] or run["started_at"]
                cur.execute(
                    """SELECT avg(value) FILTER (WHERE observed_at >= %s-interval '30 minutes' AND observed_at < %s)::float8 AS before_avg,
                              avg(value) FILTER (WHERE observed_at > %s AND observed_at <= %s+interval '30 minutes')::float8 AS after_avg
                       FROM farm_db.sensor_readings WHERE farm_id=%s AND zone_id=%s AND metric_type='soil_moisture'
                         AND observed_at BETWEEN %s-interval '30 minutes' AND %s+interval '30 minutes'""",
                    (run["started_at"],run["started_at"],end_at,end_at,farm_id,zone_id,run["started_at"],end_at),
                )
                response=cur.fetchone()
                if response["before_avg"] is not None and response["after_avg"] is not None:
                    irrigation_response={"available":True,"before_avg":round(float(response["before_avg"]),3),"after_avg":round(float(response["after_avg"]),3),"delta":round(float(response["after_avg"])-float(response["before_avg"]),3),"run_started_at":run["started_at"]}

        cur.execute("SELECT count(DISTINCT metric_type) AS n FROM farm_db.sensor_readings WHERE farm_id=%s AND observed_at>=now()-interval '24 hours' AND metric_type IN ('temperature','air_humidity')", (farm_id,))
        weather_have=int(cur.fetchone()["n"] or 0)

    stddev = float(stats["stddev_value"] or 0)
    avg_value = float(stats["avg_value"] or 0)
    cv = abs(stddev / avg_value) if avg_value else None
    quality_score = max(0.0, 1.0 - ((int(stats["suspect_count"] or 0) + 2*int(stats["bad_count"] or 0)) / max(1,sample_count)))
    result = {
        "farm_id": farm_id,"zone": zone,"metric": metric,"window_minutes": minutes,
        "statistics": {**stats,"coefficient_of_variation": round(cv,4) if cv is not None else None},
        "data_quality": {"expected_samples":expected_count,"actual_samples":sample_count,"completeness":round(completeness,4),"freshness_seconds":round(latest_age,2) if latest_age is not None else None,"quality_score":round(quality_score,4)},
        "threshold_compliance": threshold,
        "device_uptime": {"online_percent":round(int(uptime["online"] or 0)*100/uptime_total,2),"samples":int(uptime["total"] or 0)},
        "irrigation": {"success_percent":round(int(irrigation["success"] or 0)*100/irr_total,2) if irrigation["total"] else None,"runs":int(irrigation["total"] or 0),"total_liters":float(irrigation["total_liters"] or 0),"moisture_response":irrigation_response},
        "eto_readiness": {"ready":False,"available_core_metrics":weather_have,"missing":["solar_radiation","wind_speed"],"note":"Không tính ETo FAO-56 khi thiếu bức xạ và gió; hệ thống chỉ báo mức sẵn sàng để tránh tạo kết quả giả."},
        "interpretation": [],
    }
    if completeness < 0.9: result["interpretation"].append("Dữ liệu thiếu so với chu kỳ gửi dự kiến; cần kiểm tra kết nối hoặc cảm biến.")
    if latest_age is None or latest_age > expected_interval_seconds*3: result["interpretation"].append("Dữ liệu mới nhất đang trễ.")
    slope = stats.get("slope_per_hour")
    if slope is not None: result["interpretation"].append(f"Xu hướng {metric}: {float(slope):+.3f} đơn vị/giờ.")
    with conn() as db, db.cursor() as cur:
        cur.execute("INSERT INTO farm_db.data_evaluation_snapshots(farm_id,zone_id,metric_type,window_minutes,evaluation) VALUES (%s,%s,%s,%s,%s)", (farm_id,zone_id if zone_id not in {None,'__missing__'} else None,metric,minutes,Jsonb(json.loads(json.dumps(result,default=str)))))
        db.commit()
    return result


@app.get("/studio/export.csv")
def studio_export_csv(farm_id: str, zone: str | None = None, minutes: int = Query(default=60, ge=1, le=10080)):
    data = studio_grid(farm_id=farm_id, zone=zone, minutes=minutes, limit=2000)
    output = io.StringIO()
    fields = data["columns"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in reversed(data["items"]):
        normalized = dict(row)
        if normalized.get("observed_at"): normalized["observed_at"] = normalized["observed_at"].isoformat()
        writer.writerow(normalized)
    filename = f"nextfarm-{farm_id}-{zone or 'all'}-{minutes}m.csv"
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/studio/stream")
async def studio_stream(farm_id: str | None = None):
    async def event_generator():
        with conn() as db, db.cursor() as cur:
            if farm_id:
                cur.execute("SELECT coalesce(max(reading_id),0) AS n FROM farm_db.sensor_readings WHERE farm_id=%s", (farm_id,))
            else:
                cur.execute("SELECT coalesce(max(reading_id),0) AS n FROM farm_db.sensor_readings")
            last_id = int(cur.fetchone()["n"] or 0)
        while True:
            try:
                with conn() as db, db.cursor() as cur:
                    if farm_id:
                        cur.execute("SELECT reading_id,farm_id,zone_id,metric_type,value,unit,quality,observed_at FROM farm_db.sensor_readings WHERE farm_id=%s AND reading_id>%s ORDER BY reading_id LIMIT 50", (farm_id,last_id))
                    else:
                        cur.execute("SELECT reading_id,farm_id,zone_id,metric_type,value,unit,quality,observed_at FROM farm_db.sensor_readings WHERE reading_id>%s ORDER BY reading_id LIMIT 50", (last_id,))
                    rows=cur.fetchall()
                if rows:
                    last_id=max(int(r["reading_id"]) for r in rows)
                    payload=[]
                    for r in rows:
                        x=dict(r); x["value"]=float(x["value"]); x["observed_at"]=x["observed_at"].isoformat(); payload.append(x)
                    yield f"event: readings\ndata: {json.dumps(payload,ensure_ascii=False)}\n\n"
                else:
                    yield "event: heartbeat\ndata: {}\n\n"
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                yield f"event: error\ndata: {json.dumps({'error':str(exc)},ensure_ascii=False)}\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
