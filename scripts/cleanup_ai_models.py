from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ARCHIVE_RELATIVE_PATHS = (
    "backup",
    "model-artifacts/data/customers",
    "model-artifacts/data/benchmark-retrain",
    "model-artifacts/data/device-v11",
    "model-artifacts/data/device-v11-corrected-20260910",
    "model-artifacts/data/device-v11-validation-b-20260910",
    "model-artifacts/data/historical-customer",
    "model-artifacts/data/shared",
    "model-artifacts/data/device-runtime",
    "model-artifacts/shared",
    "model-artifacts/shared_models_report.json",
    "model-artifacts/benchmark-retrain",
    "model-artifacts/historical-customer",
    "model-artifacts/device-v11",
    "model-artifacts/device-v11-candidate-b",
    "model-artifacts/device-v11-corrected-20260910",
    "model-artifacts/device-v11-validation-b-20260910",
    "model-artifacts/datasets",
    "model-artifacts/reports",
    "model-artifacts/farmer-v13",
)


def bytes_under(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.project_root.resolve()
    archive = args.archive_root.resolve()
    if archive == root or root in archive.parents:
        raise SystemExit("archive-root must be outside project-root")
    archive.mkdir(parents=True, exist_ok=True)
    entries = []
    for relative in ARCHIVE_RELATIVE_PATHS:
        source = (root / relative).resolve()
        if not source.exists():
            continue
        destination = archive / relative
        entries.append(
            {
                "path": relative,
                "source": str(source),
                "destination": str(destination),
                "bytes": bytes_under(source),
                "action": "MOVE" if args.apply else "PLAN",
            }
        )
        if args.apply:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise SystemExit(f"archive destination already exists: {destination}")
            shutil.move(str(source), str(destination))

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "archive_root": str(archive),
        "applied": args.apply,
        "entries": entries,
        "bytes_moved": sum(item["bytes"] for item in entries),
        "runtime_policy": {
            "auto_training": False,
            "farmer_ml_predictions": False,
            "kept": [
                "canonical query data",
                "operational data",
                "deterministic query/rule code",
                "model training source and evaluation scripts",
            ],
        },
    }
    report_path = root / "docs" / "evidence" / "AI_CLEANUP_MOVE.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
