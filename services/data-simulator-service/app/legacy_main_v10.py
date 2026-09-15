from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import psycopg
from fastapi import FastAPI
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.calibrated_model import ResearchCalibratedFarmModel

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
INTERVAL_SECONDS = float(os.getenv("SIMULATION_INTERVAL_SECONDS", "2"))
BACKFILL_HOURS = int(os.getenv("SIMULATION_BACKFILL_HOURS", "72"))
BACKFILL_STEP_MINUTES = int(os.getenv("SIMULATION_BACKFILL_STEP_MINUTES", "5"))
RANDOM_SEED = int(os.getenv("SIMULATION_RANDOM_SEED", "20260811"))
MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "").strip()
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_TLS = os.getenv("MQTT_TLS", "false").lower() == "true"
MQTT_CA_CERT = os.getenv("MQTT_CA_CERT", "").strip()
PROFILE_PATH = Path(os.getenv("SIMULATION_PROFILE_PATH", "/app/research-data/calibration/v9_profiles.json"))
CALIBRATION_PATH = Path(os.getenv("SIMULATION_REFERENCE_CALIBRATION_PATH", "/app/research-data/reference/reference_calibration.json"))
REFERENCE_LOCK_PATH = Path(os.getenv("SIMULATION_REFERENCE_LOCK_PATH", "/app/research-data/reference/reference_lock.json"))
DATA_ORIGIN = "simulated_device_calibrated_v9"
SOURCE_DATASET = "v9-downloaded-reference-calibration"

stop_event = threading.Event()
state: dict[str, Any] = {
    "running": False,
    "mqtt_connected": False,
    "last_generated_at": None,
    "generated_batches": 0,
    "published_packets": 0,
    "published_readings": 0,
    "backfill_rows": 0,
    "last_error": None,
    "startup_stage": "booting",
    "worker_restarts": 0,
}
mqtt_client: mqtt.Client | None = None
model: ResearchCalibratedFarmModel | None = None


def _require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("Thiếu DATABASE_URL; hãy chạy dịch vụ qua Docker Compose sau scripts/setup_v9_env.cmd.")
    return DATABASE_URL


def conn():
    return psycopg.connect(_require_database_url(), row_factory=dict_row)


def wait_for_database() -> None:
    for _ in range(60):
        try:
            with conn() as db, db.cursor() as cur:
                cur.execute("SELECT 1 FROM farm_db.sensors LIMIT 1")
                cur.fetchone()
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("Không kết nối được PostgreSQL/schema sau 120 giây.")


def _mqtt_reason_success(reason_code: Any) -> bool:
    """Paho MQTT v2 passes a ReasonCode object, not a plain int."""
    is_failure = getattr(reason_code, "is_failure", None)
    if is_failure is not None:
        return not bool(is_failure)
    return reason_code == 0


def on_connect(_client: mqtt.Client, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any = None) -> None:
    ok = _mqtt_reason_success(reason_code)
    state["mqtt_connected"] = ok
    state["last_error"] = None if ok else f"MQTT CONNACK rejected: {reason_code}"


def on_disconnect(_client: mqtt.Client, _userdata: Any, _flags: Any, _reason_code: Any, _properties: Any = None) -> None:
    state["mqtt_connected"] = False


def connect_mqtt() -> None:
    global mqtt_client
    if mqtt_client is not None:
        try:
            mqtt_client.loop_stop(); mqtt_client.disconnect()
        except Exception:
            pass
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="nextfarm-v9-research-calibrated-simulator", clean_session=True)
    mqtt_client.suppress_exceptions = True
    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.reconnect_delay_set(min_delay=1, max_delay=15)
    if MQTT_USERNAME:
        mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    if MQTT_TLS:
        mqtt_client.tls_set(ca_certs=MQTT_CA_CERT or None)
    state["mqtt_connected"] = False
    last_exc: Exception | None = None
    for _ in range(20):
        if stop_event.is_set(): return
        try:
            mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            mqtt_client.loop_start()
            for _ in range(20):
                if state["mqtt_connected"]:
                    state["last_error"] = None
                    return
                if stop_event.wait(0.25): return
            mqtt_client.loop_stop(); mqtt_client.disconnect()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            state["last_error"] = f"MQTT connect: {exc}"
        stop_event.wait(1)
    raise RuntimeError(f"Không kết nối được MQTT broker: {last_exc or 'timeout'}")


def list_sensors(cur) -> list[dict[str, Any]]:
    cur.execute("""
        SELECT s.sensor_id,s.farm_id,s.zone_id,s.metric_type,s.unit,s.device_id,z.zone_code
        FROM farm_db.sensors s JOIN farm_db.zones z ON z.zone_id=s.zone_id
        WHERE s.active=true ORDER BY s.farm_id,z.zone_code,s.sensor_id
    """)
    return cur.fetchall()


