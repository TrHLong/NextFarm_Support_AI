from __future__ import annotations

import os
import re
import unicodedata
import uuid
from typing import Any

import psycopg
from fastapi import FastAPI
from pydantic import BaseModel
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL")
app = FastAPI(title="NextFarm Sales Consultation Service", version="1.0.0")


def conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.lower().replace("đ", "d")


def detect_area(text: str) -> tuple[float | None, str | None]:
    m = re.search(r"(\d+(?:[\.,]\d+)?)\s*(m2|m²|ha|hecta)", norm(text))
    if not m:
        return None, None
    return float(m.group(1).replace(",", ".")), ("m2" if m.group(2).startswith("m") else "ha")


def detect_crop(text: str) -> str:
    x = norm(text)
    if any(k in x for k in ["vai", "cay an qua", "sau rieng", "xoai", "buoi", "cam"]):
        return "cây ăn quả"
    if any(k in x for k in ["rau", "cai", "xa lach", "dua leo", "ca chua"]):
        return "rau/nhà màng"
    if any(k in x for k in ["hoa", "lan", "cay canh"]):
        return "hoa/cây cảnh"
    return "cây trồng chưa rõ"


def wants_handover(text: str) -> bool:
    x = norm(text)
    return any(k in x for k in ["demo", "bao gia", "tu van vien", "gap nguoi", "goi lai", "ky hop dong", "lien he"])


class ConsultRequest(BaseModel):
    lead_profile_id: str
    message: str


@app.get("/health")
def health():
    return {"service": "sales-service", "status": "ok"}


def build_recommendations(crop: str, area: float | None, unit: str | None) -> list[tuple[str, str, str]]:
    small = bool(area and ((unit == "m2" and area <= 200) or (unit == "ha" and area < 0.2)))
    if small:
        return [
            ("mod_irrigation", "must_have", "Diện tích nhỏ nên bắt đầu bằng tưới tự động gọn, chia ít khu, dễ vận hành trên điện thoại."),
            ("mod_management", "recommended", "Nhật ký chăm sóc giúp người mới làm vườn ghi lại việc tưới, bón, phun và theo dõi kết quả."),
            ("mod_weather", "recommended", "Weather giúp biết mưa/nắng/ẩm để điều chỉnh tưới và phòng rủi ro thời tiết."),
            ("mod_gis", "later", "GIS cần thiết hơn khi mở rộng nhiều lô hoặc cần bản đồ hóa vùng trồng."),
            ("mod_qr", "later", "QR Check phù hợp khi bắt đầu bán sản phẩm và cần truy xuất nguồn gốc."),
        ]
    return [
        ("mod_gis", "must_have", "GIS định danh lô/khu trước khi gắn thiết bị, cảnh báo và nhật ký."),
        ("mod_irrigation", "must_have", "Tưới thông minh là lớp vận hành nước, giảm phụ thuộc thao tác tay."),
        ("mod_nmc", "recommended", "NMC theo dõi nhiệt độ, độ ẩm không khí, môi trường nhà màng hoặc vùng sản xuất có rủi ro."),
        ("mod_fertikit", "recommended", "Fertikit phù hợp khi cần châm phân/dinh dưỡng theo lịch hoặc theo chỉ số EC/pH."),
        ("mod_management", "recommended", "Management gom nhật ký, công việc, thiết bị và hồ sơ vận hành."),
        ("mod_yield", "later", "Sản lượng/Yield dùng tốt khi đã có dữ liệu vụ mùa đủ dài."),
        ("mod_ai_pest", "later", "AI sâu bệnh nên dùng khi có ảnh/cảnh báo thường xuyên từ vườn."),
        ("mod_qr", "later", "QR Check phục vụ truy xuất, bán hàng và chứng nhận."),
    ]


