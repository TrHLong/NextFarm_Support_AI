from __future__ import annotations

import json
import re
from typing import Any

ASSERTIVE_PATTERNS = [
    r"\bchắc chắn\b",
    r"(?<!\d)100\s*%",
    r"\bchắc chắn sẽ\b",
    r"\bbảo đảm năng suất\b",
    r"\bnăng suất cao nhất\b",
    r"\bkhông thể sai\b",
]
HIGH_RISK_PATTERNS = [
    r"\bphun\s+thuốc\b",
    r"\bdùng\s+thuốc\b",
    r"\bpha\s+liều\b",
    r"\bliều\s+lượng\b",
    r"\bthời gian cách ly\b",
    r"\b(?:bật|tắt|mở|đóng)\s+(?:van|bơm)\b",
    r"\b(?:khởi động|dừng)\s+bơm\b",
]


def flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def number_values(text: str) -> list[float]:
    values: list[float] = []
    for raw in re.findall(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)?(?![A-Za-z0-9_])", text or ""):
        normalized = raw.replace(",", ".").lstrip("+")
        try:
            values.append(float(normalized))
        except ValueError:
            continue
    return values


def evidence_number_values(evidence: list[Any]) -> list[float]:
    """Collect numbers from evidence values without treating URLs/identifiers as facts."""
    values: list[float] = []
    ignored_key_parts = ("url", "uri", "_id", "checksum", "artifact_path", "token")

    def walk(value: Any, key: str = "") -> None:
        lowered = key.lower()
        if any(part in lowered for part in ignored_key_parts) or lowered == "id":
            return
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            values.append(float(value))
            return
        if isinstance(value, str):
            values.extend(number_values(value))
            return
        if isinstance(value, dict):
            for nested_key, nested in value.items():
                walk(nested, str(nested_key))
            return
        if isinstance(value, list):
            for nested in value:
                walk(nested, key)

    walk(evidence)
    return values


def number_is_grounded(value: float, evidence_values: list[float]) -> bool:
    """Accept exact/rounded values and 0-1 probability to percent conversion."""
    for evidence_value in evidence_values:
        tolerance = max(0.01, abs(evidence_value) * 0.015)
        if abs(value - evidence_value) <= tolerance:
            return True
        if 0 <= evidence_value <= 1 and abs((value / 100.0) - evidence_value) <= 0.015:
            return True
        if 0 <= value <= 1 and abs((evidence_value / 100.0) - value) <= 0.015:
            return True
    return False


