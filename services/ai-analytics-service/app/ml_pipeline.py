from __future__ import annotations

import json
import hashlib
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, ExtraTreesRegressor, RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
)

DATASET_VERSION = "nextfarm-v9-test-fixture"
MODEL_VERSION = "2.1.0"
RANDOM_SEED = 20260804

# Hồ sơ chỉ là feature/configuration; không tạo model riêng theo farm_id.
FARM_PROFILES: dict[str, dict[str, Any]] = {
    "farm_long": {
        "name": "Vườn cà chua Anh Long",
        "crop": "tomato",
        "cultivation_type": "greenhouse",
        "climate_region": "highland",
        "soil_type": "loam",
        "area_ha": 1.2,
        "base_moisture": 62.0,
        "base_temp": 25.5,
        "base_ec": 1.9,
        "base_ph": 6.2,
        "moisture_min": 55.0,
        "moisture_max": 70.0,
        "ec_min": 1.5,
        "ec_max": 2.5,
        "ph_min": 5.8,
        "ph_max": 6.8,
    },
    "farm_lan": {
        "name": "Vườn sầu riêng Chị Lan",
        "crop": "durian",
        "cultivation_type": "open_field",
        "climate_region": "central_highlands",
        "soil_type": "basalt",
        "area_ha": 2.8,
        "base_moisture": 56.0,
        "base_temp": 27.0,
        "base_ec": 1.4,
        "base_ph": 5.8,
        "moisture_min": 50.0,
        "moisture_max": 68.0,
        "ec_min": 1.0,
        "ec_max": 2.0,
        "ph_min": 5.3,
        "ph_max": 6.5,
    },
    "farm_minh": {
        "name": "Vườn rau Anh Minh",
        "crop": "leafy_vegetable",
        "cultivation_type": "net_house",
        "climate_region": "mekong_delta",
        "soil_type": "alluvial",
        "area_ha": 0.8,
        "base_moisture": 69.0,
        "base_temp": 28.5,
        "base_ec": 1.55,
        "base_ph": 6.4,
        "moisture_min": 62.0,
        "moisture_max": 78.0,
        "ec_min": 1.1,
        "ec_max": 2.0,
        "ph_min": 5.8,
        "ph_max": 7.0,
    },
}

CROP_CODES = {"tomato": 0, "durian": 1, "leafy_vegetable": 2, "other": 3}
CULTIVATION_CODES = {"greenhouse": 0, "open_field": 1, "net_house": 2, "other": 3}
CLIMATE_CODES = {"highland": 0, "central_highlands": 1, "mekong_delta": 2, "other": 3}
SOIL_CODES = {"loam": 0, "basalt": 1, "alluvial": 2, "other": 3}

ZONES = ("A", "B", "C")
SCENARIOS = (
    "normal", "normal", "low_moisture", "normal", "no_flow", "leak",
    "sensor_stuck", "device_offline", "ec_high", "irrigation_failed", "ph_out", "sensor_noise",
)

PROFILE_FEATURES = [
    "crop_index",
    "cultivation_index",
    "climate_index",
    "soil_index",
    "area_ha",
    "moisture_target_mid",
    "moisture_target_width",
    "ec_target_mid",
    "ph_target_mid",
]

DYNAMIC_FEATURES = [
    "zone_index", "minute_sin", "minute_cos", "day_sin", "day_cos",
    "soil_moisture", "temperature", "air_humidity", "ec", "ph", "flow_rate",
    "soil_moisture_missing", "temperature_missing", "air_humidity_missing", "ec_missing", "ph_missing", "flow_rate_missing",
    "valve_running", "pump_running", "device_online", "scheduled_irrigation",
    "minutes_since_irrigation", "sensor_age_seconds", "packet_loss_rate", "command_failure_rate",
    "moisture_delta", "temperature_delta", "humidity_delta", "ec_delta", "ph_delta", "flow_delta",
    "moisture_roll_mean", "moisture_roll_std", "flow_roll_mean", "flow_roll_std",
]
FEATURES = PROFILE_FEATURES + DYNAMIC_FEATURES


@dataclass(frozen=True)
class ModelSpec:
    name: str
    display_name: str
    task: str
    target: str
    description: str


MODEL_SPECS = [
    ModelSpec("moisture_forecast", "Dự báo độ ẩm đất", "regression", "target_moisture_30m", "Dự báo độ ẩm sau 30 phút."),
    ModelSpec("temperature_forecast", "Dự báo nhiệt độ", "regression", "target_temperature_30m", "Dự báo nhiệt độ sau 30 phút."),
    ModelSpec("ec_forecast", "Dự báo EC", "regression", "target_ec_30m", "Dự báo EC sau 30 phút."),
    ModelSpec("ph_forecast", "Dự báo pH", "regression", "target_ph_30m", "Dự báo pH sau 30 phút."),
    ModelSpec("anomaly_multisensor", "Bất thường đa cảm biến", "classification", "anomaly_label", "Phát hiện dữ liệu hoặc trạng thái bất thường."),
    ModelSpec("flow_fault", "Chẩn đoán lưu lượng", "classification", "flow_fault_label", "Phân loại bình thường, thiếu lưu lượng hoặc rò rỉ."),
    ModelSpec("irrigation_failure", "Ca tưới thất bại", "classification", "irrigation_failure_label", "Phát hiện ca tưới không tạo được kết quả mong đợi."),
    ModelSpec("irrigation_need", "Nhu cầu tưới", "classification", "irrigation_need_label", "Ước lượng khu có cần tưới hoặc theo dõi sát."),
    ModelSpec("device_health", "Sức khỏe thiết bị", "classification", "device_health_label", "Đánh giá trạng thái tốt, cần theo dõi hoặc cần kiểm tra."),
    ModelSpec("farm_health", "Sức khỏe tổng thể vườn", "classification", "farm_health_label", "Tổng hợp rủi ro của vườn từ cảm biến, tưới và thiết bị."),
]

# Lớp cần ưu tiên recall vì bỏ sót có thể che khuất sự cố vận hành.
CRITICAL_CLASSES: dict[str, tuple[int, ...]] = {
    "anomaly_multisensor": (1,),
    "flow_fault": (1, 2),
    "irrigation_failure": (1,),
    "irrigation_need": (1,),
    "device_health": (2,),
    "farm_health": (2,),
}


def profile_feature_values(profile: dict[str, Any]) -> dict[str, float]:
    return {
        "crop_index": float(CROP_CODES.get(str(profile.get("crop")), CROP_CODES["other"])),
        "cultivation_index": float(CULTIVATION_CODES.get(str(profile.get("cultivation_type")), CULTIVATION_CODES["other"])),
        "climate_index": float(CLIMATE_CODES.get(str(profile.get("climate_region")), CLIMATE_CODES["other"])),
        "soil_index": float(SOIL_CODES.get(str(profile.get("soil_type")), SOIL_CODES["other"])),
        "area_ha": float(profile.get("area_ha", 1.0)),
        "moisture_target_mid": (float(profile["moisture_min"]) + float(profile["moisture_max"])) / 2.0,
        "moisture_target_width": float(profile["moisture_max"]) - float(profile["moisture_min"]),
        "ec_target_mid": (float(profile["ec_min"]) + float(profile["ec_max"])) / 2.0,
        "ph_target_mid": (float(profile["ph_min"]) + float(profile["ph_max"])) / 2.0,
    }