def grouped_sensors() -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    with conn() as db, db.cursor() as cur:
        sensors = list_sensors(cur)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for sensor in sensors:
        key = (sensor["farm_id"], sensor["zone_id"], sensor["zone_code"])
        groups.setdefault(key, []).append(sensor)
    return groups


def register_calibration() -> None:
    assert model is not None
    manifest_path = PROFILE_PATH.parent.parent / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"sources": []}
    source_ids = [s["id"] for s in manifest.get("sources", [])]
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """INSERT INTO research_db.calibration_profiles(profile_version,checksum_sha256,source_ids,parameters,active)
               VALUES (%s,%s,%s,%s,true)
               ON CONFLICT(profile_version) DO UPDATE SET checksum_sha256=EXCLUDED.checksum_sha256,source_ids=EXCLUDED.source_ids,parameters=EXCLUDED.parameters,active=true""",
            (model.profile_version, model.checksum, source_ids, Jsonb({**model.config, "reference_calibration_sha256": model.calibration_checksum})),
        )
        db.commit()


def backfill_if_needed() -> None:
    assert model is not None
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    groups = grouped_sensors()
    with conn() as db, db.cursor() as cur:
        for (farm_id, zone_id, zone_code), sensors in groups.items():
            cur.execute(
                "SELECT count(*) AS n FROM farm_db.sensor_readings WHERE farm_id=%s AND zone_id=%s AND observed_at >= %s",
                (farm_id, zone_id, now - timedelta(hours=BACKFILL_HOURS)),
            )
            # Existing V9/real telemetry is respected; only sparse histories are filled.
            if int(cur.fetchone()["n"] or 0) >= max(60, int(BACKFILL_HOURS * 60 / BACKFILL_STEP_MINUTES * max(1, len(sensors)) * 0.45)):
                continue
            start = now - timedelta(hours=BACKFILL_HOURS)
            # Isolate deterministic chronology per farm/zone while preserving one state chain.
            ts = start
            while ts < now:
                zstate = model.step(farm_id, zone_code, ts, force=True)
                for sensor in sensors:
                    value, quality = model.reading(zstate, sensor["metric_type"])
                    if value is None:
                        continue
                    cur.execute(
                        """INSERT INTO farm_db.sensor_readings(
                             sensor_id,farm_id,zone_id,metric_type,value,unit,quality,observed_at,
                             data_origin,source_dataset,simulation_profile_version,ingest_metadata
                           ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            sensor["sensor_id"], farm_id, zone_id, sensor["metric_type"], round(value, 3), sensor["unit"], quality, ts,
                            DATA_ORIGIN, SOURCE_DATASET, model.profile_version,
                            Jsonb({"mode": "historical_backfill", "research_calibrated": True, "reference_calibration_sha256": model.calibration_checksum}),
                        ),
                    )
                    state["backfill_rows"] += 1
                ts += timedelta(minutes=BACKFILL_STEP_MINUTES)
        db.commit()


def publish(topic: str, payload: dict[str, Any]) -> None:
    if not mqtt_client or not state["mqtt_connected"]:
        raise RuntimeError("MQTT chưa kết nối")
    info = mqtt_client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1)
    info.wait_for_publish(timeout=5)
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f"Publish MQTT lỗi rc={info.rc}")
    state["published_packets"] += 1


def publish_sensor_batches(now: datetime) -> int:
    assert model is not None
    groups = grouped_sensors()
    total = 0
    for (farm_id, zone_id, zone_code), sensors in groups.items():
        zstate = model.step(farm_id, zone_code, now)
        readings = []
        for sensor in sensors:
            value, quality = model.reading(zstate, sensor["metric_type"])
            if value is None:
                continue
            readings.append({
                "sensor_id": sensor["sensor_id"], "device_id": sensor.get("device_id"),
                "metric_type": sensor["metric_type"], "value": round(value, 3), "unit": sensor["unit"],
                "quality": quality, "observed_at": now.isoformat(),
                "data_origin": DATA_ORIGIN, "source_dataset": SOURCE_DATASET,
                "simulation_profile_version": model.profile_version,
            })
        if not readings:
            continue
        payload = {
            "packet_id": str(uuid.uuid4()), "message_type": "telemetry", "farm_id": farm_id,
            "zone_id": zone_id, "zone_code": zone_code, "sent_at": now.isoformat(),
            "data_origin": DATA_ORIGIN, "source_dataset": SOURCE_DATASET,
            "simulation_profile_version": model.profile_version, "reference_calibration_sha256": model.calibration_checksum,
            "readings": readings,
        }
        publish(f"nextfarm/{farm_id}/{zone_code}/telemetry", payload)
        total += len(readings)
    return total


def publish_device_status(now: datetime) -> None:
    assert model is not None
    with conn() as db, db.cursor() as cur:
        cur.execute("""
            SELECT d.device_id,p.port_id,d.farm_id,z.zone_code,p.port_type
            FROM farm_db.devices d
            LEFT JOIN farm_db.device_ports p ON p.device_id=d.device_id
            LEFT JOIN farm_db.zones z ON z.zone_id=p.zone_id
            WHERE d.active=true ORDER BY d.farm_id,d.device_id,p.port_id
        """)
        rows = cur.fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        zone_code = row.get("zone_code") or "A"
        zstate = model.step(row["farm_id"], zone_code, now)
        online = zstate.fault != "offline"
        running = None
        if row["port_id"]:
            p = model.farm_profile(row["farm_id"])
            running = bool(online and model._is_irrigating(zstate, p, now))
            if zstate.fault == "no_flow":
                running = True  # valve/pump command on but flow absent => diagnostically useful
        grouped.setdefault(row["farm_id"], []).append({
            "device_id": row["device_id"], "port_id": row["port_id"], "online": online,
            "running": running, "last_seen_at": (now if online else now - timedelta(minutes=8)).isoformat(),
        })
    for farm_id, statuses in grouped.items():
        publish(f"nextfarm/{farm_id}/all/device_status", {
            "packet_id": str(uuid.uuid4()), "message_type": "device_status", "farm_id": farm_id,
            "zone_id": None, "sent_at": now.isoformat(), "observed_at": now.isoformat(), "statuses": statuses,
            "data_origin": DATA_ORIGIN, "simulation_profile_version": model.profile_version,
        })


def generate_batch() -> None:
    now = datetime.now(timezone.utc)
    readings = publish_sensor_batches(now)
    publish_device_status(now)
    state["last_generated_at"] = now.isoformat()
    state["generated_batches"] += 1
    state["published_readings"] += readings
    state["last_error"] = None


def worker() -> None:
    global model
    state["running"] = False
    while not stop_event.is_set():
        try:
            state["startup_stage"] = "waiting_database"; wait_for_database()
            model = ResearchCalibratedFarmModel(PROFILE_PATH, CALIBRATION_PATH, RANDOM_SEED)
            register_calibration()
            state["startup_stage"] = "backfilling"; backfill_if_needed()
            state["startup_stage"] = "connecting_mqtt"; connect_mqtt()
            state["running"] = True; state["startup_stage"] = "streaming"; state["last_error"] = None
            while not stop_event.is_set():
                if not state["mqtt_connected"]:
                    raise RuntimeError("MQTT bị ngắt kết nối; đang kết nối lại.")
                generate_batch()
                stop_event.wait(INTERVAL_SECONDS)
        except Exception as exc:  # noqa: BLE001
            state["running"] = False; state["last_error"] = str(exc); state["worker_restarts"] += 1; state["startup_stage"] = "retrying"
            if mqtt_client:
                try: mqtt_client.loop_stop(); mqtt_client.disconnect()
                except Exception: pass
            stop_event.wait(3)
    state["running"] = False; state["startup_stage"] = "stopped"


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop_event.clear()
    thread = threading.Thread(target=worker, daemon=True, name="nextfarm-v9-calibrated-simulator")
    thread.start()
    yield
    stop_event.set(); thread.join(timeout=5)


app = FastAPI(title="NextFarm V10.1 Research-Calibrated Digital Farm", version="10.1.0", lifespan=lifespan)


@app.get("/health")
def health():
    recent_rows = 0; newest = None; origin_rows = 0
    try:
        with conn() as db, db.cursor() as cur:
            cur.execute("SELECT count(*) AS n,max(observed_at) AS newest,count(*) FILTER (WHERE data_origin=%s) AS origin_n FROM farm_db.sensor_readings WHERE observed_at >= now()-interval '2 minutes'", (DATA_ORIGIN,))
            row = cur.fetchone(); recent_rows = int(row["n"] or 0); newest = row["newest"]; origin_rows = int(row["origin_n"] or 0)
    except Exception as exc:  # noqa: BLE001
        state["last_error"] = state.get("last_error") or f"DB health: {exc}"
    return {
        "service": "data-simulator-service", "version": "9.0.0",
        "status": "ok" if state["running"] and state["mqtt_connected"] and origin_rows > 0 else "starting",
        "transport": "MQTT QoS 1", "interval_seconds": INTERVAL_SECONDS,
        "physical_state_min_step_seconds": model.minimum_step_seconds if model else None,
        "data_origin": DATA_ORIGIN, "simulation_profile_version": model.profile_version if model else None,
        "reference_calibration_sha256": model.calibration_checksum if model else None,
        "recent_rows_2m": recent_rows, "recent_calibrated_rows_2m": origin_rows,
        "newest_reading_at": newest, **state,
    }


@app.post("/generate-now")
def generate_now():
    generate_batch(); return {"ok": True, **state}