def source_entries(evidence: list[Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("source_url") or value.get("source_name") or value.get("source_id"):
                found.append(value)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(evidence)
    unique: list[dict[str, Any]] = []
    keys: set[str] = set()
    for item in found:
        key = str(item.get("source_url") or item.get("source_id") or item.get("source_name"))
        if key not in keys:
            keys.add(key)
            unique.append(item)
    return unique


def evaluate_answer(
    *,
    answer: str,
    evidence: list[Any],
    confidence: float | None,
    min_confidence: float,
    requires_human: bool,
    knowledge_mode: bool,
    expected_farm_id: str | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    warnings: list[str] = []
    evidence_text = flatten(evidence)
    answer_numbers = number_values(answer)
    evidence_numbers = evidence_number_values(evidence)
    unmatched_numbers = sorted(
        {f"{value:g}" for value in answer_numbers if not number_is_grounded(value, evidence_numbers)}
    )
    sources = source_entries(evidence)

    # Tenant evidence check: một câu trả lời không được trộn evidence của farm khác.
    evidence_farm_ids: set[str] = set()
    def collect_farm_ids(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("farm_id"):
                evidence_farm_ids.add(str(value.get("farm_id")))
            for nested in value.values():
                collect_farm_ids(nested)
        elif isinstance(value, list):
            for nested in value:
                collect_farm_ids(nested)
    collect_farm_ids(evidence)
    if expected_farm_id and any(fid != expected_farm_id for fid in evidence_farm_ids):
        reasons.append("Evidence chứa farm_id ngoài phạm vi được phép của câu hỏi.")

    # Freshness guard: nếu evidence báo stale/fresh=false thì câu trả lời phải nói rõ dữ liệu cũ.
    stale_evidence = bool(re.search(r'"fresh"\s*:\s*false|"status"\s*:\s*"stale"|"freshness"\s*:\s*"stale"', evidence_text, re.I))
    if stale_evidence and not re.search(r"quá cũ|bị trễ|không phải.*hiện tại|chưa thể coi.*hiện tại|stale", answer, re.I):
        reasons.append("Evidence bị trễ nhưng câu trả lời không cảnh báo freshness.")

    suspect_quality = bool(re.search(r'"quality"\s*:\s*"(?:suspect|bad)"', evidence_text, re.I))
    if suspect_quality and not re.search(r"chất lượng.*(?:kém|nghi ngờ)|cảm biến.*(?:lỗi|nghi ngờ)|không dùng.*khẳng định|quality", answer, re.I):
        reasons.append("Evidence có quality suspect/bad nhưng câu trả lời không cảnh báo chất lượng dữ liệu.")

    unavailable_evidence = bool(re.search(r'"available"\s*:\s*false|"error_code"\s*:\s*"(?:NO_DATA|NOT_FOUND)"', evidence_text, re.I))
    if unavailable_evidence and answer_numbers:
        reasons.append("Evidence báo không có dữ liệu nhưng câu trả lời vẫn chứa số liệu vận hành.")

    # Model-status guard: experimental/blocked không được diễn đạt như production-ready.
    experimental_evidence = bool(re.search(r'"(?:deployment_status|resolved_status|status)"\s*:\s*"(?:experimental|blocked)"', evidence_text, re.I))
    if experimental_evidence and re.search(r"đã xác nhận|đã sẵn sàng|production|chắc chắn|khẳng định", answer, re.I) and not re.search(r"experimental|thử nghiệm|blocked|chưa", answer, re.I):
        reasons.append("Kết quả model/capability chưa đạt nhưng câu trả lời diễn đạt như đã sẵn sàng.")

    has_factual_shape = bool(answer_numbers or len(answer.split()) > 18)
    if has_factual_shape and not evidence:
        reasons.append("Câu trả lời có nội dung thực tế nhưng không có bằng chứng đi kèm.")
    if unmatched_numbers:
        reasons.append("Có số liệu không xuất hiện trong dữ liệu hoặc nguồn: " + ", ".join(unmatched_numbers[:8]))
    if knowledge_mode and not any(source.get("source_url") for source in sources):
        reasons.append("Câu trả lời kiến thức không có URL nguồn đã kiểm duyệt.")
    if confidence is not None and confidence < min_confidence:
        reasons.append(f"Độ tin cậy {confidence:.2f} thấp hơn ngưỡng {min_confidence:.2f}.")
    if any(re.search(pattern, answer, re.I) for pattern in ASSERTIVE_PATTERNS):
        reasons.append("Câu trả lời dùng ngôn ngữ khẳng định quá mức.")
    high_risk = any(re.search(pattern, answer, re.I) for pattern in HIGH_RISK_PATTERNS)
    if high_risk and not requires_human:
        reasons.append("Nội dung có hành động rủi ro nhưng chưa yêu cầu xác nhận hoặc chuyên gia.")
    if requires_human:
        warnings.append("Cần kỹ thuật viên hoặc chuyên gia xác nhận trước khi hành động thực tế.")

    allowed = not reasons
    final_answer = answer if allowed else (
        "Tôi chưa có đủ dữ liệu hoặc nguồn đã kiểm duyệt để trả lời chắc chắn. "
        "Tôi sẽ không đoán. Vui lòng bổ sung dữ liệu còn thiếu hoặc chuyển câu hỏi cho kỹ thuật viên/chuyên gia NextFarm."
    )
    return {
        "allowed": allowed,
        "final_answer": final_answer,
        "reasons": reasons,
        "warnings": warnings,
        "source_count": len(sources),
        "unmatched_numbers": unmatched_numbers,
        "evidence_farm_ids": sorted(evidence_farm_ids),
        "checks": {
            "numeric_grounding": not bool(unmatched_numbers),
            "tenant_grounding": not expected_farm_id or all(fid == expected_farm_id for fid in evidence_farm_ids),
            "freshness_guard": not stale_evidence or bool(re.search(r"quá cũ|bị trễ|không phải.*hiện tại|chưa thể coi.*hiện tại|stale", answer, re.I)),
            "quality_guard": not suspect_quality or bool(re.search(r"chất lượng.*(?:kém|nghi ngờ)|cảm biến.*(?:lỗi|nghi ngờ)|không dùng.*khẳng định|quality", answer, re.I)),
            "no_data_guard": not unavailable_evidence or not bool(answer_numbers),
            "model_status_guard": not experimental_evidence or not bool(re.search(r"đã xác nhận|đã sẵn sàng|production|chắc chắn|khẳng định", answer, re.I)),
        },
    }
