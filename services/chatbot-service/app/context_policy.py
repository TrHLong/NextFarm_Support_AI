from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class ContextPolicyError(Exception):
    status_code: int
    code: str
    message: str
    details: dict[str, Any]


def _zones_in_payload(value: Any) -> set[str]:
    zones: set[str] = set()

    def walk(item: Any, key: str = "") -> None:
        if isinstance(item, dict):
            for nested_key, nested_value in item.items():
                normalized_key = str(nested_key).lower()
                if normalized_key in {"zone", "zone_code"} and isinstance(nested_value, str):
                    candidate = nested_value.strip().upper()
                    if re.fullmatch(r"[A-Z0-9_-]{1,32}", candidate):
                        zones.add(candidate)
                else:
                    walk(nested_value, normalized_key)
        elif isinstance(item, list):
            for nested_value in item:
                walk(nested_value, key)

    walk(value)
    return zones


def resolve_zone_context(explicit_zone: str | None, recent_tool_payloads: list[Any]) -> tuple[str | None, str]:
    """Use an explicit zone first, then one unambiguous zone confirmed by recent tool evidence."""
    if explicit_zone:
        return explicit_zone.strip().upper(), "message"
    for payload in recent_tool_payloads:
        zones = _zones_in_payload(payload)
        if len(zones) == 1:
            return next(iter(zones)), "recent_confirmed_tool_result"
    return None, "missing"


def resolve_farm_context(user: dict[str, Any], requested_farm_id: str | None) -> str:
    readable = [item for item in user.get("farms", []) if item.get("can_read")]
    if requested_farm_id:
        if not any(item.get("farm_id") == requested_farm_id for item in readable):
            raise ContextPolicyError(
                403,
                "FORBIDDEN",
                "Tài khoản không có quyền truy cập vườn được yêu cầu.",
                {"farm_id": requested_farm_id},
            )
        return requested_farm_id
    if len(readable) == 1:
        return str(readable[0]["farm_id"])
    if not readable:
        raise ContextPolicyError(403, "FORBIDDEN", "Tài khoản chưa được cấp quyền đọc vườn nào.", {})
    raise ContextPolicyError(
        409,
        "FARM_CONTEXT_REQUIRED",
        "Tài khoản có nhiều vườn; hãy chọn rõ vườn trước khi hỏi dữ liệu.",
        {"allowed_farm_ids": [str(item["farm_id"]) for item in readable]},
    )
