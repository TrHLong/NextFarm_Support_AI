from __future__ import annotations

import json
import os
import hmac
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt
import psycopg
from fastapi import FastAPI, Header, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "nextfarm/+/+/+")
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "").strip()
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_TLS = os.getenv("MQTT_TLS", "false").lower() == "true"
MQTT_CA_CERT = os.getenv("MQTT_CA_CERT", "").strip()
INGEST_API_KEY = os.getenv("INGEST_API_KEY", "")

state: dict[str, Any] = {
    "connected": False,
    "messages_received": 0,
    "readings_inserted": 0,
    "duplicates": 0,
    "rejected": 0,
    "errors": 0,
    "last_packet_id": None,
    "last_received_at": None,
    "last_error": None,
}
client: mqtt.Client | None = None
lock = threading.Lock()


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
                cur.execute("SELECT 1")
                cur.fetchone()
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("Không kết nối được PostgreSQL.")


def parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def record_failed_attempt(topic: str, payload: Any, status: str, error: str, transport: str = "mqtt") -> None:
    """Best-effort audit for packets that never reached telemetry_ingest_events."""
    packet = payload if isinstance(payload, dict) else {}
    try:
        with conn() as db, db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops_db.ingest_attempts(
                  packet_id,farm_id,data_origin,transport,status,error_message,metadata
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    str(packet.get("packet_id") or "") or None,
                    packet.get("farm_id"),
                    str(packet.get("data_origin") or "") or None,
                    transport,
                    status,
                    error[:2000],
                    Jsonb({"mqtt_topic": topic, "message_type": packet.get("message_type"), "payload_type": type(payload).__name__}),
                ),
            )
            db.commit()
    except Exception:  # noqa: BLE001
        # Health state still exposes last_error if even the audit database is unavailable.
        pass


