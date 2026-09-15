from __future__ import annotations

import argparse
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


DATASET_ID = "nextfarm-v10.1-operational-acceptance"
SCHEMA_VERSION = "10.1.1"
GENERATOR_VERSION = "v10.1.1"
GENERATED_AT = "2026-09-04T00:00:00Z"
SNAPSHOT_AT = datetime(2026, 9, 4, tzinfo=timezone.utc)


def metadata(table_name: str) -> dict[bytes, bytes]:
    return {
        b"dataset_id": DATASET_ID.encode(),
        b"schema_version": SCHEMA_VERSION.encode(),
        b"generator_version": GENERATOR_VERSION.encode(),
        b"generated_at": GENERATED_AT.encode(),
        b"snapshot_at": GENERATED_AT.encode(),
        b"synthetic": b"true",
        b"table_name": table_name.encode(),
        b"usage": b"acceptance_and_acl_testing_only_not_production_telemetry",
    }


def trace(scenario_id: str) -> dict[str, object]:
    return {"synthetic": True, "scenario_id": scenario_id, "generator_version": GENERATOR_VERSION}


def write_rows(path: Path, rows: list[dict], table_name: str) -> None:
    table = pa.Table.from_pylist(rows).replace_schema_metadata(metadata(table_name))
    pq.write_table(table, path, compression="zstd", use_dictionary=True)


