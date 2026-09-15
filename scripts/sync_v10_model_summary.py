from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "model-artifacts" / "shared" / "latest_training_report.json"
SUMMARY_PATH = ROOT / "docs" / "evidence" / "shared-ml-latest.json"


def main() -> int:
    suite = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
    models = suite.get("models") or []
    if len(models) != 10:
        raise RuntimeError(f"Expected 10 current model evaluations, found {len(models)}")

    statuses = [model.get("deployment_status") for model in models]
    approved = statuses.count("approved")
    experimental = statuses.count("experimental")
    if approved != suite.get("approved_model_count") or experimental != suite.get("experimental_model_count"):
        raise RuntimeError("latest_training_report.json contains inconsistent deployment counters")

    metadata = suite.get("dataset_metadata") or {}
    dataset_version = suite.get("dataset_version")
    csv_directory = ROOT / "model-artifacts" / "data" / "shared" / "processed" / str(dataset_version)
    csv_manifest = csv_directory / "evidence_manifest.json"
    human_report = ROOT / "model-artifacts" / "reports" / "LATEST_TRAINING_REPORT.md"
    active_manifest = ROOT / "model-artifacts" / "shared" / "active_models.json"

    compact_models = []
    for model in models:
        compact_models.append(
            {
                "model_name": model.get("model_name"),
                "task": model.get("task"),
                "algorithm": model.get("algorithm"),
                "test_metrics": model.get("test_metrics"),
                "deployment_status": model.get("deployment_status"),
                "quality_gate_reasons": (model.get("quality_gate") or {}).get("reasons") or [],
            }
        )

    summary = {
        "architecture": suite.get("architecture"),
        "dataset_version": dataset_version,
        "customer_count": metadata.get("customer_count"),
        "processed_rows": metadata.get("row_count"),
        "train_count": suite.get("train_count"),
        "validation_count": suite.get("validation_count"),
        "test_count": suite.get("test_count"),
        "candidate_model_count": len(models),
        "approved_candidate_count": approved,
        "active_model_count": suite.get("total_active_model_count", 0),
        "production_ready": bool(suite.get("production_ready")),
        "human_report": str(human_report),
        "active_manifest": str(active_manifest),
        "csv_evidence": {
            "directory": str(csv_directory),
            "manifest": str(csv_manifest),
            "file_count": len(list(csv_directory.glob("*.csv"))) if csv_directory.exists() else 0,
            "chat_messages_used_for_training": bool(metadata.get("chat_messages_used_for_training", False)),
        },
        "customer_sources": metadata.get("customer_sources") or [],
        "models": compact_models,
    }

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = SUMMARY_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, SUMMARY_PATH)
    print(
        "[OK] Synchronized current V10 model evidence: "
        f"candidates={len(models)}, approved={approved}, active={summary['active_model_count']}, "
        f"production_ready={summary['production_ready']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