def store_packet(
    topic: str,
    payload: dict[str, Any],
    *,
    allowed_origins: set[str] | None = None,
    transport: str = "mqtt",
) -> dict[str, Any]:
    started = time.perf_counter()
    packet_id = str(payload.get("packet_id") or "")
    if not packet_id:
        raise ValueError("Thiếu packet_id")
    message_type = str(payload.get("message_type") or "telemetry")
    farm_id = payload.get("farm_id")
    zone_id = payload.get("zone_id")
    if message_type not in {"telemetry", "device_status"}:
        raise ValueError(f"message_type không hỗ trợ: {message_type!r}")
    if not farm_id:
        raise ValueError("Thiếu farm_id")
    sent_at = parse_dt(payload.get("sent_at"))
    inserted = 0
    # V9 standalone chỉ nhận telemetry do simulator thiết bị hiệu chỉnh phát sinh.
    # Static reference không được đẩy vào sensor_readings và packet thiếu provenance bị từ chối.
    packet_origin = str(payload.get("data_origin") or "")
    accepted_origins = allowed_origins or {"simulated_device_calibrated_v9"}
    if packet_origin not in accepted_origins:
        raise ValueError(f"data_origin không hợp lệ cho V9 runtime: {packet_origin!r}")
    packet_source = payload.get("source_dataset")
    packet_profile = payload.get("simulation_profile_version")

    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT 1 FROM farm_db.telemetry_ingest_events WHERE packet_id=%s", (packet_id,))
        if cur.fetchone():
            cur.execute(
                """
                INSERT INTO ops_db.ingest_attempts(
                  packet_id,farm_id,data_origin,transport,status,row_count,metadata
                ) VALUES (%s,%s,%s,%s,'duplicate',0,%s)
                """,
                (packet_id, farm_id, packet_origin, transport, Jsonb({"topic": topic, "message_type": message_type})),
            )
            db.commit()
            with lock:
                state["duplicates"] += 1
            return {"status": "duplicate", "packet_id": packet_id, "inserted_readings": 0}

        if message_type == "telemetry":
            readings = payload.get("readings")
            if not isinstance(readings, list) or not readings:
                raise ValueError("Telemetry packet phải có readings không rỗng")
            for reading in readings:
                observed_at = parse_dt(reading.get("observed_at") or payload.get("sent_at"))
                reading_origin = str(reading.get("data_origin") or packet_origin)
                if reading_origin != packet_origin:
                    raise ValueError("data_origin của reading không được khác provenance đã kiểm tra ở packet")
                cur.execute(
                    "SELECT farm_id,zone_id,metric_type,unit FROM farm_db.sensors WHERE sensor_id=%s AND active=true",
                    (reading["sensor_id"],),
                )
                sensor = cur.fetchone()
                if not sensor:
                    raise ValueError(f"sensor_id chưa được map hoặc đã tắt: {reading['sensor_id']!r}")
                if sensor["farm_id"] != farm_id or (zone_id and sensor["zone_id"] and sensor["zone_id"] != zone_id):
                    raise ValueError("sensor_id không thuộc farm/zone trong packet")
                if sensor["metric_type"] != reading["metric_type"] or sensor["unit"] != reading["unit"]:
                    raise ValueError("metric_type/unit không khớp data dictionary của sensor")
                cur.execute(
                    """
                    INSERT INTO farm_db.sensor_readings(
                      sensor_id,farm_id,zone_id,metric_type,value,unit,quality,observed_at,
                      data_origin,source_dataset,simulation_profile_version,ingest_metadata
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        reading["sensor_id"], farm_id, zone_id, reading["metric_type"],
                        reading["value"], reading["unit"], reading.get("quality", "good"), observed_at,
                        reading_origin,
                        reading.get("source_dataset") or packet_source,
                        reading.get("simulation_profile_version") or packet_profile,
                        Jsonb({
                            "transport": transport,
                            "topic": topic,
                            "packet_id": packet_id,
                            "generator": payload.get("generator"),
                        }),
                    ),
                )
                inserted += 1
        elif message_type == "device_status":
            observed_at = parse_dt(payload.get("observed_at") or payload.get("sent_at"))
            statuses = payload.get("statuses")
            if not isinstance(statuses, list) or not statuses:
                raise ValueError("Device-status packet phải có statuses không rỗng")
            for item in statuses:
                cur.execute(
                    """
                    SELECT d.farm_id,d.zone_id,p.port_id
                    FROM farm_db.devices d
                    LEFT JOIN farm_db.device_ports p ON p.device_id=d.device_id AND p.port_id=%s
                    WHERE d.device_id=%s AND d.active=true
                    """,
                    (item.get("port_id"), item["device_id"]),
                )
                device = cur.fetchone()
                if not device or (item.get("port_id") and not device["port_id"]):
                    raise ValueError("device_id/port_id chưa được map hoặc không cùng thiết bị")
                if device["farm_id"] != farm_id or (zone_id and device["zone_id"] and device["zone_id"] != zone_id):
                    raise ValueError("device_id không thuộc farm/zone trong packet")
                cur.execute(
                    """
                    INSERT INTO farm_db.device_status(device_id,port_id,online,running,last_seen_at,observed_at)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        item["device_id"], item.get("port_id"), bool(item.get("online")), item.get("running"),
                        parse_dt(item.get("last_seen_at") or payload.get("sent_at")), observed_at,
                    ),
                )

        latency_ms = (datetime.now(timezone.utc) - sent_at).total_seconds() * 1000.0
        cur.execute(
            """
            INSERT INTO farm_db.telemetry_ingest_events(
              packet_id,mqtt_topic,farm_id,zone_id,message_type,payload,sent_at,inserted_readings,insert_latency_ms,status
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'stored')
            """,
            (packet_id, topic, farm_id, zone_id, message_type, Jsonb(payload), sent_at, inserted, latency_ms),
        )
        cur.execute(
            """
            INSERT INTO ops_db.ingest_attempts(
              packet_id,farm_id,data_origin,transport,status,row_count,latency_ms,metadata
            ) VALUES (%s,%s,%s,%s,'accepted',%s,%s,%s)
            """,
            (
                packet_id,
                farm_id,
                packet_origin,
                transport,
                inserted,
                latency_ms,
                Jsonb({"topic": topic, "message_type": message_type}),
            ),
        )
        db.commit()

    with lock:
        state["messages_received"] += 1
        state["readings_inserted"] += inserted
        state["last_packet_id"] = packet_id
        state["last_received_at"] = datetime.now(timezone.utc).isoformat()
        state["last_error"] = None
        state["last_processing_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    return {"status": "accepted", "packet_id": packet_id, "inserted_readings": inserted}


def _mqtt_reason_success(reason_code: Any) -> bool:
    """Paho MQTT v2 passes a ReasonCode object, not a plain int."""
    is_failure = getattr(reason_code, "is_failure", None)
    if is_failure is not None:
        return not bool(is_failure)
    return reason_code == 0


def on_connect(mqtt_client: mqtt.Client, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any = None) -> None:
    ok = _mqtt_reason_success(reason_code)
    with lock:
        state["connected"] = ok
        state["last_error"] = None if ok else f"MQTT CONNACK rejected: {reason_code}"
    if ok:
        result, _mid = mqtt_client.subscribe(MQTT_TOPIC, qos=1)
        if result != mqtt.MQTT_ERR_SUCCESS:
            with lock:
                state["connected"] = False
                state["last_error"] = f"MQTT subscribe failed: rc={result}"


def on_disconnect(_client: mqtt.Client, _userdata: Any, _flags: Any, _reason_code: Any, _properties: Any = None) -> None:
    with lock:
        state["connected"] = False


def on_message(_client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
    payload: dict[str, Any] | None = None
    try:
        payload = json.loads(message.payload.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("MQTT payload phải là JSON object")
        store_packet(message.topic, payload)
    except Exception as exc:  # noqa: BLE001
        status = "rejected" if isinstance(exc, (ValueError, KeyError, TypeError)) else "error"
        record_failed_attempt(message.topic, payload, status, str(exc))
        with lock:
            state["errors"] += 1
            if status == "rejected":
                state["rejected"] += 1
            state["last_error"] = str(exc)


def start_mqtt() -> None:
    global client
    wait_for_database()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="nextfarm-telemetry-ingestion", clean_session=True)
    # Keep callback exceptions from killing the network loop; callbacks update last_error explicitly.
    client.suppress_exceptions = True
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=20)
    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    if MQTT_TLS:
        client.tls_set(ca_certs=MQTT_CA_CERT or None)
    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            client.loop_forever(retry_first_connection=True)
        except Exception as exc:  # noqa: BLE001
            with lock:
                state["connected"] = False
                state["last_error"] = str(exc)
            time.sleep(3)


@asynccontextmanager
async def lifespan(_: FastAPI):
    thread = threading.Thread(target=start_mqtt, daemon=True, name="mqtt-ingestion")
    thread.start()
    yield
    if client:
        client.disconnect()


app = FastAPI(title="NextFarm Telemetry Ingestion Service", version="9.0.2", lifespan=lifespan)


@app.get("/health")
def health():
    return {"service": "telemetry-ingestion-service", "status": "ok" if state["connected"] else "starting", **state}


@app.get("/stats")
def stats():
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FILTER (WHERE received_at >= now()-interval '1 minute') AS packets_last_minute,
                   coalesce(sum(inserted_readings) FILTER (WHERE received_at >= now()-interval '1 minute'),0) AS readings_last_minute,
                   round(avg(insert_latency_ms) FILTER (WHERE received_at >= now()-interval '1 minute'),2) AS avg_latency_ms,
                   max(received_at) AS latest_received_at
            FROM farm_db.telemetry_ingest_events
            """
        )
        db_stats = cur.fetchone()
    return {**state, **db_stats}


@app.post("/integrations/nextfarm/ingest")
def ingest_nextfarm_api(
    payload: dict[str, Any],
    x_ingest_api_key: str | None = Header(default=None),
):
    """Read-only product integration entry: ingest NextFarm telemetry with audit.

    The caller must send a stable packet_id (idempotency key), farm/zone/sensor IDs
    already mapped in the approved data contract, and data_origin=nextfarm_api.
    """
    if not INGEST_API_KEY or not x_ingest_api_key or not hmac.compare_digest(x_ingest_api_key, INGEST_API_KEY):
        raise HTTPException(status_code=403, detail="Integration key không hợp lệ.")
    try:
        return store_packet(
            "api/nextfarm",
            payload,
            allowed_origins={"nextfarm_api"},
            transport="https_api",
        )
    except (ValueError, KeyError, TypeError) as exc:
        record_failed_attempt("api/nextfarm", payload, "rejected", str(exc), transport="https_api")
        raise HTTPException(status_code=422, detail=f"Payload NextFarm bị từ chối: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        record_failed_attempt("api/nextfarm", payload, "error", str(exc), transport="https_api")
        raise HTTPException(status_code=503, detail="Không ghi được dữ liệu NextFarm; lỗi đã được audit.") from exc
