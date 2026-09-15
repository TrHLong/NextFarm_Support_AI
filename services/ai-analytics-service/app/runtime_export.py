from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg


EXPORT_QUERIES: dict[str, tuple[str, list[str]]] = {
    "customers": (
        "user_db.customers",
        ["customer_id", "customer_name", "customer_type", "status", "created_at", "updated_at"],
    ),
    "users": (
        "user_db.users",
        ["customer_id", "user_id", "username", "display_name", "role", "status", "created_at", "updated_at"],
    ),
    "user_farm_permissions": (
        """user_db.farm_access a
           JOIN user_db.users u ON u.user_id=a.user_id
           JOIN farm_db.farms f ON f.farm_id=a.farm_id""",
        [
            "u.customer_id AS actor_customer_id", "f.customer_id AS farm_customer_id",
            "a.user_id", "a.farm_id", "a.access_role", "a.can_read", "a.can_support", "a.created_at",
        ],
    ),
    "farms": (
        "farm_db.farms",
        [
            "customer_id", "farm_id", "owner_user_id", "farm_name", "crop_name", "region", "address",
            "area_ha", "latitude", "longitude", "cultivation_type", "soil_texture", "drainage", "created_at",
        ],
    ),
    "zones": (
        "farm_db.zones z JOIN farm_db.farms f ON f.farm_id=z.farm_id",
        [
            "f.customer_id", "z.farm_id", "z.zone_id", "z.zone_code", "z.zone_name", "z.crop_name", "z.area_ha",
            "z.moisture_min", "z.moisture_max", "z.ec_min", "z.ec_max", "z.ph_min", "z.ph_max",
        ],
    ),
    "devices": (
        "farm_db.devices d JOIN farm_db.farms f ON f.farm_id=d.farm_id",
        [
            "f.customer_id", "d.farm_id", "d.zone_id", "d.device_id", "d.device_name", "d.device_type",
            "d.model_name", "d.firmware_version", "d.connectivity", "d.installed_at", "d.active",
        ],
    ),
    "sensors": (
        "farm_db.sensors s JOIN farm_db.farms f ON f.farm_id=s.farm_id",
        [
            "f.customer_id", "s.farm_id", "s.zone_id", "s.device_id", "s.sensor_id", "s.sensor_name",
            "s.metric_type", "s.unit", "s.active",
        ],
    ),
    "sensor_readings": (
        """farm_db.sensor_readings r
           JOIN farm_db.farms f ON f.farm_id=r.farm_id
           JOIN farm_db.sensors s ON s.sensor_id=r.sensor_id
           LEFT JOIN farm_db.zones z ON z.zone_id=r.zone_id""",
        [
            "f.customer_id", "f.owner_user_id", "r.farm_id", "r.zone_id", "z.zone_code", "s.device_id",
            "r.sensor_id", "r.reading_id", "r.metric_type", "r.value", "r.unit", "r.quality",
            "r.observed_at", "r.received_at", "r.created_at", "r.data_origin", "r.source_dataset",
            "r.simulation_profile_version",
        ],
    ),
    "device_status": (
        """farm_db.device_status ds
           JOIN farm_db.devices d ON d.device_id=ds.device_id
           JOIN farm_db.farms f ON f.farm_id=d.farm_id
           LEFT JOIN farm_db.device_ports p ON p.port_id=ds.port_id""",
        [
            "f.customer_id", "d.farm_id", "coalesce(d.zone_id,p.zone_id) AS zone_id", "ds.device_id",
            "ds.port_id", "ds.status_id", "ds.online", "ds.running", "ds.last_seen_at", "ds.observed_at", "ds.created_at",
        ],
    ),
    "irrigation_schedules": (
        "farm_db.irrigation_schedules s JOIN farm_db.farms f ON f.farm_id=s.farm_id",
        [
            "f.customer_id", "s.farm_id", "s.zone_id", "s.port_id", "s.schedule_id", "s.schedule_name",
            "s.start_time", "s.duration_minutes", "s.days_of_week", "s.enabled",
        ],
    ),
    "irrigation_runs": (
        "farm_db.irrigation_runs r JOIN farm_db.farms f ON f.farm_id=r.farm_id",
        [
            "f.customer_id", "r.farm_id", "r.zone_id", "r.port_id", "r.run_id", "r.started_at", "r.ended_at",
            "r.duration_minutes", "r.water_liters", "r.result", "r.source",
        ],
    ),
    "control_commands": (
        """farm_db.control_commands c
           JOIN farm_db.farms f ON f.farm_id=c.farm_id
           JOIN user_db.users u ON u.user_id=c.requested_by""",
        [
            "f.customer_id AS farm_customer_id", "u.customer_id AS actor_customer_id", "c.farm_id", "c.zone_id",
            "c.device_id", "c.port_id", "c.command_id", "c.requested_by", "c.command_type", "c.parameters",
            "c.status", "c.confirmation_required", "c.confirmed_by", "c.requested_at", "c.confirmed_at",
            "c.executed_at", "c.result", "c.error_message", "c.correlation_id",
        ],
    ),
    "alerts": (
        "farm_db.alerts a JOIN farm_db.farms f ON f.farm_id=a.farm_id",
        [
            "f.customer_id", "a.farm_id", "a.zone_id", "a.device_id", "a.alert_id", "a.alert_type", "a.severity",
            "a.title", "a.message", "a.status", "a.suggested_checklist_code", "a.detected_at", "a.resolved_at",
        ],
    ),
    "chat_messages": (
        """support_db.chat_messages m
           JOIN support_db.conversations c ON c.conversation_id=m.conversation_id
           JOIN user_db.users u ON u.user_id=c.user_id
           LEFT JOIN farm_db.farms f ON f.farm_id=c.farm_id""",
        [
            "u.customer_id AS user_customer_id", "f.customer_id AS farm_customer_id", "c.user_id", "c.farm_id",
            "m.conversation_id", "m.message_id", "m.sender_type", "m.sender_id", "m.content", "m.intent",
            "m.grounded", "m.tool_name", "m.tool_payload", "m.delivery_status", "m.created_at",
        ],
    ),
    "model_registry": (
        "knowledge_db.model_registry",
        [
            "model_id", "model_family", "model_version", "scope_type", "scope_key", "metric_type", "model_type",
            "task", "trained_at", "sample_count", "dataset_version", "dataset_source", "train_count", "test_count",
            "split_strategy", "status", "deployment_status", "quality_gate", "artifact_path", "feature_names",
            "training_origin_mix", "training_phase",
        ],
    ),
    "ai_capabilities": (
        "ai_db.model_capabilities",
        [
            "capability_key", "display_name_vi", "category", "implementation_type", "model_family",
            "required_inputs", "optional_inputs", "output_kind", "risk_level", "default_status",
            "implementation_state", "implementation_ref", "source_title", "source_url", "evidence_note", "active",
        ],
    ),
    "crop_capability_map": (
        "ai_db.crop_capability_map",
        [
            "crop_key", "capability_key", "applicability", "crop_specific_status", "reason_vi", "min_history_days",
        ],
    ),
    "farm_crop_inventory": (
        """ai_db.farm_crop_inventory i
           JOIN farm_db.farms f ON f.farm_id=i.farm_id""",
        [
            "f.customer_id", "i.farm_id", "i.zone_id", "i.crop_key", "i.source_crop_name", "i.confidence",
            "i.mapping_method", "i.active", "i.detected_at",
        ],
    ),
    "chat_feedback": (
        """support_db.chat_feedback cf
           JOIN support_db.chat_messages m ON m.message_id=cf.message_id
           JOIN support_db.conversations c ON c.conversation_id=m.conversation_id
           JOIN user_db.users u ON u.user_id=c.user_id""",
        [
            "u.customer_id", "c.farm_id", "cf.feedback_id", "cf.message_id", "cf.submitted_by", "cf.rating",
            "cf.correction", "cf.review_status", "cf.training_use_allowed", "cf.reviewed_by", "cf.reviewed_at", "cf.created_at",
        ],
    ),
}


