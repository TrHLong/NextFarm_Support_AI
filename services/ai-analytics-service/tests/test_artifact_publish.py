from pathlib import Path

import app.main as analytics


def test_publish_suite_replaces_previous_directory_atomically(monkeypatch, tmp_path: Path):
    root = tmp_path / "models"
    previous = root / "shared"
    previous.mkdir(parents=True)
    (previous / "old.txt").write_text("old", encoding="utf-8")

    staging = root / ".training" / "run-1"
    model_dir = staging / "shared" / "moisture_forecast" / "v2.0.0"
    model_dir.mkdir(parents=True)
    (model_dir / "model.joblib").write_bytes(b"model")

    report = {
        "model_count": 1,
        "models": [{
            "model_name": "moisture_forecast",
            "model_version": "2.0.0",
            "artifact_path": str(model_dir / "model.joblib"),
            "evaluation_chart": str(model_dir / "evaluation.png"),
            "importance_chart": str(model_dir / "importance.png"),
            "per_farm_chart": str(model_dir / "per_farm.png"),
        }],
    }
    monkeypatch.setattr(analytics, "ARTIFACT_ROOT", root)
    published = analytics._publish_trained_suite(staging, report)

    assert not (root / "shared" / "old.txt").exists()
    assert (root / "shared" / "moisture_forecast" / "v2.0.0" / "model.joblib").exists()
    assert published["models"][0]["artifact_path"].startswith(str(root / "shared"))
    assert (root / "shared" / "suite_report.json").exists()
    assert (root / "shared_models_report.json").exists()
