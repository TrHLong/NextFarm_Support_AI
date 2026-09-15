from __future__ import annotations

import os
import re
import logging
import unicodedata
from contextvars import ContextVar
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import psycopg
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.context_policy import ContextPolicyError, resolve_farm_context, resolve_zone_context

IDENTITY_URL = os.getenv("IDENTITY_URL", "http://localhost:8100")
FARM_DATA_URL = os.getenv("FARM_DATA_URL", "http://localhost:8300")
KNOWLEDGE_URL = os.getenv("KNOWLEDGE_URL", "http://localhost:8200")
TICKET_URL = os.getenv("TICKET_URL", "http://localhost:8500")
ANALYTICS_URL = os.getenv("ANALYTICS_URL", "http://localhost:8600")
TRUTH_GUARD_URL = os.getenv("TRUTH_GUARD_URL", "http://localhost:8700")
CROP_ROUTER_URL = os.getenv("CROP_ROUTER_URL", "http://localhost:8900")
LLM_GATEWAY_URL = os.getenv("LLM_GATEWAY_URL", "http://localhost:8950")
LLM_ENABLE_VERBALIZER = os.getenv("LLM_ENABLE_VERBALIZER", "true").lower() in {"1","true","yes","on"}
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")

LOGGER = logging.getLogger("nextfarm.chatbot")
CURRENT_CLIENT_MESSAGE_ID: ContextVar[str | None] = ContextVar("client_message_id", default=None)

app = FastAPI(title="NextFarm AI Support Orchestrator - Bài toán B", version="10.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOW_ORIGINS",
            "http://localhost:8080,http://localhost:8081,http://localhost:8082,http://localhost:8084",
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def clear_request_context(request, call_next):
    token = CURRENT_CLIENT_MESSAGE_ID.set(None)
    try:
        return await call_next(request)
    finally:
        CURRENT_CLIENT_MESSAGE_ID.reset(token)

VN = ZoneInfo("Asia/Ho_Chi_Minh")


def _require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("Thiếu DATABASE_URL; hãy chạy dịch vụ qua Docker Compose sau scripts/setup_v10_env.cmd.")
    return DATABASE_URL


def conn():
    return psycopg.connect(_require_database_url(), row_factory=dict_row)


def new_http_client(timeout: float, headers: dict[str, str] | None = None) -> httpx.Client:
    """One bounded downstream policy: connect retry, timeout and optional auth headers."""
    return httpx.Client(timeout=timeout, headers=headers, transport=httpx.HTTPTransport(retries=2))


def norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower().replace("đ", "d")
    return re.sub(r"[^a-z0-9\s]", " ", text).strip()


def is_llm_identity_question(text: str) -> bool:
    """Nhận diện câu hỏi người dùng muốn biết chatbot đang chạy model/API nào."""
    value = norm(text)
    direct_phrases = [
        "dang dung model nao",
        "dang su dung model nao",
        "dang dung mo hinh nao",
        "dang su dung mo hinh nao",
        "model nao dang duoc su dung",
        "mo hinh nao dang duoc su dung",
        "dung llm nao",
        "nha cung cap llm",
        "api cua chatgpt",
        "api chatgpt",
        "api openai",
        "co dung chatgpt",
        "co dung openai",
        "co dung gemini",
    ]
    return any(phrase in value for phrase in direct_phrases)


def is_chat_training_question(text: str) -> bool:
    """Nhận diện câu hỏi về việc tin nhắn chat có quay lại để train model hay không."""
    value = norm(text)
    mentions_chat_data = any(term in value for term in ["cau hoi", "tin nhan", "du lieu chat", "noi dung chat", "nguoi dung hoi"])
    mentions_training = any(term in value for term in ["train", "huan luyen", "hoc lai", "quay ve model", "dua vao model"])
    return mentions_chat_data and mentions_training


def describe_chat_training_policy() -> str:
    return (
        "Câu hỏi và câu trả lời được lưu trong PostgreSQL để giữ lịch sử và truy vết, nhưng không tự động quay vào pipeline train. "
        "Mười model RandomForest học từ CSV dữ liệu vận hành như sensor, thiết bị và lịch sử tưới đã được xử lý theo thời gian. "
        "Nếu muốn dùng phản hồi chat sau này, bản ghi phải đi qua support_db.chat_feedback, được người có quyền duyệt và đặt "
        "training_use_allowed=true; sau đó một pipeline tuyển chọn riêng mới được phép sử dụng. Khi trả lời một câu hỏi, chatbot có thể gọi "
        "model nghiệp vụ đã approved để suy luận, nhưng việc gọi model không làm model tự học thêm từ câu hỏi đó."
    )


def describe_llm_runtime(runtime: dict[str, Any]) -> str:
    """Giải thích provider hội thoại đang hoạt động và tách nó khỏi 10 model ML."""
    provider = str(runtime.get("provider") or "unknown").lower()
    configured_model = str(runtime.get("configured_model") or "").strip()
    active_external = bool(runtime.get("active_external_llm"))
    if provider == "openai" and active_external:
        active_model = str(runtime.get("model") or configured_model or "chưa xác định")
        llm_part = (
            f"Phần hội thoại hiện gọi OpenAI Responses API với model {active_model}. "
            "LLM chỉ lập kế hoạch gọi công cụ và diễn đạt lại bằng chứng; nó không có thông tin đăng nhập cơ sở dữ liệu. "
            "Gemini chưa được tích hợp trong phiên bản này."
        )
    elif provider == "openai":
        llm_part = (
            "Cấu hình đang yêu cầu OpenAI nhưng chưa có kết nối API hoạt động, nên hệ thống tự rơi về bộ định tuyến deterministic. "
            "Không có câu hỏi nào được gửi tới Gemini."
        )
    else:
        configured_note = f" Model OpenAI dự phòng trong cấu hình là {configured_model}, nhưng chưa được kích hoạt." if configured_model else ""
        llm_part = (
            "Phần hội thoại hiện chạy provider deterministic: hệ thống dùng quy tắc để chọn công cụ và tạo câu trả lời từ dữ liệu đã truy xuất. "
            "Phiên hiện tại không gửi câu hỏi tới OpenAI/ChatGPT hoặc Gemini."
            + configured_note
        )
    return (
        llm_part
        + " Mười model nghiệp vụ nông nghiệp là các model RandomForest riêng biệt, không phải LLM; "
        "chúng chỉ được dùng cho suy luận khi đã vượt quality gate."
    )


def extract_zone(text: str) -> str | None:
    match = re.search(r"khu\s*([a-zA-Z])", text or "", re.I)
    return match.group(1).upper() if match else None


def extract_port(text: str) -> int | None:
    match = re.search(r"(?:van|cong|cổng|port)\s*(?:so|số)?\s*(\d+)", text or "", re.I)
    return int(match.group(1)) if match else None


def extract_hours(text: str) -> int:
    normalized = norm(text)
    day_match = re.search(r"(\d+)\s*(?:ngay|day)", normalized)
    if day_match:
        return max(1, min(int(day_match.group(1)) * 24, 168))
    hour_match = re.search(r"(\d+)\s*(?:gio|hour|h)", normalized)
    if hour_match:
        return max(1, min(int(hour_match.group(1)), 168))
    if "tuan" in normalized:
        return 168
    if "hom nay" in normalized or "24 gio" in normalized:
        return 24
    return 24


def missing_numeric_advice_context(text: str) -> list[str]:
    """Fail closed for agronomy dosage/duration advice when context is incomplete."""
    value = norm(text)
    action = any(key in value for key in ["tuoi", "bon", "phan", "phun", "thuoc", "pha"])
    explicit_quantity = bool(re.search(r"(?<!\w)\d+(?:[.,]\d+)?\s*%", text or "")) or bool(
        re.search(
            r"(?<!\w)\d+(?:[.,]\d+)?\s*(?:%|(?:ml|l|lit|g|kg|phut|gio|lan|ppm|ms/cm|us/cm)\b)",
            value,
        )
    )
    asks_amount = explicit_quantity or any(
        key in value
        for key in ["bao nhieu", "may phut", "lieu luong", "nong do", "tan suat", "kg", "lit", "phan tram"]
    )
    if not (action and asks_amount):
        return []
    required = {
        "mùa vụ": ["mua mua", "mua kho", "vu dong", "vu he", "vu xuan", "vu thu", "vu nay"],
        "loại/đặc điểm đất": ["dat set", "dat cat", "dat thit", "gia the", "dat do", "thoat nuoc"],
        "giai đoạn sinh trưởng": ["cay con", "sinh truong", "ra hoa", "dau trai", "nuoi trai", "thu hoach", "giai doan"],
    }
    return [label for label, markers in required.items() if not any(marker in value for marker in markers)]


def unsupported_quantitative_prediction(text: str) -> str | None:
    """Chặn câu hỏi đòi con số khi hệ thống chưa có model/evidence tương ứng."""
    value = norm(text)
    asks_number = any(
        key in value
        for key in ["bao nhieu", "chinh xac", "con so", "du bao", "uoc tinh", "kg", "tan", "doanh thu"]
    )
    unsupported_targets = {
        "năng suất/sản lượng": ["nang suat", "san luong"],
        "doanh thu/giá bán": ["doanh thu", "gia ban", "loi nhuan"],
        "ngày thu hoạch": ["ngay thu hoach", "thoi diem thu hoach"],
    }
    if not asks_number:
        return None
    return next(
        (label for label, markers in unsupported_targets.items() if any(marker in value for marker in markers)),
        None,
    )


def detect_metric(text: str) -> tuple[str | None, str | None]:
    x = norm(text)
    if any(k in x for k in ["do am khong khi", "am khong khi", "humidity"]):
        return "air_humidity", "độ ẩm không khí"
    if any(k in x for k in ["do am", "am dat"]):
        return "soil_moisture", "độ ẩm đất"
    if "nhiet do" in x:
        return "temperature", "nhiệt độ"
    if re.search(r"\bec\b", x):
        return "ec", "EC"
    if re.search(r"\bph\b", x):
        return "ph", "pH"
    if any(k in x for k in ["luu luong", "nuoc chay", "co nuoc"]):
        return "flow_rate", "lưu lượng"
    return None, None


def format_time(value: Any) -> str:
    if not value:
        return "không rõ thời điểm"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if isinstance(value, datetime):
        return value.astimezone(VN).strftime("%H:%M ngày %d/%m/%Y")
    return str(value)


def auth_user(authorization: str | None) -> dict[str, Any]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Thiếu phiên đăng nhập.")
    try:
        with new_http_client(timeout=8) as client:
            res = client.post(f"{IDENTITY_URL}/auth/verify", headers={"Authorization": authorization})
        if res.status_code != 200:
            raise HTTPException(status_code=401, detail="Phiên đăng nhập không hợp lệ.")
        return res.json()["user"]
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Không kết nối được dịch vụ xác thực.") from exc


def downstream_headers(authorization: str | None) -> dict[str, str]:
    # Request thay mặt người dùng phải giữ Bearer token để downstream kiểm tra tenant.
    if authorization:
        return {"Authorization": authorization}
    return {"X-Internal-Service-Key": INTERNAL_SERVICE_KEY} if INTERNAL_SERVICE_KEY else {}


def ensure_farm(user: dict[str, Any], farm_id: str | None) -> str:
    try:
        return resolve_farm_context(user, farm_id)
    except ContextPolicyError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message, **exc.details},
        ) from exc


