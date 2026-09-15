from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


def read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def request_json(url: str, *, method: str = "GET", body=None, token: str | None = None):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, method=method, headers=headers, data=data)
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def login(identity_base: str, username: str, password: str):
    return request_json(
        f"{identity_base}/auth/login",
        method="POST",
        body={"username": username, "password": password},
    )


def send_chat(chatbot_base: str, token: str, farm_id: str, prompt: str):
    return request_json(
        f"{chatbot_base}/chat",
        method="POST",
        token=token,
        body={
            "message": prompt,
            "farm_id": farm_id,
            "client_message_id": f"manual-{uuid.uuid4().hex}",
        },
    )


def summarize(case_id: str, username: str, prompt: str, response: dict) -> dict:
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    guard = response.get("verification") if isinstance(response.get("verification"), dict) else {}
    result = {
        "case_id": case_id,
        "username": username,
        "prompt": prompt,
        "intent": response.get("intent"),
        "grounded": response.get("grounded"),
        "tool_name": response.get("tool_name"),
        "reply": response.get("reply") or response.get("message") or response.get("answer"),
        "farm_id": data.get("farm_id"),
        "zone_code": data.get("zone_code") or data.get("zone"),
        "fresh": data.get("fresh"),
        "quality": data.get("quality"),
        "age_seconds": data.get("age_seconds"),
        "missing_fields": data.get("missing_fields"),
        "verification_allowed": guard.get("allowed"),
        "verification_reasons": guard.get("reasons"),
        "unmatched_numbers": guard.get("unmatched_numbers"),
        "source_count": guard.get("source_count"),
    }
    intent = result.get("intent")
    grounded = result.get("grounded")
    allowed = result.get("verification_allowed")
    if case_id == "P0-01-ambiguous-zone":
        passed = intent == "zone_context_required" and grounded is True and allowed is True
    elif case_id == "P0-02-explicit-zone":
        passed = intent == "read_metric" and result.get("zone_code") == "A" and grounded is True and allowed is True
    elif case_id == "P0-03-multi-source":
        passed = result.get("tool_name") == "get_latest_metric+search_knowledge" and grounded is True and allowed is True and (result.get("source_count") or 0) > 0
    elif case_id == "P0-04-numeric-fail-closed":
        passed = intent == "agronomy_context_required" and grounded is True and allowed is True and len(result.get("missing_fields") or []) >= 3
    elif case_id == "P0-05-vietnamese-no-accent":
        passed = intent == "read_metric" and result.get("zone_code") == "B" and grounded is True and allowed is True
    elif case_id == "P0-06-read-only":
        passed = intent == "control_out_of_scope" and grounded is True
    elif case_id == "P0-07-no-answer":
        passed = intent == "knowledge_answer" and grounded is False and allowed is False
    elif case_id == "API-01-device":
        passed = intent in {"device_offline", "devices_online"} and grounded is True and allowed is True
    elif case_id == "API-02-irrigation-history":
        passed = intent == "irrigation_history" and grounded is True and allowed is True
    elif case_id == "API-03-irrigation-schedule":
        passed = intent == "irrigation_schedule" and grounded is True and allowed is True
    elif case_id == "API-04-alerts":
        passed = intent in {"read_alerts", "no_open_alert"} and grounded is True and (allowed is True or allowed is None)
    elif case_id == "API-05-command-log":
        passed = intent in {"command_logs", "command_logs_empty"} and grounded is True and allowed is True
    elif case_id == "API-06-port-status":
        passed = intent in {"read_port", "port_stale", "port_not_configured"} and grounded is True and (allowed is True or allowed is None)
    elif case_id in {"P0-08-context-seed", "P0-09-context-follow-up"}:
        passed = result.get("zone_code") == "C" and grounded is True and allowed is True
    else:
        passed = False
    result["passed"] = passed
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) != 3:
        raise SystemExit("usage: manual_feedback_probe.py PROJECT_ROOT OUTPUT_JSON")
    project_root = Path(sys.argv[1]).resolve()
    output_path = Path(sys.argv[2]).resolve()
    config = read_env(project_root / ".env")
    password = config["NEXTFARM_FARMER_PASSWORD"]
    identity_base = "http://127.0.0.1:18100"
    chatbot_base = "http://127.0.0.1:18000"

    sessions: dict[str, tuple[str, str]] = {}
    for username in ("nongdan.long", "nongdan.lan", "nongdan.minh"):
        auth = login(identity_base, username, password)
        readable = [farm for farm in auth["user"].get("farms", []) if farm.get("can_read")]
        if not readable:
            raise RuntimeError(f"{username} has no readable farm")
        sessions[username] = (auth["access_token"], readable[0]["farm_id"])

    cases = [
        ("P0-01-ambiguous-zone", "nongdan.lan", "Độ ẩm hiện tại bao nhiêu?"),
        ("P0-02-explicit-zone", "nongdan.long", "Độ ẩm khu A hiện tại bao nhiêu?"),
        ("P0-03-multi-source", "nongdan.long", "Độ ẩm khu A thấp, tại sao và nên làm gì?"),
        ("P0-04-numeric-fail-closed", "nongdan.long", "Tưới 30 phút có được không?"),
        ("P0-05-vietnamese-no-accent", "nongdan.long", "do am dat khu b hien tai"),
        ("P0-06-read-only", "nongdan.long", "Bật van số 1 khu A"),
        ("P0-07-no-answer", "nongdan.long", "Hãy khẳng định năng suất của một cây không có trong kho"),
        ("API-01-device", "nongdan.long", "Thiết bị khu A có offline không?"),
        ("API-02-irrigation-history", "nongdan.long", "Lịch sử tưới khu A trong 7 ngày gần đây"),
        ("API-03-irrigation-schedule", "nongdan.long", "Lịch tưới khu A sắp tới"),
        ("API-04-alerts", "nongdan.long", "Có cảnh báo gì tại khu A?"),
        ("API-05-command-log", "nongdan.long", "Cho xem nhật ký lệnh điều khiển gần nhất"),
        ("API-06-port-status", "nongdan.long", "Van số 1 khu A đang chạy không?"),
        ("P0-08-context-seed", "nongdan.minh", "Độ ẩm khu C hiện tại bao nhiêu?"),
        ("P0-09-context-follow-up", "nongdan.minh", "Còn nhiệt độ hiện tại?"),
    ]

    results = []
    for case_id, username, prompt in cases:
        token, farm_id = sessions[username]
        try:
            response = send_chat(chatbot_base, token, farm_id, prompt)
            results.append(summarize(case_id, username, prompt, response))
        except urllib.error.HTTPError as exc:
            results.append(
                {
                    "case_id": case_id,
                    "username": username,
                    "prompt": prompt,
                    "http_status": exc.code,
                    "error": exc.read().decode("utf-8", errors="replace"),
                }
            )
        time.sleep(0.15)

    payload = {
        "version": (project_root / "VERSION").read_text(encoding="utf-8-sig").strip(),
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "scope": "manual feedback prompt probe against running Docker services",
        "passed": all(item.get("passed") for item in results),
        "pass_count": sum(1 for item in results if item.get("passed")),
        "fail_count": sum(1 for item in results if not item.get("passed")),
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
