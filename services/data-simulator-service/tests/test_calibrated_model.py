from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from app.calibrated_model import ResearchCalibratedFarmModel

PROFILE = Path(__file__).resolve().parents[3] / "research-data" / "calibration" / "v9_profiles.json"
TZ7 = timezone(timedelta(hours=7))


def calibration_file(tmp_path: Path) -> Path:
    path = tmp_path / "reference_calibration.json"
    payload = {
        "normalized_rows": 20000,
        "metrics": {
            "temperature": {"median": 26.0, "median_abs_step": 0.02},
            "air_humidity": {"median": 76.0, "median_abs_step": 0.08},
            "soil_moisture": {"median": 58.0, "median_abs_step": 0.03},
            "ec": {"median": 1.65, "median_abs_step": 0.002},
            "ph": {"median": 6.2, "median_abs_step": 0.002},
            "flow_rate": {"median": 0.0, "median_abs_step": 0.01},
        },
        "correlations": {
            "temperature__air_humidity": -0.68,
            "air_humidity__temperature": -0.68,
        },
        "sources": [{"source_id": "unit-test-reference-fixture"}],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def model(tmp_path: Path, seed: int = 7) -> ResearchCalibratedFarmModel:
    m = ResearchCalibratedFarmModel(PROFILE, calibration_file(tmp_path), seed=seed)
    for farm in m.config["farms"].values():
        farm["fault_rate_per_day"] = 0.0
    return m


def test_reference_calibration_is_mandatory(tmp_path: Path):
    missing = tmp_path / "missing.json"
    try:
        ResearchCalibratedFarmModel(PROFILE, missing, seed=1)
    except RuntimeError as exc:
        assert "reference_calibration" in str(exc)
    else:
        raise AssertionError("Simulator must fail closed when reference calibration is missing")


def test_physical_state_does_not_jump_every_mqtt_packet(tmp_path: Path):
    m = model(tmp_path)
    t0 = datetime(2026, 8, 10, 8, 0, tzinfo=TZ7)
    s0 = m.step("farm_long", "A", t0, force=True)
    before = (s0.temperature, s0.air_humidity, s0.soil_moisture, s0.ec, s0.ph, s0.flow_rate)
    s1 = m.step("farm_long", "A", t0 + timedelta(seconds=2))
    after = (s1.temperature, s1.air_humidity, s1.soil_moisture, s1.ec, s1.ph, s1.flow_rate)
    assert before == after


def test_temperature_and_humidity_follow_inverse_daily_pattern(tmp_path: Path):
    m = model(tmp_path, 11)
    start = datetime(2026, 8, 10, 0, 0, tzinfo=TZ7)
    temperatures, humidity = [], []
    for hour in range(72):
        s = m.step("farm_long", "A", start + timedelta(hours=hour), force=True)
        temperatures.append(s.temperature)
        humidity.append(s.air_humidity)
    corr = float(np.corrcoef(temperatures, humidity)[0, 1])
    assert corr < -0.45


def test_irrigation_event_has_flow_and_raises_soil_moisture(tmp_path: Path):
    m = model(tmp_path, 13)
    t0 = datetime(2026, 8, 10, 5, 45, tzinfo=TZ7)
    s = m.step("farm_long", "A", t0, force=True)
    moisture_before = s.soil_moisture
    s = m.step("farm_long", "A", datetime(2026, 8, 10, 6, 10, tzinfo=TZ7), force=True)
    assert s.flow_rate > 10.0
    assert s.soil_moisture > moisture_before
    s = m.step("farm_long", "A", datetime(2026, 8, 10, 7, 0, tzinfo=TZ7), force=True)
    assert s.flow_rate < 1.0


def test_values_remain_agronomically_bounded_over_a_week(tmp_path: Path):
    m = model(tmp_path, 17)
    start = datetime(2026, 8, 10, 0, 0, tzinfo=TZ7)
    values = []
    for i in range(7 * 24 * 2):
        s = m.step("farm_long", "A", start + timedelta(minutes=30 * i), force=True)
        values.append((s.temperature, s.air_humidity, s.soil_moisture, s.ec, s.ph, s.flow_rate))
    arr = np.asarray(values)
    assert arr[:, 0].min() >= 5 and arr[:, 0].max() <= 50
    assert arr[:, 1].min() >= 32 and arr[:, 1].max() <= 99
    assert arr[:, 2].min() >= 32 and arr[:, 2].max() <= 78
    assert arr[:, 3].min() >= 0.15 and arr[:, 3].max() <= 3.375
    assert arr[:, 4].min() >= 4.2 and arr[:, 4].max() <= 8.2
    assert arr[:, 5].min() >= 0
