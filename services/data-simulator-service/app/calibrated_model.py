from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class ZoneState:
    farm_id: str
    zone_code: str
    temperature: float
    air_humidity: float
    soil_moisture: float
    ec: float
    ph: float
    flow_rate: float = 0.0
    rain_mm_h: float = 0.0
    weather_offset: float = 0.0
    humidity_offset: float = 0.0
    fault: str | None = None
    fault_until: datetime | None = None
    fault_metric: str | None = None
    stuck_values: dict[str, float] = field(default_factory=dict)
    drift: dict[str, float] = field(default_factory=dict)
    last_ts: datetime | None = None


class ResearchCalibratedFarmModel:
    """Stateful simulator whose dynamics are calibrated from public IoT literature.

    It deliberately separates physical state updates from MQTT publish cadence.  A 2 s
    packet cadence therefore does not create unrealistic 2 s physical jumps.
    """

    def __init__(self, profile_path: str | Path, calibration_path: str | Path, seed: int = 20260811):
        self.profile_path = Path(profile_path)
        self.calibration_path = Path(calibration_path)
        self.config = json.loads(self.profile_path.read_text(encoding="utf-8"))
        if not self.calibration_path.exists():
            raise RuntimeError("Thiếu reference_calibration.json. Chạy scripts\\prepare_v9_research_data.cmd trước khi build V9.")
        self.reference_calibration = json.loads(self.calibration_path.read_text(encoding="utf-8"))
        if int(self.reference_calibration.get("normalized_rows") or 0) < 10000:
            raise RuntimeError("Reference calibration chưa đủ >= 10.000 dòng chuẩn hóa.")
        self.profile_version = self.config["profile_version"]
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)
        self.states: dict[tuple[str, str], ZoneState] = {}
        self.last_physical_update: dict[tuple[str, str], datetime] = {}
        self.minimum_step_seconds = int(self.config["principles"].get("physical_state_minimum_step_seconds", 30))
        self.nasa_hourly: dict[tuple[str, int, int, int], dict[str, float]] = {}
        self._load_nasa_power_cache()

    def _load_nasa_power_cache(self) -> None:
        """Load optional NASA POWER hourly CSV caches bundled/downloaded before build.

        We index by month/day/hour so a historical reference year can drive a current
        demonstration without pretending those NASA rows are NextFarm sensor readings.
        """
        root = self.profile_path.parent.parent / "reference" / "raw" / "nasa_power"
        if not root.exists():
            return
        for farm_id in self.config.get("farms", {}):
            candidates = sorted(root.glob(f"{farm_id}_*.csv"), reverse=True)
            if not candidates:
                continue
            path = candidates[0]
            try:
                lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
                header_idx = next(
                    (i for i, line in enumerate(lines[:100]) if {"YEAR", "MO", "DY", "HR"}.issubset(set(x.strip() for x in line.split(",")))),
                    None,
                )
                if header_idx is None:
                    continue
                for row in csv.DictReader(lines[header_idx:]):
                    try:
                        key = (farm_id, int(row["MO"]), int(row["DY"]), int(row["HR"]))
                        vals = {}
                        for name in ("T2M", "RH2M", "PRECTOTCORR", "ALLSKY_SFC_SW_DWN", "WS2M"):
                            raw = row.get(name)
                            if raw not in (None, ""):
                                value = float(raw)
                                if value > -900:
                                    vals[name] = value
                        if vals:
                            self.nasa_hourly[key] = vals
                    except (ValueError, TypeError, KeyError):
                        continue
            except OSError:
                continue

    def _nasa_weather(self, farm_id: str, ts: datetime) -> dict[str, float] | None:
        local = ts.astimezone(timezone(timedelta(hours=7)))
        return self.nasa_hourly.get((farm_id, local.month, local.day, local.hour))

    @property
    def calibration_checksum(self) -> str:
        return hashlib.sha256(self.calibration_path.read_bytes()).hexdigest()

    @property
    def checksum(self) -> str:
        h = hashlib.sha256()
        h.update(self.profile_path.read_bytes())
        h.update(self.calibration_path.read_bytes())
        return h.hexdigest()

    def reference_metric(self, metric: str) -> dict[str, Any]:
        return dict(self.reference_calibration.get("metrics", {}).get(metric, {}) or {})

    def reference_median(self, metric: str, fallback: float) -> float:
        return float(self.reference_metric(metric).get("median", fallback))

    def reference_step(self, metric: str, fallback: float) -> float:
        return max(0.0, float(self.reference_metric(metric).get("median_abs_step", fallback)))

    def reference_corr(self, a: str, b: str, fallback: float) -> float:
        value = float(self.reference_calibration.get("correlations", {}).get(f"{a}__{b}", fallback))
        return min(0.95, max(-0.95, value))

    def farm_profile(self, farm_id: str) -> dict[str, Any]:
        return self.config["farms"][farm_id]

    def _zone_offset(self, zone_code: str) -> float:
        return {"A": 0.0, "B": -1.2, "C": 0.7}.get(zone_code.upper(), 0.0)

    def _initial_state(self, farm_id: str, zone_code: str, ts: datetime) -> ZoneState:
        p = self.farm_profile(farm_id)
        z = self._zone_offset(zone_code)
        state = ZoneState(
            farm_id=farm_id,
            zone_code=zone_code,
            temperature=float(0.25*self.reference_median("temperature", p["climate"]["temp_mean"]) + 0.75*float(p["climate"]["temp_mean"]) + self.rng.normal(0, 0.20)),
            air_humidity=float(0.25*self.reference_median("air_humidity", p["climate"]["rh_mean"]) + 0.75*float(p["climate"]["rh_mean"]) + self.rng.normal(0, 0.55)),
            soil_moisture=float(0.20*self.reference_median("soil_moisture", p["soil"]["moisture_target"]) + 0.80*float(p["soil"]["moisture_target"]) + z + self.rng.normal(0, 0.45)),
            ec=float(0.20*self.reference_median("ec", p["nutrition"]["ec_target"]) + 0.80*float(p["nutrition"]["ec_target"]) + self.rng.normal(0, 0.012)),
            ph=float(0.20*self.reference_median("ph", p["nutrition"]["ph_target"]) + 0.80*float(p["nutrition"]["ph_target"]) + self.rng.normal(0, 0.010)),
            last_ts=ts,
        )
        self.states[(farm_id, zone_code)] = state
        self.last_physical_update[(farm_id, zone_code)] = ts
        return state

    @staticmethod
    def _solar_factor(local_hour: float) -> float:
        if local_hour < 5.5 or local_hour > 18.5:
            return 0.0
        return max(0.0, math.sin(math.pi * (local_hour - 5.5) / 13.0))

    def _maybe_update_rain(self, state: ZoneState, p: dict[str, Any], dt_hours: float, solar: float) -> None:
        # Rain is an episode, not independent packet noise. Greenhouses receive only a weak indirect effect.
        sensitivity = float(p["climate"]["rain_sensitivity"])
        if state.rain_mm_h > 0:
            state.rain_mm_h *= math.exp(-dt_hours / 0.75)
            if state.rain_mm_h < 0.08:
                state.rain_mm_h = 0.0
        else:
            # roughly a small number of rain starts per week; more likely in humid/open-field profiles
            daily_hazard = 0.18 * sensitivity
            if self.rng.random() < daily_hazard * dt_hours / 24.0:
                state.rain_mm_h = float(self.rng.uniform(3.0, 14.0))
        # keep greenhouse rain from directly behaving like open-field rainfall
        if p["cultivation"] == "greenhouse":
            state.rain_mm_h = min(state.rain_mm_h, 1.0)

    def _maybe_fault(self, state: ZoneState, p: dict[str, Any], ts: datetime, dt_hours: float) -> None:
        if state.fault and state.fault_until and ts >= state.fault_until:
            state.fault = None
            state.fault_until = None
            state.fault_metric = None
            state.stuck_values.clear()
            state.drift.clear()
        if state.fault:
            return
        daily_rate = float(p.get("fault_rate_per_day", 0.08))
        if self.rng.random() >= daily_rate * dt_hours / 24.0:
            return
        faults = ["offline", "no_flow", "leak", "sensor_drift", "sensor_stuck"]
        weights = np.array([0.16, 0.24, 0.12, 0.26, 0.22], dtype=float)
        fault = str(self.rng.choice(faults, p=weights / weights.sum()))
        fcfg = self.config["faults"][fault]
        duration = float(self.rng.uniform(fcfg["min_minutes"], fcfg["max_minutes"]))
        state.fault = fault
        state.fault_until = ts + timedelta(minutes=duration)
        if fault in {"sensor_drift", "sensor_stuck"}:
            state.fault_metric = str(self.rng.choice(["soil_moisture", "temperature", "air_humidity", "ec", "ph"]))
            if fault == "sensor_stuck":
                state.stuck_values[state.fault_metric] = float(getattr(state, state.fault_metric))
            else:
                scales = {"soil_moisture": 2.0, "temperature": 0.7, "air_humidity": 2.5, "ec": 0.10, "ph": 0.12}
                state.drift[state.fault_metric] = float(self.rng.choice([-1, 1]) * scales[state.fault_metric])

    def _is_irrigating(self, state: ZoneState, p: dict[str, Any], ts: datetime) -> bool:
        local = ts.astimezone(timezone(timedelta(hours=7)))
        cfg = p["irrigation"]
        scheduled = any(local.hour == int(hour) and local.minute < int(cfg["duration_minutes"]) for hour in cfg["hours"])
        # Threshold irrigation can start in a small control window; avoids a permanently-on valve.
        threshold = state.soil_moisture < float(cfg["threshold_trigger"])
        threshold_window = local.minute < min(10, int(cfg["duration_minutes"]))
        return bool(scheduled or (threshold and threshold_window))

    def step(self, farm_id: str, zone_code: str, ts: datetime, *, force: bool = False) -> ZoneState:
        key = (farm_id, zone_code)
        state = self.states.get(key) or self._initial_state(farm_id, zone_code, ts)
        last = state.last_ts or ts
        elapsed = max(0.0, (ts - last).total_seconds())
        if not force and elapsed < self.minimum_step_seconds:
            return state
        dt_hours = max(elapsed, self.minimum_step_seconds if not force else elapsed) / 3600.0
        dt_hours = min(max(dt_hours, 1.0 / 3600.0), 1.0)  # numerical stability after long pauses
        p = self.farm_profile(farm_id)
        local = ts.astimezone(timezone(timedelta(hours=7)))
        local_hour = local.hour + local.minute / 60.0 + local.second / 3600.0
        solar = self._solar_factor(local_hour)

        nasa = self._nasa_weather(farm_id, ts)
        if nasa and "PRECTOTCORR" in nasa:
            # POWER precipitation is mm/hour. Greenhouse receives only an attenuated indirect effect.
            state.rain_mm_h = max(0.0, float(nasa["PRECTOTCORR"]))
            if p["cultivation"] == "greenhouse":
                state.rain_mm_h = min(1.0, state.rain_mm_h * 0.08)
        else:
            self._maybe_update_rain(state, p, dt_hours, solar)
        self._maybe_fault(state, p, ts, dt_hours)

        # Weather is an AR(1)-like state around a diurnal target. If a NASA POWER cache
        # exists, its hourly T/RH becomes the baseline while local cultivation modifies it.
        state.weather_offset = 0.965 * state.weather_offset + float(self.rng.normal(0, p["climate"]["weather_noise"] * math.sqrt(dt_hours)))
        profile_temp = float(p["climate"]["temp_mean"]) + float(p["climate"]["temp_amp"]) * (solar - 0.32)
        if nasa and "T2M" in nasa:
            climate_weight = 0.88 if p["cultivation"] == "open_field" else (0.72 if p["cultivation"] == "net_house" else 0.60)
            temp_target = climate_weight * float(nasa["T2M"]) + (1.0 - climate_weight) * profile_temp + state.weather_offset
        else:
            temp_target = profile_temp + state.weather_offset
        temp_alpha = 1.0 - math.exp(-dt_hours / 0.45)
        state.temperature += (temp_target - state.temperature) * temp_alpha + float(self.rng.normal(0, min(0.035, max(0.005, self.reference_step("temperature", 0.02) * 0.35))))

        profile_rh = float(p["climate"]["rh_mean"]) - float(p["climate"]["rh_amp"]) * solar
        if nasa and "RH2M" in nasa:
            climate_weight = 0.88 if p["cultivation"] == "open_field" else (0.72 if p["cultivation"] == "net_house" else 0.58)
            rh_target = climate_weight * float(nasa["RH2M"]) + (1.0 - climate_weight) * profile_rh
        else:
            rh_target = profile_rh
        # RH is usually anti-correlated with temperature/solar load, but not perfectly:
        # ventilation, cloud cover and local moisture create their own slowly-varying component.
        state.humidity_offset = 0.975 * state.humidity_offset + float(self.rng.normal(0, 0.85 * math.sqrt(dt_hours)))
        rh_target -= min(0.90, max(0.25, abs(self.reference_corr("temperature", "air_humidity", -0.60)))) * (state.temperature - float(p["climate"]["temp_mean"]))
        rh_target += state.humidity_offset
        rh_target += min(14.0, state.rain_mm_h * 1.7)
        rh_alpha = 1.0 - math.exp(-dt_hours / 0.55)
        state.air_humidity += (rh_target - state.air_humidity) * rh_alpha + float(self.rng.normal(0, min(0.16, max(0.02, self.reference_step("air_humidity", 0.10) * 0.40))))
        state.air_humidity = float(np.clip(state.air_humidity, 32, 99))

        irrigating = self._is_irrigating(state, p, ts)
        nominal_flow = float(p["irrigation"]["flow_lpm"]) * (1.0 + 0.04 * self._zone_offset(zone_code))
        if state.fault == "offline":
            state.flow_rate = 0.0
        elif state.fault == "no_flow" and irrigating:
            state.flow_rate = float(max(0.0, self.rng.normal(0.18, 0.07)))
        elif state.fault == "leak" and not irrigating:
            state.flow_rate = float(max(1.2, self.rng.normal(nominal_flow * 0.22, 0.25)))
        elif irrigating:
            state.flow_rate = float(max(0.0, self.rng.normal(nominal_flow, nominal_flow * 0.015)))
        else:
            state.flow_rate = float(max(0.0, self.rng.normal(0.03, 0.018)))

        soil = p["soil"]
        evap = float(soil["evap_per_hour"]) * (0.35 + 0.95 * solar) * (1.15 - min(state.air_humidity, 95) / 130.0)
        moisture_change = -evap * dt_hours
        if state.flow_rate > 1.0 and irrigating:
            moisture_change += float(soil["irrigation_gain_per_min"]) * dt_hours * 60.0 * min(1.2, state.flow_rate / max(nominal_flow, 0.1))
        if state.rain_mm_h > 0 and p["cultivation"] != "greenhouse":
            moisture_change += state.rain_mm_h * dt_hours * 0.72 * float(p["climate"]["rain_sensitivity"])
        if state.soil_moisture > float(soil["moisture_target"]):
            moisture_change -= float(soil["drain_per_hour"]) * dt_hours * (state.soil_moisture - float(soil["moisture_target"])) / 10.0
        state.soil_moisture = float(np.clip(state.soil_moisture + moisture_change + self.rng.normal(0, min(0.06, max(0.008, self.reference_step("soil_moisture", 0.03) * 0.25))), soil["dry_floor"], soil["field_capacity"]))

        nutrition = p["nutrition"]
        # Slow EC dynamics. Tomato calibration includes a strong positive EC/soil-humidity relation in one irrigation line,
        # while cumulative water volume is negatively correlated; use a modest coupling rather than forcing the exact r.
        ec_target = float(nutrition["ec_target"]) + float(nutrition["ec_moisture_coupling"]) * (state.soil_moisture - float(soil["moisture_target"])) / 18.0
        if irrigating and p["crop"] == "tomato":
            ec_target += 0.04
        if state.rain_mm_h > 2 and p["cultivation"] == "open_field":
            ec_target -= 0.08
        ec_alpha = 1.0 - math.exp(-dt_hours / 5.0)
        state.ec += (ec_target - state.ec) * ec_alpha + float(self.rng.normal(0, min(0.004, max(0.0005, self.reference_step("ec", 0.002) * 0.25))))
        state.ec = float(np.clip(state.ec, max(0.15, nutrition["ec_min"] * 0.65), nutrition["ec_max"] * 1.35))

        ph_target = float(nutrition["ph_target"])
        ph_alpha = 1.0 - math.exp(-dt_hours / 14.0)
        state.ph += (ph_target - state.ph) * ph_alpha + float(self.rng.normal(0, min(float(nutrition["ph_drift_per_hour"]) * math.sqrt(dt_hours), max(0.0004, self.reference_step("ph", 0.002) * 0.15))))
        state.ph = float(np.clip(state.ph, 4.2, 8.2))

        state.last_ts = ts
        self.last_physical_update[key] = ts
        return state

    def reading(self, state: ZoneState, metric: str) -> tuple[float | None, str]:
        if state.fault == "offline":
            return None, "bad"
        value = float(getattr(state, metric))
        quality = "good"
        if state.fault_metric == metric:
            if state.fault == "sensor_stuck":
                value = float(state.stuck_values.get(metric, value))
                quality = "suspect"
            elif state.fault == "sensor_drift":
                value += float(state.drift.get(metric, 0.0))
                quality = "suspect"
        hard_cap = {"soil_moisture":0.08,"temperature":0.025,"air_humidity":0.10,"ec":0.003,"ph":0.004,"flow_rate":0.025}.get(metric,0.01)
        empirical = self.reference_step(metric, hard_cap)
        sensor_noise = min(hard_cap, max(hard_cap * 0.12, empirical * 0.20))
        value += float(self.rng.normal(0, sensor_noise))
        bounds = {
            "soil_moisture": (0, 100), "temperature": (5, 50), "air_humidity": (0, 100),
            "ec": (0, 6), "ph": (0, 14), "flow_rate": (0, 60),
        }
        lo, hi = bounds.get(metric, (-1e9, 1e9))
        return float(np.clip(value, lo, hi)), quality