# Dữ liệu dùng cho ML được chụp riêng theo từng khách hàng. Các biểu thức lọc
# luôn đi qua farm/customer thay vì tin customer_id do client truyền trong dữ liệu.
CUSTOMER_TRAINING_QUERIES: dict[str, tuple[str, list[str], str]] = {
    "customer": (
        "user_db.customers c",
        ["c.customer_id", "c.customer_name", "c.customer_type", "c.status", "c.created_at", "c.updated_at"],
        "c.customer_id=%s",
    ),
    "farms": (
        "farm_db.farms f",
        [
            "f.customer_id", "f.farm_id", "f.owner_user_id", "f.farm_name", "f.crop_name", "f.region",
            "f.address", "f.area_ha", "f.latitude", "f.longitude", "f.cultivation_type", "f.soil_texture",
            "f.drainage", "f.created_at",
        ],
        "f.customer_id=%s",
    ),
    "zones": (
        "farm_db.zones z JOIN farm_db.farms f ON f.farm_id=z.farm_id",
        [
            "f.customer_id", "z.farm_id", "z.zone_id", "z.zone_code", "z.zone_name", "z.crop_name",
            "z.area_ha", "z.moisture_min", "z.moisture_max", "z.ec_min", "z.ec_max", "z.ph_min", "z.ph_max",
        ],
        "f.customer_id=%s",
    ),
    "farm_ai_profiles": (
        "farm_db.farm_ai_profiles p JOIN farm_db.farms f ON f.farm_id=p.farm_id",
        [
            "f.customer_id", "p.farm_id", "p.crop_code", "p.crop_variety", "p.growth_stage",
            "p.cultivation_type", "p.climate_region", "p.soil_type", "p.target_moisture_min",
            "p.target_moisture_max", "p.target_ec_min", "p.target_ec_max", "p.target_ph_min",
            "p.target_ph_max", "p.active_model_scope", "p.active_model_version", "p.updated_at",
        ],
        "f.customer_id=%s",
    ),
    "sensors": (
        "farm_db.sensors s JOIN farm_db.farms f ON f.farm_id=s.farm_id",
        [
            "f.customer_id", "s.farm_id", "s.zone_id", "s.device_id", "s.sensor_id", "s.sensor_name",
            "s.metric_type", "s.unit", "s.active",
        ],
        "f.customer_id=%s",
    ),
    "sensor_readings": (
        """farm_db.sensor_readings r
           JOIN farm_db.farms f ON f.farm_id=r.farm_id
           JOIN farm_db.sensors s ON s.sensor_id=r.sensor_id
           LEFT JOIN farm_db.zones z ON z.zone_id=r.zone_id""",
        [
            "f.customer_id", "f.owner_user_id", "r.farm_id", "r.zone_id", "z.zone_code", "s.device_id",
            "r.sensor_id", "r.reading_id", "r.metric_type", "r.value", "r.unit", "r.quality",
            "r.observed_at", "r.received_at", "r.created_at", "r.data_origin", "r.source_dataset",
            "r.simulation_profile_version",
        ],
        "f.customer_id=%s",
    ),
    "device_status": (
        """farm_db.device_status ds
           JOIN farm_db.devices d ON d.device_id=ds.device_id
           JOIN farm_db.farms f ON f.farm_id=d.farm_id
           LEFT JOIN farm_db.device_ports p ON p.port_id=ds.port_id""",
        [
            "f.customer_id", "d.farm_id", "coalesce(d.zone_id,p.zone_id) AS zone_id", "ds.device_id",
            "ds.port_id", "ds.status_id", "ds.online", "ds.running", "ds.last_seen_at", "ds.observed_at",
            "ds.created_at",
        ],
        "f.customer_id=%s",
    ),
    "irrigation_schedules": (
        "farm_db.irrigation_schedules s JOIN farm_db.farms f ON f.farm_id=s.farm_id",
        [
            "f.customer_id", "s.farm_id", "s.zone_id", "s.port_id", "s.schedule_id", "s.schedule_name",
            "s.start_time", "s.duration_minutes", "s.days_of_week", "s.enabled",
        ],
        "f.customer_id=%s",
    ),
    "irrigation_runs": (
        "farm_db.irrigation_runs r JOIN farm_db.farms f ON f.farm_id=r.farm_id",
        [
            "f.customer_id", "r.farm_id", "r.zone_id", "r.port_id", "r.run_id", "r.started_at",
            "r.ended_at", "r.duration_minutes", "r.water_liters", "r.result", "r.source",
        ],
        "f.customer_id=%s",
    ),
    "telemetry_ingest_events": (
        "farm_db.telemetry_ingest_events e JOIN farm_db.farms f ON f.farm_id=e.farm_id",
        [
            "f.customer_id", "e.farm_id", "e.zone_id", "e.event_id", "e.packet_id", "e.mqtt_topic",
            "e.message_type", "e.sent_at", "e.received_at", "e.inserted_readings", "e.insert_latency_ms",
            "e.status", "e.error_message",
        ],
        "f.customer_id=%s",
    ),
    "alerts": (
        "farm_db.alerts a JOIN farm_db.farms f ON f.farm_id=a.farm_id",
        [
            "f.customer_id", "a.farm_id", "a.zone_id", "a.device_id", "a.alert_id", "a.alert_type",
            "a.severity", "a.title", "a.message", "a.status", "a.detected_at", "a.resolved_at",
        ],
        "f.customer_id=%s",
    ),
    "control_commands": (
        "farm_db.control_commands c JOIN farm_db.farms f ON f.farm_id=c.farm_id",
        [
            "f.customer_id", "c.farm_id", "c.zone_id", "c.device_id", "c.port_id", "c.command_id",
            "c.requested_by", "c.command_type", "c.parameters", "c.status", "c.confirmation_required",
            "c.requested_at", "c.confirmed_at", "c.executed_at", "c.result", "c.error_message",
        ],
        "f.customer_id=%s",
    ),
}