def generate_training_frame(
    farm_id: str,
    *,
    days: int = 14,
    freq_minutes: int = 15,
    seed: int | None = None,
) -> pd.DataFrame:
    """Sinh dữ liệu có quan hệ vật lý cho một farm; model sẽ train trên frame hợp nhất nhiều farm."""
    if farm_id not in FARM_PROFILES:
        raise ValueError(f"Farm không được hỗ trợ trong bộ mô phỏng: {farm_id}")
    profile = FARM_PROFILES[farm_id]
    profile_values = profile_feature_values(profile)
    seed_value = seed if seed is not None else RANDOM_SEED + list(FARM_PROFILES).index(farm_id) * 1009
    rng = np.random.default_rng(seed_value)
    end = pd.Timestamp("2026-08-04T12:00:00Z")
    timestamps = pd.date_range(end=end, periods=max(96, days * 24 * 60 // freq_minutes), freq=f"{freq_minutes}min", tz="UTC")
    rows: list[dict[str, Any]] = []

    for zone_index, zone in enumerate(ZONES):
        moisture = float(profile["base_moisture"] + rng.normal(0, 1.4) + zone_index * 0.7)
        ec = float(profile["base_ec"] + rng.normal(0, 0.08))
        ph = float(profile["base_ph"] + rng.normal(0, 0.05))
        last_irrigation_ts = timestamps[0] - pd.Timedelta(hours=4)
        stuck_values: dict[str, float] | None = None

        for i, ts in enumerate(timestamps):
            hour = ts.hour + ts.minute / 60.0
            day_wave = math.sin(2 * math.pi * (hour - 7) / 24)
            temp = float(profile["base_temp"] + 4.5 * day_wave + rng.normal(0, 0.65))
            rh_base = {"highland": 76.0, "central_highlands": 78.0, "mekong_delta": 82.0}.get(profile["climate_region"], 76.0)
            air_humidity = float(np.clip(rh_base - 1.35 * (temp - profile["base_temp"]) + rng.normal(0, 1.1), 35, 99))
            irrigation_hours = {5, 11, 16} if profile["crop"] != "durian" else {5, 17}
            scenario = SCENARIOS[(i // max(4, 2 * 60 // freq_minutes)) % len(SCENARIOS)]
            scenario = "normal" if rng.random() < 0.65 else scenario
            scheduled = int(ts.hour in irrigation_hours and ts.minute < max(30, freq_minutes))
            if scenario == "irrigation_failed" and ts.hour % 3 == 0 and ts.minute < max(30, freq_minutes):
                scheduled = 1
            device_online = 0 if scenario == "device_offline" else 1
            valve_running = int(scheduled and device_online)
            pump_running = int(scheduled and device_online)
            normal_flow = 10.0 + zone_index * 1.8 + float(profile["area_ha"]) * 0.8
            flow = normal_flow + rng.normal(0, 0.7) if scheduled and device_online else max(0.0, rng.normal(0.05, 0.07))

            if scenario in {"no_flow", "irrigation_failed"} and scheduled:
                flow = max(0.0, rng.normal(0.18, 0.12))
            elif scenario == "leak" and not scheduled:
                flow = max(1.2, rng.normal(3.0, 0.65))
            if scheduled and flow > 1.0:
                moisture += 5.5 + rng.normal(0, 0.8)
                last_irrigation_ts = ts
            else:
                evap = 0.05 + max(temp - 24, 0) * 0.012
                moisture -= evap + rng.normal(0, 0.06)
            if scenario == "low_moisture":
                moisture -= 0.25
            if scenario in {"no_flow", "irrigation_failed"} and scheduled:
                moisture -= 0.35
            moisture = float(np.clip(moisture, 18, 92))

            ec += rng.normal(0, 0.012) + (0.025 if scheduled and profile["crop"] == "tomato" else 0)
            ph += rng.normal(0, 0.01)
            if scenario == "ec_high":
                ec += 0.06
            if scenario == "ph_out":
                ph += 0.05 if (i // 16) % 2 == 0 else -0.05

            packet_loss = float(np.clip(rng.beta(1.4, 22), 0, 1))
            command_failure = float(np.clip(rng.beta(1.3, 30), 0, 1))
            sensor_age = float(rng.integers(2, 18))
            if scenario == "device_offline":
                packet_loss = float(np.clip(0.65 + rng.normal(0, 0.08), 0, 1))
                command_failure = float(np.clip(0.75 + rng.normal(0, 0.08), 0, 1))
                sensor_age = float(rng.integers(300, 900))
            elif scenario == "sensor_stuck":
                sensor_age = float(rng.integers(80, 220))
                if stuck_values is None:
                    stuck_values = {"moisture": moisture, "temperature": temp, "air_humidity": air_humidity, "ec": ec, "ph": ph}
                moisture = stuck_values["moisture"]
                temp = stuck_values["temperature"]
                air_humidity = stuck_values["air_humidity"]
                ec = stuck_values["ec"]
                ph = stuck_values["ph"]
            else:
                stuck_values = None
            if scenario == "sensor_noise":
                moisture += rng.normal(0, 7.0)
                temp += rng.normal(0, 3.0)
                air_humidity += rng.normal(0, 8.0)
                ec += rng.normal(0, 0.45)
                ph += rng.normal(0, 0.55)

            minutes_since_irrigation = max(0.0, (ts - last_irrigation_ts).total_seconds() / 60.0)
            anomaly = int(scenario != "normal")
            flow_fault = 1 if scenario in {"no_flow", "irrigation_failed"} and scheduled else 2 if scenario == "leak" and not scheduled else 0
            irrigation_failure = int(scheduled and (flow < 1.0 or device_online == 0))
            irrigation_need = int(scenario == "low_moisture" or moisture < float(profile["moisture_min"]) or (moisture < profile_values["moisture_target_mid"] and minutes_since_irrigation > 300))
            device_health = 2 if device_online == 0 or sensor_age > 240 or command_failure > 0.55 else 1 if packet_loss > 0.18 or sensor_age > 60 or command_failure > 0.18 else 0
            critical = irrigation_failure or flow_fault > 0 or device_health == 2
            warning = anomaly or irrigation_need or ec > float(profile["ec_max"]) or not (float(profile["ph_min"]) <= ph <= float(profile["ph_max"]))
            farm_health = 2 if critical else 1 if warning else 0

            # Nhiễu nhãn nhỏ để bài toán không quá lý tưởng.
            if rng.random() < 0.018:
                flow_fault = int(rng.choice([x for x in (0, 1, 2) if x != flow_fault]))
            if rng.random() < 0.022:
                irrigation_failure = 1 - irrigation_failure
            if rng.random() < 0.018:
                irrigation_need = 1 - irrigation_need
            if rng.random() < 0.015:
                device_health = int(rng.choice([x for x in (0, 1, 2) if x != device_health]))
            if rng.random() < 0.020:
                farm_health = int(rng.choice([x for x in (0, 1, 2) if x != farm_health]))

            row: dict[str, Any] = {
                "farm_id": farm_id,
                "farm_name": profile["name"],
                "crop": profile["crop"],
                "zone_code": zone,
                "zone_index": zone_index,
                "observed_at": ts,
                "scenario_label": scenario,
                "soil_moisture": round(float(np.clip(moisture, 0, 100)), 4),
                "temperature": round(float(np.clip(temp, 5, 50)), 4),
                "air_humidity": round(float(np.clip(air_humidity, 0, 100)), 4),
                "ec": round(float(np.clip(ec, 0, 6)), 4),
                "ph": round(float(np.clip(ph, 2, 10)), 4),
                "flow_rate": round(float(np.clip(flow, 0, 40)), 4),
                "soil_moisture_missing": int(device_online == 0),
                "temperature_missing": int(device_online == 0),
                "air_humidity_missing": int(device_online == 0),
                "ec_missing": int(device_online == 0),
                "ph_missing": int(device_online == 0),
                "flow_rate_missing": int(device_online == 0),
                "valve_running": valve_running,
                "pump_running": pump_running,
                "device_online": device_online,
                "scheduled_irrigation": scheduled,
                "minutes_since_irrigation": round(minutes_since_irrigation, 2),
                "sensor_age_seconds": round(sensor_age, 2),
                "packet_loss_rate": round(packet_loss, 5),
                "command_failure_rate": round(command_failure, 5),
                "anomaly_label": anomaly,
                "flow_fault_label": flow_fault,
                "irrigation_failure_label": irrigation_failure,
                "irrigation_need_label": irrigation_need,
                "device_health_label": device_health,
                "farm_health_label": farm_health,
                **profile_values,
            }
            rows.append(row)

    frame = pd.DataFrame(rows).sort_values(["observed_at", "zone_code"]).reset_index(drop=True)
    minute = frame["observed_at"].dt.hour * 60 + frame["observed_at"].dt.minute
    frame["minute_sin"] = np.sin(2 * np.pi * minute / 1440)
    frame["minute_cos"] = np.cos(2 * np.pi * minute / 1440)
    day = frame["observed_at"].dt.dayofweek
    frame["day_sin"] = np.sin(2 * np.pi * day / 7)
    frame["day_cos"] = np.cos(2 * np.pi * day / 7)
    for metric, short in [("soil_moisture", "moisture"), ("temperature", "temperature"), ("air_humidity", "humidity"), ("ec", "ec"), ("ph", "ph"), ("flow_rate", "flow")]:
        frame[f"{short}_delta"] = frame.groupby("zone_code")[metric].diff().fillna(0.0)
    frame["moisture_roll_mean"] = frame.groupby("zone_code")["soil_moisture"].transform(lambda s: s.rolling(8, min_periods=1).mean())
    frame["moisture_roll_std"] = frame.groupby("zone_code")["soil_moisture"].transform(lambda s: s.rolling(8, min_periods=2).std()).fillna(0.0)
    frame["flow_roll_mean"] = frame.groupby("zone_code")["flow_rate"].transform(lambda s: s.rolling(8, min_periods=1).mean())
    frame["flow_roll_std"] = frame.groupby("zone_code")["flow_rate"].transform(lambda s: s.rolling(8, min_periods=2).std()).fillna(0.0)
    horizon_steps = max(1, round(30 / freq_minutes))
    for metric, target in [
        ("soil_moisture", "target_moisture_30m"),
        ("temperature", "target_temperature_30m"),
        ("ec", "target_ec_30m"),
        ("ph", "target_ph_30m"),
    ]:
        frame[target] = frame.groupby("zone_code")[metric].shift(-horizon_steps)
    return frame.dropna().reset_index(drop=True)


def generate_shared_training_frame(
    farm_ids: Iterable[str] | None = None,
    *,
    days: int = 14,
    freq_minutes: int = 15,
) -> pd.DataFrame:
    selected = list(farm_ids or FARM_PROFILES.keys())
    frames = [generate_training_frame(farm_id, days=days, freq_minutes=freq_minutes) for farm_id in selected]
    return pd.concat(frames, ignore_index=True).sort_values(["observed_at", "farm_id", "zone_code"]).reset_index(drop=True)


def temporal_train_validation_test_split(
    frame: pd.DataFrame,
    train_ratio: float = 0.70,
    validation_ratio: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    ordered_times = np.sort(frame["observed_at"].unique())
    if len(ordered_times) < 10:
        raise ValueError("Không đủ dữ liệu để chia train/validation/test theo thời gian.")
    train_index = max(1, int(len(ordered_times) * train_ratio))
    validation_index = max(train_index + 1, int(len(ordered_times) * (train_ratio + validation_ratio)))
    validation_index = min(validation_index, len(ordered_times) - 1)
    train_end = pd.Timestamp(ordered_times[train_index])
    validation_end = pd.Timestamp(ordered_times[validation_index])
    train = frame[frame["observed_at"] < train_end].copy()
    validation = frame[(frame["observed_at"] >= train_end) & (frame["observed_at"] < validation_end)].copy()
    test = frame[frame["observed_at"] >= validation_end].copy()
    if train.empty or validation.empty or test.empty:
        raise ValueError("Không đủ dữ liệu cho một trong ba tập train/validation/test.")
    return train, validation, test, train_end, validation_end


def _csv_evidence_directory(base: str | Path, dataset_version: str) -> Path:
    safe_version = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in dataset_version)
    path = Path(base) / safe_version
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _file_evidence(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "relative_path": str(path.relative_to(root)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _new_model(spec: ModelSpec, estimators: int, seed_offset: int = 0, algorithm: str = "random_forest") -> Any:
    """Create one candidate model. V10 compares RF and ExtraTrees on validation only."""
    seed = RANDOM_SEED + seed_offset
    if spec.task == "regression":
        if algorithm == "extra_trees":
            return ExtraTreesRegressor(
                n_estimators=estimators, max_depth=18, min_samples_leaf=2,
                max_features=0.85, random_state=seed, n_jobs=-1,
            )
        return RandomForestRegressor(
            n_estimators=estimators, max_depth=17, min_samples_leaf=2,
            max_features=0.85, random_state=seed, n_jobs=-1,
        )
    if algorithm == "extra_trees":
        return ExtraTreesClassifier(
            n_estimators=estimators, max_depth=18, min_samples_leaf=1,
            max_features=0.85, random_state=seed, class_weight="balanced", n_jobs=-1,
        )
    return RandomForestClassifier(
        n_estimators=estimators, max_depth=17, min_samples_leaf=1,
        max_features=0.85, random_state=seed, class_weight="balanced", n_jobs=-1,
    )


def _selection_score(spec: ModelSpec, metrics: dict[str, Any]) -> float:
    if spec.task == "regression":
        value = float(metrics.get("r2", -999.0))
        return value if math.isfinite(value) else -999.0
    # Macro-F1 prevents a dominant normal class from hiding rare-fault weakness.
    return float(metrics.get("f1_macro", 0.0))


def _regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    return {
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 5),
        "rmse": round(float(math.sqrt(mean_squared_error(y_true, y_pred))), 5),
        "r2": round(float(r2_score(y_true, y_pred)), 5),
    }


def _classification_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    true_values = np.asarray(y_true)
    predicted_values = np.asarray(y_pred)
    true_labels = sorted(set(true_values.tolist()))
    predicted_labels = sorted(set(predicted_values.tolist()))
    labels = sorted(set(true_labels) | set(predicted_labels))
    precisions = precision_score(true_values, predicted_values, labels=labels, average=None, zero_division=0)
    recalls = recall_score(true_values, predicted_values, labels=labels, average=None, zero_division=0)
    f1s = f1_score(true_values, predicted_values, labels=labels, average=None, zero_division=0)
    per_class = {
        str(label): {
            "precision": round(float(precisions[index]), 5),
            "recall": round(float(recalls[index]), 5),
            "f1": round(float(f1s[index]), 5),
            "support": int((true_values == label).sum()),
        }
        for index, label in enumerate(labels)
    }
    return {
        "accuracy": round(float(accuracy_score(true_values, predicted_values)), 5),
        "precision_macro": round(float(precision_score(true_values, predicted_values, average="macro", zero_division=0)), 5),
        "recall_macro": round(float(recall_score(true_values, predicted_values, average="macro", zero_division=0)), 5),
        "f1_macro": round(float(f1_score(true_values, predicted_values, average="macro", zero_division=0)), 5),
        "labels": labels,
        "true_labels": true_labels,
        "predicted_labels": predicted_labels,
        "per_class": per_class,
        "confusion_matrix": confusion_matrix(true_values, predicted_values, labels=labels).tolist(),
    }


def _metrics(spec: ModelSpec, y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    if spec.task == "regression":
        return _regression_metrics(y_true.astype(float), y_pred.astype(float))
    return _classification_metrics(y_true, y_pred)


def _plot_regression(path: Path, title: str, y_true: np.ndarray, y_pred: np.ndarray) -> None:
    n = min(260, len(y_true))
    fig, ax = plt.subplots(figsize=(10, 4.8), dpi=145)
    ax.plot(np.arange(n), y_true[:n], label="Thực tế", linewidth=1.8)
    ax.plot(np.arange(n), y_pred[:n], label="Dự đoán", linewidth=1.6, linestyle="--")
    ax.set_title(f"{title} – tập test dùng chung")
    ax.set_xlabel("Mẫu test")
    ax.set_ylabel("Giá trị")
    ax.grid(True, alpha=0.22)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, format="png", bbox_inches="tight")
    plt.close(fig)


def _plot_confusion(path: Path, title: str, cm: np.ndarray, labels: list[Any]) -> None:
    fig, ax = plt.subplots(figsize=(6.2, 5.2), dpi=145)
    image = ax.imshow(cm, interpolation="nearest", cmap="Blues")
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    ax.set_title(f"{title} – ma trận nhầm lẫn tập test")
    ax.set_xlabel("Dự đoán")
    ax.set_ylabel("Thực tế")
    ax.set_xticks(range(len(labels)), [str(x) for x in labels])
    ax.set_yticks(range(len(labels)), [str(x) for x in labels])
    threshold = cm.max() / 2 if cm.size else 0
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, int(cm[i, j]), ha="center", va="center", color="white" if cm[i, j] > threshold else "black")
    fig.tight_layout()
    fig.savefig(path, format="png", bbox_inches="tight")
    plt.close(fig)


def _plot_importance(path: Path, title: str, importances: np.ndarray) -> list[dict[str, Any]]:
    ranked = sorted(zip(FEATURES, importances), key=lambda x: x[1], reverse=True)[:14]
    names = [x[0] for x in ranked][::-1]
    values = [float(x[1]) for x in ranked][::-1]
    fig, ax = plt.subplots(figsize=(8.8, 5.8), dpi=145)
    ax.barh(names, values)
    ax.set_title(f"{title} – đặc trưng dùng chung quan trọng")
    ax.set_xlabel("Mức đóng góp")
    ax.grid(True, axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, format="png", bbox_inches="tight")
    plt.close(fig)
    return [{"feature": name, "importance": round(value, 6)} for name, value in reversed(ranked)]


def _plot_per_farm(path: Path, title: str, per_farm_metrics: dict[str, dict[str, Any]], task: str) -> None:
    labels = [FARM_PROFILES.get(farm_id, {}).get("name", farm_id) for farm_id in per_farm_metrics]
    values = [
        float(metrics["f1_macro"] if task == "classification" else max(-1.0, metrics["r2"]))
        for metrics in per_farm_metrics.values()
    ]
    fig, ax = plt.subplots(figsize=(8.8, 4.8), dpi=145)
    x = np.arange(len(labels))
    ax.bar(x, values)
    ax.set_xticks(x, labels, rotation=12, ha="right")
    ax.set_ylabel("F1 macro" if task == "classification" else "R²")
    ax.set_title(f"{title} – chất lượng theo từng vườn")
    ax.grid(True, axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, format="png", bbox_inches="tight")
    plt.close(fig)


def _score_for_report(report: dict[str, Any]) -> float:
    if report["task"] == "classification":
        return float(report["test_metrics"]["f1_macro"])
    return max(0.0, min(1.0, float(report["test_metrics"]["r2"])))


def _plot_suite_summary(path: Path, suite: dict[str, Any]) -> None:
    labels = [m["display_name"] for m in suite["models"]]
    scores = [_score_for_report(m) for m in suite["models"]]
    fig, ax = plt.subplots(figsize=(10, 6), dpi=145)
    y = np.arange(len(labels))
    ax.barh(y, scores)
    ax.set_yticks(y, labels)
    ax.set_xlim(0, 1)
    ax.set_xlabel("F1 macro (phân loại) hoặc R² chuẩn hóa (dự báo)")
    ax.set_title("Kết quả 10 họ mô hình AI dùng chung – Multi-tenant")
    ax.grid(True, axis="x", alpha=0.2)
    for idx, score in enumerate(scores):
        ax.text(min(score + 0.015, 0.96), idx, f"{score:.3f}", va="center")
    fig.tight_layout()
    fig.savefig(path, format="png", bbox_inches="tight")
    plt.close(fig)


def _farm_calibration(
    spec: ModelSpec,
    validation: pd.DataFrame,
    validation_predictions: np.ndarray,
) -> dict[str, dict[str, float]]:
    calibrations: dict[str, dict[str, float]] = {}
    if spec.task != "regression":
        return calibrations
    validation_with_prediction = validation[["farm_id", spec.target]].copy()
    validation_with_prediction["prediction"] = validation_predictions.astype(float)
    for farm_id, group in validation_with_prediction.groupby("farm_id"):
        residual = group[spec.target].astype(float) - group["prediction"].astype(float)
        bias = float(residual.mean())
        calibrations[str(farm_id)] = {
            "bias": round(bias, 6),
            "mae_before": round(float(np.abs(residual).mean()), 6),
            "sample_count": int(len(group)),
        }
    return calibrations


def _leave_one_farm_out(
    frame: pd.DataFrame,
    spec: ModelSpec,
    estimators: int,
    algorithm: str = "random_forest",
    group_column: str = "farm_id",
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    lofo_estimators = max(16, min(estimators, estimators // 3 + 8))
    group_ids = [str(x) for x in sorted(frame[group_column].dropna().unique())]
    for index, held_out in enumerate(group_ids):
        train = frame[frame[group_column].astype(str) != held_out]
        held_frame = frame[frame[group_column].astype(str) == held_out]
        ordered_times = np.sort(held_frame["observed_at"].unique())
        if train.empty or len(ordered_times) < 3:
            continue
        split_index = min(len(ordered_times) - 1, max(1, int(len(ordered_times) * 0.80)))
        split = pd.Timestamp(ordered_times[split_index])
        test = held_frame[held_frame["observed_at"] >= split]
        if test.empty:
            continue
        model = _new_model(spec, lofo_estimators, seed_offset=100 + index, algorithm=algorithm)
        model.fit(train[FEATURES].to_numpy(dtype=float), train[spec.target].to_numpy())
        pred = model.predict(test[FEATURES].to_numpy(dtype=float))
        result[held_out] = {
            "group_column": group_column,
            "group_name": FARM_PROFILES.get(held_out, {}).get("name", held_out),
            "train_groups": [group for group in group_ids if group != held_out],
            "test_count": int(len(test)),
            "metrics": _metrics(spec, test[spec.target].to_numpy(), pred),
        }
    return result


def _quality_gate(
    spec: ModelSpec,
    test_metrics: dict[str, Any],
    lofo: dict[str, dict[str, Any]],
    *,
    expected_farm_count: int,
    expected_classes: list[Any] | None = None,
    generalization_label: str = "vườn",
    minimum_generalization_groups: int = 3,
) -> dict[str, Any]:
    reasons: list[str] = []
    if expected_farm_count < minimum_generalization_groups:
        reasons.append(
            f"chỉ có {expected_farm_count} {generalization_label}; "
            f"cần ít nhất {minimum_generalization_groups} để kiểm định tổng quát hóa"
        )
    if len(lofo) < expected_farm_count:
        reasons.append(
            f"holdout theo {generalization_label} chỉ hoàn thành {len(lofo)}/{expected_farm_count} fold"
        )

    if spec.task == "regression":
        test_score = float(test_metrics.get("r2", -999))
        lofo_scores = [float(x.get("metrics", {}).get("r2", -999)) for x in lofo.values()]
        if not math.isfinite(test_score) or test_score < 0.20:
            reasons.append(f"test R² {test_score:.3f} < 0.20 hoặc không hữu hạn")
        if lofo_scores and (not all(math.isfinite(x) for x in lofo_scores) or min(lofo_scores) < 0.0):
            reasons.append(
                f"holdout {generalization_label} R² thấp nhất {min(lofo_scores):.3f} < 0 hoặc không hữu hạn"
            )
    else:
        test_score = float(test_metrics.get("f1_macro", 0))
        lofo_scores = [float(x.get("metrics", {}).get("f1_macro", 0)) for x in lofo.values()]
        if test_score < 0.65:
            reasons.append(f"test F1 {test_score:.3f} < 0.65")
        if lofo_scores and min(lofo_scores) < 0.55:
            reasons.append(f"holdout {generalization_label} F1 thấp nhất {min(lofo_scores):.3f} < 0.55")

        expected = {str(x) for x in (expected_classes or [])}
        present = {str(x) for x in test_metrics.get("true_labels", [])}
        missing = sorted(expected - present)
        if missing:
            reasons.append(f"tập test thiếu lớp thật: {', '.join(missing)}")
        for farm_id, fold in lofo.items():
            fold_present = {str(x) for x in fold.get("metrics", {}).get("true_labels", [])}
            fold_missing = sorted(expected - fold_present)
            if fold_missing:
                reasons.append(f"holdout {generalization_label} {farm_id} thiếu lớp thật: {', '.join(fold_missing)}")

        for critical_class in CRITICAL_CLASSES.get(spec.name, ()):
            key = str(critical_class)
            if key not in expected:
                reasons.append(f"dataset không có lớp rủi ro {critical_class}")
                continue
            test_recall = float(test_metrics.get("per_class", {}).get(key, {}).get("recall", 0.0))
            if test_recall < 0.50:
                reasons.append(f"recall lớp rủi ro {critical_class} trên test {test_recall:.3f} < 0.50")
            fold_recalls: list[float] = []
            for fold in lofo.values():
                per_class = fold.get("metrics", {}).get("per_class", {})
                if key in per_class:
                    fold_recalls.append(float(per_class[key].get("recall", 0.0)))
            if len(fold_recalls) < expected_farm_count:
                reasons.append(f"không đủ recall holdout {generalization_label} cho lớp rủi ro {critical_class}")
            elif min(fold_recalls) < 0.35:
                reasons.append(
                    f"recall holdout {generalization_label} thấp nhất lớp rủi ro "
                    f"{critical_class} {min(fold_recalls):.3f} < 0.35"
                )
    return {
        "passed": not reasons,
        "deployment_status": "approved" if not reasons else "experimental",
        "reasons": reasons,
        "policy": (
            f"cần >={minimum_generalization_groups} {generalization_label} và đủ holdout; "
            "regression: test R²>=0.20, min holdout R²>=0; classification: test F1>=0.65, "
            "min holdout F1>=0.55, đủ lớp test/holdout, recall lớp rủi ro test>=0.50 "
            "và min holdout>=0.35"
        ),
    }


def train_shared_suite(
    artifact_root: str | Path,
    *,
    days: int = 14,
    freq_minutes: int = 15,
    estimators: int = 90,
    run_lofo: bool = True,
    training_frame: pd.DataFrame | None = None,
    dataset_version: str | None = None,
    dataset_source: str = "explicit_required",
    dataset_metadata: dict[str, Any] | None = None,
    evidence_root: str | Path | None = None,
    published_artifact_root: str | Path | None = None,
    scope_type: str = "global",
    scope_key: str = "all_farms",
    generalization_column: str = "farm_id",
    generalization_label: str = "vườn",
    minimum_generalization_groups: int = 3,
) -> dict[str, Any]:
    """Train đúng 10 artifact dùng chung. Runtime V9 luôn truyền locked dataset frame.

    `test_fixture` chỉ dành cho unit/offline tests và không được gọi từ API production.
    """
    if training_frame is None:
        if dataset_source != "test_fixture":
            raise RuntimeError("V9 production training requires an explicit locked dataset frame; no internal synthetic fallback.")
        frame = generate_shared_training_frame(days=days, freq_minutes=freq_minutes)
    else:
        frame = training_frame.copy()
    effective_dataset_version = dataset_version or DATASET_VERSION
    train, validation, test, train_end, validation_end = temporal_train_validation_test_split(frame)
    root = Path(artifact_root) / "shared"
    publish_root = Path(published_artifact_root or artifact_root)
    root.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(root / "training_dataset.parquet", index=False, engine="pyarrow", compression="zstd")
    csv_root = _csv_evidence_directory(evidence_root or (root / "csv_evidence"), effective_dataset_version)
    identity_columns = [
        column for column in ("customer_id", "farm_id", "farm_name", "zone_id", "zone_code", "observed_at")
        if column in frame.columns
    ]
    split_frame = frame.copy()
    split_frame.insert(0, "split", np.where(
        split_frame["observed_at"] < train_end,
        "train",
        np.where(split_frame["observed_at"] < validation_end, "validation", "test"),
    ))
    _write_csv(split_frame, csv_root / "01_processed_features_targets.csv")
    _write_csv(train, csv_root / "02_train.csv")
    _write_csv(validation, csv_root / "03_validation.csv")
    _write_csv(test, csv_root / "04_test.csv")
    _write_csv(
        pd.DataFrame([
            {
                "dataset_version": effective_dataset_version,
                "dataset_source": dataset_source,
                "row_count": len(frame),
                "customer_count": int(frame["customer_id"].nunique()) if "customer_id" in frame.columns else 0,
                "farm_count": int(frame["farm_id"].nunique()),
                "zone_count": int(frame[["farm_id", "zone_code"]].drop_duplicates().shape[0]),
                "feature_count": len(FEATURES),
                "target_count": len(MODEL_SPECS),
                "train_count": len(train),
                "validation_count": len(validation),
                "test_count": len(test),
                "train_end": train_end.isoformat(),
                "validation_end": validation_end.isoformat(),
                "split_strategy": "chronological_70_15_15_on_unique_timestamps",
                "random_seed": RANDOM_SEED,
            }
        ]),
        csv_root / "00_dataset_summary.csv",
    )
    _write_csv(
        pd.DataFrame([
            {
                "feature_order": index + 1,
                "feature_name": feature,
                "feature_group": "profile" if feature in PROFILE_FEATURES else "dynamic",
                "used_for_training": True,
                "contains_customer_identity": False,
            }
            for index, feature in enumerate(FEATURES)
        ]),
        csv_root / "05_feature_catalog.csv",
    )
    _write_csv(
        pd.DataFrame([
            {
                "model_name": spec.name,
                "display_name": spec.display_name,
                "task": spec.task,
                "target": spec.target,
                "description": spec.description,
            }
            for spec in MODEL_SPECS
        ]),
        csv_root / "06_target_catalog.csv",
    )
    reports: list[dict[str, Any]] = []
    metrics_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    lofo_rows: list[dict[str, Any]] = []
    importance_rows: list[dict[str, Any]] = []
    class_rows: list[dict[str, Any]] = []
    target_summary_rows: list[dict[str, Any]] = []

    for spec_index, spec in enumerate(MODEL_SPECS):
        x_train = train[FEATURES].to_numpy(dtype=float)
        y_train = train[spec.target].to_numpy()
        x_validation = validation[FEATURES].to_numpy(dtype=float)
        y_validation = validation[spec.target].to_numpy()
        x_test = test[FEATURES].to_numpy(dtype=float)
        y_test = test[spec.target].to_numpy()

        candidate_reports: dict[str, dict[str, Any]] = {}
        best_algorithm = "random_forest"
        best_score = -999.0
        best_validation_predictions = None
        for algorithm_index, algorithm in enumerate(("random_forest", "extra_trees")):
            candidate = _new_model(spec, estimators, seed_offset=spec_index * 10 + algorithm_index, algorithm=algorithm)
            candidate.fit(x_train, y_train)
            candidate_predictions = candidate.predict(x_validation)
            candidate_metrics = _metrics(spec, y_validation, candidate_predictions)
            score = _selection_score(spec, candidate_metrics)
            candidate_reports[algorithm] = {"validation_metrics": candidate_metrics, "selection_score": round(score, 6)}
            if score > best_score:
                best_score = score
                best_algorithm = algorithm
                best_validation_predictions = candidate_predictions

        validation_predictions = np.asarray(best_validation_predictions)
        validation_metrics = candidate_reports[best_algorithm]["validation_metrics"]
        calibrations = _farm_calibration(spec, validation, validation_predictions)

        final_model = _new_model(spec, estimators, seed_offset=50 + spec_index, algorithm=best_algorithm)
        train_validation = pd.concat([train, validation], ignore_index=True)
        final_model.fit(train_validation[FEATURES].to_numpy(dtype=float), train_validation[spec.target].to_numpy())
        test_predictions = final_model.predict(x_test)
        test_metrics = _metrics(spec, y_test, test_predictions)

        per_farm_metrics: dict[str, dict[str, Any]] = {}
        for farm_id in sorted(frame["farm_id"].unique()):
            mask = test["farm_id"] == farm_id
            if mask.any():
                per_farm_metrics[str(farm_id)] = _metrics(
                    spec, test.loc[mask, spec.target].to_numpy(), test_predictions[mask.to_numpy()]
                )
        farm_count = int(frame["farm_id"].nunique())
        generalization_group_count = int(frame[generalization_column].nunique())
        lofo = _leave_one_farm_out(
            frame, spec, estimators, algorithm=best_algorithm, group_column=generalization_column
        ) if run_lofo and generalization_group_count >= minimum_generalization_groups else {}
        expected_classes = sorted(frame[spec.target].dropna().unique().tolist()) if spec.task == "classification" else None
        gate = _quality_gate(
            spec,
            test_metrics,
            lofo,
            expected_farm_count=generalization_group_count,
            expected_classes=expected_classes,
            generalization_label=generalization_label,
            minimum_generalization_groups=minimum_generalization_groups,
        )

        prediction_frame = test[identity_columns].copy()
        prediction_frame["actual"] = y_test
        prediction_frame["prediction"] = test_predictions
        if spec.task == "regression":
            prediction_frame["absolute_error"] = np.abs(y_test.astype(float) - test_predictions.astype(float))
            prediction_frame["squared_error"] = np.square(y_test.astype(float) - test_predictions.astype(float))
        else:
            prediction_frame["correct"] = y_test == test_predictions
        prediction_path = csv_root / "predictions" / f"{spec.name}.csv"
        _write_csv(prediction_frame, prediction_path)

        for algorithm, candidate_report in candidate_reports.items():
            validation_result = candidate_report["validation_metrics"]
            candidate_rows.append({
                "model_name": spec.name,
                "task": spec.task,
                "algorithm": algorithm,
                "selected": algorithm == best_algorithm,
                "selection_metric": "r2" if spec.task == "regression" else "f1_macro",
                "selection_score": candidate_report["selection_score"],
                "validation_metrics_json": json.dumps(validation_result, ensure_ascii=False),
            })

        for split_name, split_data in (("train", train), ("validation", validation), ("test", test)):
            target_values = split_data[spec.target]
            if spec.task == "classification":
                for label, count in target_values.value_counts(dropna=False).sort_index().items():
                    class_rows.append({
                        "model_name": spec.name,
                        "target": spec.target,
                        "split": split_name,
                        "class_label": label,
                        "sample_count": int(count),
                        "ratio": round(float(count) / max(len(target_values), 1), 6),
                    })
            else:
                numeric = pd.to_numeric(target_values, errors="coerce").dropna()
                target_summary_rows.append({
                    "model_name": spec.name,
                    "target": spec.target,
                    "split": split_name,
                    "sample_count": int(len(numeric)),
                    "minimum": float(numeric.min()),
                    "maximum": float(numeric.max()),
                    "mean": float(numeric.mean()),
                    "standard_deviation": float(numeric.std(ddof=0)),
                })

        for held_out_farm, fold in lofo.items():
            fold_metrics = fold.get("metrics", {})
            lofo_rows.append({
                "model_name": spec.name,
                "task": spec.task,
                "held_out_farm_id": held_out_farm,
                "held_out_farm_name": fold.get("group_name", held_out_farm),
                "group_column": fold.get("group_column", generalization_column),
                "test_count": fold.get("test_count", 0),
                "mae": fold_metrics.get("mae"),
                "rmse": fold_metrics.get("rmse"),
                "r2": fold_metrics.get("r2"),
                "accuracy": fold_metrics.get("accuracy"),
                "f1_macro": fold_metrics.get("f1_macro"),
                "recall_macro": fold_metrics.get("recall_macro"),
                "metrics_json": json.dumps(fold_metrics, ensure_ascii=False),
            })

        metrics_rows.append({
            "model_name": spec.name,
            "display_name": spec.display_name,
            "task": spec.task,
            "target": spec.target,
            "algorithm": best_algorithm,
            "train_count": len(train),
            "validation_count": len(validation),
            "test_count": len(test),
            "mae": test_metrics.get("mae"),
            "rmse": test_metrics.get("rmse"),
            "r2": test_metrics.get("r2"),
            "accuracy": test_metrics.get("accuracy"),
            "precision_macro": test_metrics.get("precision_macro"),
            "recall_macro": test_metrics.get("recall_macro"),
            "f1_macro": test_metrics.get("f1_macro"),
            "deployment_status": gate["deployment_status"],
            "quality_gate_passed": gate["passed"],
            "quality_gate_reasons": " | ".join(gate["reasons"]),
            "prediction_csv": str(prediction_path),
        })

        model_dir = root / spec.name / f"v{MODEL_VERSION}"
        model_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = model_dir / "model.joblib"
        bundle = {
            "model": final_model,
            "features": FEATURES,
            "feature_medians": {
                name: float(train_validation[name].median()) for name in FEATURES
            },
            "spec": asdict(spec),
            "dataset_version": effective_dataset_version,
            "model_version": MODEL_VERSION,
            "scope_type": scope_type,
            "scope_key": scope_key,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "train_end": train_end.isoformat(),
            "validation_end": validation_end.isoformat(),
            "profile_encodings": {
                "crop": CROP_CODES,
                "cultivation": CULTIVATION_CODES,
                "climate": CLIMATE_CODES,
                "soil": SOIL_CODES,
            },
            "farm_calibrations": calibrations,
            "deployment_status": gate["deployment_status"],
            "quality_gate": gate,
            "algorithm": best_algorithm,
            "candidate_validation": candidate_reports,
            "dataset_source": dataset_source,
        }
        joblib.dump(bundle, artifact_path)

        evaluation_chart = model_dir / "evaluation.png"
        if spec.task == "regression":
            _plot_regression(evaluation_chart, spec.display_name, y_test.astype(float), test_predictions.astype(float))
        else:
            _plot_confusion(
                evaluation_chart,
                spec.display_name,
                np.asarray(test_metrics["confusion_matrix"]),
                test_metrics["labels"],
            )
        importance_chart = model_dir / "feature_importance.png"
        importance = _plot_importance(importance_chart, spec.display_name, final_model.feature_importances_)
        for rank, item in enumerate(importance, 1):
            importance_rows.append({
                "model_name": spec.name,
                "rank": rank,
                "feature": item["feature"],
                "importance": item["importance"],
            })
        per_farm_chart = model_dir / "per_farm_evaluation.png"
        _plot_per_farm(per_farm_chart, spec.display_name, per_farm_metrics, spec.task)
        report = {
            "model_id": f"{scope_type}_{scope_key}_{spec.name}_v{MODEL_VERSION}",
            "model_name": spec.name,
            "display_name": spec.display_name,
            "task": spec.task,
            "target": spec.target,
            "description": spec.description,
            "scope_type": scope_type,
            "scope_key": scope_key,
            "model_version": MODEL_VERSION,
            "algorithm": best_algorithm,
            "candidate_validation": candidate_reports,
            "dataset_version": effective_dataset_version,
            "farm_count": int(frame["farm_id"].nunique()),
            "train_count": int(len(train)),
            "validation_count": int(len(validation)),
            "test_count": int(len(test)),
            "split_strategy": "chronological_70_15_15",
            "train_end": train_end.isoformat(),
            "validation_end": validation_end.isoformat(),
            "validation_metrics": validation_metrics,
            "test_metrics": test_metrics,
            # Giữ alias metrics cho frontend/code cũ.
            "metrics": test_metrics,
            "per_farm_metrics": per_farm_metrics,
            "leave_one_farm_out": lofo,
            "generalization_holdout": lofo,
            "generalization_column": generalization_column,
            "farm_calibrations": calibrations,
            "feature_importance": importance,
            "artifact_path": str(artifact_path),
            "evaluation_chart": str(evaluation_chart),
            "importance_chart": str(importance_chart),
            "per_farm_chart": str(per_farm_chart),
            "prediction_csv": str(prediction_path),
            "status": gate["deployment_status"],
            "deployment_status": gate["deployment_status"],
            "quality_gate": gate,
            "dataset_source": dataset_source,
        }
        (model_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        reports.append(report)

    _write_csv(pd.DataFrame(metrics_rows), csv_root / "07_model_metrics.csv")
    _write_csv(pd.DataFrame(candidate_rows), csv_root / "08_candidate_validation.csv")
    _write_csv(pd.DataFrame(lofo_rows), csv_root / "09_generalization_holdout.csv")
    _write_csv(pd.DataFrame(class_rows), csv_root / "10_class_distribution.csv")
    _write_csv(pd.DataFrame(target_summary_rows), csv_root / "11_regression_target_summary.csv")
    _write_csv(pd.DataFrame(importance_rows), csv_root / "12_feature_importance.csv")
    _write_csv(
        pd.DataFrame([
            {
                "model_id": item["model_id"],
                "model_name": item["model_name"],
                "display_name": item["display_name"],
                "task": item["task"],
                "target": item["target"],
                "algorithm": item["algorithm"],
                "model_version": item["model_version"],
                "dataset_version": item["dataset_version"],
                "deployment_status": item["deployment_status"],
                "quality_gate_passed": item["quality_gate"]["passed"],
                "artifact_path": str(publish_root / "shared" / item["model_name"] / f"v{item['model_version']}" / "model.joblib"),
                "report_path": str(publish_root / "shared" / item["model_name"] / f"v{item['model_version']}" / "report.json"),
                "prediction_csv": item["prediction_csv"],
            }
            for item in reports
        ]),
        csv_root / "13_model_inventory.csv",
    )
    provenance_rows: list[dict[str, Any]] = []
    for origin, values in (dataset_metadata or {}).get("origin_mix", {}).items():
        provenance_rows.append({
            "dataset_version": effective_dataset_version,
            "dataset_source": dataset_source,
            "origin": origin,
            "row_count": values.get("count") if isinstance(values, dict) else None,
            "ratio": values.get("ratio") if isinstance(values, dict) else None,
            "raw_reading_count": (dataset_metadata or {}).get("raw_reading_count"),
            "source_tables": " | ".join((dataset_metadata or {}).get("source_tables", [])),
            "label_method": (dataset_metadata or {}).get("label_method"),
            "runtime_snapshot_id": (dataset_metadata or {}).get("runtime_snapshot_id"),
        })
    _write_csv(pd.DataFrame(provenance_rows), csv_root / "14_data_provenance.csv")

    csv_files = sorted(csv_root.rglob("*.csv"))
    csv_manifest = {
        "dataset_version": effective_dataset_version,
        "dataset_source": dataset_source,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "identity_columns": identity_columns,
        "customer_identity_is_feature": False,
        "scope_type": scope_type,
        "scope_key": scope_key,
        "chat_messages_used_for_training": False,
        "split_strategy": "chronological_70_15_15_on_unique_timestamps",
        "random_seed": RANDOM_SEED,
        "files": [_file_evidence(path, csv_root) for path in csv_files],
    }
    csv_manifest_path = csv_root / "evidence_manifest.json"
    csv_manifest_path.write_text(json.dumps(csv_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    suite = {
        "architecture": "per_customer_models" if scope_type == "customer" else "multi_tenant_shared_models",
        "scope_type": scope_type,
        "scope_key": scope_key,
        "model_version": MODEL_VERSION,
        "dataset_version": effective_dataset_version,
        "dataset_source": dataset_source,
        "dataset_metadata": dataset_metadata or {},
        "farm_count": int(frame["farm_id"].nunique()),
        "farm_ids": sorted(frame["farm_id"].unique().tolist()),
        "generated_rows": int(len(frame)),
        "train_count": int(len(train)),
        "validation_count": int(len(validation)),
        "test_count": int(len(test)),
        "model_count": len(reports),
        "approved_model_count": sum(1 for item in reports if item["deployment_status"] == "approved"),
        "experimental_model_count": sum(1 for item in reports if item["deployment_status"] != "approved"),
        "total_model_artifacts": len(reports),
        "split_strategy": "chronological_70_15_15",
        "generalization_test": f"leave_one_{generalization_column}_out",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "models": reports,
        "csv_evidence": {
            "directory": str(csv_root),
            "manifest": str(csv_manifest_path),
            "file_count": len(csv_files),
            "chat_messages_used_for_training": False,
        },
    }
    (root / "suite_report.json").write_text(json.dumps(suite, ensure_ascii=False, indent=2), encoding="utf-8")
    (Path(artifact_root) / "shared_models_report.json").write_text(json.dumps(suite, ensure_ascii=False, indent=2), encoding="utf-8")
    _plot_suite_summary(root / "suite_summary.png", suite)
    return suite


def load_shared_suite_report(artifact_root: str | Path) -> dict[str, Any] | None:
    root = Path(artifact_root) / "shared"
    for path in (root / "latest_training_report.json", root / "suite_report.json"):
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def load_shared_model_report(artifact_root: str | Path, model_name: str) -> dict[str, Any] | None:
    suite = load_shared_suite_report(artifact_root)
    if not suite:
        return None
    return next(
        (item for item in suite.get("models", []) if item.get("model_name") == model_name),
        None,
    )


def shared_model_path(artifact_root: str | Path, model_name: str) -> Path:
    manifest_path = Path(artifact_root) / "shared" / "active_models.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        item = (manifest.get("models") or {}).get(model_name) or {}
        artifact_path = item.get("artifact_path")
        if artifact_path:
            return Path(artifact_path)
    # Chỉ để đọc artifact v10 cũ trong quá trình chuyển đổi kiến trúc.
    return Path(artifact_root) / "shared" / model_name / f"v{MODEL_VERSION}" / "model.joblib"


def farm_view_report(artifact_root: str | Path, farm_id: str) -> dict[str, Any] | None:
    """Dashboard theo farm nhưng đọc cùng 10 artifact; không tạo thư mục/model riêng."""
    suite = load_shared_suite_report(artifact_root)
    if not suite:
        return None
    models: list[dict[str, Any]] = []
    for model in suite["models"]:
        item = dict(model)
        farm_metrics = model.get("per_farm_metrics", {}).get(farm_id, model.get("test_metrics", {}))
        item["metrics"] = farm_metrics
        item["farm_metrics"] = farm_metrics
        item["calibration"] = model.get("farm_calibrations", {}).get(farm_id)
        models.append(item)
    return {
        "architecture": "multi_tenant_shared_models",
        "farm_id": farm_id,
        "farm_name": FARM_PROFILES.get(farm_id, {}).get("name", farm_id),
        "profile": FARM_PROFILES.get(farm_id, {"name": farm_id}),
        "model_count": suite["model_count"],
        "shared_artifact_count": suite["total_model_artifacts"],
        "train_count": suite["train_count"],
        "validation_count": suite["validation_count"],
        "test_count": suite["test_count"],
        "split_strategy": suite["split_strategy"],
        "generalization_test": suite["generalization_test"],
        "models": models,
        "note": "Farm này dùng 10 model dùng chung; chỉ profile, feature snapshot và calibration được cá nhân hóa.",
    }


# Alias giữ tương thích với một số script cũ, nhưng không còn train theo từng farm.
def train_all_farms(artifact_root: str | Path, **kwargs: Any) -> dict[str, Any]:
    return train_shared_suite(artifact_root, **kwargs)