def log_message(
    user: dict[str, Any],
    farm_id: str,
    sender_type: str,
    content: str,
    *,
    strict: bool = False,
    client_message_id: str | None = None,
    **meta: Any,
) -> dict[str, Any]:
    """Persist one chat message and make any storage failure visible.

    User messages use ``strict=True``: the bot must not pretend an exchange was
    saved when PostgreSQL is unavailable. Bot-message failures are returned in
    the response as an explicit warning so the UI can tell the customer.
    """
    conversation_id = f"conv_{user['user_id']}_{farm_id}"
    try:
        with conn() as db, db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO support_db.conversations(conversation_id,user_id,farm_id)
                VALUES (%s,%s,%s)
                ON CONFLICT (conversation_id) DO UPDATE SET last_message_at=now()
                """,
                (conversation_id, user["user_id"], farm_id),
            )
            values = (
                conversation_id,
                sender_type,
                user["user_id"] if sender_type == "farmer" else None,
                content,
                meta.get("intent"),
                meta.get("grounded"),
                meta.get("tool_name"),
                Jsonb(meta.get("tool_payload")) if meta.get("tool_payload") is not None else None,
                client_message_id,
            )
            cur.execute(
                """
                INSERT INTO support_db.chat_messages(
                  conversation_id,sender_type,sender_id,content,intent,grounded,
                  tool_name,tool_payload,client_message_id
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (conversation_id,client_message_id) WHERE client_message_id IS NOT NULL
                DO NOTHING
                RETURNING message_id,created_at
                """,
                values,
            )
            saved = cur.fetchone()
            duplicate = saved is None and client_message_id is not None
            if duplicate:
                cur.execute(
                    "SELECT message_id,created_at FROM support_db.chat_messages WHERE conversation_id=%s AND client_message_id=%s",
                    (conversation_id, client_message_id),
                )
                saved = cur.fetchone()
            db.commit()
        return {
            "saved": True,
            "store": "postgresql",
            "conversation_id": conversation_id,
            "message_id": saved["message_id"] if saved else None,
            "duplicate": duplicate,
        }
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Không lưu được chat conversation=%s sender=%s", conversation_id, sender_type)
        if strict:
            raise HTTPException(
                status_code=503,
                detail="PostgreSQL chưa lưu được tin nhắn. Hệ thống dừng xử lý để tránh làm mất lịch sử; vui lòng thử lại.",
            ) from exc
        return {
            "saved": False,
            "store": "postgresql",
            "conversation_id": conversation_id,
            "error_code": "CHAT_PERSISTENCE_FAILED",
        }


def recent_session_tool_payloads(user_id: str, farm_id: str, limit: int = 12) -> list[Any]:
    """Return recent bot evidence for the same user/farm, newest first.

    Only tool payloads from the last 30 minutes are eligible for zone carry-over.
    The pure resolver rejects payloads containing multiple zones.
    """
    conversation_id = f"conv_{user_id}_{farm_id}"
    try:
        with conn() as db, db.cursor() as cur:
            cur.execute(
                """
                SELECT tool_payload
                FROM support_db.chat_messages
                WHERE conversation_id=%s
                  AND sender_type='bot'
                  AND tool_payload IS NOT NULL
                  AND created_at >= now()-interval '30 minutes'
                ORDER BY created_at DESC,message_id DESC
                LIMIT %s
                """,
                (conversation_id, max(1, min(int(limit), 30))),
            )
            return [row["tool_payload"] for row in cur.fetchall()]
    except Exception:  # history is optional context; authorization still fails closed elsewhere
        LOGGER.exception("Không đọc được context hội thoại conversation=%s", conversation_id)
        return []


def ticket_suggestion(
    farm_id: str,
    title: str,
    description: str,
    category: str = "GENERAL",
    priority: str = "normal",
    zone_code: str | None = None,
) -> dict[str, Any]:
    return {
        "label": "Tạo ticket cho kỹ thuật viên",
        "payload": {
            "farm_id": farm_id,
            "zone_code": zone_code,
            "title": title,
            "description": description,
            "category": category,
            "priority": priority,
            "source": "chatbot",
        },
    }


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    farm_id: str | None = None
    client_message_id: str | None = Field(default=None, min_length=8, max_length=128)


class TicketConfirmRequest(BaseModel):
    farm_id: str
    zone_code: str | None = None
    title: str
    description: str
    category: str = "GENERAL"
    priority: str = "normal"
    source: str = "chatbot"


@app.get("/health")
def health():
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT 1 AS ok")
        database_ok = bool(cur.fetchone()["ok"])
    return {"service": "chatbot-service", "status": "ok", "version": "10.1.0", "database_ok": database_ok, "scope": "grounded_iot_rag_crop_aware_multi_tool", "llm_gateway": LLM_GATEWAY_URL, "crop_router": CROP_ROUTER_URL}


@app.get("/conversations")
def conversations(authorization: str | None = Header(default=None)):
    user = auth_user(authorization)
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT c.conversation_id,c.farm_id,f.farm_name,c.started_at,c.last_message_at,
                   count(m.message_id) AS message_count
            FROM support_db.conversations c
            LEFT JOIN farm_db.farms f ON f.farm_id=c.farm_id
            LEFT JOIN support_db.chat_messages m ON m.conversation_id=c.conversation_id
            WHERE c.user_id=%s
            GROUP BY c.conversation_id,c.farm_id,f.farm_name,c.started_at,c.last_message_at
            ORDER BY c.last_message_at DESC
            """,
            (user["user_id"],),
        )
        rows = cur.fetchall()
    # Defense in depth: a stale conversation is hidden if farm_access was revoked.
    allowed = {x["farm_id"] for x in user.get("farms", []) if x.get("can_read")}
    return {"items": [row for row in rows if row.get("farm_id") in allowed]}