def _normal(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _query(source: str, columns: list[str]) -> str:
    return "SELECT " + ",".join(columns) + " FROM " + source


def _write_cursor_csv(cur: Any, path: Path) -> tuple[int, list[str]]:
    row_count = 0
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        headers = [item.name for item in cur.description]
        writer = csv.writer(handle)
        writer.writerow(headers)
        while True:
            rows = cur.fetchmany(10000)
            if not rows:
                break
            writer.writerows([[_normal(value) for value in row] for row in rows])
            row_count += len(rows)
    return row_count, headers


def export_customer_training_snapshot(
    database_url: str,
    output_root: str | Path,
    customer_id: str,
) -> dict[str, Any]:
    """Xuất snapshot CSV bất biến cho đúng một khách hàng trong một DB transaction."""
    exported_at = datetime.now(timezone.utc)
    snapshot_id = exported_at.strftime("runtime_%Y%m%dT%H%M%SZ")
    customer_root = Path(output_root) / "customers" / customer_id
    output = customer_root / "snapshots" / snapshot_id / "raw"
    output.mkdir(parents=True, exist_ok=False)
    files: list[dict[str, Any]] = []

    with psycopg.connect(database_url) as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        with db.cursor() as meta_cur:
            meta_cur.execute("SELECT current_database(),now(),txid_current()")
            database_name, database_snapshot_at, transaction_id = meta_cur.fetchone()
            meta_cur.execute("SELECT 1 FROM user_db.customers WHERE customer_id=%s AND status='active'", (customer_id,))
            if meta_cur.fetchone() is None:
                raise ValueError(f"Customer không tồn tại hoặc không active: {customer_id}")

        for name, (source, columns, customer_filter) in CUSTOMER_TRAINING_QUERIES.items():
            path = output / f"{name}.csv"
            with db.cursor(name=f"customer_export_{name}") as cur:
                cur.itersize = 10000
                cur.execute(_query(source, columns) + " WHERE " + customer_filter, (customer_id,))
                row_count, headers = _write_cursor_csv(cur, path)
            files.append({
                "name": name,
                "path": str(path),
                "row_count": row_count,
                "bytes": path.stat().st_size,
                "sha256": _checksum(path),
                "columns": headers,
            })

    manifest = {
        "snapshot_id": snapshot_id,
        "customer_id": customer_id,
        "exported_at": exported_at.isoformat(),
        "database": database_name,
        "database_snapshot_at": database_snapshot_at.isoformat(),
        "transaction_id": transaction_id,
        "isolation": "repeatable_read_read_only",
        "layout": "model-artifacts/data/customers/<customer_id>/snapshots/<snapshot_id>/raw",
        "contains_other_customers": False,
        "contains_password_hashes": False,
        "chat_messages_used_for_training": False,
        "files": files,
    }
    manifest_path = output.parent / "snapshot_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (customer_root / "CURRENT_SNAPSHOT.txt").write_text(snapshot_id + "\n", encoding="utf-8")
    return {**manifest, "manifest_path": str(manifest_path), "output_directory": str(output)}


def export_runtime_snapshot(database_url: str, output_root: str | Path) -> dict[str, Any]:
    exported_at = datetime.now(timezone.utc)
    snapshot_id = exported_at.strftime("runtime_%Y%m%dT%H%M%SZ")
    root = Path(output_root)
    output = root / snapshot_id
    output.mkdir(parents=True, exist_ok=False)
    files: list[dict[str, Any]] = []

    with psycopg.connect(database_url) as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        with db.cursor() as meta_cur:
            meta_cur.execute("SELECT current_database(),now(),txid_current()")
            database_name, database_snapshot_at, transaction_id = meta_cur.fetchone()

        for name, (source, columns) in EXPORT_QUERIES.items():
            path = output / f"{name}.csv"
            row_count = 0
            with db.cursor(name=f"export_{name}") as cur, path.open("w", encoding="utf-8-sig", newline="") as handle:
                cur.itersize = 10000
                cur.execute(_query(source, columns))
                headers = [item.name for item in cur.description]
                writer = csv.writer(handle)
                writer.writerow(headers)
                while True:
                    rows = cur.fetchmany(10000)
                    if not rows:
                        break
                    writer.writerows([[_normal(value) for value in row] for row in rows])
                    row_count += len(rows)
            files.append({
                "name": name,
                "path": str(path),
                "source": source.replace("\n", " ").strip(),
                "row_count": row_count,
                "bytes": path.stat().st_size,
                "sha256": _checksum(path),
                "columns": headers,
            })

    origin_counts: dict[str, int] = {}
    sensor_file = output / "sensor_readings.csv"
    if sensor_file.exists():
        with sensor_file.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                origin = row.get("data_origin") or "unknown"
                origin_counts[origin] = origin_counts.get(origin, 0) + 1

    manifest = {
        "snapshot_id": snapshot_id,
        "exported_at": exported_at.isoformat(),
        "database": database_name,
        "database_snapshot_at": database_snapshot_at.isoformat(),
        "transaction_id": transaction_id,
        "isolation": "repeatable_read_read_only",
        "customer_identity_columns": ["customer_id", "farm_id", "zone_id", "device_id", "sensor_id"],
        "contains_password_hashes": False,
        "chat_messages_used_for_training": False,
        "sensor_data_origins": origin_counts,
        "files": files,
    }
    manifest_path = output / "snapshot_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "CURRENT_SNAPSHOT.txt").write_text(snapshot_id + "\n", encoding="utf-8")
    return {**manifest, "manifest_path": str(manifest_path), "output_directory": str(output)}
