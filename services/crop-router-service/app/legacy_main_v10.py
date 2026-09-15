from __future__ import annotations

import hmac
import os
from datetime import datetime, timezone
from typing import Any

import httpx
import psycopg
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row

from app.logic import norm, resolve_crop_key as resolve_crop_key_from_catalog

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
IDENTITY_URL = os.getenv("IDENTITY_URL", "http://identity-service:8000")
INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")
SENSOR_FRESH_MINUTES = int(os.getenv("SENSOR_FRESH_MINUTES", "30"))

app = FastAPI(title="NextFarm Crop-aware AI Router", version="10.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:8080,http://localhost:8081,http://localhost:8082,http://localhost:8084",
    ).split(",") if x.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


def conn():
    if not DATABASE_URL:
        raise RuntimeError("Thiếu DATABASE_URL")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def _internal_ok(value: str | None) -> bool:
    return bool(
        INTERNAL_SERVICE_KEY
        and value
        and hmac.compare_digest(value, INTERNAL_SERVICE_KEY)
    )


def _auth_user(authorization: str | None) -> dict[str, Any]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Bách khoa AI yêu cầu đăng nhập.")
    try:
        with httpx.Client(timeout=8) as client:
            response = client.post(
                f"{IDENTITY_URL}/auth/verify",
                headers={"Authorization": authorization},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Không kết nối được dịch vụ xác thực.") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập không hợp lệ hoặc đã hết hạn.")
    try:
        return dict(response.json()["user"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Dịch vụ xác thực trả dữ liệu không hợp lệ.") from exc


def _ensure_farm(user: dict[str, Any], farm_id: str) -> None:
    allowed = any(
        str(item.get("farm_id")) == farm_id and bool(item.get("can_read"))
        for item in user.get("farms", [])
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Tài khoản không có quyền đọc vườn này.")


def _catalog() -> list[dict[str, Any]]:
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT crop_key,display_name_vi,crop_group,aliases,perennial,notes_vi
            FROM ai_db.crop_catalog
            WHERE active
            ORDER BY display_name_vi
            """
        )
        return [dict(row) for row in cur.fetchall()]


def resolve_crop_key(name: str | None, catalog: list[dict[str, Any]] | None = None) -> tuple[str, float, str]:
    return resolve_crop_key_from_catalog(name, catalog or _catalog())


def _model_status_map() -> dict[str, dict[str, Any]]:
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (model_family)
                   model_family,model_version,
                   COALESCE(deployment_status,status,'experimental') AS status,
                   metrics,quality_gate,dataset_source,training_phase,trained_at,
                   artifact_uri,artifact_path,scope_type,scope_key
            FROM knowledge_db.model_registry
            WHERE model_family IS NOT NULL
            ORDER BY model_family,trained_at DESC NULLS LAST
            """
        )
        return {str(r["model_family"]): dict(r) for r in cur.fetchall()}


def _farm_crop_rows(farm_id: str) -> list[dict[str, Any]]:
    catalog = _catalog()
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT farm_id,farm_name,crop_name FROM farm_db.farms WHERE farm_id=%s", (farm_id,))
        farm = cur.fetchone()
        if not farm:
            raise HTTPException(404, "Không tìm thấy vườn.")
        cur.execute("SELECT zone_id,zone_code,zone_name,crop_name FROM farm_db.zones WHERE farm_id=%s ORDER BY zone_code", (farm_id,))
        zones = list(cur.fetchall())
        result = []
        base_key, base_conf, base_method = resolve_crop_key(farm["crop_name"], catalog)
        result.append({"farm_id": farm_id, "farm_name": farm["farm_name"], "zone_id": None, "zone_code": None, "source_crop_name": farm["crop_name"], "crop_key": base_key, "confidence": base_conf, "mapping_method": base_method})
        for z in zones:
            source_name = z.get("crop_name") or farm["crop_name"]
            key, confidence, method = resolve_crop_key(source_name, catalog)
            result.append({"farm_id": farm_id, "farm_name": farm["farm_name"], "zone_id": z["zone_id"], "zone_code": z["zone_code"], "zone_name": z["zone_name"], "source_crop_name": source_name, "crop_key": key, "confidence": confidence, "mapping_method": method})
    return result


def _readiness_snapshot(farm_id: str, zone_id: str | None) -> dict[str, Any]:
    """Return observable inputs for one authorization-approved farm scope.

    This is intentionally conservative: an input is available only when it exists in
    PostgreSQL and time-sensitive telemetry is fresh. Advanced imagery, agronomic labels
    and weather variables stay absent until a real connector stores them.
    """
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT f.region,f.latitude,f.longitude,f.cultivation_type,f.soil_texture,f.drainage,
                   z.moisture_min,z.moisture_max,z.ec_min,z.ec_max,z.ph_min,z.ph_max
            FROM farm_db.farms f
            LEFT JOIN farm_db.zones z ON z.farm_id=f.farm_id AND z.zone_id=%s
            WHERE f.farm_id=%s
            """,
            (zone_id, farm_id),
        )
        profile = dict(cur.fetchone() or {})
        scope_sql = "farm_id=%s" + (" AND zone_id=%s" if zone_id else "")
        scope_args: tuple[Any, ...] = (farm_id, zone_id) if zone_id else (farm_id,)
        cur.execute(
            f"""
            SELECT metric_type,count(*) AS sample_count,min(observed_at) AS oldest_at,
                   max(observed_at) AS newest_at,
                   array_remove(array_agg(DISTINCT data_origin),NULL) AS data_origins
            FROM farm_db.sensor_readings
            WHERE {scope_sql}
            GROUP BY metric_type
            """,
            scope_args,
        )
        metric_rows = [dict(row) for row in cur.fetchall()]
        device_scope = "d.farm_id=%s" + (" AND d.zone_id=%s" if zone_id else "")
        cur.execute(
            f"SELECT count(*) AS n FROM farm_db.devices d WHERE {device_scope} AND d.active",
            scope_args,
        )
        device_count = int(cur.fetchone()["n"])
        cur.execute(
            f"""
            SELECT count(*) AS n,
                   count(*) FILTER (WHERE p.port_type='valve') AS valve_n,
                   count(*) FILTER (WHERE p.port_type='pump') AS pump_n
            FROM farm_db.device_status s
            JOIN farm_db.devices d ON d.device_id=s.device_id
            LEFT JOIN farm_db.device_ports p ON p.port_id=s.port_id
            WHERE {device_scope}
              AND s.observed_at >= now() - (%s * interval '1 minute')
            """,
            (*scope_args, SENSOR_FRESH_MINUTES),
        )
        device_status = dict(cur.fetchone())
        recent_device_status_count = int(device_status["n"])
        recent_valve_status_count = int(device_status["valve_n"])
        recent_pump_status_count = int(device_status["pump_n"])
        cur.execute(
            "SELECT count(*) AS n,count(water_liters) AS volume_n FROM farm_db.irrigation_runs WHERE " + scope_sql,
            scope_args,
        )
        irrigation_runs = dict(cur.fetchone())
        irrigation_run_count = int(irrigation_runs["n"])
        irrigation_volume_count = int(irrigation_runs["volume_n"])
        cur.execute(
            "SELECT count(*) AS n FROM farm_db.irrigation_schedules WHERE " + scope_sql + " AND enabled",
            scope_args,
        )
        irrigation_schedule_count = int(cur.fetchone()["n"])

    now = datetime.now(timezone.utc)
    available_inputs: set[str] = {"crop_key"}
    origins: set[str] = set()
    metrics: dict[str, Any] = {}
    oldest_values: list[datetime] = []
    newest_values: list[datetime] = []
    for row in metric_rows:
        newest = row.get("newest_at")
        oldest = row.get("oldest_at")
        fresh = bool(newest and (now - newest).total_seconds() <= SENSOR_FRESH_MINUTES * 60)
        metric = str(row["metric_type"])
        metrics[metric] = {
            "sample_count": int(row.get("sample_count") or 0),
            "oldest_at": oldest,
            "newest_at": newest,
            "fresh": fresh,
        }
        origins.update(str(value) for value in (row.get("data_origins") or []) if value)
        if oldest:
            oldest_values.append(oldest)
        if newest:
            newest_values.append(newest)
        if fresh:
            available_inputs.add(metric)
        if int(row.get("sample_count") or 0) >= 2:
            available_inputs.add(f"{metric}_timeseries")

    if metric_rows:
        available_inputs.update({"sensor_value", "observed_at", "sensor_id", "quality_flag"})
    if recent_device_status_count:
        available_inputs.update({"device_online", "sensor_age_seconds"})
    if recent_valve_status_count:
        available_inputs.add("valve_state")
    if recent_pump_status_count:
        available_inputs.add("pump_state")
    if irrigation_run_count:
        available_inputs.add("irrigation_history")
    if irrigation_volume_count:
        available_inputs.add("irrigation_volume")
    if irrigation_schedule_count:
        available_inputs.add("irrigation_schedule")
    for key in ("region", "latitude", "longitude", "cultivation_type", "soil_texture", "drainage"):
        if profile.get(key) is not None:
            available_inputs.add("soil_type" if key == "soil_texture" else key)
    if profile.get("moisture_min") is not None and profile.get("moisture_max") is not None:
        available_inputs.add("soil_water_balance")

    history_days = 0.0
    if oldest_values and newest_values:
        history_days = max(0.0, (max(newest_values) - min(oldest_values)).total_seconds() / 86400.0)
    if origins and all(value.startswith("nextfarm_") for value in origins):
        origin_kind = "production"
    elif any(value.startswith("simulated_") for value in origins):
        origin_kind = "demo"
    elif origins:
        origin_kind = "external"
    else:
        origin_kind = "unavailable"
    return {
        "available_inputs": sorted(available_inputs),
        "metrics": metrics,
        "history_days": round(history_days, 3),
        "data_origins": sorted(origins),
        "origin_kind": origin_kind,
        "production_data": origin_kind == "production",
        "device_count": device_count,
        "recent_device_status_count": recent_device_status_count,
        "recent_valve_status_count": recent_valve_status_count,
        "recent_pump_status_count": recent_pump_status_count,
        "irrigation_run_count": irrigation_run_count,
        "irrigation_volume_count": irrigation_volume_count,
        "irrigation_schedule_count": irrigation_schedule_count,
    }


def _resolve_capabilities(
    crop_key: str,
    *,
    farm_id: str | None = None,
    zone_id: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    models = _model_status_map()
    readiness = _readiness_snapshot(farm_id, zone_id) if farm_id else None
    available_inputs = set((readiness or {}).get("available_inputs", []))
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT c.capability_key,c.display_name_vi,c.category,c.implementation_type,c.model_family,
                   c.required_inputs,c.optional_inputs,c.output_kind,c.risk_level,c.default_status,
                   c.source_title,c.source_url,c.evidence_note,c.implementation_state,c.implementation_ref,
                   m.applicability,m.crop_specific_status,m.reason_vi,m.min_history_days
            FROM ai_db.model_capabilities c
            LEFT JOIN ai_db.crop_capability_map m
              ON m.capability_key=c.capability_key AND m.crop_key=%s
            WHERE c.active
            ORDER BY c.category,c.display_name_vi
            """,
            (crop_key,),
        )
        rows = list(cur.fetchall())
    output: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        reasons: list[str] = []
        mapped = item.get("crop_specific_status") or item.get("default_status") or "blocked"
        implementation_status = str(item.get("implementation_state") or "catalog_only")
        validation_status = mapped
        model_meta = models.get(str(item.get("model_family"))) if item.get("model_family") else None
        if item.get("implementation_type") == "trained_model":
            if not model_meta:
                mapped = "blocked"
                implementation_status = "missing"
                reasons.append("Chưa có artifact/model registry tương ứng.")
            else:
                implementation_status = "available"
                registry_status = str(model_meta.get("status") or "experimental")
                if registry_status != "approved" and registry_status != "ready":
                    mapped = "experimental"
                    validation_status = "experimental"
                    reasons.append(f"Model registry đang ở trạng thái {registry_status}.")
        elif implementation_status != "available":
            mapped = "blocked"
            reasons.append("Capability mới có trong catalog; V10 chưa có implementation executable.")
        required_inputs = [str(value) for value in (item.get("required_inputs") or [])]
        missing_inputs = sorted(value for value in required_inputs if value not in available_inputs) if readiness else []
        if readiness and missing_inputs:
            mapped = "blocked"
            reasons.append("Thiếu dữ liệu đầu vào tại farm/zone: " + ", ".join(missing_inputs) + ".")
        min_history_days = int(item.get("min_history_days") or 0)
        if readiness and min_history_days and float(readiness.get("history_days") or 0) < min_history_days:
            mapped = "blocked"
            reasons.append(
                f"Lịch sử mới có {readiness.get('history_days', 0)} ngày; cần tối thiểu {min_history_days} ngày."
            )
        if item.get("reason_vi"):
            reasons.append(item["reason_vi"])
        item["resolved_status"] = mapped
        item["implementation_status"] = implementation_status
        item["validation_status"] = validation_status
        item["data_status"] = "ready" if readiness and not missing_inputs else "blocked" if readiness else "not_evaluated"
        item["missing_inputs"] = missing_inputs
        item["readiness_level"] = (
            "production_candidate"
            if mapped == "ready" and bool((readiness or {}).get("production_data"))
            else "demo_ready"
            if mapped == "ready"
            else mapped
        )
        item["model"] = model_meta
        item["reasons"] = list(dict.fromkeys(reasons))
        output.append(item)
    return output, readiness


@app.get("/health")
def health():
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM ai_db.crop_catalog WHERE active")
        crops = int(cur.fetchone()["n"])
        cur.execute("SELECT count(*) AS n FROM ai_db.model_capabilities WHERE active")
        caps = int(cur.fetchone()["n"])
    return {"service": "crop-router-service", "status": "ok", "version": "10.1.0", "crop_count": crops, "capability_count": caps}


@app.get("/catalog/crops")
def crops():
    return {"items": _catalog()}


@app.get("/catalog/capabilities")
def capabilities(crop_key: str | None = Query(default=None)):
    if crop_key:
        items, _ = _resolve_capabilities(crop_key)
        return {"crop_key": crop_key, "items": items, "data_status": "not_evaluated_without_farm"}
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT * FROM ai_db.model_capabilities WHERE active ORDER BY category,display_name_vi")
        return {"items": list(cur.fetchall())}


@app.get("/me/crops")
def me_crops(authorization: str | None = Header(default=None)):
    user = _auth_user(authorization)
    items: list[dict[str, Any]] = []
    for farm in user.get("farms", []):
        if farm.get("can_read"):
            items.extend(_farm_crop_rows(str(farm["farm_id"])))
    unique = []
    seen = set()
    catalog_by_key = {r["crop_key"]: r for r in _catalog()}
    for item in items:
        key = item["crop_key"]
        if key not in seen:
            unique.append(catalog_by_key.get(key, {"crop_key": key, "display_name_vi": item["source_crop_name"]}))
            seen.add(key)
    return {"user": {"user_id": user["user_id"], "display_name": user["display_name"], "role": user["role"]}, "farm_crops": items, "unique_crops": unique}


@app.get("/farms/{farm_id}/capabilities")
def farm_capabilities(farm_id: str, zone: str | None = None, authorization: str | None = Header(default=None), x_internal_service_key: str | None = Header(default=None)):
    user = None
    if not _internal_ok(x_internal_service_key):
        user = _auth_user(authorization)
        _ensure_farm(user, farm_id)
    rows = _farm_crop_rows(farm_id)
    if zone:
        selected = next((r for r in rows if r.get("zone_code") == zone.upper()), None)
        if not selected:
            raise HTTPException(status_code=404, detail="Không tìm thấy khu trong vườn được yêu cầu.")
    else:
        selected = rows[0]
    caps, readiness = _resolve_capabilities(
        selected["crop_key"],
        farm_id=farm_id,
        zone_id=selected.get("zone_id"),
    )
    counts = {"ready": 0, "experimental": 0, "blocked": 0}
    for c in caps:
        counts[c["resolved_status"]] = counts.get(c["resolved_status"], 0) + 1
    production_candidate = bool((readiness or {}).get("production_data")) and counts.get("ready", 0) > 0
    production_blockers = []
    if not bool((readiness or {}).get("production_data")):
        production_blockers.append("Chưa có telemetry NextFarm thật cho farm/zone này.")
    if counts.get("ready", 0) <= 0:
        production_blockers.append("Chưa có capability nào vượt qua đủ implementation, validation và data gate.")
    production_blockers.append("Chưa có biên bản nghiệm thu sandbox/field, security và chuyên gia nông học cho V10.")
    return {
        "farm_id": farm_id,
        "zone": zone,
        "crop": selected,
        "counts": counts,
        "readiness": readiness,
        "production_candidate": production_candidate,
        "production_ready": False,
        "production_blockers": production_blockers,
        "capabilities": caps,
        "policy": "Capability chỉ READY khi implementation + quality gate + crop/data-domain đều đạt; production_candidate vẫn không đồng nghĩa production-ready nếu chưa nghiệm thu độc lập.",
    }
