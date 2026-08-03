from __future__ import annotations

import os
import re
import unicodedata
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

IDENTITY_URL = os.getenv("IDENTITY_URL", "http://localhost:8100")
KNOWLEDGE_URL = os.getenv("KNOWLEDGE_URL", "http://localhost:8200")
FARM_DATA_URL = os.getenv("FARM_DATA_URL", "http://localhost:8300")
SALES_URL = os.getenv("SALES_URL", "http://localhost:8400")
TICKET_URL = os.getenv("TICKET_URL", "http://localhost:8500")

app = FastAPI(title="NextFarm Chatbot Orchestrator", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class IntakeRequest(BaseModel):
    full_name: str
    phone: str
    region: str | None = None
    note: str | None = None
    channel: str = "web_chat"


class ChatRequest(BaseModel):
    subject_id: str
    message: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "chatbot-service", "status": "ok"}


@app.post("/intake/resolve")
def intake_resolve(payload: IntakeRequest) -> dict[str, Any]:
    with httpx.Client(timeout=12) as client:
        return client.post(f"{IDENTITY_URL}/intake/resolve", json=payload.model_dump()).json()


def norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9\s]", " ", text.lower().replace("đ", "d")).strip()


def zone(text: str) -> str | None:
    m = re.search(r"khu\s*([a-fA-F])", text or "")
    return m.group(1).upper() if m else None


def port(text: str) -> int | None:
    m = re.search(r"(van|cổng|cong|port)\s*(số|so)?\s*(\d+)", text or "", re.I)
    return int(m.group(3)) if m else None


def is_greeting(text: str) -> bool:
    x = norm(text)
    return x in {"hi", "hello", "xin chao", "chao", "alo"} or x.startswith("chao ")


def wants_human(text: str) -> bool:
    x = norm(text)
    return any(k in x for k in ["gap ky thuat", "gap nhan vien", "tu van vien", "goi lai", "lien he", "bao gia", "demo", "hop dong"])


def is_control(text: str) -> bool:
    x = norm(text)
    return any(k in x for k in ["bat van", "mo van", "tat van", "dung tuoi", "bat bom", "tat bom"])


def is_private_farm_data(text: str) -> bool:
    x = norm(text)
    return any(k in x for k in ["do am", "am dat", "khu a", "khu b", "van", "lich tuoi", "tuoi may lan", "canh bao", "ec", "ph", "cam bien"])


def is_sales_or_advice(text: str) -> bool:
    x = norm(text)
    return any(
        k in x
        for k in [
            "muon lam",
            "xay dung",
            "vuon",
            "nha mang",
            "trong",
            "bao gia",
            "demo",
            "tu van",
            "ky hop dong",
            "trien khai",
            "50m2",
            "1000m2",
            "m2",
            "ha",
        ]
    )


def human_moisture(row: dict[str, Any]) -> str:
    value = row["value"]
    zone_code = row["zone_code"]
    target = f"{row['target_min']}-{row['target_max']}%"
    status = row.get("status")
    if status == "low":
        meaning = "thấp hơn ngưỡng mục tiêu, nên kiểm tra lịch tưới, van tưới và đầu nhỏ giọt của khu này."
    elif status == "high":
        meaning = "cao hơn ngưỡng mục tiêu, chưa nên tưới thêm nếu đất hoặc giá thể đã đủ ẩm."
    else:
        meaning = "đang trong ngưỡng mục tiêu."
    return f"Khu {zone_code} hiện khoảng {value}% độ ẩm đất, {meaning} Ngưỡng demo của khu này là {target}"


def create_support_ticket(client: httpx.Client, ctx: dict[str, Any], message: str, reason: str) -> dict[str, Any]:
    return client.post(
        f"{TICKET_URL}/tickets",
        json={
            "subject_id": ctx["subject_id"],
            "farm_id": ctx.get("farm_id"),
            "title": reason,
            "description": message,
            "priority": "medium",
            "source": "chatbot",
        },
    ).json()


