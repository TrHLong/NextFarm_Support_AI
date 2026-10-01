"""Production-safe training pipeline for NextFarm.

Principles:
- Real, traceable telemetry only for production candidates.
- Audit/clean/readiness happens before training.
- Time-series split is chronological and horizon-purged.
- Train-only preprocessing prevents leakage.
- Test is evaluated once after validation model selection.
- Synthetic/simulation/pipeline-test data can exercise the pipeline but can never
  create a production candidate.
- Every run is immutable and produces machine-readable evidence plus REPORT.docx.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import os
import re

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score, median_absolute_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

REAL_ORIGINS = {"real_device", "field_device", "verified_import"}
NON_PRODUCTION_ORIGINS = {"synthetic", "simulation", "pipeline_test", "demo", "generated"}

BOUNDS = {
    "soil_moisture": (0.0, 100.0), "temperature": (-40.0, 85.0),
    "air_humidity": (0.0, 100.0), "ph": (0.0, 14.0), "ec": (0.0, 30.0),
    "flow_rate": (0.0, 10000.0), "pressure": (0.0, 100.0),
    "supply_voltage": (0.0, 1000.0), "rssi": (-150.0, 20.0),
    "packet_loss_rate": (0.0, 1.0), "command_failure_rate": (0.0, 1.0),
}

PRODUCTION_REQUIRED_COLUMNS = {
    "customer_id", "farm_id", "zone_id", "device_id", "observed_at",
    "metric_type", "value", "data_origin"
}

HORIZONS_MINUTES = (60, 180, 360, 720)

@dataclass(frozen=True)
class ReadinessPolicy:
    min_history_days: float = 30.0
    recommended_history_days: float = 60.0
    min_real_rows: int = 10000
    max_duplicate_fraction: float = 0.01
    max_invalid_fraction: float = 0.03
    min_moisture_coverage: float = 0.90
    min_timestamp_validity: float = 0.99
    min_irrigation_events: int = 100
    min_before_after_irrigation_events: int = 80
    horizon_coverage_60: float = 0.90
    horizon_coverage_180: float = 0.85
    horizon_coverage_360: float = 0.80
    horizon_coverage_720: float = 0.70
    min_train_rows: int = 1000
    min_validation_rows: int = 200
    min_test_rows: int = 200
    min_baseline_mae_gain: float = 0.05

POLICY = ReadinessPolicy()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")
    os.replace(tmp, path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:120]


def _find_table(dataset: Path, names: list[str]) -> Path | None:
    for name in names:
        for ext in (".parquet", ".csv", ".jsonl", ".json"):
            p = dataset / f"{name}{ext}"
            if p.exists():
                return p
    return None


def _read_table(path: Path | None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame()
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix == ".csv":
        return pd.read_csv(path)
    if path.suffix == ".jsonl":
        return pd.read_json(path, lines=True)
    if path.suffix == ".json":
        obj = json.loads(path.read_text(encoding="utf-8"))
        return pd.DataFrame(obj if isinstance(obj, list) else obj.get("rows", []))
    raise ValueError(f"Unsupported file: {path}")


def load_dataset(dataset: str | Path) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, str]]:
    dataset = Path(dataset).resolve()
    sensor_path = _find_table(dataset, ["sensor_readings", "sensor_reading", "sensors"])
    if sensor_path is None:
        raise FileNotFoundError("Không tìm thấy sensor_readings.(parquet/csv/jsonl) trong dataset")
    sensor = _read_table(sensor_path)
    # Existing NextFarm demo/canonical datasets may not carry row-level origin.
    # Infer only NON-production provenance from an explicit manifest; never infer real data.
    manifest_path = dataset / "manifest.json"
    if "data_origin" not in sensor.columns:
        inferred = "unknown"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                status = str(manifest.get("dataset_status", "")).lower()
                source = str(manifest.get("source", "")).lower()
                if "pipeline_test" in status or "test_only" in status:
                    inferred = "pipeline_test"
                elif "synthetic" in source or manifest.get("synthetic") is True:
                    inferred = "synthetic"
            except Exception:
                pass
        sensor["data_origin"] = inferred
    extras = {}
    sources = {"sensor_readings": str(sensor_path)}
    aliases = {
        "irrigation_events": ["irrigation_events", "irrigation_event", "irrigation_runs"],
        "fertilizer_events": ["fertilizer_events", "fertilizer_event"],
        "alerts": ["alerts", "alert"],
        "command_logs": ["command_logs", "command_log", "control_commands"],
        "device_status": ["device_status", "device_state"],
    }
    for key, names in aliases.items():
        p = _find_table(dataset, names)
        extras[key] = _read_table(p)
        if p is not None:
            sources[key] = str(p)
    return sensor, extras, sources


def _normalize_sensor_schema(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    # Support the current canonical wide telemetry format while normalizing into
    # the production long schema. This is schema adaptation only, not provenance promotion.
    wide_map = {
        "soil_moisture_pct":"soil_moisture", "air_temperature_c":"temperature",
        "air_humidity_pct":"air_humidity", "ec":"ec", "ph":"ph",
        "flow_rate_lpm":"flow_rate", "pressure_bar":"pressure",
        "supply_voltage_v":"supply_voltage", "rssi_dbm":"rssi"
    }
    wide_cols = [c for c in wide_map if c in df.columns]
    if wide_cols and "metric_type" not in df.columns:
        ids = [c for c in ["customer_id","farmer_id","farm_id","zone_id","device_id","sensor_id","timestamp","observed_at","received_at","quality","data_origin"] if c in df.columns]
        long = df.melt(id_vars=ids, value_vars=wide_cols, var_name="_wide_metric", value_name="value")
        long["metric_type"] = long["_wide_metric"].map(wide_map)
        long.drop(columns=["_wide_metric"], inplace=True)
        df = long
    rename = {}
    if "timestamp" in df and "observed_at" not in df: rename["timestamp"] = "observed_at"
    if "metric" in df and "metric_type" not in df: rename["metric"] = "metric_type"
    if "origin" in df and "data_origin" not in df: rename["origin"] = "data_origin"
    if "farmer_id" in df and "customer_id" not in df: rename["farmer_id"] = "customer_id"
    df.rename(columns=rename, inplace=True)
    missing = sorted(PRODUCTION_REQUIRED_COLUMNS - set(df.columns))
    if missing:
        raise ValueError("Thiếu cột bắt buộc: " + ", ".join(missing))
    if "sensor_id" not in df: df["sensor_id"] = df["device_id"].astype(str) + ":" + df["metric_type"].astype(str)
    if "quality" not in df: df["quality"] = "unknown"
    if "reading_id" not in df: df["reading_id"] = np.arange(len(df)).astype(str)
    df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True, errors="coerce")
    if "received_at" in df:
        df["received_at"] = pd.to_datetime(df["received_at"], utc=True, errors="coerce")
    else:
        df["received_at"] = df["observed_at"]
    df["metric_type"] = df["metric_type"].astype(str).str.strip().str.lower()
    df["data_origin"] = df["data_origin"].astype(str).str.strip().str.lower()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df


def audit_and_clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    df = _normalize_sensor_schema(raw)
    input_rows = len(df)
    valid_ts = df["observed_at"].notna()
    duplicate_mask = df.duplicated(subset=["customer_id", "farm_id", "zone_id", "device_id", "sensor_id", "metric_type", "observed_at"], keep="last")
    numeric_ok = np.isfinite(df["value"])
    range_ok = pd.Series(True, index=df.index)
    unknown_metric = ~df["metric_type"].isin(BOUNDS)
    for metric, (lo, hi) in BOUNDS.items():
        m = df["metric_type"].eq(metric)
        range_ok.loc[m] = df.loc[m, "value"].between(lo, hi)
    quality_bad = df["quality"].astype(str).str.lower().isin({"bad", "invalid", "error"})
    invalid = (~valid_ts) | (~numeric_ok) | (~range_ok) | quality_bad

    # Do not remove valid-but-unusual values inside physical bounds: those may be incidents.
    clean = df.loc[~invalid & ~duplicate_mask].copy()
    clean.sort_values(["customer_id", "farm_id", "zone_id", "device_id", "metric_type", "observed_at"], inplace=True)

    origins = df["data_origin"].value_counts(dropna=False).to_dict()
    audit = {
        "input_rows": input_rows,
        "output_rows": len(clean),
        "timestamp_validity": float(valid_ts.mean()) if input_rows else 0.0,
        "duplicate_rows": int(duplicate_mask.sum()),
        "duplicate_fraction": float(duplicate_mask.mean()) if input_rows else 0.0,
        "invalid_rows": int(invalid.sum()),
        "invalid_fraction": float(invalid.mean()) if input_rows else 0.0,
        "unknown_metric_rows": int(unknown_metric.sum()),
        "origins": {str(k): int(v) for k, v in origins.items()},
        "real_rows": int(df["data_origin"].isin(REAL_ORIGINS).sum()),
        "non_production_rows": int(df["data_origin"].isin(NON_PRODUCTION_ORIGINS).sum()),
        "policy": "Physical-invalid/bad-quality rows removed; valid anomalies retained; no mean-fill performed; raw source is immutable.",
    }
    return clean, audit


def _series_key_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in ["customer_id", "farm_id", "zone_id", "device_id", "sensor_id"] if c in df.columns]


def build_moisture_features(clean: pd.DataFrame) -> pd.DataFrame:
    real = clean.loc[clean["data_origin"].isin(REAL_ORIGINS)].copy()
    moisture = real.loc[real["metric_type"].eq("soil_moisture")].copy()
    keys = _series_key_columns(moisture)
    if moisture.empty:
        return moisture
    # 10-minute causal grid. Gaps remain NaN; short gaps are not silently converted to observations.
    frames = []
    for keyvals, part in moisture.groupby(keys, sort=False):
        part = part.sort_values("observed_at").set_index("observed_at")
        grid = pd.date_range(part.index.min().floor("10min"), part.index.max().ceil("10min"), freq="10min", tz="UTC")
        base = part["value"].resample("10min").last().reindex(grid).rename("soil_moisture").to_frame()
        base.index.name = "observed_at"
        if not isinstance(keyvals, tuple): keyvals = (keyvals,)
        for k, v in zip(keys, keyvals): base[k] = v
        base["observed_present"] = base["soil_moisture"].notna().astype(int)
        for lag_m in (10, 30, 60, 180):
            steps = lag_m // 10
            base[f"moisture_lag_{lag_m}m"] = base["soil_moisture"].shift(steps)
        base["moisture_mean_30m"] = base["soil_moisture"].rolling(3, min_periods=1).mean()
        base["moisture_mean_1h"] = base["soil_moisture"].rolling(6, min_periods=1).mean()
        base["moisture_std_1h"] = base["soil_moisture"].rolling(6, min_periods=2).std()
        base["moisture_slope_30m"] = (base["soil_moisture"] - base["soil_moisture"].shift(3)) / 30.0
        base["moisture_slope_1h"] = (base["soil_moisture"] - base["soil_moisture"].shift(6)) / 60.0
        base["missing_ratio_1h"] = 1.0 - base["observed_present"].rolling(6, min_periods=1).mean()
        frames.append(base.reset_index())
    f = pd.concat(frames, ignore_index=True)

    # Add exogenous sensor values causally using last-known <= timestamp per device/zone.
    exogenous = ["temperature", "air_humidity", "ec", "ph", "flow_rate", "pressure", "supply_voltage", "rssi", "packet_loss_rate", "command_failure_rate"]
    merge_keys = [c for c in ["customer_id", "farm_id", "zone_id", "device_id"] if c in f.columns]
    for metric in exogenous:
        src = real.loc[real["metric_type"].eq(metric), merge_keys + ["observed_at", "value"]].copy()
        if src.empty:
            f[metric] = np.nan
            continue
        src.rename(columns={"value": metric}, inplace=True)
        src.sort_values(merge_keys + ["observed_at"], inplace=True)
        pieces = []
        for gvals, left in f.groupby(merge_keys, sort=False):
            if not isinstance(gvals, tuple): gvals = (gvals,)
            right = src
            for c, v in zip(merge_keys, gvals): right = right.loc[right[c].eq(v)]
            left = left.sort_values("observed_at")
            if right.empty:
                left[metric] = np.nan
            else:
                left = pd.merge_asof(left, right[["observed_at", metric]].sort_values("observed_at"), on="observed_at", direction="backward", tolerance=pd.Timedelta(minutes=30))
            pieces.append(left)
        f = pd.concat(pieces, ignore_index=True)

    t = pd.to_datetime(f["observed_at"], utc=True)
    f["hour_sin"] = np.sin(2*np.pi*t.dt.hour/24.0)
    f["hour_cos"] = np.cos(2*np.pi*t.dt.hour/24.0)
    f["day_sin"] = np.sin(2*np.pi*t.dt.dayofyear/365.25)
    f["day_cos"] = np.cos(2*np.pi*t.dt.dayofyear/365.25)

    keys = _series_key_columns(f)
    for horizon in HORIZONS_MINUTES:
        steps = horizon // 10
        f[f"target_{horizon}m"] = f.groupby(keys, sort=False)["soil_moisture"].shift(-steps)
        f[f"label_end_{horizon}m"] = f["observed_at"] + pd.Timedelta(minutes=horizon)
    return f.sort_values(keys + ["observed_at"]).reset_index(drop=True)


def _irrigation_event_stats(events: pd.DataFrame) -> tuple[int, int]:
    if events.empty:
        return 0, 0
    count = len(events)
    cols = set(events.columns)
    before_after_pairs = [
        ("soil_moisture_before", "soil_moisture_after"),
        ("moisture_before", "moisture_after"),
    ]
    for a, b in before_after_pairs:
        if a in cols and b in cols:
            return count, int(events[[a,b]].notna().all(axis=1).sum())
    return count, 0


def readiness(clean: pd.DataFrame, features: pd.DataFrame, extras: dict[str, pd.DataFrame], audit: dict[str, Any], policy: ReadinessPolicy = POLICY) -> dict[str, Any]:
    real = clean.loc[clean["data_origin"].isin(REAL_ORIGINS)]
    moisture = real.loc[real["metric_type"].eq("soil_moisture")]
    if len(real):
        lo, hi = real["observed_at"].min(), real["observed_at"].max()
        history_days = float((hi-lo).total_seconds()/86400) if pd.notna(lo) and pd.notna(hi) else 0.0
    else: history_days = 0.0
    moisture_coverage = float(features["observed_present"].mean()) if len(features) and "observed_present" in features else 0.0
    irrigation_count, paired_count = _irrigation_event_stats(extras.get("irrigation_events", pd.DataFrame()))
    horizon_req = {60:policy.horizon_coverage_60, 180:policy.horizon_coverage_180, 360:policy.horizon_coverage_360, 720:policy.horizon_coverage_720}
    hcov = {}
    allowed = []
    for h in HORIZONS_MINUTES:
        col = f"target_{h}m"
        denominator = int(features["soil_moisture"].notna().sum()) if len(features) else 0
        cov = float(features[col].notna().sum()/denominator) if denominator else 0.0
        hcov[str(h)] = {"coverage": cov, "required": horizon_req[h], "pass": cov >= horizon_req[h]}
        if cov >= horizon_req[h]: allowed.append(h)
    checks = {
        "production_origin_only_available": {"value": int(len(real)), "required": policy.min_real_rows, "pass": len(real) >= policy.min_real_rows},
        "history_days": {"value": history_days, "required": policy.min_history_days, "pass": history_days >= policy.min_history_days},
        "timestamp_validity": {"value": audit["timestamp_validity"], "required": policy.min_timestamp_validity, "pass": audit["timestamp_validity"] >= policy.min_timestamp_validity},
        "duplicate_fraction": {"value": audit["duplicate_fraction"], "required_max": policy.max_duplicate_fraction, "pass": audit["duplicate_fraction"] <= policy.max_duplicate_fraction},
        "invalid_fraction": {"value": audit["invalid_fraction"], "required_max": policy.max_invalid_fraction, "pass": audit["invalid_fraction"] <= policy.max_invalid_fraction},
        "moisture_coverage": {"value": moisture_coverage, "required": policy.min_moisture_coverage, "pass": moisture_coverage >= policy.min_moisture_coverage},
        "irrigation_events": {"value": irrigation_count, "required": policy.min_irrigation_events, "pass": irrigation_count >= policy.min_irrigation_events},
        "irrigation_before_after_events": {"value": paired_count, "required": policy.min_before_after_irrigation_events, "pass": paired_count >= policy.min_before_after_irrigation_events},
    }
    # Soil forecast can be trained without event labels; event checks are advisory for later irrigation optimizer.
    forecast_required = ["production_origin_only_available", "history_days", "timestamp_validity", "duplicate_fraction", "invalid_fraction", "moisture_coverage"]
    forecast_pass = all(checks[k]["pass"] for k in forecast_required) and bool(allowed)

    # Readiness for all five product models. Only model 1 has a trainer in this production-safe release.
    model_status = {
        "soil_moisture_forecast": {"status": "READY_FOR_TRAIN" if forecast_pass else "NOT_READY", "trainable_horizons_minutes": allowed},
        "nutrient_recommendation": {"status": "NOT_READY", "reason": "Thiếu nhãn chuyên gia/outcome đã xác minh cho recommended_fertilizer_ml hoặc increase/keep/decrease."},
        "leak_valve_anomaly": {"status": "RULE_READY_ML_NOT_READY", "reason": "Rule vật lý có thể chạy; ML production cần incident ground truth thật, độc lập theo episode/device/farm."},
        "smart_irrigation_scheduling": {"status": "NOT_READY" if not (checks["irrigation_events"]["pass"] and checks["irrigation_before_after_events"]["pass"]) else "DATA_BASE_READY", "reason": "Ưu tiên forecast + optimization trước RL; cần đủ ca tưới before/after thật."},
        "predictive_maintenance": {"status": "NOT_READY", "reason": "Cần failure episodes thật và telemetry thiết bị như RSSI/voltage/packet loss/command latency."},
    }
    return {
        "status": "PASS" if forecast_pass else "FAIL",
        "policy": asdict(policy), "checks": checks, "horizon_coverage": hcov,
        "model_status": model_status,
        "real_metric_rows": {str(k):int(v) for k,v in real["metric_type"].value_counts().to_dict().items()},
        "real_customers": int(real["customer_id"].nunique()) if len(real) else 0,
        "real_farms": int(real["farm_id"].nunique()) if len(real) else 0,
        "real_zones": int(real["zone_id"].nunique()) if len(real) else 0,
        "real_devices": int(real["device_id"].nunique()) if len(real) else 0,
        "history_days": history_days,
    }


def _feature_columns(frame: pd.DataFrame) -> list[str]:
    wanted = [
        "soil_moisture", "moisture_lag_10m", "moisture_lag_30m", "moisture_lag_60m", "moisture_lag_180m",
        "moisture_mean_30m", "moisture_mean_1h", "moisture_std_1h", "moisture_slope_30m", "moisture_slope_1h",
        "missing_ratio_1h", "temperature", "air_humidity", "ec", "ph", "flow_rate", "pressure",
        "supply_voltage", "rssi", "packet_loss_rate", "command_failure_rate", "hour_sin", "hour_cos", "day_sin", "day_cos"
    ]
    return [c for c in wanted if c in frame.columns]


def _chronological_split(frame: pd.DataFrame, horizon: int) -> tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame,dict[str,Any]]:
    target = f"target_{horizon}m"
    label_end = f"label_end_{horizon}m"
    x = frame.dropna(subset=["soil_moisture", target]).copy().sort_values("observed_at")
    if x.empty: return x,x,x,{"status":"FAIL","reason":"No labeled rows"}
    t0, t1 = x["observed_at"].min(), x["observed_at"].max()
    span = t1-t0
    cut1 = t0 + span*0.70
    cut2 = t0 + span*0.85
    # Strict purge: labels from train/validation may not cross the next split boundary.
    tr = x.loc[x[label_end] < cut1]
    va = x.loc[(x["observed_at"] >= cut1) & (x[label_end] < cut2)]
    te = x.loc[x["observed_at"] >= cut2]
    manifest = {"strategy":"chronological_70_15_15_horizon_purged", "start":t0, "train_boundary":cut1, "validation_boundary":cut2, "end":t1,
                "horizon_minutes":horizon, "rows":{"train":len(tr),"validation":len(va),"test":len(te)}}
    return tr,va,te,manifest


def _reg_metrics(y: np.ndarray, pred: np.ndarray) -> dict[str,float]:
    err = np.abs(y-pred)
    denom = np.maximum(np.abs(y)+np.abs(pred), 1e-9)
    return {
        "mae":float(mean_absolute_error(y,pred)), "rmse":float(mean_squared_error(y,pred)**0.5), "r2":float(r2_score(y,pred)),
        "median_absolute_error":float(median_absolute_error(y,pred)), "p90_absolute_error":float(np.quantile(err,0.90)),
        "smape":float(np.mean(2.0*err/denom)*100.0),
    }


def train_moisture(frame: pd.DataFrame, horizons: list[int], out: Path, policy: ReadinessPolicy = POLICY) -> list[dict[str,Any]]:
    results=[]; feature_cols=_feature_columns(frame)
    for horizon in horizons:
        tr,va,te,split=_chronological_split(frame,horizon)
        target=f"target_{horizon}m"
        record={"model":"soil_moisture_forecast","horizon_minutes":horizon,"split":split,"features":feature_cols,"status":"BLOCKED"}
        if len(tr)<policy.min_train_rows or len(va)<policy.min_validation_rows or len(te)<policy.min_test_rows:
            record["gate_reasons"]=[f"Insufficient split rows: train={len(tr)}, validation={len(va)}, test={len(te)}"]
            results.append(record);continue
        candidates={
            "ridge":make_pipeline(SimpleImputer(add_indicator=True),StandardScaler(),Ridge(alpha=10.0)),
            "random_forest":make_pipeline(SimpleImputer(add_indicator=True),RandomForestRegressor(n_estimators=180,min_samples_leaf=4,n_jobs=-1,random_state=20260928)),
            "extra_trees":make_pipeline(SimpleImputer(add_indicator=True),ExtraTreesRegressor(n_estimators=180,min_samples_leaf=4,n_jobs=-1,random_state=20260928)),
            "hist_gradient_boosting":make_pipeline(SimpleImputer(add_indicator=True),HistGradientBoostingRegressor(max_iter=220,max_leaf_nodes=31,l2_regularization=1.0,random_state=20260928)),
        }
        evals={};fitted={}
        ytr=tr[target].to_numpy(); yva=va[target].to_numpy()
        for name,model in candidates.items():
            model.fit(tr[feature_cols],ytr)
            p=model.predict(va[feature_cols]);evals[name]=_reg_metrics(yva,p);fitted[name]=model
        selected=min(evals,key=lambda k:evals[k]["mae"]);model=fitted[selected]
        # Test exactly once after selection; no refit using validation or test.
        pred=model.predict(te[feature_cols]); y=te[target].to_numpy()
        test_metrics=_reg_metrics(y,pred)
        persistence=te["soil_moisture"].to_numpy(); baseline=_reg_metrics(y,persistence)
        gain=(baseline["mae"]-test_metrics["mae"])/baseline["mae"] if baseline["mae"]>0 else 0.0
        reasons=[]
        if gain < policy.min_baseline_mae_gain: reasons.append(f"MAE gain vs persistence {gain:.3f} < {policy.min_baseline_mae_gain:.3f}")
        prediction=te[[c for c in ["customer_id","farm_id","zone_id","device_id","sensor_id","observed_at",target] if c in te.columns]].copy()
        prediction["prediction"]=pred;prediction["persistence"]=persistence;prediction["absolute_error"]=np.abs(pred-y)
        pred_path=out/f"moisture_{horizon}m_predictions.csv";prediction.to_csv(pred_path,index=False)
        artifact_path=out/f"soil_moisture_{horizon}m.joblib"
        joblib.dump({"pipeline":model,"features":feature_cols,"horizon_minutes":horizon,"task":"regression","metric":"soil_moisture","production_candidate":not reasons},artifact_path,compress=3)
        record.update({"status":"CANDIDATE_PASS" if not reasons else "CANDIDATE_FAIL","selected_algorithm":selected,
                       "validation_candidates":evals,"test_metrics":test_metrics,"baseline":{"persistence":baseline},"baseline_mae_gain":gain,
                       "gate_reasons":reasons,"artifact_path":str(artifact_path),"artifact_sha256":_sha256(artifact_path),"prediction_csv":str(pred_path)})
        results.append(record)
    return results


def run_production_pipeline(project: str|Path, dataset: str|Path, artifact_root: str|Path|None=None, allow_training: bool=True) -> dict[str,Any]:
    project=Path(project).resolve(); dataset=Path(dataset).resolve()
    root=Path(artifact_root).resolve() if artifact_root else project/"model-artifacts"/"production-safe"
    run_id=datetime.now(timezone.utc).strftime("prod-%Y%m%dT%H%M%SZ")
    out=root/"runs"/run_id;out.mkdir(parents=True,exist_ok=False)
    raw,extras,sources=load_dataset(dataset)
    clean,audit=audit_and_clean(raw)
    features=build_moisture_features(clean)
    ready=readiness(clean,features,extras,audit)
    try:
        clean_path=out/"cleaned_sensor_readings.parquet";clean.to_parquet(clean_path,index=False)
        feature_path=out/"moisture_features.parquet";features.to_parquet(feature_path,index=False)
    except ImportError:
        # Audit must still be usable on minimal developer environments. Production
        # service requirements include pyarrow, but CSV is an explicit fallback.
        clean_path=out/"cleaned_sensor_readings.csv";clean.to_csv(clean_path,index=False)
        feature_path=out/"moisture_features.csv";features.to_csv(feature_path,index=False)
    _write_json(out/"data_audit.json",audit);_write_json(out/"data_readiness.json",ready)
    split_sources={k:{"path":v,"sha256":_sha256(Path(v))} for k,v in sources.items() if Path(v).is_file()}
    report={"run_id":run_id,"created_at":datetime.now(timezone.utc).isoformat(),"pipeline_version":"production_safe_v10.2",
            "dataset":str(dataset),"sources":split_sources,"audit":audit,"readiness":ready,"models":[],"production_registry_modified":False,
            "rules":{"synthetic_training_forbidden":True,"test_used_for_model_selection":False,"train_only_preprocessing":True,"chronological_horizon_purge":True}}
    horizons=ready["model_status"]["soil_moisture_forecast"].get("trainable_horizons_minutes",[])
    if allow_training and ready["status"]=="PASS" and horizons:
        report["models"]=train_moisture(features,horizons,out)
    else:
        report["training_skipped_reason"]="Data readiness FAIL hoặc --audit-only; không tạo model production candidate."
    _write_json(out/"training_report.json",report)
    try:
        from .training_report_docx import generate_training_report
        report_path=generate_training_report(report,out)
        report["docx_report"]=str(report_path)
        _write_json(out/"training_report.json",report)
    except Exception as exc:
        report["docx_report_error"]=repr(exc);_write_json(out/"training_report.json",report)
    _write_json(root/"latest_run.json",{"run_id":run_id,"report":str(out/"training_report.json"),"docx_report":report.get("docx_report")})
    return report
