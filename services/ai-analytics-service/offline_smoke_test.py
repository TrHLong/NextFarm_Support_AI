from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.ml_pipeline import train_shared_suite


def main() -> None:
    parser = argparse.ArgumentParser(description="Train/test 10 shared NextFarm model families.")
    parser.add_argument("--output", default="/models", help="Artifact root")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--estimators", type=int, default=25)
    parser.add_argument("--skip-lofo", action="store_true")
    args = parser.parse_args()
    report = train_shared_suite(
        Path(args.output),
        days=args.days,
        estimators=args.estimators,
        run_lofo=not args.skip_lofo,
        dataset_source="test_fixture",
    )
    summary = {
        "architecture": report["architecture"],
        "farm_count": report["farm_count"],
        "total_model_artifacts": report["total_model_artifacts"],
        "farm_specific_model_count": 0,
        "train_count": report["train_count"],
        "validation_count": report["validation_count"],
        "test_count": report["test_count"],
        "models": [
            {
                "model": model["model_name"],
                "task": model["task"],
                "test_metrics": model["test_metrics"],
                "lofo": model["leave_one_farm_out"],
            }
            for model in report["models"]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
