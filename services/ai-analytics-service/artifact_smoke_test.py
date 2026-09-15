from __future__ import annotations

import json
import warnings
from pathlib import Path

import joblib
import numpy as np
from sklearn.exceptions import InconsistentVersionWarning


MODEL_ROOT = Path("/models")
LATEST_REPORT = MODEL_ROOT / "shared" / "latest_training_report.json"
ACTIVE_MANIFEST = MODEL_ROOT / "shared" / "active_models.json"


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"Missing model evidence file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_and_predict(path: Path, label: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{label}: artifact does not exist: {path}")
    bundle = joblib.load(path)
    features = bundle.get("features") or []
    if not features:
        raise RuntimeError(f"{label}: no feature contract in {path}")
    bundle["model"].predict(np.zeros((1, len(features)), dtype=float))


def main() -> None:
    warnings.simplefilter("error", InconsistentVersionWarning)
    latest = _read_json(LATEST_REPORT)
    models = latest.get("models") or []
    if len(models) != 10:
        raise RuntimeError(
            f"Expected 10 models in {LATEST_REPORT}, found {len(models)}."
        )

    names: set[str] = set()
    for item in models:
        name = str(item.get("model_name") or "").strip()
        if not name or name in names:
            raise RuntimeError(f"Invalid or duplicate model_name in latest report: {name!r}")
        names.add(name)
        path = Path(str(item.get("artifact_path") or ""))
        _load_and_predict(path, f"latest candidate {name}")

    active = _read_json(ACTIVE_MANIFEST)
    active_models = active.get("models") or {}
    for name, item in active_models.items():
        path = Path(str(item.get("artifact_path") or ""))
        _load_and_predict(path, f"active model {name}")

    dataset = latest.get("dataset_version")
    print(
        "10 latest candidate artifacts loaded and predicted successfully; "
        f"active={len(active_models)}; dataset_version={dataset}"
    )


if __name__ == "__main__":
    main()