def build(output: Path, days: int = 14, farm_count: int = 40) -> None:
    random.seed(20260904)
    output.mkdir(parents=True, exist_ok=True)
    crops = ["Cà chua", "Sầu riêng", "Rau ăn lá", "Ớt", "Dưa lưới"]
    varieties = ["Giống A", "Giống địa phương", "Giống nhà màng", "Giống ngắn ngày", "Giống thử nghiệm"]
    growth_stages = ["cây con", "sinh trưởng", "ra hoa", "đậu trái", "nuôi trái"]
    soils = ["đất thịt", "đất đỏ bazan", "đất phù sa", "giá thể", "đất cát pha"]
    regions = ["Lâm Đồng", "Đắk Lắk", "Đồng Tháp", "Gia Lai", "Tiền Giang"]
    alert_types = [
        "SENSOR_STALE", "SENSOR_MISSING", "SENSOR_OUTLIER", "DEVICE_OFFLINE",
        "MISSED_IRRIGATION", "IRRIGATION_INTERRUPTED", "LOW_MOISTURE", "HIGH_TEMPERATURE",
    ]

    farms: list[dict] = []
    zones: list[dict] = []
    users: list[dict] = []
    permissions: list[dict] = []
    devices: list[dict] = []
    sensors: list[dict] = []
    schedules: list[dict] = []
    events: list[dict] = []
    alerts: list[dict] = []
    commands: list[dict] = []

    for farm_index in range(1, farm_count + 1):
        farm_id = f"farm_accept_{farm_index:03d}"
        owner_id = f"accept_owner_{farm_index:03d}"
        customer_id = f"customer_accept_{farm_index:03d}"
        crop_index = (farm_index - 1) % len(crops)
        crop = crops[crop_index]
        stale_device = farm_index % 8 == 0
        device_updated_at = SNAPSHOT_AT - timedelta(minutes=5 if not stale_device else 150)

        users.append({
            "user_id": owner_id, "customer_id": customer_id, "role": "farmer", "status": "active",
            **trace(f"owner_{farm_index:03d}"),
        })
        farms.append({
            "farm_id": farm_id, "customer_id": customer_id, "owner_user_id": owner_id,
            "farm_name": f"Vườn nghiệm thu {farm_index:03d}", "crop_name": crop,
            "crop_profile": f"{crop} - {varieties[crop_index]}", "province": regions[crop_index],
            "region": regions[crop_index], "area_ha": 1.5 + farm_index * 0.03,
            **trace(f"base_{farm_index:03d}"),
        })
        permissions.append({
            "user_id": owner_id, "farm_id": farm_id, "can_read": True, "can_control": True,
            "access_role": "owner", **trace(f"owner_acl_{farm_index:03d}"),
        })

        controller_id = f"ctrl_{farm_index:03d}"
        gateway_id = f"gateway_{farm_index:03d}"
        devices.extend([
            {
                "device_id": controller_id, "farm_id": farm_id, "zone_id": None,
                "device_type": "controller", "controller_type": "irrigation_controller",
                "online": not stale_device, "updated_at": device_updated_at, "active": True,
                **trace("device_offline" if stale_device else "device_online"),
            },
            {
                "device_id": gateway_id, "farm_id": farm_id, "zone_id": None,
                "device_type": "sensor_gateway", "controller_type": "telemetry_gateway",
                "online": not stale_device, "updated_at": device_updated_at, "active": True,
                **trace("device_offline" if stale_device else "device_online"),
            },
        ])

        for zone_index, zone_code in enumerate("ABC", start=1):
            zone_id = f"zone_{farm_index:03d}_{zone_code.lower()}"
            zones.append({
                "zone_id": zone_id, "farm_id": farm_id, "zone_code": zone_code,
                "zone_name": f"Khu {zone_code}", "crop_name": crop, "variety": varieties[crop_index],
                "growth_stage": growth_stages[(crop_index + zone_index - 1) % len(growth_stages)],
                "soil_type": soils[crop_index], "area_ha": 0.5 + farm_index * 0.01,
                "moisture_min": 50.0, "moisture_max": 70.0, "ph_min": 5.5, "ph_max": 7.0,
                **trace(f"zone_profile_{crop_index + 1}"),
            })
            schedules.append({
                "schedule_id": f"schedule_{farm_index:03d}_{zone_code.lower()}", "farm_id": farm_id,
                "zone_id": zone_id, "start_time": f"{5 + zone_index:02d}:00:00",
                "duration_minutes": 15 + zone_index * 5, "days_of_week": "1,2,3,4,5,6,7",
                "enabled": True, **trace("daily_irrigation_schedule"),
            })
            for metric, unit in [("soil_moisture", "%"), ("temperature", "°C"), ("ph", "pH")]:
                sensors.append({
                    "sensor_id": f"sensor_{farm_index:03d}_{zone_code.lower()}_{metric}", "farm_id": farm_id,
                    "zone_id": zone_id, "device_id": gateway_id, "metric_type": metric,
                    "unit": unit, "active": True, **trace("sensor_catalog"),
                })
            for day in range(days):
                for run_no in range(2):
                    start = datetime(2026, 8, 21, 5 + run_no * 12, zone_index * 5, tzinfo=timezone.utc) + timedelta(days=day)
                    result = "failed" if farm_index % 13 == 0 and day == days - 1 and run_no == 1 else "success"
                    events.append({
                        "run_id": f"run_{farm_index:03d}_{zone_code.lower()}_{day:02d}_{run_no}",
                        "farm_id": farm_id, "zone_id": zone_id, "started_at": start,
                        "ended_at": start + timedelta(minutes=20), "duration_minutes": 20.0,
                        "water_liters": 180.0 + zone_index * 10, "result": result, "source": "schedule",
                        **trace("irrigation_failure" if result == "failed" else "normal_irrigation"),
                    })

        alert_type = alert_types[(farm_index - 1) % len(alert_types)]
        alerts.append({
            "alert_id": f"alert_{farm_index:03d}", "farm_id": farm_id,
            "zone_id": f"zone_{farm_index:03d}_a", "alert_type": alert_type,
            "severity": "high" if alert_type in {"SENSOR_STALE", "DEVICE_OFFLINE", "MISSED_IRRIGATION"} else "medium",
            "status": "open", "detected_at": SNAPSHOT_AT - timedelta(minutes=30 + farm_index),
            **trace(alert_type.lower()),
        })
        for command_index, status in enumerate(["rejected", "pending_confirmation", "failed", "succeeded"]):
            commands.append({
                "command_id": f"command_{farm_index:03d}_{command_index}", "farm_id": farm_id,
                "device_id": controller_id, "actor": owner_id, "requested_by": owner_id,
                "command": "open_valve", "command_type": "open_valve", "status": status,
                "result": "not_executed" if status in {"rejected", "pending_confirmation"} else status,
                "confirmation_required": True,
                "requested_at": datetime(2026, 9, 1 + command_index, tzinfo=timezone.utc),
                **trace(f"command_{status}"),
            })

    for user_index in range(1, 21):
        user_id = f"accept_multi_{user_index:03d}"
        users.append({
            "user_id": user_id, "customer_id": f"customer_multi_{user_index:03d}",
            "role": "farmer", "status": "active", **trace("multi_farm_user"),
        })
        for offset in (0, 1):
            farm_number = ((user_index * 2 + offset - 1) % farm_count) + 1
            permissions.append({
                "user_id": user_id, "farm_id": f"farm_accept_{farm_number:03d}",
                "can_read": True, "can_control": offset == 0, "access_role": "owner",
                **trace("multi_farm_acl"),
            })
    for user_index in range(1, 21):
        user_id = f"accept_tech_{user_index:03d}"
        users.append({
            "user_id": user_id, "customer_id": f"support_team_{(user_index - 1) // 5 + 1}",
            "role": "technician", "status": "active", **trace("technician_user"),
        })
        for offset in range(4):
            farm_number = ((user_index - 1) * 2 + offset) % farm_count + 1
            permissions.append({
                "user_id": user_id, "farm_id": f"farm_accept_{farm_number:03d}",
                "can_read": True, "can_control": False, "access_role": "technician",
                **trace("technician_acl"),
            })

    for name, rows in [
        ("users", users), ("user_farm_permissions", permissions), ("farms", farms), ("zones", zones),
        ("devices", devices), ("sensors", sensors), ("irrigation_schedules", schedules),
        ("irrigation_events", events), ("alerts", alerts), ("command_logs", commands),
    ]:
        write_rows(output / f"{name}.parquet", rows, name)

    reading_schema = pa.schema([
        ("reading_id", pa.string()), ("sensor_id", pa.string()), ("farm_id", pa.string()),
        ("zone_id", pa.string()), ("metric_type", pa.string()), ("value", pa.float64()),
        ("unit", pa.string()), ("quality", pa.string()), ("measured_at", pa.timestamp("us", tz="UTC")),
        ("received_at", pa.timestamp("us", tz="UTC")), ("data_origin", pa.string()),
        ("synthetic", pa.bool_()), ("scenario_id", pa.string()), ("scenario_tag", pa.string()),
        ("generator_version", pa.string()),
    ], metadata=metadata("sensor_readings"))
    writer = pq.ParquetWriter(output / "sensor_readings.parquet", reading_schema, compression="zstd", use_dictionary=True)
    base = datetime(2026, 8, 21, tzinfo=timezone.utc)
    try:
        for day in range(days):
            batch = []
            for farm_index in range(1, farm_count + 1):
                for zone_index, zone_code in enumerate("ABC", start=1):
                    zone_id = f"zone_{farm_index:03d}_{zone_code.lower()}"
                    for step in range(144):
                        scheduled = base + timedelta(days=day, minutes=step * 10)
                        stale_case = farm_index % 8 == 0 and day == days - 1 and step > 130
                        measured = scheduled - timedelta(hours=2) if stale_case else scheduled
                        for metric, unit in [("soil_moisture", "%"), ("temperature", "°C"), ("ph", "pH")]:
                            phase = step / 144 * math.tau
                            if metric == "soil_moisture":
                                value = 60 + 8 * math.sin(phase + zone_index) + random.uniform(-1.2, 1.2)
                            elif metric == "temperature":
                                value = 26 + 5 * math.sin(phase - 1.2) + random.uniform(-0.5, 0.5)
                            else:
                                value = 6.2 + random.uniform(-0.15, 0.15)
                            suspect_case = farm_index % 11 == 0 and day == days - 1 and step == 143
                            quality = "suspect" if suspect_case else "good"
                            scenario_id = "stale_sensor" if stale_case else "suspect_quality" if suspect_case else "normal_reading"
                            batch.append({
                                "reading_id": f"r_{farm_index:03d}_{zone_code}_{day:02d}_{step:03d}_{metric}",
                                "sensor_id": f"sensor_{farm_index:03d}_{zone_code.lower()}_{metric}",
                                "farm_id": f"farm_accept_{farm_index:03d}", "zone_id": zone_id,
                                "metric_type": metric, "value": round(value, 3), "unit": unit,
                                "quality": quality, "measured_at": measured, "received_at": measured + timedelta(minutes=1),
                                "data_origin": "synthetic_acceptance", "synthetic": True,
                                "scenario_id": scenario_id,
                                "scenario_tag": "freshness" if stale_case else "quality" if suspect_case else "baseline",
                                "generator_version": GENERATOR_VERSION,
                            })
            writer.write_table(pa.Table.from_pylist(batch, schema=reading_schema))
    finally:
        writer.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/operational")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--farms", type=int, default=40)
    args = parser.parse_args()
    build(Path(args.output), days=args.days, farm_count=args.farms)