@app.post("/chat")
def chat(payload: ChatRequest) -> dict[str, Any]:
    message = payload.message.strip()
    if not message:
        return {"answer": "Anh/chị nhập giúp em câu hỏi hoặc nhu cầu cần hỗ trợ nhé.", "intent": "empty", "grounded": True}

    with httpx.Client(timeout=15) as client:
        ctx = client.get(f"{IDENTITY_URL}/context/{payload.subject_id}").json()
        identity_kind = ctx["identity_kind"]
        farm_id = ctx.get("farm_id")

        if is_greeting(message):
            if identity_kind == "customer":
                return {
                    "answer": (
                        f"Chào {ctx['display_name']}. Em có thể hỗ trợ theo 2 hướng: "
                        "đọc dữ liệu vườn đã phân quyền như độ ẩm, cảnh báo, van, lịch tưới; "
                        "hoặc giải thích các nền tảng NextFarm như GIS, tưới thông minh, NMC, Fertikit, QR Check, sản lượng, AI sâu bệnh và Weather."
                    ),
                    "intent": "greeting_customer",
                    "grounded": True,
                }
            return {
                "answer": (
                    "Chào anh/chị. Anh/chị cứ hỏi tự nhiên về NextFarm hoặc mô tả khu vườn muốn làm. "
                    "Em có thể tư vấn theo hướng của NextFarm: bản đồ lô thửa GIS, tưới thông minh, NMC theo dõi vi khí hậu, "
                    "Fertikit châm phân, quản lý nhật ký, QR truy xuất, dự báo sản lượng, AI sâu bệnh và Weather. "
                    "Nếu anh/chị muốn trao đổi với tư vấn viên, em sẽ ghi nhận thành hồ sơ/ticket."
                ),
                "intent": "greeting_lead",
                "grounded": True,
            }

        if identity_kind == "lead":
            if wants_human(message):
                ticket = create_support_ticket(client, ctx, message, "Khách mới muốn tư vấn trực tiếp")
                return {
                    "answer": (
                        "Em đã ghi nhận nhu cầu để tư vấn viên tiếp nhận. "
                        f"Mã ticket: {ticket.get('ticket_id')}. Trong lúc chờ, anh/chị có thể cho em thêm cây trồng, diện tích, tỉnh/khu vực, nguồn nước và mục tiêu đầu tư để đề xuất sát hơn."
                    ),
                    "intent": "lead_ticket_created",
                    "grounded": True,
                    "ticket": ticket,
                }
            if is_sales_or_advice(message):
                data = client.post(f"{SALES_URL}/consult", json={"lead_profile_id": ctx["lead_profile_id"], "message": message}).json()
                return {"answer": data["answer"], "intent": "lead_consultation", "grounded": True, "sales": data}
            if is_private_farm_data(message):
                return {
                    "answer": (
                        "Câu này liên quan đến dữ liệu riêng của một vườn cụ thể nên em chưa được phép đọc khi anh/chị chưa được xác minh là khách hàng. "
                        "Nếu anh/chị đang tìm hiểu giải pháp, hãy mô tả cây trồng, diện tích, khu vực và vấn đề đang gặp; em sẽ tư vấn cấu hình NextFarm phù hợp."
                    ),
                    "intent": "unverified_private_data",
                    "grounded": True,
                }
            know = client.post(f"{KNOWLEDGE_URL}/query", json={"question": message, "user_type": "lead"}).json()
            if know.get("answerable"):
                return {"answer": know["answer"], "intent": "knowledge_answer", "grounded": True, "source": know.get("source")}
            return {
                "answer": (
                    "Em chưa có tài liệu kiểm duyệt đủ chắc cho câu hỏi này. Anh/chị có thể nói rõ hơn: đang trồng cây gì, diện tích bao nhiêu, "
                    "muốn tự động tưới, theo dõi môi trường, quản lý sản lượng hay truy xuất QR? Em sẽ bám vào các nền tảng NextFarm để tư vấn."
                ),
                "intent": "ask_clarification",
                "grounded": False,
            }

        if is_control(message):
            auth = client.post(f"{IDENTITY_URL}/authorize", json={"subject_id": ctx["user_id"], "farm_id": farm_id, "action": "request_control"}).json()
            if not auth.get("allowed"):
                return {"answer": auth["reason"], "intent": "control_denied", "grounded": True}
            p = port(message)
            if not p:
                return {"answer": "Anh/chị muốn điều khiển van số mấy và trong bao nhiêu phút? Ví dụ: bật van 2 trong 10 phút.", "intent": "control_missing_slot", "grounded": True}
            return {
                "answer": (
                    f"Em đã nhận yêu cầu điều khiển van số {p}. Vì đây là hành động vật lý có thể ảnh hưởng cây và thiết bị, "
                    "hệ thống chỉ tạo lệnh nháp và bắt buộc xác nhận rõ ràng trước khi gửi xuống bộ điều khiển."
                ),
                "intent": "control_draft",
                "grounded": True,
                "requires_confirmation": True,
            }

        x = norm(message)
        if "do am" in x or "am dat" in x:
            z = zone(message) or "A"
            data = client.get(f"{FARM_DATA_URL}/farms/{farm_id}/moisture/latest", params={"zone": z}).json()
            return {"answer": human_moisture(data), "intent": "read_moisture", "grounded": True, "data": data}

        if "van" in x or "cong" in x:
            p = port(message)
            if not p:
                return {"answer": "Anh/chị muốn xem van/cổng số mấy? Nếu có nhiều bộ điều khiển, nên nói thêm khu A/B/C để tránh nhầm.", "intent": "ask_slot_port", "grounded": True}
            data = client.get(f"{FARM_DATA_URL}/farms/{farm_id}/devices/port/{p}").json()
            if not data.get("configured"):
                return {
                    "answer": f"Van/cổng số {p} chưa có trong cấu hình vườn này, nên em không đoán trạng thái. Cần bổ sung cấu hình thiết bị vào Data Hub trước.",
                    "intent": "device_not_configured",
                    "grounded": True,
                }
            first = data["items"][0]
            state = "đang mở/chạy" if first.get("running") else "đang tắt"
            extra = " Có nhiều thiết bị cùng số cổng; bản thật cần hỏi rõ bộ điều khiển hoặc khu để tránh nhầm lệnh." if data.get("ambiguous") else ""
            return {"answer": f"{first['port_name']} hiện {state}.{extra}", "intent": "read_device_status", "grounded": True, "data": data}

        if "lich tuoi" in x or "tuoi may lan" in x or "hom nay tuoi" in x:
            data = client.get(f"{FARM_DATA_URL}/farms/{farm_id}/irrigation/summary").json()
            return {
                "answer": f"Hôm nay vườn ghi nhận {data['run_count']} ca tưới, tổng khoảng {data['total_minutes']} phút và {data['total_liters']} lít nước.",
                "intent": "irrigation_summary",
                "grounded": True,
                "data": data,
            }

        if "canh bao" in x or "thieu nuoc" in x or ("khu" in x and "sao" in x):
            z = zone(message)
            data = client.get(f"{FARM_DATA_URL}/farms/{farm_id}/alerts", params={"zone": z} if z else {}).json()
            if not data["items"]:
                return {"answer": "Hiện chưa có cảnh báo mở phù hợp. Nếu ngoài vườn vẫn bất thường, nên kiểm tra cảm biến, van và lịch tưới trước khi kết luận.", "intent": "read_alerts", "grounded": True}
            a = data["items"][0]
            return {
                "answer": f"Có cảnh báo mức {a['severity']}: {a['message_vi']} Checklist gợi ý: {a.get('checklist_title') or 'kiểm tra dữ liệu liên quan'}. Nếu cần kỹ thuật viên theo dõi, em có thể tạo ticket.",
                "intent": "read_alerts",
                "grounded": True,
                "data": data,
            }

        if wants_human(message):
            ticket = create_support_ticket(client, ctx, message, "Khách hàng yêu cầu hỗ trợ kỹ thuật")
            return {"answer": f"Em đã tạo ticket để kỹ thuật viên tiếp nhận. Mã ticket: {ticket.get('ticket_id')}.", "intent": "support_ticket_created", "grounded": True, "ticket": ticket}

        know = client.post(f"{KNOWLEDGE_URL}/query", json={"question": message, "user_type": "customer"}).json()
        if know.get("answerable"):
            return {"answer": know["answer"], "intent": "knowledge_answer", "grounded": True, "source": know.get("source")}
        return {
            "answer": "Em chưa có dữ liệu hoặc tài liệu kiểm duyệt đủ chắc để trả lời câu này. Em sẽ không đoán; anh/chị có thể hỏi cụ thể hơn hoặc yêu cầu tạo ticket hỗ trợ.",
            "intent": "insufficient_data",
            "grounded": False,
        }
