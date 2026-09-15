from __future__ import annotations

import re
import unicodedata
from typing import Any


ZONE_REQUIRED_TOOLS = {"get_latest_metric", "get_port_status", "get_crop_recommendation"}


def norm(text: str) -> str:
    value = unicodedata.normalize("NFD", text or "")
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    value = value.lower().replace("đ", "d")
    return re.sub(r"[^a-z0-9\s]", " ", value).strip()


def _step(tool_name: str, arguments: dict[str, Any], purpose: str) -> dict[str, Any]:
    return {"tool_name": tool_name, "arguments": arguments, "purpose": purpose}


def deterministic_plan(message: str) -> dict[str, Any]:
    """Return a bounded multi-source plan without inventing farm or zone context."""
    text = norm(message)
    zone_match = re.search(r"khu\s*([a-z])", text)
    port_match = re.search(r"(?:van|cong|port|bom)\s*(?:so\s*)?(\d+)", text)
    zone = zone_match.group(1).upper() if zone_match else None
    port = int(port_match.group(1)) if port_match else None

    metric = None
    if "am khong khi" in text or "humidity" in text:
        metric = "air_humidity"
    elif "do am" in text or "am dat" in text:
        metric = "soil_moisture"
    elif "nhiet do" in text:
        metric = "temperature"
    elif re.search(r"\bec\b", text):
        metric = "ec"
    elif re.search(r"\bph\b", text):
        metric = "ph"
    elif "luu luong" in text or "nuoc chay" in text:
        metric = "flow_rate"

    steps: list[dict[str, Any]] = []
    intent = "knowledge_answer"
    if any(key in text for key in ["mua toi trong", "vu toi trong", "nen trong cay gi", "cay gi phu hop", "luan canh"]):
        steps.append(_step("get_crop_recommendation", {"zone": zone}, "screen_crop_candidates"))
        intent = "crop_recommendation"
    else:
        live_metric_markers = [
            "hien tai", "bay gio", "moi nhat", "dang bao nhieu", "bao nhieu", "doc ", "cam bien",
        ]
        reference_metric_markers = ["tham khao", "ly tuong", "phu hop", "cho dat trong"]
        metric_is_operational = bool(
            metric
            and not any(key in text for key in reference_metric_markers)
            and (zone is not None or any(key in text for key in live_metric_markers))
        )
        if metric_is_operational:
            steps.append(_step("get_latest_metric", {"metric": metric, "zone": zone}, "read_operational_fact"))
            intent = "read_metric"
        mentions_device = any(key in text for key in ["thiet bi", "online", "offline", "mat ket noi"])
        device_state_markers = [
            "trang thai ket noi", "tinh trang ket noi", "trang thai online", "trang thai offline",
            "danh sach thiet bi", "kiem tra thiet bi",
            "dang online", "dang offline", "co offline", "co online",
        ]
        if mentions_device and (zone is not None or any(key in text for key in device_state_markers)):
            steps.append(_step("get_devices", {"zone": zone}, "read_device_state"))
            intent = "read_devices"
        if port is not None:
            steps.append(_step("get_port_status", {"zone": zone, "port_number": port}, "read_port_state"))
            intent = "read_port"
        mentions_schedule = any(key in text for key in ["lich tuoi", "gio tuoi", "ke hoach tuoi", "sap tuoi", "thoi luong tuoi"])
        schedule_state_markers = ["sap toi", "hom nay", "ngay mai", "dang cai", "cho xem"]
        if mentions_schedule and (zone is not None or any(key in text for key in schedule_state_markers)):
            steps.append(_step("get_irrigation_schedules", {"zone": zone}, "read_irrigation_schedule"))
            intent = "irrigation_schedule"
        if any(key in text for key in ["lich su tuoi", "cac lan tuoi", "lan tuoi", "chi tiet tuoi"]):
            steps.append(_step("get_irrigation_history", {"zone": zone, "hours": 168}, "read_irrigation_history"))
            intent = "irrigation_history"
        elif any(key in text for key in ["tuoi may lan", "hom qua tuoi", "hom nay tuoi", "tuan nay tuoi"]):
            period = "yesterday" if "hom qua" in text else "week" if "tuan" in text else "today"
            steps.append(_step("get_irrigation_summary", {"zone": zone, "period": period}, "aggregate_irrigation"))
            intent = "irrigation_summary"
        if any(key in text for key in ["canh bao", "su co", "bat thuong"]):
            steps.append(_step("get_alerts", {"zone": zone}, "read_alerts"))
            intent = "read_alerts"
        if any(key in text for key in ["lenh dieu khien", "nhat ky lenh", "command log"]):
            steps.append(_step("get_command_logs", {}, "audit_control_commands"))
            intent = "command_logs"
        if any(key in text for key in ["tinh hinh vuon", "tong quan", "danh gia vuon", "ai thay"]):
            steps.append(_step("get_ai_summary", {"zone": zone}, "summarize_farm_evidence"))
            intent = "ai_smart_summary"
        asks_ai_capabilities = (
            any(key in text for key in ["bach khoa ai", "ai nao", "nang luc ai"])
            or (
                any(key in text for key in ["model", "mo hinh"])
                and any(key in text for key in [" ai ", "ai ", "hoc may", "du doan"])
            )
        )
        if asks_ai_capabilities:
            steps.append(_step("get_ai_capabilities", {"zone": zone}, "list_model_capabilities"))
            intent = "ai_capabilities"
        if any(key in text for key in ["ticket", "gap ky thuat", "bao ky thuat"]):
            steps.append(_step("create_ticket_suggestion", {"zone": zone, "description": message}, "prepare_human_handoff"))
            intent = "ticket_confirmation"
        needs_knowledge = not steps or any(
            key in text for key in ["tai sao", "vi sao", "nen lam", "co nen", "cach xu ly", "khuyen nghi", "huong dan"]
        )
        if needs_knowledge:
            steps.append(_step("search_knowledge", {"query": message}, "retrieve_approved_guidance"))
            if len(steps) == 1:
                intent = "knowledge_answer"

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in steps:
        if item["tool_name"] not in seen:
            unique.append(item)
            seen.add(item["tool_name"])
        if len(unique) == 4:
            break
    primary = unique[0]
    missing_context = []
    if zone is None and any(item["tool_name"] in ZONE_REQUIRED_TOOLS for item in unique):
        missing_context.append("zone")
    return {
        "provider": "deterministic",
        "model": None,
        "tool_name": primary["tool_name"],
        "arguments": primary["arguments"],
        "steps": unique,
        "intent": intent,
        "confidence": 0.78,
        "missing_context": missing_context,
    }
