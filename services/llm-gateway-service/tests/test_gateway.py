from app.logic import deterministic_plan
from app import main
from fastapi.testclient import TestClient


def test_metric_plan():
    p = deterministic_plan("do am khu b gio bao nhieu")
    assert p["tool_name"] == "get_latest_metric"
    assert p["arguments"]["metric"] == "soil_moisture"
    assert p["arguments"]["zone"] == "B"


def test_crop_plan():
    p = deterministic_plan("vu toi nen trong cay gi")
    assert p["tool_name"] == "get_crop_recommendation"


def test_combined_operational_and_knowledge_plan():
    p = deterministic_plan("độ ẩm đất khu A thấp, tại sao và nên làm gì")
    assert [step["tool_name"] for step in p["steps"]] == ["get_latest_metric", "search_knowledge"]


def test_metric_without_zone_marks_missing_context():
    p = deterministic_plan("nhiệt độ hiện tại bao nhiêu")
    assert p["missing_context"] == ["zone"]


def test_reference_ph_question_routes_to_knowledge():
    p = deterministic_plan("pH tham khảo cho đất trồng cà chua là bao nhiêu?")
    assert [step["tool_name"] for step in p["steps"]] == ["search_knowledge"]


def test_metric_with_explicit_zone_is_operational_without_time_marker():
    p = deterministic_plan("độ ẩm đất khu C")
    assert p["tool_name"] == "get_latest_metric"
    assert p["arguments"]["zone"] == "C"


def test_general_device_question_routes_to_knowledge():
    p = deterministic_plan("Dữ liệu thiết bị cần gắn với thông tin gì?")
    assert p["tool_name"] == "search_knowledge"


def test_general_schedule_question_routes_to_knowledge():
    p = deterministic_plan("Lịch tưới theo CROPWAT dựa trên nguyên tắc gì?")
    assert p["tool_name"] == "search_knowledge"


def test_non_ai_model_phrase_routes_to_knowledge():
    p = deterministic_plan("Dưa lưới có phù hợp mô hình đầu tư thấp không?")
    assert p["tool_name"] == "search_knowledge"


def test_read_only_command_log_never_plans_control():
    p = deterministic_plan("xem nhật ký lệnh điều khiển")
    assert p["tool_name"] == "get_command_logs"
    assert all("execute" not in step["tool_name"] for step in p["steps"])


def test_ai_capability_plan():
    p = deterministic_plan("bach khoa AI co model nao cho vuon toi")
    assert p["tool_name"] == "get_ai_capabilities"


def test_plan_rejects_missing_internal_key(monkeypatch):
    monkeypatch.setattr(main, "INTERNAL_SERVICE_KEY", "unit-test-internal-key")
    response = TestClient(main.app).post(
        "/plan",
        json={"message": "độ ẩm", "farm_id": "farm_1", "allowed_farm_ids": ["farm_1"]},
    )
    assert response.status_code == 401


def test_plan_rejects_farm_outside_authorized_list(monkeypatch):
    monkeypatch.setattr(main, "INTERNAL_SERVICE_KEY", "unit-test-internal-key")
    response = TestClient(main.app).post(
        "/plan",
        headers={"X-Internal-Service-Key": "unit-test-internal-key"},
        json={"message": "độ ẩm", "farm_id": "farm_2", "allowed_farm_ids": ["farm_1"]},
    )
    assert response.status_code == 200
    assert response.json()["denied"] is True
