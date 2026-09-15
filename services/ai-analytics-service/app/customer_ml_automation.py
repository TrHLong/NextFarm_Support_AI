from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.dataset_builder import build_database_training_dataset
from app.ml_pipeline import FEATURES, MODEL_SPECS, train_shared_suite
from app.runtime_export import export_customer_training_snapshot


GROUP_POLICIES: dict[str, dict[str, int | bool]] = {
    # minimum_rows: lịch sử tối thiểu trước phiên train đầu tiên.
    # new_rows: số dòng mới so với watermark để cho phép retrain tiếp theo.
    "sensor_readings": {"minimum_rows": int(os.getenv("AI_CUSTOMER_MIN_SENSOR_ROWS", "20000")), "new_rows": int(os.getenv("AI_CUSTOMER_NEW_SENSOR_ROWS", "5000")), "required": True},
    "device_status": {"minimum_rows": int(os.getenv("AI_CUSTOMER_MIN_STATUS_ROWS", "5000")), "new_rows": int(os.getenv("AI_CUSTOMER_NEW_STATUS_ROWS", "2000")), "required": True},
    "telemetry_ingest_events": {"minimum_rows": int(os.getenv("AI_CUSTOMER_MIN_INGEST_ROWS", "2000")), "new_rows": int(os.getenv("AI_CUSTOMER_NEW_INGEST_ROWS", "1000")), "required": True},
    "irrigation_runs": {"minimum_rows": int(os.getenv("AI_CUSTOMER_MIN_IRRIGATION_ROWS", "3")), "new_rows": int(os.getenv("AI_CUSTOMER_NEW_IRRIGATION_ROWS", "2")), "required": True},
    "alerts": {"minimum_rows": 0, "new_rows": int(os.getenv("AI_CUSTOMER_NEW_ALERT_ROWS", "5")), "required": False},
    "control_commands": {"minimum_rows": 0, "new_rows": int(os.getenv("AI_CUSTOMER_NEW_COMMAND_ROWS", "5")), "required": False},
}
MIN_PROCESSED_ROWS = int(os.getenv("AI_CUSTOMER_MIN_PROCESSED_ROWS", "200"))
MIN_USABLE_ZONES = int(os.getenv("AI_CUSTOMER_MIN_USABLE_ZONES", "2"))
SHARED_MIN_CUSTOMERS = int(os.getenv("AI_SHARED_MIN_CUSTOMERS", "3"))
SHARED_MIN_PROCESSED_ROWS_PER_CUSTOMER = int(
    os.getenv("AI_SHARED_MIN_PROCESSED_ROWS_PER_CUSTOMER", "40")
)
SHARED_MAX_PROCESSED_ROWS_PER_CUSTOMER = int(
    os.getenv("AI_SHARED_MAX_PROCESSED_ROWS_PER_CUSTOMER", "5000")
)
SHARED_HISTORY_KEEP = max(1, int(os.getenv("AI_SHARED_HISTORY_KEEP", "3")))


class CustomerDatasetInsufficientError(RuntimeError):
    pass


