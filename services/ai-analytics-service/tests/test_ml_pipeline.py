from pathlib import Path

from app.ml_pipeline import (
    FARM_PROFILES,
    MODEL_SPECS,
    generate_shared_training_frame,
    generate_training_frame,
    shared_model_path,
    train_shared_suite,
)


def test_dataset_has_profiles_labels_and_temporal_targets():
    one_farm = generate_training_frame("farm_long", days=4, freq_minutes=15)
    assert len(one_farm) > 800
    assert one_farm["scenario_label"].nunique() >= 6
    assert one_farm["anomaly_label"].nunique() == 2
    assert one_farm["target_moisture_30m"].notna().all()
    assert {"crop_index", "climate_index", "moisture_target_mid"}.issubset(one_farm.columns)

    shared = generate_shared_training_frame(days=3, freq_minutes=15)
    assert set(shared["farm_id"].unique()) == set(FARM_PROFILES)
    assert shared["crop_index"].nunique() == 3


def test_train_ten_shared_models_no_per_farm_artifacts(tmp_path: Path):
    suite = train_shared_suite(tmp_path, days=3, estimators=12, run_lofo=True, dataset_source="test_fixture")
    assert suite["architecture"] == "multi_tenant_shared_models"
    assert suite["model_count"] == len(MODEL_SPECS) == 10
    assert suite["total_model_artifacts"] == 10
    assert suite["train_count"] > suite["validation_count"] > 0
    assert suite["test_count"] > 0
    assert not (tmp_path / "farm_long").exists()
    assert not (tmp_path / "farm_lan").exists()
    assert not (tmp_path / "farm_minh").exists()

    model_files = list((tmp_path / "shared").rglob("model.joblib"))
    assert len(model_files) == 10
    for spec in MODEL_SPECS:
        assert shared_model_path(tmp_path, spec.name).exists()

    for report in suite["models"]:
        assert Path(report["artifact_path"]).exists()
        assert Path(report["evaluation_chart"]).stat().st_size > 5000
        assert Path(report["importance_chart"]).exists()
        assert Path(report["per_farm_chart"]).exists()
        assert set(report["per_farm_metrics"]) == set(FARM_PROFILES)
        assert set(report["leave_one_farm_out"]) == set(FARM_PROFILES)
        assert report["scope_type"] == "global"
        assert report["deployment_status"] in {"approved", "experimental"}
        assert "passed" in report["quality_gate"]


def test_quality_gate_requires_cross_farm_validation_and_risk_class_recall():
    from app.ml_pipeline import _quality_gate

    regression = next(spec for spec in MODEL_SPECS if spec.name == "moisture_forecast")
    result = _quality_gate(
        regression,
        {"r2": 0.95},
        {},
        expected_farm_count=1,
    )
    assert result["deployment_status"] == "experimental"
    assert any("ít nhất 3" in reason for reason in result["reasons"])

    classifier = next(spec for spec in MODEL_SPECS if spec.name == "irrigation_failure")
    fold_metrics = {
        "f1_macro": 0.8,
        "true_labels": [0, 1],
        "per_class": {"0": {"recall": 0.9}, "1": {"recall": 0.7}},
    }
    lofo = {f"farm_{index}": {"metrics": fold_metrics} for index in range(3)}
    approved = _quality_gate(
        classifier,
        {"f1_macro": 0.82, "true_labels": [0, 1], "per_class": {"0": {"recall": 0.9}, "1": {"recall": 0.75}}},
        lofo,
        expected_farm_count=3,
        expected_classes=[0, 1],
    )
    assert approved["deployment_status"] == "approved"

    missing_risk = _quality_gate(
        classifier,
        {"f1_macro": 0.9, "true_labels": [0], "per_class": {"0": {"recall": 1.0}}},
        {f"farm_{index}": {"metrics": {"f1_macro": 0.9, "true_labels": [0], "per_class": {"0": {"recall": 1.0}}}} for index in range(3)},
        expected_farm_count=3,
        expected_classes=[0, 1],
    )
    assert missing_risk["deployment_status"] == "experimental"
    assert any("thiếu lớp thật" in reason or "recall" in reason for reason in missing_risk["reasons"])