@app.get("/conversations/current/messages")
def current_conversation_messages(
    farm_id: str | None = None,
    limit: int = 200,
    authorization: str | None = Header(default=None),
):
    user = auth_user(authorization)
    selected = ensure_farm(user, farm_id)
    safe_limit = max(1, min(int(limit), 500))
    conversation_id = f"conv_{user['user_id']}_{selected}"
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM (
              SELECT message_id,sender_type,content,intent,grounded,tool_name,
                     tool_payload,client_message_id,delivery_status,created_at
              FROM support_db.chat_messages
              WHERE conversation_id=%s
              ORDER BY created_at DESC,message_id DESC
              LIMIT %s
            ) history
            ORDER BY created_at,message_id
            """,
            (conversation_id, safe_limit),
        )
        rows = cur.fetchall()
    return {
        "conversation_id": conversation_id,
        "farm_id": selected,
        "items": [
            {
                **row,
                "role": "user" if row["sender_type"] == "farmer" else "bot",
                "text": row["content"],
            }
            for row in rows
        ],
        "storage": {
            "engine": "postgresql",
            "durable_across_restart": True,
            "durable_across_normal_host_shutdown": True,
            "warning": "Lịch sử chỉ mất nếu xóa Docker volume hoặc ổ đĩa hỏng; cần backup định kỳ để phục hồi sự cố.",
        },
    }


def respond(
    user: dict[str, Any],
    farm_id: str,
    answer: str,
    intent: str,
    grounded: bool,
    tool_name: str | None = None,
    data: Any = None,
    suggestion: Any = None,
    source: Any = None,
    visualization: Any = None,
    insights: Any = None,
    confidence: float | None = None,
    knowledge_mode: bool = False,
    requires_human: bool = False,
):
    final_answer = answer
    verification = None
    llm_trace = None
    # LLM chỉ được diễn đạt lại evidence/draft; Truth Guard luôn chạy SAU LLM.
    if LLM_ENABLE_VERBALIZER and (data is not None or source is not None or knowledge_mode):
        evidence_for_llm = []
        if data is not None:
            evidence_for_llm.append(data)
        if source is not None:
            evidence_for_llm.append(source)
        if insights is not None:
            evidence_for_llm.append(insights)
        try:
            with new_http_client(timeout=25) as llm_client:
                llm_res = llm_client.post(
                    f"{LLM_GATEWAY_URL}/verbalize",
                    headers={"X-Internal-Service-Key": INTERNAL_SERVICE_KEY},
                    json={
                        "draft": answer,
                        "evidence": evidence_for_llm,
                        "user_id": user.get("user_id"),
                        "farm_id": farm_id,
                        "intent": intent,
                    },
                )
            if llm_res.status_code == 200:
                llm_trace = llm_res.json()
                final_answer = llm_trace.get("text") or answer
        except httpx.HTTPError:
            llm_trace = {"provider": "unavailable", "changed": False}
            final_answer = answer

    # Truth Guard chỉ chạy khi có nội dung dữ liệu/kiến thức cần kiểm chứng.
    if data is not None or source is not None or knowledge_mode:
        evidence = []
        if data is not None:
            evidence.append(data)
        if source is not None:
            evidence.append(source)
        if insights is not None:
            evidence.append(insights)
        try:
            with new_http_client(timeout=8) as guard_client:
                guard_res = guard_client.post(
                    f"{TRUTH_GUARD_URL}/verify",
                    headers={"X-Internal-Service-Key": INTERNAL_SERVICE_KEY},
                    json={
                        "answer": final_answer,
                        "evidence": evidence,
                        "confidence": confidence if confidence is not None else (0.82 if grounded else 0.45),
                        "intent": intent,
                        "user_id": user.get("user_id"),
                        "farm_id": farm_id,
                        "requires_human": bool(suggestion) or requires_human,
                        "knowledge_mode": knowledge_mode,
                    },
                )
            if guard_res.status_code == 200:
                verification = guard_res.json()
                final_answer = verification.get("final_answer", final_answer)
                if not verification.get("allowed", True):
                    grounded = False
        except httpx.HTTPError:
            # Truth Guard là safety gate. Nếu không gọi được thì không phát hành câu trả lời có evidence.
            verification = {"allowed": False, "reasons": ["Không kết nối được Truth Guard."]}
            final_answer = "Tôi chưa kiểm chứng được dữ liệu và nguồn trong lúc này nên sẽ không đưa ra kết luận. Vui lòng thử lại hoặc chuyển kỹ thuật viên/chuyên gia."
            grounded = False

    result = {"answer": final_answer, "intent": intent, "grounded": grounded}
    if tool_name:
        result["tool_name"] = tool_name
    if data is not None:
        result["data"] = data
    if suggestion:
        result["ticket_suggestion"] = suggestion
    if source:
        result["source"] = source
    if visualization:
        result["visualization"] = visualization
    if insights:
        result["insights"] = insights
    if verification is not None:
        result["verification"] = verification
    if llm_trace is not None:
        result["llm"] = llm_trace
    result["persistence"] = log_message(
        user,
        farm_id,
        "bot",
        final_answer,
        intent=intent,
        grounded=grounded,
        tool_name=tool_name,
        tool_payload=data,
        client_message_id=(f"{CURRENT_CLIENT_MESSAGE_ID.get()}:bot" if CURRENT_CLIENT_MESSAGE_ID.get() else None),
    )
    return result


@app.post("/chat")
def chat(payload: ChatRequest, authorization: str | None = Header(default=None)):
    user = auth_user(authorization)
    if user["role"] != "farmer":
        raise HTTPException(status_code=403, detail="Khung chat dữ liệu vườn dành cho tài khoản nông dân.")
    farm_id = ensure_farm(user, payload.farm_id)
    message = payload.message.strip()
    CURRENT_CLIENT_MESSAGE_ID.set(payload.client_message_id)
    log_message(
        user,
        farm_id,
        "farmer",
        message,
        strict=True,
        client_message_id=payload.client_message_id,
    )
    x = norm(message)
    explicit_zone = extract_zone(message)
    allow_session_zone = not any(key in x for key in ["toan vuon", "ca vuon", "tat ca khu", "moi khu"])
    recent_payloads = recent_session_tool_payloads(user["user_id"], farm_id) if allow_session_zone and not explicit_zone else []
    zone, zone_context_source = resolve_zone_context(explicit_zone, recent_payloads)
    if is_llm_identity_question(message):
        try:
            with new_http_client(timeout=8) as llm_client:
                runtime_res = llm_client.get(f"{LLM_GATEWAY_URL}/health")
            runtime_res.raise_for_status()
            runtime = runtime_res.json()
        except (httpx.HTTPError, ValueError):
            runtime = {
                "provider": "unavailable",
                "active_external_llm": False,
                "supported_providers": ["deterministic", "openai"],
                "gemini_supported": False,
            }
        return respond(
            user,
            farm_id,
            describe_llm_runtime(runtime),
            "llm_runtime_identity",
            True,
            "get_llm_runtime",
            data={
                "provider": runtime.get("provider"),
                "model": runtime.get("model"),
                "configured_model": runtime.get("configured_model"),
                "active_external_llm": runtime.get("active_external_llm", False),
                "external_api": runtime.get("external_api"),
                "supported_providers": runtime.get("supported_providers", ["deterministic", "openai"]),
                "gemini_supported": runtime.get("gemini_supported", False),
                "business_ml_family": "RandomForest",
                "business_model_count": 10,
            },
        )
    if is_chat_training_question(message):
        return respond(
            user,
            farm_id,
            describe_chat_training_policy(),
            "chat_training_policy",
            True,
            "get_chat_training_policy",
            data={
                "chat_store": "support_db.chat_messages",
                "automatic_training": False,
                "business_training_sources": ["sensor_readings", "device_status", "irrigation_runs", "telemetry_ingest_events"],
                "feedback_review_table": "support_db.chat_feedback",
                "approval_required": True,
                "training_use_flag": "training_use_allowed",
            },
        )
    missing_advice_context = missing_numeric_advice_context(message)
    if missing_advice_context:
        return respond(
            user,
            farm_id,
            "Tôi chưa thể đưa con số tưới/bón/phun khi còn thiếu: " + ", ".join(missing_advice_context) + ". Hãy bổ sung các thông tin này và chọn rõ khu; hệ thống sẽ không dùng giá trị gần đúng để suy ra liều lượng.",
            "agronomy_context_required",
            True,
            data={"farm_id": farm_id, "missing_fields": missing_advice_context, "policy": "fail_closed"},
            requires_human=True,
        )
    llm_plan: dict[str, Any] = {}
    planned_tool = None
    planned_args: dict[str, Any] = {}
    planned_steps: list[dict[str, Any]] = []
    # LLM planner không có DB credential và chỉ được lập kế hoạch trong allow-list.
    try:
        allowed_farms = [str(f.get("farm_id")) for f in user.get("farms", []) if f.get("can_read")]
        with new_http_client(timeout=25) as planner_client:
            plan_res = planner_client.post(
                f"{LLM_GATEWAY_URL}/plan",
                headers={"X-Internal-Service-Key": INTERNAL_SERVICE_KEY},
                json={
                    "message": message,
                    "user_id": user.get("user_id"),
                    "farm_id": farm_id,
                    "allowed_farm_ids": allowed_farms,
                },
            )
        if plan_res.status_code == 200:
            llm_plan = plan_res.json()
            if not llm_plan.get("denied"):
                planned_steps = [item for item in (llm_plan.get("steps") or []) if isinstance(item, dict)][:4]
                if not planned_steps and llm_plan.get("tool_name"):
                    planned_steps = [{"tool_name": llm_plan.get("tool_name"), "arguments": llm_plan.get("arguments") or {}}]
                planned_tool = planned_steps[0].get("tool_name") if planned_steps else llm_plan.get("tool_name")
                planned_args = planned_steps[0].get("arguments") or {} if planned_steps else llm_plan.get("arguments") or {}
                # Farm/zone/metric context comes from deterministic user/session parsing.
                # A model plan must never create a zone that the user did not select or confirm.
    except httpx.HTTPError:
        llm_plan = {"provider": "unavailable", "tool_name": None}

    planned_tool_names = {str(item.get("tool_name")) for item in planned_steps}
    with new_http_client(timeout=15, headers=downstream_headers(authorization)) as client:
        if x in {"chao", "xin chao", "hello", "hi", "alo"} or x.startswith("chao "):
            return respond(
                user,
                farm_id,
                f"Chào {user['display_name']}. Tôi đọc dữ liệu đã lưu trong PostgreSQL của đúng vườn được phân quyền. Bản demo mặc định dùng telemetry mô phỏng thiết bị đã hiệu chỉnh và luôn ghi rõ nguồn; khi nối API/MQTT NextFarm, từng bản ghi sẽ mang provenance tương ứng. Nếu dữ liệu thiếu hoặc quá cũ, tôi sẽ nói rõ và không đoán.",
                "greeting",
                True,
            )

        if any(k in x for k in ["bat van", "mo van", "tat van", "bat bom", "tat bom", "dung tuoi", "dieu khien"]):
            return respond(
                user,
                farm_id,
                "Phiên bản PoC này chỉ đọc dữ liệu và hỗ trợ sự cố, chưa điều khiển thiết bị. Điều khiển van hoặc bơm thuộc giai đoạn sau và bắt buộc phải có xác nhận cùng kiểm tra quyền.",
                "control_out_of_scope",
                True,
            )

        unsupported_target = unsupported_quantitative_prediction(message)
        if unsupported_target:
            return respond(
                user,
                farm_id,
                f"Tôi chưa có model đã được kiểm định và dữ liệu đầu vào đủ để đưa con số {unsupported_target}. "
                "Tôi sẽ không ước đoán hoặc dùng tài liệu chung để thay cho kết quả dự báo. "
                "Bạn có thể yêu cầu kỹ thuật viên/chuyên gia bổ sung dữ liệu và xác nhận model phù hợp.",
                "unsupported_quantitative_prediction",
                False,
                data={
                    "farm_id": farm_id,
                    "target": unsupported_target,
                    "policy": "abstain_without_validated_model_and_evidence",
                },
                requires_human=True,
            )

        # Khuyến nghị cây trồng mùa tới: kết hợp dữ liệu vườn + kho tri thức có nguồn.
        if planned_tool == "get_crop_recommendation" or any(k in x for k in [
            "mua toi trong", "vu toi trong", "nen trong cay gi", "nen trong loai gi",
            "cay gi phu hop", "cay trai gi", "nang suat cao", "luan canh cay gi",
            "sau ca chua trong", "khuyen nghi cay trong",
        ]):
            overview = client.get(f"{FARM_DATA_URL}/farms/{farm_id}/overview").json()
            available_zones = overview.get("zones") or []
            if not zone and len(available_zones) != 1:
                return respond(
                    user,
                    farm_id,
                    "Vườn có nhiều khu. Bạn hãy chọn rõ khu A/B/C trước khi yêu cầu khuyến nghị để tránh dùng nhầm điều kiện đất và mùa vụ.",
                    "zone_context_required",
                    True,
                    data={"farm_id": farm_id, "available_zones": [item.get("zone_code") for item in available_zones]},
                )
            selected_zone = zone or available_zones[0].get("zone_code")
            climate_res = client.get(
                f"{FARM_DATA_URL}/farms/{farm_id}/climate-summary",
                params={"zone": selected_zone, "hours": 24},
            )
            climate = climate_res.json() if climate_res.status_code == 200 else {"metrics": {}, "hours": 24}
            metrics = climate.get("metrics", {})
            seasonal_res = client.get(
                f"{FARM_DATA_URL}/farms/{farm_id}/seasonal-outlook",
                params={"forecast_days": 90},
            )
            seasonal = seasonal_res.json() if seasonal_res.status_code == 200 else {"available": False}
            seasonal_available = bool(seasonal.get("available"))
            rec_payload = {
                "farm_id": farm_id,
                "region": overview.get("region"),
                "previous_crop": overview.get("crop_name"),
                "cultivation_type": overview.get("cultivation_type"),
                "temperature_mean": seasonal.get("temperature_mean") if seasonal_available else (metrics.get("temperature") or {}).get("mean"),
                "temperature_min": seasonal.get("temperature_min") if seasonal_available else (metrics.get("temperature") or {}).get("min"),
                "temperature_max": seasonal.get("temperature_max") if seasonal_available else (metrics.get("temperature") or {}).get("max"),
                "air_humidity_mean": seasonal.get("air_humidity_mean") if seasonal_available else (metrics.get("air_humidity") or {}).get("mean"),
                "soil_moisture_mean": (metrics.get("soil_moisture") or {}).get("mean"),
                "soil_ph": (metrics.get("ph") or {}).get("mean"),
                "soil_ec": (metrics.get("ec") or {}).get("mean"),
                "annual_rainfall_mm": None,
                "seasonal_forecast_available": seasonal_available,
                "seasonal_forecast_days": seasonal.get("forecast_days"),
                "seasonal_precipitation_mm": seasonal.get("precipitation_total_mm"),
                "seasonal_source_url": seasonal.get("source_url"),
                "drainage": overview.get("drainage"),
                "market_data_available": False,
                "desired_cycle_days_max": 120 if any(k in x for k in ["ngan ngay", "nhanh thu", "quay vong nhanh"]) else None,
                "limit": 5,
            }
            rec_res = client.post(f"{KNOWLEDGE_URL}/recommend/crops", json=rec_payload)
            if rec_res.status_code >= 400:
                return respond(
                    user, farm_id,
                    "Tôi chưa truy cập được bộ khuyến nghị cây trồng nên sẽ không tự đoán. Bạn có thể thử lại hoặc yêu cầu chuyên gia nông học hỗ trợ.",
                    "crop_recommendation_unavailable", False,
                )
            recommendation = rec_res.json()
            items = recommendation.get("items", [])[:3]
            if not items:
                return respond(
                    user, farm_id,
                    "Kho tri thức chưa có hồ sơ cây trồng phù hợp để so sánh. Tôi sẽ không tự bịa danh sách cây.",
                    "crop_recommendation_empty", False,
                )
            candidate_text = "; ".join(
                f"{item['crop_name']} — mức phù hợp tham khảo {item['suitability_score']}%"
                for item in items
            )
            missing_map = {
                "temperature_mean": "nhiệt độ", "soil_ph": "pH đất", "annual_rainfall_mm": "lượng mưa mùa vụ",
                "drainage": "khả năng thoát nước", "cultivation_type": "hình thức canh tác",
                "desired_cycle_days_max": "thời gian quay vòng", "market_data": "giá/đầu ra thị trường",
            }
            missing_text = ", ".join(missing_map.get(v, v) for v in recommendation.get("missing_fields", []))
            climate_basis = (
                f"dự báo mùa vụ {seasonal.get('forecast_days')} ngày"
                if seasonal_available
                else f"dữ liệu quan trắc {climate.get('hours', 24)} giờ (chưa có dự báo mùa vụ)"
            )
            answer = (
                f"Tôi đã đối chiếu {climate_basis} của khu {selected_zone}, hồ sơ vườn và các nguồn nông học đã kiểm duyệt. "
                f"Các cây đứng đầu ở bước sàng lọc sinh thái là: {candidate_text}. {recommendation.get('conclusion', '')}"
            )
            if missing_text:
                answer += f" Dữ liệu còn thiếu để kết luận chắc hơn: {missing_text}."
            all_sources = []
            seen_urls = set()
            for item in items:
                for src in item.get("sources", []):
                    if src.get("source_url") and src["source_url"] not in seen_urls:
                        all_sources.append(src)
                        seen_urls.add(src["source_url"])
            primary_source = all_sources[0] if all_sources else None
            evidence_data = {
                "farm_overview": {
                    "farm_id": farm_id, "crop_name": overview.get("crop_name"), "region": overview.get("region"),
                    "cultivation_type": overview.get("cultivation_type"), "drainage": overview.get("drainage"),
                },
                "climate_summary": climate,
                "seasonal_outlook": seasonal,
                "recommendation": recommendation,
                "sources": all_sources,
            }
            confidence = max((float(item.get("confidence", 0)) for item in items), default=0.55)
            return respond(
                user, farm_id, answer, "crop_recommendation", True, "crop_suitability_rag",
                data=evidence_data, source=primary_source, insights={"candidates": items, "missing_fields": recommendation.get("missing_fields", [])},
                confidence=confidence, knowledge_mode=True,
            )

        # Bách khoa AI theo nông sản: crop router chọn capability/model phù hợp thay vì dùng bừa 10 model chung.
        if planned_tool == "get_ai_capabilities" or any(k in x for k in ["bach khoa ai", "nang luc ai", "model nao cho vuon", "mo hinh nao cho vuon"]):
            params = {"zone": zone} if zone else {}
            cap_res = client.get(
                f"{CROP_ROUTER_URL}/farms/{farm_id}/capabilities",
                params=params,
                headers={"Authorization": authorization or ""},
            )
            if cap_res.status_code != 200:
                return respond(user, farm_id, "Chưa đọc được Bách khoa AI theo nông sản nên tôi không tự gán model cho vườn.", "ai_capabilities_unavailable", False)
            caps = cap_res.json()
            crop = caps.get("crop") or {}
            counts = caps.get("counts") or {}
            ready = [c for c in caps.get("capabilities", []) if c.get("resolved_status") == "ready"][:6]
            names = ", ".join(c.get("display_name_vi", c.get("capability_key", "")) for c in ready) or "chưa có capability READY"
            answer = (
                f"Bách khoa AI đã ánh xạ vườn này sang nông sản {crop.get('source_crop_name', crop.get('crop_key', 'khác'))} "
                f"(khóa {crop.get('crop_key', 'other')}). Hiện có {counts.get('ready',0)} READY, "
                f"{counts.get('experimental',0)} EXPERIMENTAL và {counts.get('blocked',0)} BLOCKED. "
                f"Các capability READY tiêu biểu: {names}. EXPERIMENTAL/BLOCKED không được dùng để khẳng định production."
            )
            return respond(user, farm_id, answer, "ai_capabilities", True, "crop_router", data=caps, confidence=0.9)

        # AI phân tích dữ liệu đã học: biểu đồ, dự báo, bất thường và gợi ý.
        if any(k in x for k in ["ve bieu do", "bieu do", "do thi", "xuat bieu do", "xem xu huong"]):
            metric, metric_label = detect_metric(message)
            if not metric:
                return respond(user, farm_id, "Bạn cần nói rõ chỉ số muốn vẽ: độ ẩm đất, độ ẩm không khí, nhiệt độ, EC, pH hoặc lưu lượng.", "metric_context_required", True)
            hours = extract_hours(message)
            params = {"metric": metric, "hours": hours}
            if zone:
                params["zone"] = zone
            res = client.get(f"{ANALYTICS_URL}/farms/{farm_id}/chart", params=params)
            if res.status_code >= 400:
                detail = res.json().get("detail", "Chưa tạo được biểu đồ.")
                return respond(user, farm_id, detail, "chart_unavailable", False)
            chart = res.json()
            analysis = chart.get("analysis", {})
            model = analysis.get("model", {})
            rec = analysis.get("recommendation", {})
            answer = (
                f"Tôi đã vẽ biểu đồ {metric_label} khu {analysis.get('zone_code', zone or 'A')} trong {hours} giờ. "
                f"Giá trị gần nhất là {model.get('latest_value', '-')} {analysis.get('unit', '')}; "
                f"dự báo sau {model.get('forecast_minutes', 30)} phút khoảng {model.get('forecast_value', '-')} {analysis.get('unit', '')}. "
                f"Đánh giá: {rec.get('summary', 'đang theo dõi dữ liệu')}."
            )
            suggestion = None
            if rec.get("decision") == "human_required":
                suggestion = ticket_suggestion(
                    farm_id, rec.get("title", "AI phát hiện vấn đề cần kiểm tra"),
                    rec.get("summary", answer), "GENERAL", "urgent", analysis.get("zone_code"),
                )
            return respond(
                user, farm_id, answer, "ai_chart", True, "ai_chart_and_forecast",
                data={**analysis, "requested_hours": hours}, suggestion=suggestion, visualization={k: chart[k] for k in ["type", "mime_type", "base64", "filename", "title"]},
                insights=rec,
            )

        if planned_tool == "get_ai_summary" or any(k in x for k in ["phan tich", "danh gia", "goi y", "du bao", "nguy co", "xu huong", "ai thay", "tinh hinh vuon"]):
            metric, metric_label = detect_metric(message)
            hours = extract_hours(message)
            if planned_tool == "get_ai_summary" or any(k in x for k in ["tinh hinh vuon", "tong quan thong minh", "danh gia vuon"]):
                summary = client.get(f"{ANALYTICS_URL}/farms/{farm_id}/smart-summary").json()
                top = summary.get("top_recommendation") or {}
                trained = None
                if zone:
                    try:
                        trained_res = client.get(f"{ANALYTICS_URL}/ml/predict/{farm_id}", params={"zone": zone})
                        if trained_res.status_code == 200:
                            trained = trained_res.json()
                    except httpx.HTTPError:
                        trained = None
                if trained:
                    all_predictions = trained.get("predictions", [])
                    approved_predictions = [p for p in all_predictions if p.get("deployment_status") == "approved"]
                    by_name = {p["model_name"]: p for p in approved_predictions}
                    if approved_predictions:
                        farm_health = by_name.get("farm_health", {}).get("label", "chưa có model approved")
                        anomaly = by_name.get("anomaly_multisensor", {}).get("label", "chưa có model approved")
                        irrigation = by_name.get("irrigation_need", {}).get("label", "chưa có model approved")
                        device = by_name.get("device_health", {}).get("label", "chưa có model approved")
                        answer = (
                            f"{len(approved_predictions)}/{len(all_predictions)} mô hình đã vượt quality gate và suy luận trên dữ liệu IoT mới nhất "
                            f"của khu {trained.get('zone_code', zone or 'A')}. Tổng thể vườn: {farm_health}; "
                            f"đa cảm biến: {anomaly}; thiết bị: {device}; nhu cầu tưới: {irrigation}. "
                            f"{top.get('summary', 'AI tiếp tục theo dõi và chỉ chuyển kỹ thuật viên khi cần kiểm tra vật lý.')}"
                        )
                    else:
                        answer = (
                            f"10 mô hình đã chạy thử trên khu {trained.get('zone_code', zone or 'A')}, nhưng chưa mô hình nào vượt quality gate. "
                            "Kết quả hiện chỉ để quan sát, không dùng để tự phát cảnh báo hoặc khẳng định tình trạng vườn."
                        )
                else:
                    answer = (
                        f"AI đã phân tích tự động các khu trong vườn. {top.get('summary', 'Chưa có bất thường nghiêm trọng.')} "
                        f"Có {summary.get('human_required_count', 0)} tình huống cần con người kiểm tra thực tế."
                    )
                suggestion = None
                human_required = (trained and trained.get("decision") == "human_required") or summary.get("human_required_count", 0) > 0
                if human_required:
                    suggestion = ticket_suggestion(farm_id, top.get("title", "Cần kiểm tra hiện trường"), top.get("summary", answer), "GENERAL", "urgent", zone)
                return respond(
                    user, farm_id, answer, "ai_smart_summary", True, "trained_models+smart_summary",
                    data={
                        "summary": summary,
                        "trained_models": trained,
                        "model_count": len((trained or {}).get("predictions", [])) if trained else 0,
                    },
                    suggestion=suggestion, insights=top,
                )

            if not metric:
                return respond(user, farm_id, "Bạn cần nói rõ chỉ số cần phân tích; hệ thống không tự mặc định sang độ ẩm đất.", "metric_context_required", True)
            params = {"metric": metric, "hours": hours}
            if zone:
                params["zone"] = zone
            analysis = client.get(f"{ANALYTICS_URL}/farms/{farm_id}/analyze", params=params).json()
            model = analysis.get("model", {})
            rec = analysis.get("recommendation", {})
            if not model.get("ready"):
                return respond(user, farm_id, rec.get("summary", "AI đang thu thập thêm dữ liệu để học."), "ai_collecting_data", True, "ai_analyze", data=analysis, insights=rec)
            answer = (
                f"AI đã học từ {model.get('sample_count')} mẫu {metric_label} khu {analysis.get('zone_code', zone or 'A')}. "
                f"Xu hướng hiện tại {model.get('slope_per_hour', 0):+.2f} {analysis.get('unit', '')}/giờ; "
                f"dự báo {model.get('forecast_value')} {analysis.get('unit', '')} sau {model.get('forecast_minutes')} phút. "
                f"Độ tin cậy mô hình khoảng {round(float(model.get('confidence', 0))*100)}%. {rec.get('summary', '')}"
            )
            suggestion = None
            if rec.get("decision") == "human_required":
                suggestion = ticket_suggestion(farm_id, rec.get("title", "Cần kỹ thuật viên kiểm tra"), rec.get("summary", answer), "GENERAL", "urgent", analysis.get("zone_code"))
            analysis_evidence = {
                **analysis,
                "requested_hours": hours,
                "confidence_percent": round(float(model.get("confidence", 0)) * 100),
            }
            return respond(
                user, farm_id, answer, "ai_analysis", True, "ai_analyze",
                data=analysis_evidence, suggestion=suggestion, insights=rec,
                confidence=float(model.get("confidence", 0)),
            )

        metric, metric_label = detect_metric(message)
        if planned_tool == "get_latest_metric" and metric is None:
            return respond(
                user,
                farm_id,
                "Bạn cần nói rõ chỉ số cần đọc: độ ẩm đất, độ ẩm không khí, nhiệt độ, EC, pH hoặc lưu lượng. Hệ thống không dùng chỉ số do mô hình tự suy diễn.",
                "metric_context_required",
                True,
                data={"farm_id": farm_id, "zone": zone, "zone_context_source": zone_context_source},
            )

        if metric:
            metric_res = client.get(
                f"{FARM_DATA_URL}/farms/{farm_id}/metrics/latest",
                params={"metric": metric, "zone": zone} if zone else {"metric": metric},
            )
            data = metric_res.json()
            error = data.get("error") or data.get("detail") or {}
            if metric_res.status_code == 409 and isinstance(error, dict) and error.get("code") == "ZONE_CONTEXT_REQUIRED":
                return respond(
                    user,
                    farm_id,
                    "Vườn có nhiều khu. Bạn hãy nói rõ khu A/B/C trước khi hỏi số liệu; hệ thống sẽ không tự chọn khu đầu tiên.",
                    "zone_context_required",
                    True,
                    "get_latest_metric",
                    data,
                )
            if metric_res.status_code >= 400:
                message_text = error.get("message") if isinstance(error, dict) else None
                return respond(user, farm_id, message_text or "Chưa đọc được dữ liệu cảm biến.", "metric_unavailable", False, "get_latest_metric", data)
            zone_text = f"khu {data.get('zone_code') or zone}" if (data.get("zone_code") or zone) else "khu được chọn"
            if not data.get("available"):
                suggestion = ticket_suggestion(
                    farm_id,
                    f"Không có dữ liệu {metric_label} {zone_text}",
                    f"Chatbot không tìm thấy dữ liệu {metric_label} cho {zone_text}. Cần kiểm tra cấu hình hoặc cảm biến.",
                    "SENSOR_STALE",
                    "high",
                    data.get("zone_code") or zone,
                )
                return respond(
                    user,
                    farm_id,
                    f"Hiện không có dữ liệu {metric_label} cho {zone_text}. Tôi sẽ không ước đoán giá trị. Có thể tạo ticket để kỹ thuật viên kiểm tra cấu hình và cảm biến.",
                    "metric_missing",
                    True,
                    "get_latest_metric",
                    data,
                    suggestion,
                )
            observed = format_time(data["observed_at"])
            # Truth Guard must see the exact localized timestamp shown to the user.
            # Otherwise a UTC hour in observed_at can be compared with the UTC+7
            # display hour and be rejected as an invented number.
            data = {**data, "display_observed_at": observed}
            if str(data.get("quality") or "").lower() in {"suspect", "bad"}:
                return respond(
                    user,
                    farm_id,
                    f"Số đo gần nhất của {zone_text} là {data['value']} {data['unit']} lúc {observed}, nhưng chất lượng cảm biến đang ở mức {data['quality']}. Tôi không dùng số đo nghi ngờ này để khẳng định tình trạng hiện tại.",
                    "metric_quality_rejected",
                    False,
                    "get_latest_metric",
                    data,
                )
            if not data["fresh"]:
                suggestion = ticket_suggestion(
                    farm_id,
                    f"Dữ liệu {metric_label} {zone_text} bị trễ",
                    f"Dữ liệu gần nhất ghi nhận lúc {observed} và đã vượt ngưỡng cập nhật. Cần kiểm tra cảm biến/gateway.",
                    "SENSOR_STALE",
                    "high",
                    data.get("zone_code"),
                )
                return respond(
                    user,
                    farm_id,
                    f"Dữ liệu gần nhất của {zone_text} là {data['value']} {data['unit']} lúc {observed}, nhưng dữ liệu đã quá cũ nên chưa thể coi là số liệu hiện tại. Tôi không suy đoán giá trị mới.",
                    "metric_stale",
                    True,
                    "get_latest_metric",
                    data,
                    suggestion,
                )
            meaning = ""
            if data.get("status") == "low":
                meaning = f", thấp hơn ngưỡng mục tiêu {data['target_min']}–{data['target_max']} {data['unit']}"
            elif data.get("status") == "high":
                meaning = f", cao hơn ngưỡng mục tiêu {data['target_min']}–{data['target_max']} {data['unit']}"
            elif data.get("status") == "normal":
                meaning = f", đang trong ngưỡng mục tiêu {data['target_min']}–{data['target_max']} {data['unit']}"
            suggestion = None
            if data.get("status") == "low" and metric == "soil_moisture":
                suggestion = ticket_suggestion(
                    farm_id,
                    f"Độ ẩm thấp tại {zone_text}",
                    f"Độ ẩm {zone_text} là {data['value']} {data['unit']} lúc {observed}, thấp hơn ngưỡng mục tiêu.",
                    "LOW_MOISTURE",
                    "high",
                    data.get("zone_code"),
                )
            answer = f"{zone_text.capitalize()} hiện có {metric_label} {data['value']} {data['unit']}{meaning}. Dữ liệu ghi nhận lúc {observed}."
            evidence: Any = data
            source = None
            tool_name = "get_latest_metric"
            if "search_knowledge" in planned_tool_names:
                knowledge = client.get(f"{KNOWLEDGE_URL}/query", params={"q": message, "farm_id": farm_id}).json()
                if knowledge.get("answerable"):
                    source = knowledge.get("source")
                    source_name = (source or {}).get("source_name", "nguồn đã kiểm duyệt")
                    answer += f" Hướng dẫn tham khảo từ {source_name}: {knowledge['answer']}"
                    evidence = {"operational_fact": data, "approved_knowledge": knowledge}
                    tool_name = "get_latest_metric+search_knowledge"
            return respond(
                user,
                farm_id,
                answer,
                "read_metric",
                True,
                tool_name,
                evidence,
                suggestion,
                source=source,
                knowledge_mode=source is not None,
            )

        if planned_tool == "get_devices" or any(k in x for k in ["thiet bi", "online", "offline", "mat ket noi", "ket noi"]):
            data = client.get(f"{FARM_DATA_URL}/farms/{farm_id}/devices", params={"zone": zone} if zone else {}).json()
            if not data["items"]:
                return respond(user, farm_id, "Không tìm thấy thiết bị phù hợp trong cấu hình vườn.", "device_missing", True, "get_devices", data)
            offline = [d for d in data["items"] if not d["effective_online"]]
            if offline:
                names = ", ".join(d["device_name"] for d in offline)
                last = format_time(offline[0].get("last_seen_at"))
                data = {**data, "display_last_seen_at": last}
                suggestion = ticket_suggestion(
                    farm_id,
                    "Thiết bị mất kết nối",
                    f"Thiết bị {names} không có trạng thái online hợp lệ. Last seen gần nhất: {last}.",
                    "DEVICE_OFFLINE",
                    "urgent",
                    zone,
                )
                return respond(
                    user,
                    farm_id,
                    f"Phát hiện thiết bị không online: {names}. Dữ liệu trạng thái đã bị trễ; lần ghi nhận gần nhất lúc {last}. Cần kiểm tra nguồn và kết nối mạng; có thể tạo ticket khẩn để kỹ thuật viên tiếp nhận.",
                    "device_offline",
                    True,
                    "get_devices",
                    data,
                    suggestion,
                )
            names = ", ".join(d["device_name"] for d in data["items"])
            return respond(user, farm_id, f"Các thiết bị đang có trạng thái online hợp lệ: {names}.", "devices_online", True, "get_devices", data)

        if planned_tool == "get_port_status" or any(k in x for k in ["van", "cong", "cổng", "bom", "bơm"]):
            port = planned_args.get("port_number") or extract_port(message)
            if port is None:
                return respond(user, farm_id, "Bạn cần nói rõ số cổng hoặc số van, ví dụ: “Van số 2 đang chạy không?”.", "port_missing_slot", True)
            data = client.get(
                f"{FARM_DATA_URL}/farms/{farm_id}/ports/{port}",
                params={"zone": zone} if zone else {},
            ).json()
            if not data["configured"]:
                return respond(user, farm_id, f"Cổng số {port} chưa có trong cấu hình vườn. Tôi sẽ không đoán trạng thái.", "port_not_configured", True, "get_port_status", data)
            if data["ambiguous"]:
                return respond(user, farm_id, f"Có nhiều thiết bị cùng sử dụng cổng số {port}. Bạn hãy nói thêm khu A/B hoặc tên thiết bị để tránh nhầm.", "port_ambiguous", True, "get_port_status", data)
            item = data["items"][0]
            item["display_observed_at"] = format_time(item.get("observed_at"))
            item["display_last_seen_at"] = format_time(item.get("last_seen_at"))
            if not item["fresh"]:
                suggestion = ticket_suggestion(
                    farm_id,
                    f"Trạng thái {item['port_name']} bị trễ",
                    f"Không có bản tin trạng thái mới cho {item['port_name']}; last seen {format_time(item.get('last_seen_at'))}.",
                    "DEVICE_OFFLINE",
                    "high",
                    item.get("zone_code"),
                )
                return respond(user, farm_id, f"Trạng thái gần nhất của {item['port_name']} đã quá cũ, nên tôi chưa thể khẳng định van/bơm hiện đang chạy hay tắt.", "port_stale", True, "get_port_status", data, suggestion)
            state = "đang chạy/mở" if item.get("running") else "đang tắt/đóng"
            return respond(user, farm_id, f"{item['port_name']} hiện {state}. Thiết bị đang online; trạng thái ghi nhận lúc {item['display_observed_at']}.", "read_port", True, "get_port_status", data)

        if "get_irrigation_schedules" in planned_tool_names or planned_tool == "get_irrigation_schedules":
            data = client.get(
                f"{FARM_DATA_URL}/farms/{farm_id}/irrigation/schedules",
                params={"zone": zone} if zone else {},
            ).json()
            if not data.get("items"):
                return respond(user, farm_id, "Không tìm thấy lịch tưới đã cấu hình cho phạm vi được chọn.", "irrigation_schedule_empty", True, "get_irrigation_schedules", data)
            previews = "; ".join(
                f"{item['schedule_name']} lúc {item['start_time']}, {item['duration_minutes']} phút ({'đang bật' if item['enabled'] else 'đang tắt'})"
                for item in data["items"][:4]
            )
            return respond(user, farm_id, f"Có {data['total']} lịch tưới: {previews}.", "irrigation_schedule", True, "get_irrigation_schedules", data)

        if "get_irrigation_history" in planned_tool_names or planned_tool == "get_irrigation_history":
            history_args = next((item.get("arguments") or {} for item in planned_steps if item.get("tool_name") == "get_irrigation_history"), {})
            hours = max(1, min(int(history_args.get("hours") or 168), 2160))
            data = client.get(
                f"{FARM_DATA_URL}/farms/{farm_id}/irrigation/history",
                params={"hours": hours, **({"zone": zone} if zone else {})},
            ).json()
            if not data.get("items"):
                return respond(user, farm_id, f"Không có ca tưới nào trong {hours} giờ gần đây cho phạm vi được chọn.", "irrigation_history_empty", True, "get_irrigation_history", data)
            failed = sum(1 for item in data["items"] if item.get("result") == "failed")
            liters = sum(float(item.get("water_liters") or 0) for item in data["items"])
            data = {
                **data,
                "query_hours": hours,
                "summary_total_liters": round(liters, 1),
                "summary_failed_count": failed,
            }
            return respond(user, farm_id, f"Trong {hours} giờ gần đây có {data['total']} ca tưới, tổng {liters:.1f} lít; {failed} ca thất bại.", "irrigation_history", True, "get_irrigation_history", data)

        if "get_command_logs" in planned_tool_names or planned_tool == "get_command_logs":
            data = client.get(f"{FARM_DATA_URL}/farms/{farm_id}/commands", params={"limit": 50}).json()
            if not data.get("items"):
                return respond(user, farm_id, "Chưa có lệnh điều khiển nào trong nhật ký của vườn này.", "command_logs_empty", True, "get_command_logs", data)
            latest = data["items"][0]
            latest["display_requested_at"] = format_time(latest.get("requested_at"))
            return respond(
                user,
                farm_id,
                f"Nhật ký có {data['total']} lệnh. Lệnh gần nhất là {latest['command_type']} ở trạng thái {latest['status']}, tạo lúc {latest['display_requested_at']}. Đây chỉ là truy vấn đọc, chatbot không thực thi lệnh.",
                "command_logs",
                True,
                "get_command_logs",
                data,
            )

        if planned_tool == "get_irrigation_summary" or any(k in x for k in ["tuoi may lan", "hom nay tuoi", "hom qua tuoi", "tuan nay tuoi"]):
            period = str(planned_args.get("period") or ("yesterday" if "hom qua" in x else "week" if "tuan" in x else "today"))
            data = client.get(
                f"{FARM_DATA_URL}/farms/{farm_id}/irrigation/summary",
                params={"period": period, **({"zone": zone} if zone else {})},
            ).json()
            period_label = {"today": "Hôm nay", "yesterday": "Hôm qua", "week": "Tuần này"}[period]
            warning = ""
            suggestion = None
            if data["failed_count"]:
                warning = f" Có {data['failed_count']} ca thất bại."
                suggestion = ticket_suggestion(
                    farm_id,
                    "Lịch tưới có ca thất bại",
                    f"{period_label} ghi nhận {data['failed_count']} ca tưới thất bại.",
                    "GENERAL",
                    "high",
                    zone,
                )
            return respond(
                user,
                farm_id,
                f"{period_label}{' tại khu ' + zone if zone else ''} ghi nhận {data['run_count']} ca tưới, tổng {data['total_minutes']} phút và {data['total_liters']} lít nước.{warning}",
                "irrigation_summary",
                True,
                "get_irrigation_summary",
                data,
                suggestion,
            )

        if planned_tool == "get_alerts" or any(k in x for k in ["canh bao", "su co", "bat thuong", "thieu nuoc", "khong co nuoc"]):
            data = client.get(f"{FARM_DATA_URL}/farms/{farm_id}/alerts", params={"zone": zone} if zone else {}).json()
            if not data["items"]:
                return respond(user, farm_id, "Hiện hệ thống không có cảnh báo mở phù hợp. Nếu ngoài vườn vẫn bất thường, hãy mô tả khu, thiết bị và thời điểm để kiểm tra tiếp.", "no_open_alert", True, "get_alerts", data)
            top = data["items"][0]
            top["display_detected_at"] = format_time(top.get("detected_at"))
            suggestion = ticket_suggestion(
                farm_id,
                top["title"],
                top["message"],
                top.get("suggested_checklist_code") or "GENERAL",
                "urgent" if top["severity"] == "urgent" else "high" if top["severity"] == "high" else "normal",
                top.get("zone_code"),
            )
            return respond(
                user,
                farm_id,
                f"Cảnh báo {top['severity']}: {top['title']}. {top['message']} Phát hiện lúc {top['display_detected_at']}.",
                "read_alerts",
                True,
                "get_alerts",
                data,
                suggestion,
            )

        if planned_tool == "create_ticket_suggestion" or any(k in x for k in ["gap ky thuat", "nhan vien", "tao ticket", "ho tro ky thuat", "bao ky thuat"]):
            suggestion = ticket_suggestion(
                farm_id,
                "Yêu cầu hỗ trợ kỹ thuật từ chatbot",
                message,
                "GENERAL",
                "normal",
                zone,
            )
            return respond(user, farm_id, "Tôi đã chuẩn bị nội dung ticket. Bạn hãy bấm “Tạo ticket cho kỹ thuật viên” để xác nhận gửi.", "ticket_confirmation", True, suggestion=suggestion)

        if any(k in x for k in ["ticket cua toi", "yeu cau cua toi", "tinh trang ticket"]):
            return respond(user, farm_id, "Bạn mở mục “Ticket của tôi” để xem trạng thái, phản hồi kỹ thuật viên và gửi thêm thông tin.", "ticket_navigation", True)

        know = client.get(f"{KNOWLEDGE_URL}/query", params={"q": message, "farm_id": farm_id}).json()
        if know.get("answerable"):
            source_name = (know.get("source") or {}).get("source_name", "nguồn đã kiểm duyệt")
            citation = know.get("citation") or {}
            section = citation.get("section") or "mục nội dung liên quan"
            answer = f"Theo {source_name}, {section}: {know['answer']}"
            return respond(
                user, farm_id, answer, "knowledge_answer", True, "knowledge_query",
                data={"items": know.get("items", []), "sources": know.get("sources", [])},
                source=know.get("source"), confidence=know.get("confidence"), knowledge_mode=True,
            )

    return respond(
        user,
        farm_id,
        "Tôi chưa có dữ liệu hoặc tài liệu đủ chắc để trả lời câu này. Tôi sẽ không đoán. Bạn hãy nêu rõ khu, chỉ số, thiết bị hoặc thời gian; hoặc yêu cầu tạo ticket hỗ trợ.",
        "insufficient_data",
        False,
    )


@app.post("/tickets/confirm")
def confirm_ticket(payload: TicketConfirmRequest, authorization: str | None = Header(default=None)):
    user = auth_user(authorization)
    farm_id = ensure_farm(user, payload.farm_id)
    body = payload.model_dump()
    body["farm_id"] = farm_id
    with new_http_client(timeout=15, headers=downstream_headers(authorization)) as client:
        res = client.post(f"{TICKET_URL}/tickets", json=body, headers={"Authorization": authorization or ""})
    if res.status_code >= 400:
        try:
            detail = res.json().get("detail", "Không tạo được ticket.")
        except Exception:
            detail = "Không tạo được ticket."
        raise HTTPException(status_code=res.status_code, detail=detail)
    return res.json()

@app.get("/farm/dashboard")
def farm_dashboard(farm_id: str | None = None, authorization: str | None = Header(default=None)):
    user = auth_user(authorization)
    if user["role"] != "farmer":
        raise HTTPException(status_code=403, detail="Trang dữ liệu vườn dành cho nông dân.")
    selected = ensure_farm(user, farm_id)
    with new_http_client(timeout=15, headers=downstream_headers(authorization)) as client:
        overview_data = client.get(f"{FARM_DATA_URL}/farms/{selected}/overview").json()
        metrics = []
        for zone_item in overview_data.get("zones", []):
            metric = client.get(
                f"{FARM_DATA_URL}/farms/{selected}/metrics/latest",
                params={"metric": "soil_moisture", "zone": zone_item["zone_code"]},
            ).json()
            metrics.append(metric)
        devices_data = client.get(f"{FARM_DATA_URL}/farms/{selected}/devices").json()
        irrigation_data = client.get(f"{FARM_DATA_URL}/farms/{selected}/irrigation/summary", params={"period": "today"}).json()
        alerts_data = client.get(f"{FARM_DATA_URL}/farms/{selected}/alerts").json()
    return {
        "overview": overview_data,
        "moisture_by_zone": metrics,
        "devices": devices_data,
        "irrigation": irrigation_data,
        "alerts": alerts_data,
    }


@app.get("/farm/ai-dashboard")
def farm_ai_dashboard(farm_id: str | None = None, authorization: str | None = Header(default=None)):
    user = auth_user(authorization)
    if user["role"] != "farmer":
        raise HTTPException(status_code=403, detail="Trang AI dành cho nông dân.")
    selected = ensure_farm(user, farm_id)
    with new_http_client(timeout=60, headers=downstream_headers(authorization)) as client:
        summary = client.get(f"{ANALYTICS_URL}/farms/{selected}/smart-summary").json()
        chart = client.get(
            f"{ANALYTICS_URL}/farms/{selected}/chart",
            params={"metric": "soil_moisture", "hours": 24},
        ).json()
        models = client.get(f"{ANALYTICS_URL}/models/status", params={"farm_id": selected}).json()
    return {
        "summary": summary,
        "chart": {k: chart.get(k) for k in ["type", "mime_type", "base64", "filename", "title"]},
        "models": models,
    }
