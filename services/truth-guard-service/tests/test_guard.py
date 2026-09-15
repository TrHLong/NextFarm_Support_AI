from app.guard_logic import evaluate_answer
from app import main
from fastapi.testclient import TestClient


def check(**kwargs):
    defaults = {
        "answer": "",
        "evidence": [],
        "confidence": 0.8,
        "min_confidence": 0.55,
        "requires_human": False,
        "knowledge_mode": False,
    }
    defaults.update(kwargs)
    return evaluate_answer(**defaults)


def test_rejects_ungrounded_number():
    result = check(answer="Độ ẩm là 99%.", evidence=[{"soil_moisture": 62}])
    assert result["allowed"] is False
    assert "99" in result["unmatched_numbers"]


def test_allows_grounded_number_and_source():
    result = check(
        answer="Độ ẩm là 62% theo dữ liệu mới nhất.",
        evidence=[{"soil_moisture": 62, "source_url": "https://nextfarm.vn/help-center"}],
        knowledge_mode=True,
    )
    assert result["allowed"] is True


def test_allows_probability_to_percent_conversion():
    result = check(
        answer="Độ tin cậy mô hình khoảng 83%.",
        evidence=[{"confidence": 0.83}],
    )
    assert result["allowed"] is True


def test_does_not_ground_number_from_source_url_or_identifier():
    result = check(
        answer="Độ ẩm là 99%.",
        evidence=[{"source_url": "https://example.test/report/99", "farm_id": "farm_99"}],
    )
    assert result["allowed"] is False
    assert "99" in result["unmatched_numbers"]


def test_rejects_absolute_certainty_percentage():
    result = check(answer="Kết quả này chính xác 100%.", evidence=[{"confidence_percent": 100}])
    assert result["allowed"] is False


def test_rejects_knowledge_without_citation():
    result = check(
        answer="Cà chua phù hợp nhất và chắc chắn cho năng suất cao.",
        evidence=[{"crop": "tomato"}],
        knowledge_mode=True,
    )
    assert result["allowed"] is False


def test_rejects_high_risk_action_without_human_confirmation():
    result = check(
        answer="Hãy bật van ngay trong 20 phút.",
        evidence=[{"duration_minutes": 20}],
    )
    assert result["allowed"] is False


def test_allows_high_risk_wording_when_human_confirmation_required():
    result = check(
        answer="Kỹ thuật viên cần xác nhận trước khi bật van trong 20 phút.",
        evidence=[{"duration_minutes": 20}],
        requires_human=True,
    )
    assert result["allowed"] is True
    assert result["warnings"]


def test_verify_endpoint_requires_internal_key(monkeypatch):
    monkeypatch.setattr(main, "INTERNAL_SERVICE_KEY", "unit-test-internal-key")
    response = TestClient(main.app).post(
        "/verify",
        json={"answer": "Không đủ dữ liệu.", "evidence": []},
    )
    assert response.status_code == 401


def test_rejects_suspect_quality_without_warning():
    result = check(answer="Độ ẩm hiện là 62%.", evidence=[{"value": 62, "quality": "suspect"}])
    assert result["allowed"] is False
    assert result["checks"]["quality_guard"] is False


def test_rejects_number_when_evidence_has_no_data():
    result = check(answer="Độ ẩm hiện là 62%.", evidence=[{"available": False, "error_code": "NO_DATA"}])
    assert result["allowed"] is False
    assert result["checks"]["no_data_guard"] is False


def test_allows_localized_display_timestamp_when_explicitly_in_evidence():
    result = check(
        answer="Khu A hiện có độ ẩm đất 62%, ghi nhận lúc 04:59 ngày 07/09/2026.",
        evidence=[{
            "farm_id": "farm_long",
            "value": 62,
            "observed_at": "2026-09-06T21:59:00+00:00",
            "display_observed_at": "04:59 ngày 07/09/2026",
            "fresh": True,
            "quality": "good",
        }],
        expected_farm_id="farm_long",
    )
    assert result["allowed"] is True
