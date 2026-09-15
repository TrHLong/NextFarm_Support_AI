import pytest

from app.context_policy import ContextPolicyError, resolve_farm_context, resolve_zone_context
from app.main import (
    describe_chat_training_policy,
    describe_llm_runtime,
    is_chat_training_question,
    is_llm_identity_question,
    missing_numeric_advice_context,
    unsupported_quantitative_prediction,
)


def test_single_readable_farm_can_be_selected_implicitly():
    user = {"farms": [{"farm_id": "farm_a", "can_read": True}]}
    assert resolve_farm_context(user, None) == "farm_a"


def test_multiple_farms_require_explicit_selection():
    user = {"farms": [{"farm_id": "farm_a", "can_read": True}, {"farm_id": "farm_b", "can_read": True}]}
    with pytest.raises(ContextPolicyError) as caught:
        resolve_farm_context(user, None)
    assert caught.value.code == "FARM_CONTEXT_REQUIRED"


def test_cross_farm_access_is_denied():
    user = {"farms": [{"farm_id": "farm_a", "can_read": True}]}
    with pytest.raises(ContextPolicyError) as caught:
        resolve_farm_context(user, "farm_b")
    assert caught.value.code == "FORBIDDEN"


def test_non_readable_permission_does_not_grant_access():
    user = {"farms": [{"farm_id": "farm_a", "can_read": False}]}
    with pytest.raises(ContextPolicyError) as caught:
        resolve_farm_context(user, "farm_a")
    assert caught.value.code == "FORBIDDEN"


def test_explicit_zone_wins_over_recent_context():
    zone, source = resolve_zone_context("b", [{"zone_code": "A"}])
    assert zone == "B"
    assert source == "message"


def test_single_recent_tool_zone_supports_follow_up():
    zone, source = resolve_zone_context(None, [{"farm_id": "farm_a", "zone_code": "C", "value": 61.2}])
    assert zone == "C"
    assert source == "recent_confirmed_tool_result"


def test_multi_zone_payload_is_not_used_as_session_default():
    zone, source = resolve_zone_context(None, [{"items": [{"zone_code": "A"}, {"zone_code": "B"}]}])
    assert zone is None
    assert source == "missing"


@pytest.mark.parametrize(
    "message",
    [
        "Tưới 30 phút được không?",
        "Pha thuốc 2% rồi phun nhé?",
        "Bón 250 g phân cho cây được chứ?",
    ],
)
def test_numeric_advice_with_explicit_quantity_requires_full_context(message):
    assert set(missing_numeric_advice_context(message)) == {
        "mùa vụ",
        "loại/đặc điểm đất",
        "giai đoạn sinh trưởng",
    }


def test_sensor_value_question_is_not_misclassified_as_dosage_advice():
    assert missing_numeric_advice_context("Độ ẩm khu A đang 62% có ổn không?") == []


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Năng suất vụ tới chính xác bao nhiêu kg?", "năng suất/sản lượng"),
        ("Ước tính doanh thu vụ tới là bao nhiêu?", "doanh thu/giá bán"),
        ("Dự báo ngày thu hoạch chính xác", "ngày thu hoạch"),
    ],
)
def test_unsupported_quantitative_predictions_fail_closed(message, expected):
    assert unsupported_quantitative_prediction(message) == expected


def test_supported_live_sensor_question_is_not_blocked_by_prediction_guard():
    assert unsupported_quantitative_prediction("Độ ẩm đất khu A hiện tại bao nhiêu?") is None


@pytest.mark.parametrize(
    "message",
    [
        "Chatbot đang sử dụng model nào?",
        "Có dùng API ChatGPT không?",
        "Hệ thống có dùng Gemini không?",
        "Đang dùng LLM nào để trả lời?",
    ],
)
def test_llm_identity_question_is_detected(message):
    assert is_llm_identity_question(message)


def test_deterministic_runtime_answer_does_not_claim_external_llm():
    answer = describe_llm_runtime(
        {
            "provider": "deterministic",
            "configured_model": "gpt-5.6-luna",
            "active_external_llm": False,
        }
    )
    assert "không gửi câu hỏi tới OpenAI/ChatGPT hoặc Gemini" in answer
    assert "RandomForest" in answer


def test_openai_runtime_answer_names_active_api_and_model():
    answer = describe_llm_runtime(
        {
            "provider": "openai",
            "model": "gpt-5.6-luna",
            "active_external_llm": True,
        }
    )
    assert "OpenAI Responses API" in answer
    assert "gpt-5.6-luna" in answer
    assert "Gemini chưa được tích hợp" in answer


@pytest.mark.parametrize(
    "message",
    [
        "Câu hỏi của tôi có được dùng để train model không?",
        "Tin nhắn người dùng có quay về model để học lại không?",
        "Dữ liệu chat có đưa vào model không?",
    ],
)
def test_chat_training_question_is_detected(message):
    assert is_chat_training_question(message)


def test_chat_training_policy_requires_governed_approval():
    answer = describe_chat_training_policy()
    assert "không tự động quay vào pipeline train" in answer
    assert "training_use_allowed=true" in answer
