from app.logic import norm, resolve_crop_key
from app import main
from fastapi.testclient import TestClient


def test_norm_vi():
    assert norm("Sầu riêng") == "sau rieng"


def test_crop_resolution_without_db_catalog():
    catalog = [
        {"crop_key": "grape", "display_name_vi": "Nho", "aliases": ["grape"]},
        {"crop_key": "maize", "display_name_vi": "Ngô", "aliases": ["bắp", "corn"]},
    ]
    assert resolve_crop_key("NHO", catalog)[0] == "grape"
    assert resolve_crop_key("Bắp lai", catalog)[0] == "maize"


def test_catalog_endpoint_uses_runtime_catalog(monkeypatch):
    monkeypatch.setattr(
        main,
        "_catalog",
        lambda: [{"crop_key": "grape", "display_name_vi": "Nho", "aliases": ["nho"]}],
    )
    response = TestClient(main.app).get("/catalog/crops")
    assert response.status_code == 200
    assert response.json()["items"][0]["crop_key"] == "grape"


def test_farm_capabilities_requires_existing_zone(monkeypatch):
    monkeypatch.setattr(
        main,
        "_auth_user",
        lambda _authorization: {
            "user_id": "farmer_1",
            "farms": [{"farm_id": "farm_1", "can_read": True}],
        },
    )
    monkeypatch.setattr(
        main,
        "_farm_crop_rows",
        lambda _farm_id: [
            {"farm_id": "farm_1", "zone_id": None, "zone_code": None, "crop_key": "grape"},
            {"farm_id": "farm_1", "zone_id": "zone_a", "zone_code": "A", "crop_key": "grape"},
        ],
    )
    response = TestClient(main.app).get(
        "/farms/farm_1/capabilities?zone=Z",
        headers={"Authorization": "Bearer unit-test"},
    )
    assert response.status_code == 404


def test_farm_capabilities_returns_data_readiness(monkeypatch):
    monkeypatch.setattr(
        main,
        "_auth_user",
        lambda _authorization: {
            "user_id": "farmer_1",
            "farms": [{"farm_id": "farm_1", "can_read": True}],
        },
    )
    monkeypatch.setattr(
        main,
        "_farm_crop_rows",
        lambda _farm_id: [
            {"farm_id": "farm_1", "zone_id": "zone_a", "zone_code": "A", "crop_key": "grape"}
        ],
    )
    monkeypatch.setattr(
        main,
        "_resolve_capabilities",
        lambda crop_key, **_scope: (
            [{"capability_key": "sensor_quality_guard", "resolved_status": "ready"}],
            {"origin_kind": "demo", "production_data": False},
        ),
    )
    response = TestClient(main.app).get(
        "/farms/farm_1/capabilities?zone=A",
        headers={"Authorization": "Bearer unit-test"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["counts"]["ready"] == 1
    assert payload["readiness"]["origin_kind"] == "demo"
    assert payload["production_candidate"] is False
    assert payload["production_ready"] is False
