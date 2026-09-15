from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "services" / "data-simulator-service"
sys.path.insert(0, str(SIM))
from app.calibrated_model import ResearchCalibratedFarmModel  # noqa: E402


def main() -> int:
    model = ResearchCalibratedFarmModel(ROOT / "research-data" / "calibration" / "v9_profiles.json", ROOT / "research-data" / "reference" / "reference_calibration.json", seed=20260811)
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    farms: dict[str, dict] = {}
    all_ok = True

    for farm_id in ("farm_long", "farm_lan", "farm_minh"):
        rows = []
        for i in range(7 * 24 * 12):  # 7 days, 5-minute physical samples
            state = model.step(farm_id, "A", start + timedelta(minutes=5 * i), force=True)
            rows.append([
                state.temperature, state.air_humidity, state.soil_moisture,
                state.ec, state.ph, state.flow_rate, state.rain_mm_h,
            ])
        a = np.asarray(rows, dtype=float)
        jumps = np.abs(np.diff(a, axis=0))
        p = model.farm_profile(farm_id)
        metrics = {
            "temperature_mean": round(float(a[:, 0].mean()), 3),
            "temperature_min": round(float(a[:, 0].min()), 3),
            "temperature_max": round(float(a[:, 0].max()), 3),
            "air_humidity_mean": round(float(a[:, 1].mean()), 3),
            "air_humidity_min": round(float(a[:, 1].min()), 3),
            "air_humidity_max": round(float(a[:, 1].max()), 3),
            "soil_moisture_mean": round(float(a[:, 2].mean()), 3),
            "soil_moisture_min": round(float(a[:, 2].min()), 3),
            "soil_moisture_max": round(float(a[:, 2].max()), 3),
            "soil_moisture_target": float(p["soil"]["moisture_target"]),
            "ec_mean": round(float(a[:, 3].mean()), 4),
            "ph_mean": round(float(a[:, 4].mean()), 4),
            "flow_active_fraction": round(float((a[:, 5] > 1.0).mean()), 5),
            "corr_temperature_air_humidity": round(float(np.corrcoef(a[:, 0], a[:, 1])[0, 1]), 4),
            "corr_soil_moisture_ec": round(float(np.corrcoef(a[:, 2], a[:, 3])[0, 1]), 4),
            "max_5m_jump_temperature": round(float(jumps[:, 0].max()), 4),
            "max_5m_jump_soil_moisture": round(float(jumps[:, 2].max()), 4),
            "max_5m_jump_ec": round(float(jumps[:, 3].max()), 5),
            "max_5m_jump_ph": round(float(jumps[:, 4].max()), 5),
        }
        checks = {
            "physical_bounds": (
                a[:, 0].min() >= 5 and a[:, 0].max() <= 50
                and a[:, 1].min() >= 0 and a[:, 1].max() <= 100
                and a[:, 2].min() >= p["soil"]["dry_floor"] - 1e-6
                and a[:, 2].max() <= p["soil"]["field_capacity"] + 1e-6
                and a[:, 3].min() >= 0 and a[:, 4].min() >= 0
            ),
            "smooth_5m_state": jumps[:, 0].max() < 1.0 and jumps[:, 2].max() < 3.5 and jumps[:, 3].max() < 0.06 and jumps[:, 4].max() < 0.05,
            "temperature_rh_relation": np.corrcoef(a[:, 0], a[:, 1])[0, 1] < -0.45,
            "soil_near_operating_target": abs(a[:, 2].mean() - p["soil"]["moisture_target"]) < 12.0,
            "irrigation_is_event_like": 0.002 < (a[:, 5] > 1.0).mean() < 0.15,
        }
        checks = {k: bool(v) for k, v in checks.items()}
        ok = all(checks.values())
        all_ok = all_ok and ok
        farms[farm_id] = {"metrics": metrics, "checks": checks, "passed": bool(ok)}

    report = {
        "version": "9.0.0",
        "profile_version": model.profile_version,
        "simulation_window": "7 days at 5-minute physical cadence, deterministic seed 20260811",
        "purpose": "sanity/stability validation; not a claim that simulated values are real measurements",
        "reported_tomato_reference": {
            "source": "10.1016/j.compag.2024.109660 / calibration audit CSV",
            "note": "Reported correlations guide sign/strength; V9 does not force exact coefficients across different farms/regimes.",
        },
        "passed": all_ok,
        "farms": farms,
    }
    out = ROOT / "docs" / "evidence" / "v9-simulation-dynamics-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nReport: {out}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
