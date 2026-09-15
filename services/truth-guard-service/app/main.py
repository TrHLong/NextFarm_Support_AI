from __future__ import annotations

import hmac
import os
from typing import Any

import psycopg
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
MIN_CONFIDENCE = float(os.getenv("TRUTH_GUARD_MIN_CONFIDENCE", "0.55"))
INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")

app = FastAPI(title="NextFarm Truth Guard", version="10.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOW_ORIGINS",
            "http://localhost:8080,http://localhost:8081,http://localhost:8082",
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.guard_logic import evaluate_answer


def _require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("Thiếu DATABASE_URL; hãy chạy dịch vụ qua Docker Compose sau scripts/setup_v9_env.cmd.")
    return DATABASE_URL


def conn():
    return psycopg.connect(_require_database_url(), row_factory=dict_row)


class VerifyRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=12000)
    evidence: list[Any] = Field(default_factory=list, max_length=50)
    confidence: float | None = Field(default=None, ge=0, le=1)
    intent: str | None = None
    user_id: str | None = None
    farm_id: str | None = None
    requires_human: bool = False
    knowledge_mode: bool = False


def _require_internal_key(value: str | None) -> None:
    if not INTERNAL_SERVICE_KEY or not value or not hmac.compare_digest(value, INTERNAL_SERVICE_KEY):
        raise HTTPException(status_code=401, detail="Truth Guard chỉ nhận yêu cầu nội bộ đã xác thực.")


@app.get("/health")
def health():
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT 1 AS ok")
        database_ok = bool(cur.fetchone()["ok"])
    return {
        "service": "truth-guard-service",
        "status": "ok",
        "database_ok": database_ok,
        "min_confidence": MIN_CONFIDENCE,
        "checks": ["evidence", "numeric-grounding", "tenant-grounding", "freshness", "model-status", "source-citation", "certainty", "high-risk"],
    }


@app.post("/verify")
def verify(payload: VerifyRequest, x_internal_service_key: str | None = Header(default=None)):
    _require_internal_key(x_internal_service_key)
    result = evaluate_answer(
        answer=payload.answer,
        evidence=payload.evidence,
        confidence=payload.confidence,
        min_confidence=MIN_CONFIDENCE,
        requires_human=payload.requires_human,
        knowledge_mode=payload.knowledge_mode,
        expected_farm_id=payload.farm_id,
    )
    allowed = result["allowed"]
    final_answer = result["final_answer"]
    reasons = result["reasons"]
    warnings = result["warnings"]

    try:
        with conn() as db, db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO support_db.answer_verifications(
                  user_id,farm_id,intent,original_answer,final_answer,evidence,confidence,allowed,reasons
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    payload.user_id,
                    payload.farm_id,
                    payload.intent,
                    payload.answer,
                    final_answer,
                    Jsonb(payload.evidence),
                    payload.confidence,
                    allowed,
                    Jsonb(reasons),
                ),
            )
            db.commit()
    except Exception:
        pass

    return result
