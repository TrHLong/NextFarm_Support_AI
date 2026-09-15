import json
from pathlib import Path

from app.customer_ml_automation import prune_shared_history


def _make_run(root: Path, dataset: str, customer: str = "customer_a") -> None:
    candidate = root / "shared" / "candidates" / dataset
    candidate.mkdir(parents=True)
    snapshot = f"snapshot_{dataset}"
    processed = f"processed_{dataset}"
    report = {
        "dataset_version": dataset,
        "dataset_metadata": {
            "customer_sources": [
                {
                    "customer_id": customer,
                    "snapshot_id": snapshot,
                    "source_dataset_version": processed,
                }
            ]
        },
    }
    (candidate / "suite_report.json").write_text(json.dumps(report), encoding="utf-8")
    (candidate / "payload.bin").write_bytes(dataset.encode("utf-8"))
    (root / "data" / "shared" / "processed" / dataset).mkdir(parents=True)
    (root / "data" / "customers" / customer / "snapshots" / snapshot).mkdir(parents=True)
    (root / "data" / "customers" / customer / "processed" / processed).mkdir(parents=True)


def test_prune_keeps_newest_and_active_dataset(tmp_path: Path):
    for dataset in ("run_1", "run_2", "run_3", "run_4"):
        _make_run(tmp_path, dataset)
    active = {
        "models": {
            "moisture_forecast": {"dataset_version": "run_1"}
        }
    }
    (tmp_path / "shared" / "active_models.json").write_text(json.dumps(active), encoding="utf-8")

    result = prune_shared_history(
        tmp_path,
        preserve_dataset_versions={"run_4"},
        keep_latest=2,
    )

    candidates = tmp_path / "shared" / "candidates"
    assert (candidates / "run_1").exists()
    assert (candidates / "run_3").exists()
    assert (candidates / "run_4").exists()
    assert not (candidates / "run_2").exists()
    assert not (tmp_path / "data" / "shared" / "processed" / "run_2").exists()
    assert not (tmp_path / "data" / "customers" / "customer_a" / "snapshots" / "snapshot_run_2").exists()
    assert result["removed_count"] >= 3