def _safe_customer_id(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    if not safe:
        raise ValueError("customer_id rỗng hoặc không hợp lệ")
    return safe


def list_customer_group_counts(database_url: str) -> dict[str, dict[str, int]]:
    query = """
      WITH active_customers AS (
        SELECT DISTINCT c.customer_id
        FROM user_db.customers c
        JOIN farm_db.farms f ON f.customer_id=c.customer_id
        WHERE c.status='active'
      ), counts AS (
        SELECT f.customer_id,'sensor_readings'::text group_name,count(*)::bigint row_count
        FROM farm_db.sensor_readings r JOIN farm_db.farms f ON f.farm_id=r.farm_id GROUP BY f.customer_id
        UNION ALL
        SELECT f.customer_id,'device_status',count(*)
        FROM farm_db.device_status s JOIN farm_db.devices d ON d.device_id=s.device_id
        JOIN farm_db.farms f ON f.farm_id=d.farm_id GROUP BY f.customer_id
        UNION ALL
        SELECT f.customer_id,'telemetry_ingest_events',count(*)
        FROM farm_db.telemetry_ingest_events e JOIN farm_db.farms f ON f.farm_id=e.farm_id GROUP BY f.customer_id
        UNION ALL
        SELECT f.customer_id,'irrigation_runs',count(*)
        FROM farm_db.irrigation_runs r JOIN farm_db.farms f ON f.farm_id=r.farm_id GROUP BY f.customer_id
        UNION ALL
        SELECT f.customer_id,'alerts',count(*)
        FROM farm_db.alerts a JOIN farm_db.farms f ON f.farm_id=a.farm_id GROUP BY f.customer_id
        UNION ALL
        SELECT f.customer_id,'control_commands',count(*)
        FROM farm_db.control_commands c JOIN farm_db.farms f ON f.farm_id=c.farm_id GROUP BY f.customer_id
      )
      SELECT a.customer_id,names.group_name,coalesce(c.row_count,0) row_count
      FROM active_customers a CROSS JOIN (SELECT unnest(%s::text[]) group_name) names
      LEFT JOIN counts c ON c.customer_id=a.customer_id AND c.group_name=names.group_name
      ORDER BY a.customer_id,names.group_name
    """
    result: dict[str, dict[str, int]] = {}
    with psycopg.connect(database_url, row_factory=dict_row) as db, db.cursor() as cur:
        cur.execute(query, (list(GROUP_POLICIES),))
        for row in cur.fetchall():
            result.setdefault(str(row["customer_id"]), {})[str(row["group_name"])] = int(row["row_count"] or 0)
    return result


def load_watermark(database_url: str, customer_id: str) -> dict[str, Any]:
    with psycopg.connect(database_url, row_factory=dict_row) as db, db.cursor() as cur:
        cur.execute("SELECT * FROM knowledge_db.customer_ml_watermarks WHERE customer_id=%s", (customer_id,))
        row = cur.fetchone()
    return dict(row) if row else {"customer_id": customer_id, "last_training_status": "never", "last_group_counts": {}}


def training_decision(counts: dict[str, int], watermark: dict[str, Any]) -> dict[str, Any]:
    previous = dict(watermark.get("last_group_counts") or {})
    missing_minimum = {
        group: {"actual": int(counts.get(group, 0)), "required": int(policy["minimum_rows"])}
        for group, policy in GROUP_POLICIES.items()
        if bool(policy["required"]) and int(counts.get(group, 0)) < int(policy["minimum_rows"])
    }
    deltas = {group: max(0, int(counts.get(group, 0)) - int(previous.get(group, 0))) for group in GROUP_POLICIES}
    reached_delta = {
        group: {"new_rows": delta, "threshold": int(GROUP_POLICIES[group]["new_rows"])}
        for group, delta in deltas.items()
        if delta >= int(GROUP_POLICIES[group]["new_rows"])
    }
    first_run = watermark.get("last_training_status") in {None, "never"} or not previous
    eligible = not missing_minimum and (first_run or bool(reached_delta))
    return {
        "eligible": eligible,
        "first_run": first_run,
        "counts": counts,
        "previous_counts": previous,
        "new_rows": deltas,
        "missing_minimum": missing_minimum,
        "reached_retrain_threshold": reached_delta,
        "policy": GROUP_POLICIES,
    }


def _rewrite_paths(value: Any, old_root: Path, new_root: Path) -> Any:
    if isinstance(value, dict):
        return {key: _rewrite_paths(item, old_root, new_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_paths(item, old_root, new_root) for item in value]
    if isinstance(value, str) and value.startswith(str(old_root)):
        return str(new_root) + value[len(str(old_root)):]
    return value


def active_manifest_path(artifact_root: str | Path, customer_id: str) -> Path:
    return Path(artifact_root) / "customers" / _safe_customer_id(customer_id) / "active_models.json"


def load_active_manifest(artifact_root: str | Path, customer_id: str) -> dict[str, Any]:
    path = active_manifest_path(artifact_root, customer_id)
    if not path.exists():
        return {"customer_id": customer_id, "models": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _publish_candidate(
    artifact_root: Path,
    customer_id: str,
    staging_root: Path,
    report: dict[str, Any],
) -> dict[str, Any]:
    customer_root = artifact_root / "customers" / _safe_customer_id(customer_id)
    candidate_root = customer_root / "candidates" / report["dataset_version"]
    candidate_root.parent.mkdir(parents=True, exist_ok=True)
    if candidate_root.exists():
        raise RuntimeError(f"Candidate đã tồn tại: {candidate_root}")
    candidate_root.mkdir(parents=True)
    (staging_root / "shared").rename(candidate_root / "shared")
    final_report = _rewrite_paths(copy.deepcopy(report), staging_root, candidate_root)
    (candidate_root / "suite_report.json").write_text(
        json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for model in final_report.get("models", []):
        report_path = candidate_root / "shared" / model["model_name"] / f"v{model['model_version']}" / "report.json"
        report_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")

    active = load_active_manifest(artifact_root, customer_id)
    active.setdefault("models", {})
    activated: list[str] = []
    retained: list[str] = []
    for model in final_report.get("models", []):
        name = model["model_name"]
        if model.get("deployment_status") == "approved":
            active["models"][name] = {
                "model_name": name,
                "model_version": model["model_version"],
                "dataset_version": final_report["dataset_version"],
                "artifact_path": model["artifact_path"],
                "activated_at": datetime.now(timezone.utc).isoformat(),
                "quality_gate": model.get("quality_gate", {}),
            }
            activated.append(name)
        elif name in active["models"]:
            retained.append(name)
    active.update({
        "customer_id": customer_id,
        "scope_type": "customer",
        "activation_environment": "simulator_evaluation_only",
        "production_ready": False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "latest_candidate_dataset_version": final_report["dataset_version"],
        "activated_from_latest_candidate": activated,
        "retained_previous_approved": retained,
    })
    active_path = active_manifest_path(artifact_root, customer_id)
    active_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = active_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(active, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(active_path)
    final_report["active_manifest"] = str(active_path)
    final_report["activated_model_count"] = len(activated)
    final_report["total_active_model_count"] = len(active["models"])
    final_report["retained_previous_approved"] = retained
    (candidate_root / "suite_report.json").write_text(
        json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return final_report


def _persist_report(database_url: str, customer_id: str, report: dict[str, Any], counts: dict[str, int]) -> None:
    active = load_active_manifest(Path(report["artifact_root"]), customer_id)
    with psycopg.connect(database_url, row_factory=dict_row) as db, db.cursor() as cur:
        for model in report.get("models", []):
            candidate_id = f"candidate:{customer_id}:{report['dataset_version']}:{model['model_name']}"
            cur.execute(
                """INSERT INTO knowledge_db.model_evaluations(
                     model_id,farm_id,model_name,task,dataset_version,train_count,test_count,split_time,
                     metrics,evaluation_chart,importance_chart,evaluated_at,evaluation_scope,evaluation_key,
                     validation_count,lofo_metrics
                   ) VALUES (%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),'customer',%s,%s,%s)
                   ON CONFLICT(model_id) DO NOTHING""",
                (
                    candidate_id, model["model_name"], model["task"], report["dataset_version"],
                    model["train_count"], model["test_count"], model["validation_end"],
                    Jsonb(model["test_metrics"]), model["evaluation_chart"], model["importance_chart"],
                    customer_id, model["validation_count"], Jsonb(model.get("generalization_holdout", {})),
                ),
            )
        for name, active_model in active.get("models", {}).items():
            model = next((item for item in report.get("models", []) if item["model_name"] == name), None)
            if model is None or model.get("deployment_status") != "approved":
                continue
            model_id = f"active:{customer_id}:{name}"
            cur.execute(
                """INSERT INTO knowledge_db.model_registry(
                     model_id,farm_id,zone_id,metric_type,model_type,trained_at,sample_count,
                     training_window_hours,metrics,status,artifact_path,dataset_version,train_count,test_count,
                     split_strategy,feature_names,model_family,model_version,scope_type,scope_key,task,
                     artifact_uri,training_origin_mix,training_phase,deployment_status,quality_gate,dataset_source
                   ) VALUES (%s,NULL,NULL,%s,%s,now(),%s,%s,%s,'approved',%s,%s,%s,%s,%s,%s,%s,%s,
                             'customer',%s,%s,%s,%s,'runtime_retrain','approved',%s,%s)
                   ON CONFLICT(model_id) DO UPDATE SET
                     trained_at=now(),sample_count=EXCLUDED.sample_count,metrics=EXCLUDED.metrics,
                     artifact_path=EXCLUDED.artifact_path,dataset_version=EXCLUDED.dataset_version,
                     train_count=EXCLUDED.train_count,test_count=EXCLUDED.test_count,
                     split_strategy=EXCLUDED.split_strategy,artifact_uri=EXCLUDED.artifact_uri,
                     training_origin_mix=EXCLUDED.training_origin_mix,deployment_status='approved',
                     quality_gate=EXCLUDED.quality_gate,dataset_source=EXCLUDED.dataset_source""",
                (
                    model_id, name, model["task"], model["train_count"] + model["validation_count"] + model["test_count"],
                    14 * 24, Jsonb(model["test_metrics"]), active_model["artifact_path"], report["dataset_version"],
                    model["train_count"], model["test_count"], model["split_strategy"], Jsonb(FEATURES), name,
                    model["model_version"], customer_id, model["task"], active_model["artifact_path"],
                    Jsonb((report.get("dataset_metadata") or {}).get("origin_mix", {})),
                    Jsonb(model.get("quality_gate", {})), report.get("dataset_source", "v10_runtime_csv_snapshot"),
                ),
            )
        cur.execute(
            """INSERT INTO knowledge_db.customer_ml_watermarks(
                 customer_id,last_snapshot_id,last_dataset_version,last_group_counts,last_training_status,
                 last_finished_at,last_error,active_model_count,updated_at
               ) VALUES (%s,%s,%s,%s,'success',now(),NULL,%s,now())
               ON CONFLICT(customer_id) DO UPDATE SET
                 last_snapshot_id=EXCLUDED.last_snapshot_id,last_dataset_version=EXCLUDED.last_dataset_version,
                 last_group_counts=EXCLUDED.last_group_counts,last_training_status='success',
                 last_finished_at=now(),last_error=NULL,active_model_count=EXCLUDED.active_model_count,updated_at=now()""",
            (
                customer_id, (report.get("dataset_metadata") or {}).get("runtime_snapshot_id"),
                report["dataset_version"], Jsonb(counts), len(active.get("models", {})),
            ),
        )
        cur.execute(
            """INSERT INTO farm_db.ai_training_runs(
                 customer_id,farm_id,dataset_version,model_count,train_count,test_count,status,detail,finished_at
               ) VALUES (%s,NULL,%s,%s,%s,%s,'success',%s,now())""",
            (
                customer_id, report["dataset_version"], report["model_count"], report["train_count"],
                report["test_count"], Jsonb({
                    "scope_type": "customer", "customer_id": customer_id,
                    "snapshot_id": (report.get("dataset_metadata") or {}).get("runtime_snapshot_id"),
                    "validation_count": report["validation_count"],
                    "approved_model_count": report.get("approved_model_count", 0),
                    "active_model_count": len(active.get("models", {})),
                    "group_counts": counts,
                }),
            ),
        )
        db.commit()


def mark_training_started(database_url: str, customer_id: str) -> None:
    with psycopg.connect(database_url) as db:
        db.execute(
            """INSERT INTO knowledge_db.customer_ml_watermarks(customer_id,last_training_status,last_started_at,updated_at)
               VALUES (%s,'running',now(),now())
               ON CONFLICT(customer_id) DO UPDATE SET last_training_status='running',last_started_at=now(),last_error=NULL,updated_at=now()""",
            (customer_id,),
        )
        db.commit()


def mark_training_failed(database_url: str, customer_id: str, error: str) -> None:
    with psycopg.connect(database_url) as db:
        db.execute(
            """INSERT INTO knowledge_db.customer_ml_watermarks(customer_id,last_training_status,last_finished_at,last_error,updated_at)
               VALUES (%s,'failed',now(),%s,now())
               ON CONFLICT(customer_id) DO UPDATE SET last_training_status='failed',last_finished_at=now(),last_error=%s,updated_at=now()""",
            (customer_id, error[:4000], error[:4000]),
        )
        db.commit()


def mark_training_insufficient(
    database_url: str,
    customer_id: str,
    snapshot_id: str,
    counts: dict[str, int],
    error: str,
) -> None:
    with psycopg.connect(database_url) as db:
        db.execute(
            """INSERT INTO knowledge_db.customer_ml_watermarks(
                 customer_id,last_snapshot_id,last_group_counts,last_training_status,last_finished_at,last_error,updated_at
               ) VALUES (%s,%s,%s,'insufficient_data',now(),%s,now())
               ON CONFLICT(customer_id) DO UPDATE SET
                 last_snapshot_id=EXCLUDED.last_snapshot_id,last_group_counts=EXCLUDED.last_group_counts,
                 last_training_status='insufficient_data',last_finished_at=now(),last_error=EXCLUDED.last_error,updated_at=now()""",
            (customer_id, snapshot_id, Jsonb(counts), error[:4000]),
        )
        db.commit()


def train_customer_suite(
    database_url: str,
    artifact_root: str | Path,
    customer_id: str,
    counts: dict[str, int],
    *,
    days: int = 14,
    estimators: int = 90,
) -> dict[str, Any]:
    """Snapshot -> CSV processing -> temporal split -> candidate -> atomic activation."""
    customer_id = _safe_customer_id(customer_id)
    artifact_root = Path(artifact_root)
    customer_data_root = artifact_root / "data" / "customers" / customer_id
    policy_path = artifact_root / "data" / "training_policy.json"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(
        json.dumps({
            "scope": "per_customer",
            "group_policies": GROUP_POLICIES,
            "split_strategy": "chronological_70_15_15_on_unique_timestamps",
            "candidate_selection": "validation_only",
            "test_usage": "final_evaluation_only",
            "activation": "approved_candidates_only; retain previous approved model when candidate fails",
            "chat_messages_used_for_training": False,
            "processed_data_gate": {
                "minimum_rows": MIN_PROCESSED_ROWS,
                "minimum_usable_zones": MIN_USABLE_ZONES,
            },
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    mark_training_started(database_url, customer_id)
    staging_root = artifact_root / ".training" / f"customer-{customer_id}-{uuid.uuid4().hex}"
    try:
        snapshot = export_customer_training_snapshot(database_url, artifact_root / "data", customer_id)
        snapshot_dir = Path(snapshot["manifest_path"]).parent
        dataset_meta = build_database_training_dataset(
            database_url,
            customer_data_root,
            lookback_days=days,
            freq_minutes=15,
            snapshot_at=snapshot["database_snapshot_at"],
            runtime_snapshot_dir=snapshot_dir,
        )
        frame = dataset_meta.pop("frame")
        usable_zones = int(frame["zone_id"].nunique())
        if len(frame) < MIN_PROCESSED_ROWS or usable_zones < MIN_USABLE_ZONES:
            reason = (
                f"Dataset sau xử lý chỉ có {len(frame)} mẫu/{usable_zones} khu; "
                f"cần tối thiểu {MIN_PROCESSED_ROWS} mẫu/{MIN_USABLE_ZONES} khu."
            )
            mark_training_insufficient(database_url, customer_id, snapshot["snapshot_id"], counts, reason)
            raise CustomerDatasetInsufficientError(reason)
        dataset_meta.update({
            "runtime_snapshot_id": snapshot["snapshot_id"],
            "runtime_snapshot_manifest": snapshot["manifest_path"],
            "group_counts_at_snapshot": counts,
            "customer_id": customer_id,
            "chat_messages_used_for_training": False,
            "identity_columns_are_features": False,
        })
        candidate_root = artifact_root / "customers" / customer_id / "candidates" / dataset_meta["dataset_version"]
        report = train_shared_suite(
            staging_root,
            days=days,
            estimators=estimators,
            run_lofo=True,
            training_frame=frame,
            dataset_version=dataset_meta["dataset_version"],
            dataset_source="v10_runtime_csv_snapshot",
            dataset_metadata=dataset_meta,
            evidence_root=customer_data_root / "processed",
            published_artifact_root=candidate_root,
            scope_type="customer",
            scope_key=customer_id,
            generalization_column="zone_id",
            generalization_label="khu canh tác",
            minimum_generalization_groups=2,
        )
        report["artifact_root"] = str(artifact_root)
        report["training_phase"] = "runtime_retrain"
        report["production_ready"] = False
        final_report = _publish_candidate(artifact_root, customer_id, staging_root, report)
        _persist_report(database_url, customer_id, final_report, counts)
        customer_root = artifact_root / "customers" / customer_id
        (customer_root / "latest_training_report.json").write_text(
            json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return final_report
    except CustomerDatasetInsufficientError:
        raise
    except Exception as exc:
        mark_training_failed(database_url, customer_id, str(exc))
        raise
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def shared_active_manifest_path(artifact_root: str | Path) -> Path:
    return Path(artifact_root) / "shared" / "active_models.json"


def load_shared_active_manifest(artifact_root: str | Path) -> dict[str, Any]:
    path = shared_active_manifest_path(artifact_root)
    if not path.exists():
        return {
            "architecture": "shared_base_models_with_customer_calibration",
            "scope_type": "global",
            "scope_key": "all_customers",
            "models": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _history_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _remove_history_path(base: Path, target: Path, removed: list[dict[str, Any]]) -> None:
    base = base.resolve()
    target = target.resolve()
    if base not in target.parents or not target.exists():
        return
    size = _history_size(target)
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    removed.append({"path": str(target), "bytes": size})


def prune_shared_history(
    artifact_root: str | Path,
    *,
    preserve_dataset_versions: set[str] | None = None,
    keep_latest: int = SHARED_HISTORY_KEEP,
) -> dict[str, Any]:
    """Giữ một số phiên gần nhất và mọi dataset đang active; dọn snapshot/CSV không còn tham chiếu."""
    artifact_root = Path(artifact_root).resolve()
    shared_root = artifact_root / "shared"
    candidates_root = shared_root / "candidates"
    preserved = set(preserve_dataset_versions or set())
    active = load_shared_active_manifest(artifact_root)
    preserved.update(
        str(item.get("dataset_version"))
        for item in (active.get("models") or {}).values()
        if item.get("dataset_version")
    )

    candidate_dirs = sorted(
        [item for item in candidates_root.iterdir() if item.is_dir()] if candidates_root.exists() else [],
        key=lambda item: (item.stat().st_mtime_ns, item.name),
        reverse=True,
    )
    preserved.update(item.name for item in candidate_dirs[: max(1, int(keep_latest))])

    reports: list[dict[str, Any]] = []
    for candidate in candidate_dirs:
        if candidate.name not in preserved:
            continue
        report_path = candidate / "suite_report.json"
        if report_path.exists():
            try:
                reports.append(json.loads(report_path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass

    referenced_snapshots: dict[str, set[str]] = {}
    referenced_processed: dict[str, set[str]] = {}
    for report in reports:
        for source in (report.get("dataset_metadata") or {}).get("customer_sources", []):
            customer_id = str(source.get("customer_id") or "")
            if not customer_id:
                continue
            snapshot_id = source.get("snapshot_id")
            if snapshot_id:
                referenced_snapshots.setdefault(customer_id, set()).add(str(snapshot_id))
            processed_version = source.get("source_dataset_version") or source.get("dataset_version")
            if not processed_version and source.get("processed_csv"):
                processed_version = Path(str(source["processed_csv"]).replace("\\", "/")).parent.name
            if processed_version:
                referenced_processed.setdefault(customer_id, set()).add(str(processed_version))

    removed: list[dict[str, Any]] = []
    for candidate in candidate_dirs:
        if candidate.name not in preserved:
            _remove_history_path(candidates_root, candidate, removed)

    shared_data_root = artifact_root / "data" / "shared" / "processed"
    if shared_data_root.exists():
        for directory in shared_data_root.iterdir():
            if directory.is_dir() and directory.name not in preserved:
                _remove_history_path(shared_data_root, directory, removed)

    customers_root = artifact_root / "data" / "customers"
    if customers_root.exists():
        for customer_root in customers_root.iterdir():
            if not customer_root.is_dir():
                continue
            customer_id = customer_root.name
            for folder_name, keep_names in (
                ("snapshots", referenced_snapshots.get(customer_id, set())),
                ("processed", referenced_processed.get(customer_id, set())),
            ):
                folder = customer_root / folder_name
                if not folder.exists():
                    continue
                for directory in folder.iterdir():
                    if directory.is_dir() and directory.name not in keep_names:
                        _remove_history_path(folder, directory, removed)
            datasets = customer_root / "datasets"
            if datasets.exists():
                keep_names = referenced_processed.get(customer_id, set())
                for file_path in datasets.iterdir():
                    if file_path.is_file() and file_path.stem not in keep_names:
                        _remove_history_path(datasets, file_path, removed)

    return {
        "policy": "keep newest shared runs plus every dataset referenced by an active model",
        "keep_latest": max(1, int(keep_latest)),
        "preserved_dataset_versions": sorted(preserved),
        "removed_count": len(removed),
        "removed_bytes": sum(item["bytes"] for item in removed),
        "removed": removed,
    }


def cleanup_legacy_shared_layout(artifact_root: str | Path) -> list[str]:
    """Dọn layout model global cũ sau khi layout candidate mới đã tồn tại."""
    shared_root = (Path(artifact_root) / "shared").resolve()
    latest = shared_root / "latest_training_report.json"
    candidates = shared_root / "candidates"
    if not latest.exists() or not candidates.exists():
        return []
    removed: list[str] = []
    targets = [shared_root / spec.name for spec in MODEL_SPECS]
    targets.extend([
        shared_root / "suite_report.json",
        shared_root / "suite_summary.png",
        shared_root / "training_dataset.parquet",
    ])
    for target in targets:
        resolved = target.resolve()
        if shared_root not in resolved.parents or not resolved.exists():
            continue
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
        removed.append(str(resolved))
    return removed


def _raw_minimum_missing(counts: dict[str, int]) -> dict[str, dict[str, int]]:
    return {
        group: {
            "actual": int(counts.get(group, 0)),
            "required": int(policy["minimum_rows"]),
        }
        for group, policy in GROUP_POLICIES.items()
        if bool(policy["required"])
        and int(counts.get(group, 0)) < int(policy["minimum_rows"])
    }


def prepare_shared_customer_pool_dataset(
    database_url: str,
    artifact_root: str | Path,
    counts_by_customer: dict[str, dict[str, int]],
    *,
    days: int = 14,
    freq_minutes: int = 15,
) -> dict[str, Any]:
    """Xuất CSV riêng từng khách hàng rồi ghép các mẫu đủ điều kiện để train model nền."""
    artifact_root = Path(artifact_root)
    data_root = artifact_root / "data"
    frames: list[pd.DataFrame] = []
    sources: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    policy_path = data_root / "training_policy.json"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(
        json.dumps(
            {
                "architecture": "shared_base_models_with_customer_calibration",
                "data_isolation": "immutable CSV snapshots are stored separately by customer_id",
                "model_count": len(MODEL_SPECS),
                "group_policies": GROUP_POLICIES,
                "minimum_customers": SHARED_MIN_CUSTOMERS,
                "minimum_processed_rows_per_customer": SHARED_MIN_PROCESSED_ROWS_PER_CUSTOMER,
                "maximum_processed_rows_per_customer": SHARED_MAX_PROCESSED_ROWS_PER_CUSTOMER,
                "customer_id_used_as_feature": False,
                "generalization_test": "leave_one_customer_out",
                "split_strategy": "chronological_70_15_15_on_unique_timestamps",
                "candidate_selection": "validation_only",
                "test_usage": "final_evaluation_only",
                "activation": "approved candidates only; keep the previous approved artifact when a candidate fails",
                "history_retention_latest_runs": SHARED_HISTORY_KEEP,
                "chat_messages_used_for_training": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    for raw_customer_id in sorted(counts_by_customer):
        customer_id = _safe_customer_id(raw_customer_id)
        counts = counts_by_customer[raw_customer_id]
        missing = _raw_minimum_missing(counts)
        if missing:
            skipped.append({
                "customer_id": customer_id,
                "reason": "raw_group_minimum_not_met",
                "missing_minimum": missing,
            })
            continue

        snapshot = export_customer_training_snapshot(
            database_url, data_root, customer_id
        )
        snapshot_dir = Path(snapshot["manifest_path"]).parent
        customer_data_root = data_root / "customers" / customer_id
        dataset_meta = build_database_training_dataset(
            database_url,
            customer_data_root,
            lookback_days=days,
            freq_minutes=freq_minutes,
            snapshot_at=snapshot["database_snapshot_at"],
            runtime_snapshot_dir=snapshot_dir,
        )
        frame = dataset_meta.pop("frame")
        processed_rows_before_cap = int(len(frame))
        if processed_rows_before_cap < SHARED_MIN_PROCESSED_ROWS_PER_CUSTOMER:
            skipped.append({
                "customer_id": customer_id,
                "snapshot_id": snapshot["snapshot_id"],
                "reason": "processed_row_minimum_not_met",
                "actual": processed_rows_before_cap,
                "required": SHARED_MIN_PROCESSED_ROWS_PER_CUSTOMER,
            })
            continue

        frame = frame.sort_values(["observed_at", "farm_id", "zone_code"])
        if len(frame) > SHARED_MAX_PROCESSED_ROWS_PER_CUSTOMER:
            frame = frame.tail(SHARED_MAX_PROCESSED_ROWS_PER_CUSTOMER).copy()

        processed_root = customer_data_root / "processed" / dataset_meta["dataset_version"]
        processed_root.mkdir(parents=True, exist_ok=True)
        processed_csv = processed_root / "01_processed_features_targets.csv"
        frame.to_csv(processed_csv, index=False, encoding="utf-8-sig")
        source_manifest = processed_root / "source_manifest.json"
        source_record = {
            "customer_id": customer_id,
            "snapshot_id": snapshot["snapshot_id"],
            "snapshot_manifest": snapshot["manifest_path"],
            "snapshot_raw_directory": snapshot.get("raw_directory"),
            "processed_csv": str(processed_csv),
            "dataset_parquet": dataset_meta["artifact_path"],
            "dataset_version": dataset_meta["dataset_version"],
            "raw_group_counts": counts,
            "raw_sensor_reading_count": dataset_meta.get("raw_reading_count", 0),
            "processed_rows_before_cap": processed_rows_before_cap,
            "processed_rows_used": int(len(frame)),
            "farm_count": dataset_meta.get("farm_count", 0),
            "zone_count": dataset_meta.get("zone_count", 0),
            "checksum_sha256": dataset_meta.get("checksum_sha256"),
            "customer_id_used_as_feature": False,
        }
        source_manifest.write_text(
            json.dumps(source_record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        source_record["source_manifest"] = str(source_manifest)
        sources.append(source_record)
        frames.append(frame)

    if len(frames) < SHARED_MIN_CUSTOMERS:
        raise CustomerDatasetInsufficientError(
            f"Chỉ có {len(frames)} khách hàng đủ dữ liệu sau xử lý; "
            f"cần tối thiểu {SHARED_MIN_CUSTOMERS} để kiểm định leave-one-customer-out."
        )

    pooled = pd.concat(frames, ignore_index=True).sort_values(
        ["observed_at", "customer_id", "farm_id", "zone_code"]
    ).reset_index(drop=True)
    source_fingerprint = "|".join(
        f"{item['customer_id']}:{item['checksum_sha256']}:{item['processed_rows_used']}"
        for item in sources
    )
    checksum = hashlib.sha256(source_fingerprint.encode("utf-8")).hexdigest()
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
        "skipped_customers": skipped,
        "row_count": int(len(pooled)),
        "raw_reading_count": int(sum(item["raw_sensor_reading_count"] for item in sources)),
        "farm_count": int(pooled["farm_id"].nunique()),
        "zone_count": int(pooled[["farm_id", "zone_code"]].drop_duplicates().shape[0]),
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
                "count": int(sum(item["raw_sensor_reading_count"] for item in sources)),
                "ratio": 1.0,
            }
        },
        "label_method": "weak_labels_from_observable_rules",
        "customer_id_used_as_feature": False,
        "chat_messages_used_for_training": False,
        "balancing_policy": (
            f"latest_at_most_{SHARED_MAX_PROCESSED_ROWS_PER_CUSTOMER}_processed_rows_per_customer"
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return {**metadata, "frame": pooled}


def publish_shared_candidate(
    artifact_root: str | Path,
    staging_root: str | Path,
    report: dict[str, Any],
) -> dict[str, Any]:
    """Lưu candidate bất biến và cập nhật manifest active theo quality gate."""
    artifact_root = Path(artifact_root)
    staging_root = Path(staging_root)
    shared_root = artifact_root / "shared"
    candidate_root = shared_root / "candidates" / report["dataset_version"]
    candidate_shared = candidate_root / "shared"
    if candidate_root.exists():
        raise RuntimeError(f"Shared candidate đã tồn tại: {candidate_root}")
    candidate_root.mkdir(parents=True, exist_ok=False)
    (staging_root / "shared").rename(candidate_shared)

    final_report = _rewrite_paths(copy.deepcopy(report), staging_root, candidate_root)
    active = load_shared_active_manifest(artifact_root)
    active.setdefault("models", {})
    activated: list[str] = []
    retained: list[str] = []
    for model in final_report.get("models", []):
        name = model["model_name"]
        if model.get("deployment_status") == "approved":
            active["models"][name] = {
                "model_name": name,
                "model_version": model["model_version"],
                "dataset_version": final_report["dataset_version"],
                "artifact_path": model["artifact_path"],
                "report_path": str(
                    candidate_shared
                    / name
                    / f"v{model['model_version']}"
                    / "report.json"
                ),
                "activated_at": datetime.now(timezone.utc).isoformat(),
                "quality_gate": model.get("quality_gate", {}),
            }
            activated.append(name)
        elif name in active["models"]:
            retained.append(name)

    active.update({
        "architecture": "shared_base_models_with_customer_calibration",
        "scope_type": "global",
        "scope_key": "all_customers",
        "customer_count": (final_report.get("dataset_metadata") or {}).get("customer_count", 0),
        "latest_candidate_dataset_version": final_report["dataset_version"],
        "activated_from_latest_candidate": activated,
        "retained_previous_approved": retained,
        "active_model_count": len(active["models"]),
        "production_ready": False,
        "activation_environment": "simulator_evaluation_only",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })

    final_report.update({
        "architecture": "shared_base_models_with_customer_calibration",
        "active_manifest": str(shared_active_manifest_path(artifact_root)),
        "activated_model_count": len(activated),
        "total_active_model_count": len(active["models"]),
        "retained_previous_approved": retained,
        "candidate_directory": str(candidate_root),
        "suite_summary_chart": str(candidate_shared / "suite_summary.png"),
        "production_ready": False,
    })
    (candidate_root / "suite_report.json").write_text(
        json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (candidate_shared / "suite_report.json").write_text(
        json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for model in final_report.get("models", []):
        model_path = (
            candidate_shared
            / model["model_name"]
            / f"v{model['model_version']}"
            / "report.json"
        )
        model_path.write_text(
            json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    shared_root.mkdir(parents=True, exist_ok=True)
    active_path = shared_active_manifest_path(artifact_root)
    active_tmp = active_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    active_tmp.write_text(json.dumps(active, ensure_ascii=False, indent=2), encoding="utf-8")
    active_tmp.replace(active_path)
    latest_path = shared_root / "latest_training_report.json"
    latest_tmp = latest_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    latest_tmp.write_text(
        json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest_tmp.replace(latest_path)
    (artifact_root / "shared_models_report.json").write_text(
        json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    retention = prune_shared_history(
        artifact_root,
        preserve_dataset_versions={final_report["dataset_version"]},
    )
    final_report["history_retention"] = retention
    (candidate_root / "suite_report.json").write_text(
        json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (candidate_shared / "suite_report.json").write_text(
        json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest_tmp = latest_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    latest_tmp.write_text(
        json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest_tmp.replace(latest_path)
    (artifact_root / "shared_models_report.json").write_text(
        json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return final_report


def write_human_training_report(
    artifact_root: str | Path,
    report: dict[str, Any],
) -> Path:
    """Tạo một báo cáo Markdown ổn định để sinh viên có thể trình bày và trích dẫn."""
    artifact_root = Path(artifact_root)
    report_root = artifact_root / "reports" / report["dataset_version"]
    report_root.mkdir(parents=True, exist_ok=True)
    latest_path = artifact_root / "reports" / "LATEST_TRAINING_REPORT.md"
    version_path = report_root / "TRAINING_REPORT.md"
    meta = report.get("dataset_metadata") or {}

    lines = [
        "# Báo cáo huấn luyện 10 model AI nền dùng chung",
        "",
        f"- Dataset version: `{report['dataset_version']}`",
        f"- Thời điểm train: `{report.get('trained_at')}`",
        f"- Kiến trúc: `{report.get('architecture')}`",
        f"- Dữ liệu sau xử lý: **{report.get('generated_rows', 0)} dòng**, "
        f"{meta.get('customer_count', 0)} khách hàng, {report.get('farm_count', 0)} vườn.",
        f"- Chia theo thời gian: train **{report.get('train_count', 0)}**, "
        f"validation **{report.get('validation_count', 0)}**, test **{report.get('test_count', 0)}**.",
        f"- Candidate đạt quality gate: **{report.get('approved_model_count', 0)}/10**; "
        f"model active sau phiên train: **{report.get('total_active_model_count', 0)}/10**.",
        "- Trạng thái dữ liệu: dữ liệu thiết bị mô phỏng đã hiệu chỉnh; nhãn phân loại là weak label. "
        "Vì vậy `production_ready = false`.",
        "",
        "## CSV đầu vào và khả năng truy vết",
        "",
        "Mỗi khách hàng có snapshot CSV riêng. `customer_id` có trong CSV/manifest để phân biệt chủ dữ liệu "
        "nhưng không nằm trong danh sách feature đưa vào model.",
        "",
        "| customer_id | Dòng dùng | Snapshot manifest | CSV sau xử lý |",
        "|---|---:|---|---|",
    ]
    for item in meta.get("customer_sources", []):
        lines.append(
            f"| `{item['customer_id']}` | {item['processed_rows_used']} | "
            f"`{item['snapshot_manifest']}` | `{item['processed_csv']}` |"
        )

    lines.extend([
        "",
        "## Quá trình train",
        "",
        "1. Khóa một snapshot nhất quán của từng khách hàng và ghi SHA-256 vào manifest.",
        "2. Làm sạch theo chiều thời gian: chuẩn hóa mốc 15 phút, chỉ forward-fill tối đa 2 bước; không backfill từ tương lai.",
        "3. Tạo 44 feature từ cảm biến, trạng thái thiết bị, lịch sử tưới, thời gian và cấu hình cây/vườn.",
        "4. Tạo 4 target hồi quy ở chân trời 30 phút và 6 target phân loại weak-label.",
        "5. Gộp các tập khách hàng đủ điều kiện; giới hạn số dòng mỗi khách để khách hàng lớn không lấn át.",
        "6. Chia 70/15/15 theo timestamp. Chọn Random Forest hoặc Extra Trees chỉ bằng validation; test chỉ dùng một lần để báo cáo cuối.",
        "7. Kiểm định leave-one-customer-out: lần lượt bỏ toàn bộ dữ liệu của một khách hàng ra để đo khả năng áp dụng cho khách hàng chưa thấy.",
        "8. Chỉ candidate vượt quality gate mới cập nhật active manifest; candidate thất bại không thay model active cũ.",
        "",
        "## Kết quả 10 model và ý nghĩa",
        "",
        "| Model | Bài toán | Thuật toán | Test chính | Trạng thái | Diễn giải |",
        "|---|---|---|---|---|---|",
    ])
    for model in report.get("models", []):
        metrics = model.get("test_metrics") or {}
        if model.get("task") == "regression":
            metric_text = (
                f"MAE={metrics.get('mae')}; RMSE={metrics.get('rmse')}; R²={metrics.get('r2')}"
            )
            r2 = metrics.get("r2")
            if isinstance(r2, (int, float)) and r2 >= 0.7:
                meaning = "Giải thích tốt biến thiên trên test; vẫn phải xem holdout khách hàng."
            elif isinstance(r2, (int, float)) and r2 >= 0.2:
                meaning = "Có tín hiệu dự báo nhưng sai số còn đáng kể."
            else:
                meaning = "Chưa chứng minh được khả năng dự báo ổn định."
        else:
            metric_text = (
                f"Accuracy={metrics.get('accuracy')}; F1-macro={metrics.get('f1_macro')}; "
                f"Recall-macro={metrics.get('recall_macro')}"
            )
            meaning = (
                "F1/recall đo đều các lớp; accuracy cao một mình có thể sai lệch khi lớp hiếm."
            )
        reasons = (model.get("quality_gate") or {}).get("reasons") or []
        if reasons:
            meaning += " Gate chưa đạt: " + "; ".join(str(x) for x in reasons)
        lines.append(
            f"| `{model['model_name']}` | {model['task']} | {model.get('algorithm')} | "
            f"{metric_text} | **{model.get('deployment_status')}** | {meaning} |"
        )

    lines.extend([
        "",
        "## Cách đọc các chỉ số",
        "",
        "- **MAE**: sai số tuyệt đối trung bình, cùng đơn vị với đại lượng dự báo; càng nhỏ càng tốt.",
        "- **RMSE**: giống MAE nhưng phạt mạnh lỗi lớn; RMSE cao hơn nhiều MAE cho thấy có một số lỗi lớn.",
        "- **R²**: phần biến thiên model giải thích được; gần 1 tốt, gần 0 không hơn dự báo trung bình, âm là kém hơn trung bình.",
        "- **F1-macro**: F1 tính đều cho từng lớp; phù hợp khi lớp lỗi/cảnh báo hiếm.",
        "- **Recall lớp rủi ro**: tỷ lệ sự cố thật được phát hiện; thấp nghĩa là model bỏ sót sự cố.",
        "- **Leave-one-customer-out**: bằng chứng model có thể tổng quát sang khách hàng chưa tham gia train.",
        "",
        "## Quy mô 500 khách hàng",
        "",
        "Hệ thống không tạo 10 model cho từng khách hàng. Với 500 khách hàng vẫn duy trì 10 model nền dùng chung. "
        "Dữ liệu, watermark và snapshot vẫn tách theo khách hàng. Mỗi vườn chỉ lưu bias/scale calibration nhỏ. "
        "Chỉ tạo model riêng trong trường hợp ngoại lệ khi có đủ dữ liệu gán nhãn và A/B test chứng minh cải thiện rõ ràng.",
        "",
        "## Tệp bằng chứng máy đọc",
        "",
        f"- Báo cáo JSON: `{artifact_root / 'shared' / 'latest_training_report.json'}`",
        f"- Active manifest: `{artifact_root / 'shared' / 'active_models.json'}`",
        f"- CSV metric: `{report.get('csv_evidence', {}).get('directory')}`",
        f"- Manifest CSV: `{report.get('csv_evidence', {}).get('manifest')}`",
    ])
    content = "\n".join(lines) + "\n"
    version_path.write_text(content, encoding="utf-8")
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(content, encoding="utf-8")
    return latest_path