def build_answer(crop: str, area: float | None, unit: str | None, recommendations: list[tuple[str, str, str]]) -> str:
    area_text = f"{area:g} {unit}" if area and unit else "diện tích chưa rõ"
    first_modules = ", ".join(r[0].replace("mod_", "").upper() for r in recommendations[:3])
    if area and unit == "m2" and area <= 200:
        opening = (
            f"Với {crop} khoảng {area_text}, em không khuyên đầu tư một hệ thống lớn ngay. "
            "Cách làm hợp lý là bắt đầu nhỏ, đo được, sửa được: chia 1-2 khu tưới, dùng lịch tưới tự động, "
            "ghi nhật ký chăm sóc và theo dõi thời tiết. Khi vườn chạy ổn mới mở rộng sang GIS/QR/sản lượng."
        )
    else:
        opening = (
            f"Với nhu cầu {crop}, {area_text}, em sẽ đi theo lộ trình có nền: định danh lô/khu bằng GIS, "
            "thiết kế tưới thông minh theo từng khu, thêm NMC/Weather để theo dõi môi trường, rồi dùng Management để lưu nhật ký và ticket."
        )
    return (
        f"{opening}\n\n"
        f"Cấu hình gợi ý ban đầu: {first_modules}. "
        "Em cần hỏi thêm 4 thông tin để tư vấn sát hơn: tỉnh/khu vực, nguồn nước và máy bơm hiện có, mục tiêu làm gia đình hay kinh doanh, "
        "và anh/chị muốn tự động hóa phần nào trước. Nếu muốn trao đổi thật, em có thể ghi nhận để tư vấn viên tiếp nhận."
    )


@app.post("/consult")
def consult(payload: ConsultRequest):
    area, unit = detect_area(payload.message)
    crop = detect_crop(payload.message)
    recommendations = build_recommendations(crop, area, unit)
    answer = build_answer(crop, area, unit, recommendations)
    handover = wants_handover(payload.message)

    with conn() as db, db.cursor() as cur:
        req_id = f"req_{uuid.uuid4().hex[:12]}"
        cur.execute(
            """
            INSERT INTO sales.lead_requirements(
                requirement_id, lead_profile_id, crop_text, area_value, area_unit,
                cultivation_type, province_or_region, water_source, has_pump,
                business_goal, raw_message, extracted_confidence
            )
            VALUES (%s,%s,%s,%s,%s,'unknown',NULL,NULL,NULL,'unknown',%s,%s)
            """,
            (req_id, payload.lead_profile_id, crop, area, unit, payload.message, 0.78 if area else 0.56),
        )
        for module_id, fit, reason in recommendations:
            cur.execute(
                """
                INSERT INTO sales.module_recommendations(recommendation_id,lead_profile_id,module_id,fit_level,reason_vi,created_by)
                VALUES (%s,%s,%s,%s,%s,'chatbot')
                """,
                (f"rec_{uuid.uuid4().hex[:12]}", payload.lead_profile_id, module_id, fit, reason),
            )
        cur.execute(
            """
            INSERT INTO sales.consultation_notes(consultation_note_id,lead_profile_id,note_type,content_vi)
            VALUES (%s,%s,'bot_advice',%s)
            """,
            (f"note_{uuid.uuid4().hex[:12]}", payload.lead_profile_id, answer),
        )
        opportunity: dict[str, Any] | None = None
        if handover:
            cur.execute(
                """
                INSERT INTO sales.opportunities(opportunity_id,lead_profile_id,title,stage,assigned_to,next_action_vi)
                VALUES (%s,%s,%s,'new','user_manager_01',%s)
                RETURNING opportunity_id,stage,next_action_vi
                """,
                (
                    f"opp_{uuid.uuid4().hex[:12]}",
                    payload.lead_profile_id,
                    "Khách muốn tư vấn/demo NextFarm",
                    "Tư vấn viên gọi lại để xác nhận cây trồng, diện tích, nguồn nước, thiết bị sẵn có và lịch demo.",
                ),
            )
            opportunity = cur.fetchone()
        db.commit()

    if handover:
        answer += "\n\nEm đã ghi nhận nhu cầu tư vấn trực tiếp. Bước sau là xác nhận thực địa và chọn cấu hình vừa đủ, tránh lắp dư so với quy mô vườn."
    return {"answer": answer, "lead_profile_id": payload.lead_profile_id, "recommendations": recommendations, "opportunity": opportunity}


@app.get("/leads/{lead_profile_id}")
def lead_detail(lead_profile_id: str):
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT * FROM sales.lead_profiles WHERE lead_profile_id=%s", (lead_profile_id,))
        lead = cur.fetchone()
        cur.execute(
            """
            SELECT r.*,m.module_name
            FROM sales.module_recommendations r
            LEFT JOIN knowledge.product_modules m ON m.module_id=r.module_id
            WHERE lead_profile_id=%s
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (lead_profile_id,),
        )
        recs = cur.fetchall()
        cur.execute("SELECT * FROM sales.opportunities WHERE lead_profile_id=%s ORDER BY created_at DESC", (lead_profile_id,))
        opps = cur.fetchall()
    return {"lead": lead, "recommendations": recs, "opportunities": opps}
