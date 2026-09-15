from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.ml_pipeline import FEATURES, profile_feature_values

METRICS = ["soil_moisture", "temperature", "air_humidity", "ec", "ph", "flow_rate"]


def _rows(cur, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur.execute(query, params)
    return [dict(row) for row in cur.fetchall()]


def _profile(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "crop": row.get("crop_code") or "other",
        "cultivation_type": row.get("cultivation_type") or "other",
        "climate_region": row.get("climate_region") or "other",
        "soil_type": row.get("soil_type") or "other",
        "area_ha": float(row.get("area_ha") or 1.0),
        "moisture_min": float(row.get("target_moisture_min") or row.get("moisture_min") or 0.0),
        "moisture_max": float(row.get("target_moisture_max") or row.get("moisture_max") or 100.0),
        "ec_min": float(row.get("target_ec_min") or row.get("ec_min") or 0.0),
        "ec_max": float(row.get("target_ec_max") or row.get("ec_max") or 6.0),
        "ph_min": float(row.get("target_ph_min") or row.get("ph_min") or 0.0),
        "ph_max": float(row.get("target_ph_max") or row.get("ph_max") or 14.0),
    }


def _read_snapshot_csv(raw_dir: Path, name: str) -> pd.DataFrame:
    path = raw_dir / f"{name}.csv"
    if not path.exists():
        raise RuntimeError(f"Snapshot thiếu tệp bắt buộc: {path}")
    return pd.read_csv(path, encoding="utf-8-sig", low_memory=False)


def _load_customer_snapshot_rows(
    snapshot_dir: str | Path,
    *,
    lookback_days: int,
    snapshot_at: datetime | str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Đọc đúng CSV snapshot đã khóa; không quay lại DB để lấy thêm dòng đến muộn."""
    snapshot_root = Path(snapshot_dir)
    raw_dir = snapshot_root / "raw" if (snapshot_root / "raw").exists() else snapshot_root
    manifest_path = snapshot_root / "snapshot_manifest.json"
    if not manifest_path.exists() and raw_dir.parent != snapshot_root:
        manifest_path = raw_dir.parent / "snapshot_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cutoff = pd.Timestamp(snapshot_at or manifest["database_snapshot_at"])
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")
    lower = cutoff - pd.Timedelta(days=lookback_days)

    readings_df = _read_snapshot_csv(raw_dir, "sensor_readings")
    readings_df["observed_at"] = pd.to_datetime(readings_df["observed_at"], utc=True, errors="coerce")
    readings_df = readings_df[
        readings_df["metric_type"].isin(METRICS)
        & readings_df["observed_at"].between(lower, cutoff, inclusive="both")
    ].copy()

    farms = _read_snapshot_csv(raw_dir, "farms")
    zones = _read_snapshot_csv(raw_dir, "zones")
    profiles = _read_snapshot_csv(raw_dir, "farm_ai_profiles")
    profile_df = zones.merge(
        farms[["customer_id", "farm_id", "farm_name", "area_ha"]],
        on=["customer_id", "farm_id"],
        how="inner",
    ).merge(
        profiles.drop(columns=["customer_id"], errors="ignore"),
        on="farm_id",
        how="left",
    )

    statuses_df = _read_snapshot_csv(raw_dir, "device_status")
    statuses_df["observed_at"] = pd.to_datetime(statuses_df["observed_at"], utc=True, errors="coerce")
    statuses_df = statuses_df[statuses_df["observed_at"].between(lower, cutoff, inclusive="both")]

    runs_df = _read_snapshot_csv(raw_dir, "irrigation_runs")
    if not runs_df.empty:
        runs_df["started_at"] = pd.to_datetime(runs_df["started_at"], utc=True, errors="coerce")
        runs_df = runs_df[runs_df["started_at"].between(lower, cutoff, inclusive="both")]

    events_df = _read_snapshot_csv(raw_dir, "telemetry_ingest_events")
    if not events_df.empty:
        events_df["received_at"] = pd.to_datetime(events_df["received_at"], utc=True, errors="coerce")
        events_df = events_df[events_df["received_at"].between(lower, cutoff, inclusive="both")]

    return (
        readings_df.to_dict("records"),
        profile_df.to_dict("records"),
        statuses_df.to_dict("records"),
        runs_df.to_dict("records"),
        events_df.to_dict("records"),
        {**manifest, "manifest_path": str(manifest_path), "raw_directory": str(raw_dir)},
    )


def build_database_training_dataset(
    database_url: str,
    artifact_root: str | Path,
    *,
    lookback_days: int = 14,
    freq_minutes: int = 15,
    snapshot_at: datetime | str | None = None,
    runtime_snapshot_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Build and lock a time-series dataset from PostgreSQL operational tables.

    Classification targets are weak labels derived from observable device, flow,
    moisture and irrigation rules. They are not treated as human-verified ground truth.
    """
    snapshot_meta: dict[str, Any] = {}
    if runtime_snapshot_dir is not None:
        readings, profiles, statuses, runs, events, snapshot_meta = _load_customer_snapshot_rows(
            runtime_snapshot_dir,
            lookback_days=lookback_days,
            snapshot_at=snapshot_at,
        )
        snapshot_at = snapshot_meta.get("database_snapshot_at") or snapshot_at
    else:
        with psycopg.connect(database_url, row_factory=dict_row) as db, db.cursor() as cur:
            readings = _rows(
                cur,
                """SELECT f.customer_id,r.farm_id,r.zone_id,z.zone_code,r.metric_type,r.value,r.quality,r.observed_at,
                          r.data_origin,r.source_dataset,r.simulation_profile_version
                   FROM farm_db.sensor_readings r
                   JOIN farm_db.farms f ON f.farm_id=r.farm_id
                   JOIN farm_db.zones z ON z.zone_id=r.zone_id
                   WHERE r.observed_at >= coalesce(%s::timestamptz,now())-(%s || ' days')::interval
                     AND r.observed_at <= coalesce(%s::timestamptz,now())
                     AND r.created_at <= coalesce(%s::timestamptz,now())
                     AND r.metric_type=ANY(%s)
                     AND r.data_origin='simulated_device_calibrated_v9'
                   ORDER BY r.observed_at""",
                (snapshot_at, lookback_days, snapshot_at, snapshot_at, METRICS),
            )
            profiles = _rows(
                cur,
                """SELECT f.customer_id,f.farm_id,f.farm_name,f.area_ha,z.zone_id,z.zone_code,z.moisture_min,z.moisture_max,z.ec_min,z.ec_max,z.ph_min,z.ph_max,
                          p.crop_code,p.cultivation_type,p.climate_region,p.soil_type,p.target_moisture_min,p.target_moisture_max,
                          p.target_ec_min,p.target_ec_max,p.target_ph_min,p.target_ph_max
                   FROM farm_db.farms f JOIN farm_db.zones z ON z.farm_id=f.farm_id
                   LEFT JOIN farm_db.farm_ai_profiles p ON p.farm_id=f.farm_id
                   ORDER BY f.farm_id,z.zone_code""",
            )
            statuses = _rows(
                cur,
                """SELECT d.farm_id,coalesce(d.zone_id,p.zone_id) AS zone_id,ds.online,ds.running,ds.observed_at
                   FROM farm_db.device_status ds
                   JOIN farm_db.devices d ON d.device_id=ds.device_id
                   LEFT JOIN farm_db.device_ports p ON p.port_id=ds.port_id
                   WHERE ds.observed_at >= coalesce(%s::timestamptz,now())-(%s || ' days')::interval
                     AND ds.observed_at <= coalesce(%s::timestamptz,now())
                     AND ds.created_at <= coalesce(%s::timestamptz,now())""",
                (snapshot_at, lookback_days, snapshot_at, snapshot_at),
            )
            runs = _rows(
                cur,
                """SELECT farm_id,zone_id,started_at,coalesce(ended_at,started_at) AS ended_at,result
                   FROM farm_db.irrigation_runs
                   WHERE started_at >= coalesce(%s::timestamptz,now())-(%s || ' days')::interval
                     AND started_at <= coalesce(%s::timestamptz,now())""",
                (snapshot_at, lookback_days, snapshot_at),
            )
            events = _rows(
                cur,
                """SELECT farm_id,received_at,status,inserted_readings
                   FROM farm_db.telemetry_ingest_events
                   WHERE received_at >= coalesce(%s::timestamptz,now())-(%s || ' days')::interval
                     AND received_at <= coalesce(%s::timestamptz,now())""",
                (snapshot_at, lookback_days, snapshot_at),
            )

    if not readings or not profiles:
        raise RuntimeError("Không có sensor_readings/profile đủ để tạo dataset từ DB.")

    freq = f"{freq_minutes}min"
    rdf = pd.DataFrame(readings)
    if "customer_id" not in rdf.columns:
        # Tương thích dữ liệu/fixture trước migration 07. Snapshot v10.1 thật
        # luôn có customer_id; fallback này vẫn tạo tenant giả ổn định theo farm.
        rdf["customer_id"] = "legacy_" + rdf["farm_id"].astype(str)
    rdf["observed_at"] = pd.to_datetime(rdf["observed_at"], utc=True)
    if "data_origin" not in rdf.columns:
        raise RuntimeError("V9 runtime dataset thiếu cột provenance data_origin.")
    rdf["data_origin"] = rdf["data_origin"].fillna("missing_provenance")
    if "source_dataset" not in rdf.columns:
        rdf["source_dataset"] = "unspecified"
    if "simulation_profile_version" not in rdf.columns:
        rdf["simulation_profile_version"] = None
    origin_counts = {str(k): int(v) for k, v in rdf["data_origin"].value_counts(dropna=False).items()}
    raw_reading_count = int(len(rdf))
    origin_mix = {
        key: {"count": count, "ratio": round(count / max(raw_reading_count, 1), 6)}
        for key, count in origin_counts.items()
    }
    source_counts = {
        str(k): int(v) for k, v in rdf["source_dataset"].fillna("unspecified").value_counts(dropna=False).items()
    }
    profile_versions = sorted({
        str(x) for x in rdf["simulation_profile_version"].dropna().tolist() if str(x).strip()
    })
    latest_observed_at = rdf["observed_at"].max().isoformat() if not rdf.empty else None
    rdf["bucket"] = rdf["observed_at"].dt.floor(freq)
    rdf["value"] = pd.to_numeric(rdf["value"], errors="coerce")
    wide = (
        rdf.groupby(["customer_id", "farm_id", "zone_id", "zone_code", "bucket", "metric_type"], as_index=False)["value"]
        .mean()
        .pivot(index=["customer_id", "farm_id", "zone_id", "zone_code", "bucket"], columns="metric_type", values="value")
        .reset_index()
        .rename_axis(None, axis=1)
    )

    profile_map = {(r["farm_id"], r["zone_id"]): r for r in profiles}
    frames: list[pd.DataFrame] = []
    for (customer_id, farm_id, zone_id, zone_code), group in wide.groupby(["customer_id", "farm_id", "zone_id", "zone_code"]):
        group = group.sort_values("bucket").set_index("bucket")
        full_index = pd.date_range(group.index.min(), group.index.max(), freq=freq, tz="UTC")
        group = group.reindex(full_index)
        group["customer_id"], group["farm_id"], group["zone_id"], group["zone_code"] = customer_id, farm_id, zone_id, zone_code
        group["observed_at"] = group.index
        frames.append(group.reset_index(drop=True))
    frame = pd.concat(frames, ignore_index=True)

    # Device state aligned to the same buckets.
    if statuses:
        sdf = pd.DataFrame(statuses)
        sdf["observed_at"] = pd.to_datetime(sdf["observed_at"], utc=True)
        sdf["bucket"] = sdf["observed_at"].dt.floor(freq)
        sagg = sdf.groupby(["farm_id", "zone_id", "bucket"], dropna=False).agg(
            device_online=("online", "mean"), device_running=("running", "mean")
        ).reset_index()
        frame = frame.merge(sagg, left_on=["farm_id", "zone_id", "observed_at"], right_on=["farm_id", "zone_id", "bucket"], how="left").drop(columns=["bucket"], errors="ignore")
    else:
        frame["device_online"] = np.nan
        frame["device_running"] = np.nan

    # MQTT packet quality by farm and bucket.
    if events:
        edf = pd.DataFrame(events)
        edf["received_at"] = pd.to_datetime(edf["received_at"], utc=True)
        edf["bucket"] = edf["received_at"].dt.floor(freq)
        edf["bad_packet"] = (~edf["status"].isin(["stored", "duplicate"])).astype(float)
        eagg = edf.groupby(["farm_id", "bucket"]).agg(packet_loss_rate=("bad_packet", "mean")).reset_index()
        frame = frame.merge(eagg, left_on=["farm_id", "observed_at"], right_on=["farm_id", "bucket"], how="left").drop(columns=["bucket"], errors="ignore")
    else:
        frame["packet_loss_rate"] = 0.0

    # Irrigation schedule/result aligned by explicit run intervals.
    frame["scheduled_irrigation"] = 0
    frame["command_failure_rate"] = 0.0
    frame["minutes_since_irrigation"] = np.nan
    run_df = pd.DataFrame(runs) if runs else pd.DataFrame()
    for (farm_id, zone_id), idx in frame.groupby(["farm_id", "zone_id"]).groups.items():
        indexes = list(idx)
        times = frame.loc[indexes, "observed_at"]
        relevant = run_df[(run_df["farm_id"] == farm_id) & ((run_df["zone_id"] == zone_id) | run_df["zone_id"].isna())].copy() if not run_df.empty else pd.DataFrame()
        last_success = None
        for i in indexes:
            ts = frame.at[i, "observed_at"]
            active = relevant[(pd.to_datetime(relevant["started_at"], utc=True) <= ts) & (pd.to_datetime(relevant["ended_at"], utc=True) >= ts)] if not relevant.empty else pd.DataFrame()
            if not active.empty:
                frame.at[i, "scheduled_irrigation"] = 1
                frame.at[i, "command_failure_rate"] = float((active["result"] == "failed").mean())
            past_success = relevant[(relevant["result"] == "success") & (pd.to_datetime(relevant["started_at"], utc=True) <= ts)] if not relevant.empty else pd.DataFrame()
            if not past_success.empty:
                last_success = pd.to_datetime(past_success["started_at"], utc=True).max()
            frame.at[i, "minutes_since_irrigation"] = (ts - last_success).total_seconds() / 60 if last_success is not None else lookback_days * 1440

    # Missingness + forward-only fill. Không bfill từ tương lai để tránh leakage.
    for metric in METRICS:
        if metric not in frame:
            frame[metric] = np.nan
        frame[f"{metric}_missing"] = frame[metric].isna().astype(int)
        frame[metric] = frame.groupby(["farm_id", "zone_id"])[metric].transform(lambda x: x.ffill(limit=2))
    frame["device_online"] = frame["device_online"].fillna(0).clip(0, 1).round().astype(int)
    frame["device_running"] = frame["device_running"].fillna(0).clip(0, 1).round().astype(int)
    frame["valve_running"] = frame["device_running"]
    frame["pump_running"] = frame["device_running"]
    frame["packet_loss_rate"] = frame["packet_loss_rate"].fillna(0).clip(0, 1)

    # Profile features and thresholds.
    profile_rows = []
    for _, row in frame.iterrows():
        raw = profile_map[(row["farm_id"], row["zone_id"])]
        prof = _profile(raw)
        values = profile_feature_values(prof)
        values.update({
            "farm_name": raw.get("farm_name") or row["farm_id"],
            "moisture_min": prof["moisture_min"], "moisture_max": prof["moisture_max"],
            "ec_min": prof["ec_min"], "ec_max": prof["ec_max"],
            "ph_min": prof["ph_min"], "ph_max": prof["ph_max"],
        })
        profile_rows.append(values)
    frame = pd.concat([frame.reset_index(drop=True), pd.DataFrame(profile_rows)], axis=1)

    # Các khoảng đầu chưa có quan sát trước đó dùng giá trị cấu hình/sentinel, không dùng dữ liệu tương lai.
    frame["soil_moisture"] = frame["soil_moisture"].fillna(frame["moisture_target_mid"])
    frame["ec"] = frame["ec"].fillna(frame["ec_target_mid"])
    frame["ph"] = frame["ph"].fillna(frame["ph_target_mid"])
    frame["temperature"] = frame.groupby(["farm_id", "zone_id"])["temperature"].transform(
        lambda x: x.fillna(x.expanding(min_periods=1).median())
    ).fillna(25.0)
    frame["air_humidity"] = frame.groupby(["farm_id", "zone_id"])["air_humidity"].transform(
        lambda x: x.fillna(x.expanding(min_periods=1).median())
    ).fillna(75.0)
    frame["flow_rate"] = frame["flow_rate"].fillna(0.0)

    minute = frame["observed_at"].dt.hour * 60 + frame["observed_at"].dt.minute
    frame["minute_sin"] = np.sin(2 * np.pi * minute / 1440)
    frame["minute_cos"] = np.cos(2 * np.pi * minute / 1440)
    day = frame["observed_at"].dt.dayofweek
    frame["day_sin"] = np.sin(2 * np.pi * day / 7)
    frame["day_cos"] = np.cos(2 * np.pi * day / 7)
    zone_codes = {code: i for i, code in enumerate(sorted(frame["zone_code"].dropna().unique()))}
    frame["zone_index"] = frame["zone_code"].map(zone_codes).fillna(0).astype(float)

    groups = frame.groupby(["farm_id", "zone_id"], group_keys=False)
    for metric, short in [("soil_moisture", "moisture"), ("temperature", "temperature"), ("air_humidity", "humidity"), ("ec", "ec"), ("ph", "ph"), ("flow_rate", "flow")]:
        frame[f"{short}_delta"] = groups[metric].diff().fillna(0.0)
    frame["moisture_roll_mean"] = groups["soil_moisture"].transform(lambda x: x.rolling(8, min_periods=1).mean())
    frame["moisture_roll_std"] = groups["soil_moisture"].transform(lambda x: x.rolling(8, min_periods=2).std()).fillna(0.0)
    frame["flow_roll_mean"] = groups["flow_rate"].transform(lambda x: x.rolling(8, min_periods=1).mean())
    frame["flow_roll_std"] = groups["flow_rate"].transform(lambda x: x.rolling(8, min_periods=2).std()).fillna(0.0)
    frame["sensor_age_seconds"] = np.where(frame[[f"{m}_missing" for m in METRICS]].sum(axis=1) > 0, freq_minutes * 60, 0.0)

    horizon_steps = max(1, round(30 / freq_minutes))
    for metric, target in [("soil_moisture", "target_moisture_30m"), ("temperature", "target_temperature_30m"), ("ec", "target_ec_30m"), ("ph", "target_ph_30m")]:
        frame[target] = groups[metric].shift(-horizon_steps)
        future_was_missing = groups[f"{metric}_missing"].shift(-horizon_steps).fillna(1).astype(bool)
        frame.loc[future_was_missing, target] = np.nan

    # Weak labels, explicitly auditable and derived only from observable data.
    flow = frame["flow_rate"].fillna(0)
    scheduled = frame["scheduled_irrigation"].astype(bool)
    offline = frame["device_online"] == 0
    frame["flow_fault_label"] = np.select([scheduled & (flow < 1.0), (~scheduled) & (flow > 1.5)], [1, 2], default=0)
    frame["irrigation_failure_label"] = (scheduled & ((flow < 1.0) | offline | (frame["command_failure_rate"] > 0.3))).astype(int)
    frame["irrigation_need_label"] = ((frame["soil_moisture"] < frame["moisture_min"]) & ~scheduled).astype(int)
    noisy = (frame["moisture_roll_std"] > 6) | (frame["flow_roll_std"] > 3)
    out_of_range = (frame["ec"] > frame["ec_max"] * 1.15) | (frame["ph"] < frame["ph_min"] - 0.4) | (frame["ph"] > frame["ph_max"] + 0.4)
    frame["anomaly_label"] = (noisy | out_of_range | offline | (frame[[f"{m}_missing" for m in METRICS]].sum(axis=1) >= 2)).astype(int)
    frame["device_health_label"] = np.select([offline | (frame["packet_loss_rate"] > 0.5), (frame["packet_loss_rate"] > 0.15) | (frame["sensor_age_seconds"] > freq_minutes * 60)], [2, 1], default=0)
    frame["farm_health_label"] = np.select([(frame["irrigation_failure_label"] == 1) | (frame["flow_fault_label"] > 0) | (frame["device_health_label"] == 2), (frame["anomaly_label"] == 1) | (frame["irrigation_need_label"] == 1) | (frame["device_health_label"] == 1)], [2, 1], default=0)

    required_targets = ["target_moisture_30m", "target_temperature_30m", "target_ec_30m", "target_ph_30m", "anomaly_label", "flow_fault_label", "irrigation_failure_label", "irrigation_need_label", "device_health_label", "farm_health_label"]
    for col in FEATURES:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame[FEATURES] = frame[FEATURES].replace([np.inf, -np.inf], np.nan)
    frame[FEATURES] = frame[FEATURES].fillna(0.0)
    frame = frame.dropna(subset=required_targets).sort_values(["observed_at", "farm_id", "zone_code"]).reset_index(drop=True)

    export_cols = ["customer_id", "farm_id", "farm_name", "zone_id", "zone_code", "observed_at", *FEATURES, *required_targets]
    dataset_dir = Path(artifact_root) / "datasets"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    tmp_parquet = dataset_dir / "latest_database_training_dataset.parquet"
    frame[export_cols].to_parquet(tmp_parquet, index=False, engine="pyarrow", compression="zstd")
    checksum = hashlib.sha256(tmp_parquet.read_bytes()).hexdigest()
    customer_id = str(frame["customer_id"].iloc[0]) if frame["customer_id"].nunique() == 1 else "multi_customer"
    source_type = "v10_runtime_csv_snapshot" if runtime_snapshot_dir is not None else "v10_runtime_database"
    dataset_version = f"nextfarm-v10.1-{customer_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{checksum[:12]}"
    locked_parquet = dataset_dir / f"{dataset_version}.parquet"
    tmp_parquet.replace(locked_parquet)
    metadata = {
        "dataset_version": dataset_version,
        "dataset_source": source_type,
        "customer_id": customer_id,
        "row_count": int(len(frame)),
        "raw_reading_count": raw_reading_count,
        "farm_count": int(frame["farm_id"].nunique()),
        "zone_count": int(frame[["farm_id", "zone_code"]].drop_duplicates().shape[0]),
        "lookback_days": lookback_days,
        "frequency_minutes": freq_minutes,
        "checksum_sha256": checksum,
        "artifact_path": str(locked_parquet),
        "source_tables": ["user_db.customers", "farm_db.farms", "farm_db.zones", "farm_db.sensor_readings", "farm_db.device_status", "farm_db.irrigation_runs", "farm_db.telemetry_ingest_events", "research_db.calibration_profiles"],
        "origin_mix": origin_mix,
        "source_dataset_mix": source_counts,
        "simulated_device_calibrated_v9_ratio": round(origin_counts.get("simulated_device_calibrated_v9", 0) / max(raw_reading_count, 1), 6),
        "calibration_profile_versions": profile_versions,
        "latest_observed_at": latest_observed_at,
        "snapshot_cutoff_at": str(snapshot_at) if snapshot_at is not None else latest_observed_at,
        "runtime_snapshot_id": snapshot_meta.get("snapshot_id"),
        "runtime_snapshot_manifest": snapshot_meta.get("manifest_path"),
        "runtime_snapshot_raw_directory": snapshot_meta.get("raw_directory"),
        "label_method": "weak_labels_from_observable_rules",
        "provenance_policy": "V10.1 per-customer immutable CSV snapshot; customer identity is metadata, not a model feature; current rows are simulator-calibrated rather than production hardware telemetry",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (dataset_dir / f"{dataset_version}.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    with psycopg.connect(database_url, row_factory=dict_row) as db, db.cursor() as cur:
        cur.execute(
            """INSERT INTO knowledge_db.ml_datasets(
                 dataset_version,customer_id,source_type,source_tables,row_count,farm_count,zone_count,checksum_sha256,artifact_path,metadata,
                 origin_mix,latest_observed_at,locked_at
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
               ON CONFLICT (dataset_version) DO NOTHING""",
            (
                dataset_version, customer_id if customer_id != "multi_customer" else None, source_type,
                metadata["source_tables"], metadata["row_count"], metadata["farm_count"], metadata["zone_count"],
                checksum, str(locked_parquet), Jsonb(metadata), Jsonb(origin_mix), metadata["latest_observed_at"],
            ),
        )
        db.commit()
    return {**metadata, "frame": frame[export_cols]}



def build_reference_bootstrap_dataset(
    database_url: str,
    artifact_root: str | Path,
    reference_parquet: str | Path,
    reference_lock: str | Path,
) -> dict[str, Any]:
    """Lock initial AI training data derived only from V9 downloaded references.

    The reference-derived feature rows are training material, not observed NextFarm telemetry.
    No operational sensor table is read in this bootstrap phase.
    """
    ref_path = Path(reference_parquet)
    lock_path = Path(reference_lock)
    if not ref_path.exists() or not lock_path.exists():
        raise RuntimeError(r"Thiếu V9 static reference pack. Chạy scripts\prepare_v9_research_data.cmd trước.")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    policy = lock.get("policy", {})
    if policy.get("uses_prior_project_data") is not False or policy.get("uses_external_project_database") is not False:
        raise RuntimeError("Reference lock không xác nhận V9 standalone isolation.")
    frame = pd.read_parquet(ref_path, engine="pyarrow")
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
    targets = [
        "target_moisture_30m", "target_temperature_30m", "target_ec_30m", "target_ph_30m",
        "anomaly_label", "flow_fault_label", "irrigation_failure_label", "irrigation_need_label",
        "device_health_label", "farm_health_label",
    ]
    missing = [c for c in ["farm_id", "farm_name", "zone_code", "observed_at", *FEATURES, *targets] if c not in frame.columns]
    if missing:
        raise RuntimeError(f"Reference bootstrap thiếu cột: {missing}")
    if "customer_id" not in frame.columns:
        frame["customer_id"] = "reference_" + frame["farm_id"].astype(str)
    if "zone_id" not in frame.columns:
        frame["zone_id"] = frame["farm_id"].astype(str) + "_" + frame["zone_code"].astype(str)
    if len(frame) < 1000 or frame["farm_id"].nunique() < 3:
        raise RuntimeError(f"Reference bootstrap chưa đủ coverage: rows={len(frame)}, farms={frame['farm_id'].nunique()}")
    dataset_dir = Path(artifact_root) / "datasets"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    checksum = hashlib.sha256(ref_path.read_bytes()).hexdigest()
    dataset_version = f"nextfarm-v9-reference-{checksum[:16]}"
    locked_parquet = dataset_dir / f"{dataset_version}.parquet"
    if not locked_parquet.exists():
        locked_parquet.write_bytes(ref_path.read_bytes())
    metadata = {
        "dataset_version": dataset_version,
        "dataset_source": "reference_bootstrap",
        "training_phase": "bootstrap_reference",
        "row_count": int(len(frame)),
        "farm_count": int(frame["farm_id"].nunique()),
        "zone_count": int(frame[["farm_id", "zone_code"]].drop_duplicates().shape[0]),
        "checksum_sha256": checksum,
        "artifact_path": str(locked_parquet),
        "reference_lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        "normalized_reference_rows": int(lock.get("normalized_reference_rows") or 0),
        "reference_source_counts": lock.get("reference_source_counts", {}),
        "metric_counts": lock.get("metric_counts", {}),
        "origin_mix": {"downloaded_static_reference_anchor": {"count": int(len(frame)), "ratio": 1.0}},
        "source_tables": [],
        "label_method": "weak_bootstrap_labels_on_reference_anchored_sequences",
        "provenance_policy": "derived from freshly downloaded V9 static references; no older project database",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (dataset_dir / f"{dataset_version}.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    with psycopg.connect(database_url, row_factory=dict_row) as db, db.cursor() as cur:
        cur.execute(
            """INSERT INTO knowledge_db.ml_datasets(
                 dataset_version,source_type,source_tables,row_count,farm_count,zone_count,checksum_sha256,artifact_path,metadata,
                 origin_mix,latest_observed_at,locked_at
               ) VALUES (%s,'reference_bootstrap','{}',%s,%s,%s,%s,%s,%s,%s,NULL,now())
               ON CONFLICT (dataset_version) DO NOTHING""",
            (dataset_version, metadata["row_count"], metadata["farm_count"], metadata["zone_count"], checksum, str(locked_parquet), Jsonb(metadata), Jsonb(metadata["origin_mix"])),
        )
        cur.execute(
            """INSERT INTO research_db.reference_datasets(reference_id,lock_sha256,normalized_rows,bootstrap_rows,source_manifest,metric_counts,metadata)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(reference_id) DO UPDATE SET lock_sha256=excluded.lock_sha256,normalized_rows=excluded.normalized_rows,
                 bootstrap_rows=excluded.bootstrap_rows,source_manifest=excluded.source_manifest,metric_counts=excluded.metric_counts,metadata=excluded.metadata,loaded_at=now()""",
            (dataset_version, metadata["reference_lock_sha256"], metadata["normalized_reference_rows"], metadata["row_count"], Jsonb(lock.get("sources", [])), Jsonb(metadata["metric_counts"]), Jsonb(metadata)),
        )
        db.commit()
    return {**metadata, "frame": frame}


def build_v9_blended_training_dataset(
    database_url: str,
    artifact_root: str | Path,
    reference_parquet: str | Path,
    reference_lock: str | Path,
    *,
    lookback_days: int = 14,
    freq_minutes: int = 15,
    reference_anchor_ratio: float = 0.25,
) -> dict[str, Any]:
    """Retrain from V9 runtime telemetry while retaining a locked static-reference anchor."""
    lock_path = Path(reference_lock)
    if not lock_path.exists():
        raise RuntimeError("Thiếu reference_lock.json; không retrain nếu không xác minh được provenance static reference.")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    policy = lock.get("policy", {})
    if policy.get("uses_prior_project_data") is not False or policy.get("uses_external_project_database") is not False:
        raise RuntimeError("Reference lock không xác nhận V9 standalone isolation.")
    runtime_meta = build_database_training_dataset(database_url, artifact_root, lookback_days=lookback_days, freq_minutes=freq_minutes)
    runtime = runtime_meta.pop("frame")
    ref = pd.read_parquet(reference_parquet, engine="pyarrow")
    ref["observed_at"] = pd.to_datetime(ref["observed_at"], utc=True)
    ratio = min(0.45, max(0.05, float(reference_anchor_ratio)))
    desired = max(1, int(len(runtime) * ratio / max(1e-9, 1.0 - ratio)))
    if desired < len(ref):
        ref = ref.sample(n=desired, random_state=20260811)
    targets = [
        "target_moisture_30m", "target_temperature_30m", "target_ec_30m", "target_ph_30m",
        "anomaly_label", "flow_fault_label", "irrigation_failure_label", "irrigation_need_label",
        "device_health_label", "farm_health_label",
    ]
    if "customer_id" not in ref.columns:
        ref["customer_id"] = "reference_" + ref["farm_id"].astype(str)
    if "zone_id" not in ref.columns:
        ref["zone_id"] = ref["farm_id"].astype(str) + "_" + ref["zone_code"].astype(str)
    export_cols = ["customer_id", "farm_id", "farm_name", "zone_id", "zone_code", "observed_at", *FEATURES, *targets]
    frame = pd.concat([runtime[export_cols], ref[export_cols]], ignore_index=True).sort_values(["observed_at", "farm_id", "zone_code"]).reset_index(drop=True)
    dataset_dir = Path(artifact_root) / "datasets"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    tmp = dataset_dir / "latest_v9_runtime_blend.parquet"
    frame.to_parquet(tmp, index=False, engine="pyarrow", compression="zstd")
    checksum = hashlib.sha256(tmp.read_bytes()).hexdigest()
    dataset_version = f"nextfarm-v9-blend-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{checksum[:12]}"
    locked = dataset_dir / f"{dataset_version}.parquet"
    tmp.replace(locked)
    metadata = {
        "dataset_version": dataset_version,
        "dataset_source": "v9_runtime_blend",
        "training_phase": "runtime_retrain",
        "row_count": int(len(frame)),
        "runtime_row_count": int(len(runtime)),
        "runtime_raw_reading_count": int(runtime_meta.get("raw_reading_count", 0) or 0),
        "reference_lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        "reference_anchor_row_count": int(len(ref)),
        "reference_anchor_ratio": round(len(ref) / max(len(frame), 1), 6),
        "farm_count": int(frame["farm_id"].nunique()),
        "zone_count": int(frame[["farm_id", "zone_code"]].drop_duplicates().shape[0]),
        "checksum_sha256": checksum,
        "artifact_path": str(locked),
        "origin_mix": {
            "simulated_device_calibrated_v9": {"count": int(len(runtime)), "ratio": round(len(runtime)/max(len(frame),1), 6)},
            "downloaded_static_reference_anchor": {"count": int(len(ref)), "ratio": round(len(ref)/max(len(frame),1), 6)},
        },
        "source_tables": runtime_meta.get("source_tables", []),
        "runtime_dataset_version": runtime_meta.get("dataset_version"),
        "provenance_policy": "V9 runtime simulated-device telemetry + locked downloaded-reference anchor only",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (dataset_dir / f"{dataset_version}.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    with psycopg.connect(database_url, row_factory=dict_row) as db, db.cursor() as cur:
        cur.execute(
            """INSERT INTO knowledge_db.ml_datasets(dataset_version,source_type,source_tables,row_count,farm_count,zone_count,checksum_sha256,artifact_path,metadata,origin_mix,latest_observed_at,locked_at)
               VALUES (%s,'v9_runtime_blend',%s,%s,%s,%s,%s,%s,%s,%s,NULL,now()) ON CONFLICT(dataset_version) DO NOTHING""",
            (dataset_version, metadata["source_tables"], metadata["row_count"], metadata["farm_count"], metadata["zone_count"], checksum, str(locked), Jsonb(metadata), Jsonb(metadata["origin_mix"])),
        )
        db.commit()
    return {**metadata, "frame": frame}
