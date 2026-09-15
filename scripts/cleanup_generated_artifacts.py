from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


PRETRAIN_TARGETS = [
    "model-artifacts/.training",
    "model-artifacts/datasets",
    "model-artifacts/shared",
    "model-artifacts/shared_models_report.json",
    "model-artifacts/README.txt",
    "data/ml",
    "data/runtime_csv",
    "services/ai-analytics-service/app/__pycache__",
    "services/chatbot-service/app/__pycache__",
    "services/chatbot-service/tests/__pycache__",
    "scripts/export_train_runtime_ml.ps1",
    "scripts/export_train_runtime_ml.cmd",
]

POSTTRAIN_TARGETS = [
    "model-artifacts/customers",
    "model-artifacts/.training",
    "model-artifacts/data/shared/processed/nextfarm-v10.1-shared-customers-20260907T230218Z-cbd0f593ec9b",
    "model-artifacts/data/customers/customer_lan/snapshots/runtime_20260907T220251Z",
    "model-artifacts/data/customers/customer_lan/processed/nextfarm-v10.1-customer_lan-20260907T220300Z-b5349e76d1aa",
    "model-artifacts/data/customers/customer_lan/datasets/nextfarm-v10.1-customer_lan-20260907T220300Z-b5349e76d1aa.json",
    "model-artifacts/data/customers/customer_lan/datasets/nextfarm-v10.1-customer_lan-20260907T220300Z-b5349e76d1aa.parquet",
    "model-artifacts/data/customers/customer_long/snapshots/runtime_20260907T220310Z",
    "model-artifacts/data/customers/customer_long/processed/nextfarm-v10.1-customer_long-20260907T220323Z-2222bb001505",
    "model-artifacts/data/customers/customer_long/datasets/nextfarm-v10.1-customer_long-20260907T220323Z-2222bb001505.json",
    "model-artifacts/data/customers/customer_long/datasets/nextfarm-v10.1-customer_long-20260907T220323Z-2222bb001505.parquet",
    "docs/evidence/V10.1-AI-Model-Evidence.xlsx",
    "docs/evidence/runtime-ml-training-latest.json",
    "docs/evidence/v10-model-training-summary.json",
    "services/ai-analytics-service/app/__pycache__",
    "scripts/__pycache__",
]


def directory_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--phase", choices=("pretrain", "posttrain"), required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = args.project_root.resolve()
    targets = PRETRAIN_TARGETS if args.phase == "pretrain" else POSTTRAIN_TARGETS
    resolved = []
    for relative in targets:
        path = (root / relative).resolve()
        if root not in path.parents:
            raise RuntimeError(f"Đường dẫn dọn dẹp nằm ngoài dự án: {path}")
        resolved.append(
            {
                "relative_path": relative,
                "absolute_path": str(path),
                "existed": path.exists(),
                "bytes": directory_size(path) if path.exists() else 0,
            }
        )

    if args.apply:
        for item in resolved:
            path = Path(item["absolute_path"])
            if not path.exists():
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

    report = {
        "project_root": str(root),
        "phase": args.phase,
        "applied": args.apply,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "targets": resolved,
        "total_bytes_selected": sum(item["bytes"] for item in resolved),
        "all_absent_after_run": all(
            not Path(item["absolute_path"]).exists() for item in resolved
        ) if args.apply else None,
    }
    evidence = root / "docs" / "evidence" / f"cleanup-{args.phase}-latest.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
