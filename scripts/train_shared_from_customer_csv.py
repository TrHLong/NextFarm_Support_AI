from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = ROOT / "services" / "ai-analytics-service"
sys.path.insert(0, str(SERVICE_ROOT))

from app.customer_ml_automation import publish_shared_candidate, write_human_training_report  # noqa: E402
from app.ml_pipeline import train_shared_suite  # noqa: E402


def _latest_customer_sources(project_root: Path) -> tuple[pd.DataFrame, list[dict]]:
    latest_path = project_root / "docs" / "evidence" / "per-customer-ml-latest.json"
    payload = json.loads(latest_path.read_text(encoding="utf-8-sig"))
    frames: list[pd.DataFrame] = []
    sources: list[dict] = []
    for result in payload.get("results", []):
        if result.get("status") != "trained":
            continue
        customer_id = str(result["customer_id"])
        evidence_dir = Path(result["csv_evidence"]["directory"])
        processed_csv = evidence_dir / "01_processed_features_targets.csv"
        if not processed_csv.exists():
            raise FileNotFoundError(processed_csv)
        frame = pd.read_csv(processed_csv, encoding="utf-8-sig", low_memory=False)
        # `split` là nhãn dẫn xuất của phiên đánh giá cũ, không phải dữ liệu đầu vào.
        # Phải bỏ để bộ dùng chung tự chia lại toàn bộ timeline một cách nhất quán.
        frame = frame.drop(columns=["split"], errors="ignore")
        frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
        actual_ids = set(frame["customer_id"].astype(str).unique())
        if actual_ids != {customer_id}:
            raise RuntimeError(
                f"CSV {processed_csv} chứa customer_id {sorted(actual_ids)}, chờ đợi {customer_id}"
            )
        snapshot_manifest = (
            project_root
            / "model-artifacts"
            / "data"
            / "customers"
            / customer_id
            / "snapshots"
            / result["snapshot_id"]
            / "snapshot_manifest.json"
        )
        snapshot = json.loads(snapshot_manifest.read_text(encoding="utf-8-sig"))
        frames.append(frame)
        sources.append(
            {
                "customer_id": customer_id,
                "snapshot_id": result["snapshot_id"],
                "snapshot_manifest": str(snapshot_manifest),
                "snapshot_raw_directory": str(snapshot_manifest.parent / "raw"),
                "processed_csv": str(processed_csv),
                "source_manifest": str(evidence_dir / "evidence_manifest.json"),
                "source_dataset_version": result["dataset_version"],
                "raw_group_counts": result.get("group_counts", {}),
                "raw_sensor_reading_count": int(
                    result.get("group_counts", {}).get("sensor_readings", 0)
                ),
                "processed_rows_before_cap": int(len(frame)),
                "processed_rows_used": int(len(frame)),
                "farm_count": int(frame["farm_id"].nunique()),
                "zone_count": int(frame[["farm_id", "zone_code"]].drop_duplicates().shape[0]),
                "snapshot_file_count": int(len(snapshot.get("files", []))),
                "snapshot_database_at": snapshot.get("database_snapshot_at"),
                "customer_id_used_as_feature": False,
            }
        )
    if len(frames) < 3:
        raise RuntimeError("Cần ít nhất 3 khách hàng để kiểm định leave-one-customer-out.")
    pooled = pd.concat(frames, ignore_index=True).sort_values(
        ["observed_at", "customer_id", "farm_id", "zone_code"]
    ).reset_index(drop=True)
    return pooled, sources


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train 10 shared base models from existing per-customer CSV evidence."
    )
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--estimators", type=int, default=120)
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    artifact_root = project_root / "model-artifacts"
    frame, sources = _latest_customer_sources(project_root)
    fingerprint = "|".join(
        f"{item['customer_id']}:{item['source_dataset_version']}:{item['processed_rows_used']}"
        for item in sources
    )
    checksum = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    dataset_version = (
        "nextfarm-v10.1-shared-customers-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{checksum[:12]}"
    )
    metadata = {
        "dataset_version": dataset_version,
        "dataset_source": "v10_per_customer_csv_pool",
        "architecture": "shared_base_models_with_customer_calibration",
        "training_phase": "runtime_retrain",
        "customer_count": len(sources),
        "customer_ids": [item["customer_id"] for item in sources],
        "customer_sources": sources,
        "skipped_customers": [],
        "row_count": int(len(frame)),
        "raw_reading_count": int(sum(x["raw_sensor_reading_count"] for x in sources)),
        "farm_count": int(frame["farm_id"].nunique()),
        "zone_count": int(frame[["farm_id", "zone_code"]].drop_duplicates().shape[0]),
        "source_tables": [
            "user_db.customers",
            "farm_db.farms",
            "farm_db.zones",
            "farm_db.sensor_readings",
            "farm_db.device_status",
            "farm_db.irrigation_runs",
            "farm_db.telemetry_ingest_events",
        ],
        "origin_mix": {
            "simulated_device_calibrated_v9": {
                "count": int(sum(x["raw_sensor_reading_count"] for x in sources)),
                "ratio": 1.0,
            }
        },
        "label_method": "weak_labels_from_observable_rules",
        "customer_id_used_as_feature": False,
        "chat_messages_used_for_training": False,
        "balancing_policy": "all_current_processed_rows; runtime cap is 5000 rows per customer",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    policy_path = artifact_root / "data" / "training_policy.json"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(
        json.dumps(
            {
                "architecture": "shared_base_models_with_customer_calibration",
                "data_isolation": "immutable CSV snapshots separated by customer_id",
                "model_count": 10,
                "minimum_customers": 3,
                "minimum_processed_rows_per_customer": 40,
                "maximum_processed_rows_per_customer": 5000,
                "customer_id_used_as_feature": False,
                "generalization_test": "leave_one_customer_out",
                "split_strategy": "chronological_70_15_15_on_unique_timestamps",
                "candidate_selection": "validation_only",
                "activation": "approved candidates only; retain previous approved artifact on failure",
                "chat_messages_used_for_training": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    staging_root = artifact_root / ".training" / f"shared-{uuid.uuid4().hex}"
    try:
        report = train_shared_suite(
            staging_root,
            days=14,
            estimators=args.estimators,
            run_lofo=True,
            training_frame=frame,
            dataset_version=dataset_version,
            dataset_source="v10_per_customer_csv_pool",
            dataset_metadata=metadata,
            evidence_root=artifact_root / "data" / "shared" / "processed",
            published_artifact_root=artifact_root / "shared" / "candidates" / dataset_version,
            scope_type="global",
            scope_key="all_customers",
            generalization_column="customer_id",
            generalization_label="khách hàng",
            minimum_generalization_groups=3,
        )
        report["training_phase"] = "runtime_retrain"
        report["production_ready"] = False
        report = publish_shared_candidate(artifact_root, staging_root, report)
        human_report = write_human_training_report(artifact_root, report)
        evidence_path = project_root / "docs" / "evidence" / "shared-ml-latest.json"
        evidence_path.write_text(
            json.dumps(
                {
                    "architecture": report["architecture"],
                    "dataset_version": report["dataset_version"],
                    "customer_count": metadata["customer_count"],
                    "processed_rows": report["generated_rows"],
                    "train_count": report["train_count"],
                    "validation_count": report["validation_count"],
                    "test_count": report["test_count"],
                    "candidate_model_count": report["model_count"],
                    "approved_candidate_count": report["approved_model_count"],
                    "active_model_count": report["total_active_model_count"],
                    "production_ready": False,
                    "human_report": str(human_report),
                    "active_manifest": report["active_manifest"],
                    "csv_evidence": report["csv_evidence"],
                    "customer_sources": sources,
                    "models": [
                        {
                            "model_name": model["model_name"],
                            "task": model["task"],
                            "algorithm": model["algorithm"],
                            "test_metrics": model["test_metrics"],
                            "deployment_status": model["deployment_status"],
                            "quality_gate_reasons": model["quality_gate"]["reasons"],
                        }
                        for model in report["models"]
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(json.dumps({
            "dataset_version": report["dataset_version"],
            "rows": report["generated_rows"],
            "approved": report["approved_model_count"],
            "active": report["total_active_model_count"],
            "human_report": str(human_report),
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
