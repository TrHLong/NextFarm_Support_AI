from datetime import datetime, timedelta, timezone
from pathlib import Path

import app.dataset_builder as builder


def test_database_builder_locks_dataset_without_future_backfill(monkeypatch, tmp_path: Path):
    farms = ["farm_long", "farm_lan", "farm_minh"]
    zones = ["A", "B"]
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    readings, profiles, statuses, events = [], [], [], []
    for farm_index, farm_id in enumerate(farms):
        for zone_index, zone_code in enumerate(zones):
            zone_id = f"{farm_id}_{zone_code}"
            profiles.append({
                "farm_id": farm_id, "farm_name": farm_id, "area_ha": 1 + farm_index,
                "zone_id": zone_id, "zone_code": zone_code, "moisture_min": 50, "moisture_max": 70,
                "ec_min": 1, "ec_max": 2.5, "ph_min": 5.5, "ph_max": 7,
                "crop_code": ["tomato", "durian", "leafy_vegetable"][farm_index],
                "cultivation_type": "open_field", "climate_region": "other", "soil_type": "loam",
                "target_moisture_min": 50, "target_moisture_max": 70,
                "target_ec_min": 1, "target_ec_max": 2.5, "target_ph_min": 5.5, "target_ph_max": 7,
            })
            for index in range(100):
                observed_at = start + timedelta(minutes=15 * index)
                values = {
                    "soil_moisture": 55 + farm_index + zone_index + index * 0.01,
                    "temperature": 25 + farm_index + index * 0.02,
                    "ec": 1.5 + farm_index * 0.1, "ph": 6.2,
                    "flow_rate": 2.0 if index % 8 < 2 else 0.0,
                }
                for metric, value in values.items():
                    readings.append({"farm_id": farm_id, "zone_id": zone_id, "zone_code": zone_code,
                                     "metric_type": metric, "value": value, "quality": "good", "observed_at": observed_at,
                                         "data_origin": "simulated_device_calibrated_v9", "source_dataset": "test-reference",
                                         "simulation_profile_version": "test-v9"})
                statuses.append({"farm_id": farm_id, "zone_id": zone_id, "online": True,
                                 "running": index % 8 < 2, "observed_at": observed_at})
        for index in range(100):
            events.append({"farm_id": farm_id, "received_at": start + timedelta(minutes=15 * index),
                           "status": "stored", "inserted_readings": 10})

    class Cursor:
        query = ""
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def execute(self, query, params=()): self.query = query
        def fetchall(self):
            if "FROM farm_db.sensor_readings" in self.query: return readings
            if "FROM farm_db.farms f JOIN farm_db.zones" in self.query: return profiles
            if "FROM farm_db.device_status" in self.query: return statuses
            if "FROM farm_db.irrigation_runs" in self.query: return []
            if "FROM farm_db.telemetry_ingest_events" in self.query: return events
            return []

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def cursor(self): return Cursor()
        def commit(self): return None

    monkeypatch.setattr(builder.psycopg, "connect", lambda *args, **kwargs: Connection())
    result = builder.build_database_training_dataset("fake", tmp_path, lookback_days=14, freq_minutes=15)
    frame = result["frame"]
    assert result["row_count"] == 588
    assert result["farm_count"] == 3 and result["zone_count"] == 6
    assert result["label_method"] == "weak_labels_from_observable_rules"
    assert not frame[builder.FEATURES].isna().any().any()
    assert Path(result["artifact_path"]).exists()
    assert result["checksum_sha256"] in Path(result["artifact_path"]).with_suffix(".json").read_text(encoding="utf-8")
