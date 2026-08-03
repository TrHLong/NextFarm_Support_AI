from __future__ import annotations

import os
import re
import uuid

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL")
app = FastAPI(title="NextFarm Identity Service", version="1.0.0")


def conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def clean_phone(phone: str) -> str:
    return re.sub(r"\D+", "", phone or "")


class IntakeRequest(BaseModel):
    full_name: str
    phone: str
    region: str | None = None
    note: str | None = None
    channel: str = "web_chat"


class AuthRequest(BaseModel):
    subject_id: str
    farm_id: str | None = None
    action: str


@app.get("/health")
def health():
    return {"service": "identity-service", "status": "ok"}


@app.post("/intake/resolve")
def resolve_intake(payload: IntakeRequest):
    phone = clean_phone(payload.phone)
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT * FROM identity.user_accounts WHERE phone=%s AND status=%s", (phone, "active"))
        user = cur.fetchone()
        if user:
            cur.execute(
                """
                SELECT farm_id, farm_role, can_read_data, can_request_control
                FROM identity.farm_memberships
                WHERE user_id=%s
                ORDER BY farm_role
                LIMIT 1
                """,
                (user["user_id"],),
            )
            membership = cur.fetchone()
            return {
                "status": "MATCHED_CUSTOMER",
                "identity_kind": "customer",
                "subject_id": user["user_id"],
                "user_id": user["user_id"],
                "lead_profile_id": None,
                "display_name": user["display_name"],
                "farm_id": membership["farm_id"] if membership else None,
                "message": f"Đã xác minh {user['display_name']}. Chatbot được phép đọc dữ liệu vườn trong phạm vi đã phân quyền.",
            }

        lead_id = f"lead_{phone}" if phone else f"lead_{uuid.uuid4().hex[:12]}"
        lead_profile_id = f"lead_profile_{phone}" if phone else f"lead_profile_{uuid.uuid4().hex[:12]}"
        cur.execute(
            """
            INSERT INTO identity.customer_leads(lead_id, full_name, phone, region, note, status)
            VALUES (%s,%s,%s,%s,%s,'temp')
            ON CONFLICT (lead_id)
            DO UPDATE SET full_name=EXCLUDED.full_name, region=EXCLUDED.region, note=EXCLUDED.note, updated_at=now()
            """,
            (lead_id, payload.full_name, phone, payload.region, payload.note),
        )
        cur.execute(
            """
            INSERT INTO sales.lead_profiles(lead_profile_id, lead_id, full_name, phone, region, channel, lead_status, interest_level)
            VALUES (%s,%s,%s,%s,%s,%s,'new','learning')
            ON CONFLICT (lead_profile_id)
            DO UPDATE SET full_name=EXCLUDED.full_name, region=EXCLUDED.region, updated_at=now()
            """,
            (lead_profile_id, lead_id, payload.full_name, phone, payload.region, payload.channel),
        )
        db.commit()
        return {
            "status": "NEW_LEAD",
            "identity_kind": "lead",
            "subject_id": lead_profile_id,
            "user_id": None,
            "lead_id": lead_id,
            "lead_profile_id": lead_profile_id,
            "display_name": payload.full_name,
            "farm_id": None,
            "message": "Đã lưu thông tin vào hồ sơ khách mới. Chatbot có thể tư vấn NextFarm và ghi nhận nhu cầu, nhưng chưa được đọc dữ liệu riêng của bất kỳ vườn nào.",
        }


@app.get("/context/{subject_id}")
def context(subject_id: str):
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT * FROM identity.user_accounts WHERE user_id=%s", (subject_id,))
        user = cur.fetchone()
        if user:
            cur.execute("SELECT * FROM identity.farm_memberships WHERE user_id=%s LIMIT 1", (subject_id,))
            membership = cur.fetchone()
            return {
                "identity_kind": "customer",
                "subject_id": subject_id,
                "user_id": subject_id,
                "lead_profile_id": None,
                "display_name": user["display_name"],
                "farm_id": membership["farm_id"] if membership else None,
                "can_read_data": bool(membership and membership["can_read_data"]),
                "can_request_control": bool(membership and membership["can_request_control"]),
            }

        cur.execute(
            """
            SELECT lp.*, cl.note
            FROM sales.lead_profiles lp
            LEFT JOIN identity.customer_leads cl ON cl.lead_id=lp.lead_id
            WHERE lp.lead_profile_id=%s
            """,
            (subject_id,),
        )
        lead = cur.fetchone()
        if lead:
            return {
                "identity_kind": "lead",
                "subject_id": subject_id,
                "user_id": None,
                "lead_profile_id": subject_id,
                "display_name": lead["full_name"],
                "farm_id": None,
                "can_read_data": False,
                "can_request_control": False,
                "interest_level": lead["interest_level"],
            }
    raise HTTPException(404, "subject not found")


@app.post("/authorize")
def authorize(payload: AuthRequest):
    if payload.action.startswith("read") or payload.action in {"request_control"}:
        with conn() as db, db.cursor() as cur:
            cur.execute(
                """
                SELECT can_read_data, can_request_control
                FROM identity.farm_memberships
                WHERE user_id=%s AND farm_id=%s
                """,
                (payload.subject_id, payload.farm_id),
            )
            row = cur.fetchone()
            if not row:
                return {"allowed": False, "reason": "Người dùng chưa được phân quyền cho vườn này."}
            if payload.action == "request_control" and not row["can_request_control"]:
                return {"allowed": False, "reason": "Người dùng không có quyền tạo lệnh điều khiển thiết bị."}
            return {"allowed": True, "reason": "allowed"}
    return {"allowed": True, "reason": "no sensitive data"}
