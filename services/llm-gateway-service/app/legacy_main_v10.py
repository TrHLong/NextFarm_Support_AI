from __future__ import annotations

import json
import hmac
import os
import re
import time
import unicodedata
import uuid
from typing import Any

import httpx
import psycopg
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.logic import deterministic_plan

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deterministic").strip().lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")

app = FastAPI(title="NextFarm LLM Gateway", version="10.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:8080,http://localhost:8081,http://localhost:8082,http://localhost:8084",
    ).split(",") if x.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


TOOLS = [
    {"type":"function","name":"get_latest_metric","description":"Read the latest authorized farm sensor metric. Never invent the value.","strict":True,"parameters":{"type":"object","properties":{"metric":{"type":"string","enum":["soil_moisture","air_humidity","temperature","ec","ph","flow_rate"]},"zone":{"type":["string","null"]}},"required":["metric","zone"],"additionalProperties":False}},
    {"type":"function","name":"get_devices","description":"Read online/offline device status for the authorized farm.","strict":True,"parameters":{"type":"object","properties":{"zone":{"type":["string","null"]}},"required":["zone"],"additionalProperties":False}},
    {"type":"function","name":"get_port_status","description":"Read one configured valve/pump port from the authorized farm.","strict":True,"parameters":{"type":"object","properties":{"zone":{"type":["string","null"]},"port_number":{"type":"integer","minimum":1,"maximum":128}},"required":["zone","port_number"],"additionalProperties":False}},
    {"type":"function","name":"get_irrigation_summary","description":"Read irrigation history summary from the authorized farm.","strict":True,"parameters":{"type":"object","properties":{"period":{"type":"string","enum":["today","yesterday","week"]},"zone":{"type":["string","null"]}},"required":["period","zone"],"additionalProperties":False}},
    {"type":"function","name":"get_irrigation_history","description":"Read detailed irrigation events for the authorized farm.","strict":True,"parameters":{"type":"object","properties":{"hours":{"type":"integer","minimum":1,"maximum":2160},"zone":{"type":["string","null"]}},"required":["hours","zone"],"additionalProperties":False}},
    {"type":"function","name":"get_irrigation_schedules","description":"Read configured irrigation schedules for the authorized farm.","strict":True,"parameters":{"type":"object","properties":{"zone":{"type":["string","null"]}},"required":["zone"],"additionalProperties":False}},
    {"type":"function","name":"get_command_logs","description":"Read-only audit of device-control commands. Never create or execute a command.","strict":True,"parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False}},
    {"type":"function","name":"get_alerts","description":"Read current alerts for the authorized farm.","strict":True,"parameters":{"type":"object","properties":{"zone":{"type":["string","null"]}},"required":["zone"],"additionalProperties":False}},
    {"type":"function","name":"get_ai_summary","description":"Read crop-aware AI/model assessment for the authorized farm. Use for forecasts, risks, trends and overall farm status.","strict":True,"parameters":{"type":"object","properties":{"zone":{"type":["string","null"]}},"required":["zone"],"additionalProperties":False}},
    {"type":"function","name":"get_ai_capabilities","description":"List the AI Encyclopedia capabilities assigned to the farm crop and their READY/EXPERIMENTAL/BLOCKED status.","strict":True,"parameters":{"type":"object","properties":{"zone":{"type":["string","null"]}},"required":["zone"],"additionalProperties":False}},
    {"type":"function","name":"get_crop_recommendation","description":"Screen candidate crops using approved agronomy knowledge and farm/climate evidence. Never promise yield or profit.","strict":True,"parameters":{"type":"object","properties":{"zone":{"type":["string","null"]}},"required":["zone"],"additionalProperties":False}},
    {"type":"function","name":"search_knowledge","description":"Search approved NextFarm/agronomy knowledge for cited support.","strict":True,"parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"],"additionalProperties":False}},
    {"type":"function","name":"create_ticket_suggestion","description":"Prepare, but do not submit, a support ticket suggestion. Human confirmation is required.","strict":True,"parameters":{"type":"object","properties":{"zone":{"type":["string","null"]},"description":{"type":"string"}},"required":["zone","description"],"additionalProperties":False}},
]


class PlanRequest(BaseModel):
    message: str = Field(min_length=1, max_length=3000)
    user_id: str | None = None
    farm_id: str
    crop_key: str | None = None
    allowed_farm_ids: list[str] = Field(default_factory=list, max_length=1000)


class VerbalizeRequest(BaseModel):
    draft: str = Field(min_length=1, max_length=12000)
    evidence: list[Any] = Field(default_factory=list, max_length=20)
    user_id: str | None = None
    farm_id: str | None = None
    intent: str | None = None


def _require_internal_key(value: str | None) -> None:
    if not INTERNAL_SERVICE_KEY or not value or not hmac.compare_digest(value, INTERNAL_SERVICE_KEY):
        raise HTTPException(status_code=401, detail="LLM Gateway chỉ nhận yêu cầu nội bộ đã xác thực.")


def _audit(*, user_id: str | None, farm_id: str | None, provider: str, model_name: str | None, purpose: str, request_id: str, input_chars: int, output_chars: int, tool_name: str | None, tool_arguments: dict[str, Any] | None, success: bool, error_code: str | None, latency_ms: float) -> None:
    if not DATABASE_URL:
        return
    try:
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as db, db.cursor() as cur:
            cur.execute("""
                INSERT INTO ai_db.llm_audits(user_id,farm_id,provider,model_name,purpose,request_id,input_chars,output_chars,tool_name,tool_arguments,success,error_code,latency_ms)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (user_id,farm_id,provider,model_name,purpose,request_id,input_chars,output_chars,tool_name,Jsonb(tool_arguments) if tool_arguments is not None else None,success,error_code,latency_ms))
            db.commit()
    except Exception:
        pass


def _extract_output_text(data: dict[str, Any]) -> str:
    if data.get("output_text"):
        return str(data["output_text"])
    parts: list[str] = []
    for item in data.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                parts.append(str(content["text"]))
    return "\n".join(parts).strip()


def _openai_plan(payload: PlanRequest) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    if not OPENAI_API_KEY:
        result = deterministic_plan(payload.message)
        result.update({"fallback_reason": "OPENAI_API_KEY_missing", "provider_requested": "openai"})
        return result
    instructions = (
        "You are the routing layer for NextFarm agriculture support. Choose one to four tools when the question needs multiple evidence sources. "
        "Never answer directly, never invent farm data, never choose a farm ID, and never request device control. "
        "The application has already authorized farm_id=" + payload.farm_id + ". "
        "Vietnamese farmers may use no accents, local wording or spelling errors. "
        "For advice that depends on live farm data, call the operational tool first and search_knowledge second. "
        "For agronomy questions choose search_knowledge unless the user specifically asks what crop to plant next."
    )
    body = {
        "model": OPENAI_MODEL,
        "instructions": instructions,
        "input": payload.message,
        "tools": TOOLS,
        "tool_choice": "required",
        "parallel_tool_calls": True,
    }
    error = None
    tool_name = None
    arguments: dict[str, Any] = {}
    try:
        with httpx.Client(timeout=LLM_TIMEOUT_SECONDS, transport=httpx.HTTPTransport(retries=2)) as client:
            res = client.post(
                f"{OPENAI_BASE_URL}/responses",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json", "X-Client-Request-Id": request_id},
                json=body,
            )
        res.raise_for_status()
        data = res.json()
        steps: list[dict[str, Any]] = []
        allowed_tool_names = {item["name"] for item in TOOLS}
        for item in data.get("output") or []:
            if item.get("type") == "function_call":
                candidate_name = item.get("name")
                raw = item.get("arguments") or "{}"
                candidate_arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
                if candidate_name not in allowed_tool_names:
                    raise ValueError("Model chọn tool ngoài allow-list.")
                steps.append({"tool_name": candidate_name, "arguments": candidate_arguments, "purpose": "model_planned"})
                if len(steps) == 4:
                    break
        if not steps:
            raise ValueError("Model không trả function_call.")
        tool_name = steps[0]["tool_name"]
        arguments = steps[0]["arguments"]
        intent_by_tool = {
            "get_latest_metric":"read_metric","get_devices":"read_devices","get_irrigation_summary":"irrigation_summary",
            "get_irrigation_history":"irrigation_history","get_irrigation_schedules":"irrigation_schedule",
            "get_port_status":"read_port","get_command_logs":"command_logs","get_alerts":"read_alerts","get_ai_summary":"ai_smart_summary","get_ai_capabilities":"ai_capabilities",
            "get_crop_recommendation":"crop_recommendation","search_knowledge":"knowledge_answer","create_ticket_suggestion":"ticket_confirmation",
        }
        result = {"provider":"openai","model":OPENAI_MODEL,"tool_name":tool_name,"arguments":arguments,"steps":steps,"intent":intent_by_tool.get(tool_name,"unknown"),"confidence":0.88,"request_id":request_id}
        _audit(user_id=payload.user_id,farm_id=payload.farm_id,provider="openai",model_name=OPENAI_MODEL,purpose="plan",request_id=request_id,input_chars=len(payload.message),output_chars=len(json.dumps(result,ensure_ascii=False)),tool_name=tool_name,tool_arguments=arguments,success=True,error_code=None,latency_ms=(time.perf_counter()-started)*1000)
        return result
    except Exception as exc:  # fail closed to deterministic router
        error = type(exc).__name__
        fallback = deterministic_plan(payload.message)
        fallback.update({"provider_requested":"openai","fallback_reason":error,"request_id":request_id})
        _audit(user_id=payload.user_id,farm_id=payload.farm_id,provider="openai",model_name=OPENAI_MODEL,purpose="plan",request_id=request_id,input_chars=len(payload.message),output_chars=len(json.dumps(fallback,ensure_ascii=False)),tool_name=fallback.get("tool_name"),tool_arguments=fallback.get("arguments"),success=False,error_code=error,latency_ms=(time.perf_counter()-started)*1000)
        return fallback


@app.get("/health")
def health():
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Thiếu DATABASE_URL cho LLM audit.")
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as db, db.cursor() as cur:
        cur.execute("SELECT 1 AS ok")
        database_ok = bool(cur.fetchone()["ok"])
    return {
        "service": "llm-gateway-service", "status": "ok", "version": "10.1.0",
        "database_ok": database_ok,
        "provider": LLM_PROVIDER, "openai_key_configured": bool(OPENAI_API_KEY),
        "model": OPENAI_MODEL if LLM_PROVIDER == "openai" else None,
        "configured_model": OPENAI_MODEL,
        "active_external_llm": LLM_PROVIDER == "openai" and bool(OPENAI_API_KEY),
        "external_api": "OpenAI Responses API" if LLM_PROVIDER == "openai" and bool(OPENAI_API_KEY) else None,
        "supported_providers": ["deterministic", "openai"],
        "gemini_supported": False,
        "policy": "LLM plans tools and may verbalize evidence; it never gets database credentials and cannot bypass Truth Guard.",
    }


@app.post("/plan")
def plan(payload: PlanRequest, x_internal_service_key: str | None = Header(default=None)):
    _require_internal_key(x_internal_service_key)
    if not payload.allowed_farm_ids or payload.farm_id not in payload.allowed_farm_ids:
        return {"provider":"policy","tool_name":None,"arguments":{},"intent":"denied","confidence":1.0,"denied":True,"reason":"farm_id outside allowed_farm_ids"}
    if LLM_PROVIDER == "openai":
        return _openai_plan(payload)
    result = deterministic_plan(payload.message)
    result["provider"] = "deterministic" if LLM_PROVIDER in {"deterministic","disabled",""} else f"deterministic_fallback:{LLM_PROVIDER}"
    return result


@app.post("/verbalize")
def verbalize(payload: VerbalizeRequest, x_internal_service_key: str | None = Header(default=None)):
    _require_internal_key(x_internal_service_key)
    if LLM_PROVIDER != "openai" or not OPENAI_API_KEY:
        return {"text": payload.draft, "provider": "deterministic", "changed": False}
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    evidence_json = json.dumps(payload.evidence, ensure_ascii=False, default=str)
    # Keep context bounded. The Truth Guard after this call remains authoritative.
    evidence_json = evidence_json[:22000]
    body = {
        "model": OPENAI_MODEL,
        "instructions": (
            "Rewrite the Vietnamese draft to be concise and easy for a farmer. Use ONLY facts, numbers, units, timestamps and sources present in the draft/evidence. "
            "Do not add agronomy claims. Do not turn uncertainty into certainty. Preserve explicit statements that data is missing/stale/experimental. "
            "Do not give device-control instructions. Output only the final Vietnamese answer."
        ),
        "input": f"DRAFT:\n{payload.draft}\n\nEVIDENCE JSON:\n{evidence_json}",
    }
    try:
        with httpx.Client(timeout=LLM_TIMEOUT_SECONDS, transport=httpx.HTTPTransport(retries=2)) as client:
            res = client.post(f"{OPENAI_BASE_URL}/responses", headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type":"application/json", "X-Client-Request-Id":request_id}, json=body)
        res.raise_for_status()
        text = _extract_output_text(res.json()).strip() or payload.draft
        _audit(user_id=payload.user_id,farm_id=payload.farm_id,provider="openai",model_name=OPENAI_MODEL,purpose="verbalize",request_id=request_id,input_chars=len(payload.draft)+len(evidence_json),output_chars=len(text),tool_name=None,tool_arguments=None,success=True,error_code=None,latency_ms=(time.perf_counter()-started)*1000)
        return {"text": text, "provider":"openai", "model":OPENAI_MODEL, "changed": text != payload.draft, "request_id":request_id}
    except Exception as exc:
        _audit(user_id=payload.user_id,farm_id=payload.farm_id,provider="openai",model_name=OPENAI_MODEL,purpose="verbalize",request_id=request_id,input_chars=len(payload.draft)+len(evidence_json),output_chars=len(payload.draft),tool_name=None,tool_arguments=None,success=False,error_code=type(exc).__name__,latency_ms=(time.perf_counter()-started)*1000)
        return {"text": payload.draft, "provider":"deterministic_fallback", "changed":False, "error":type(exc).__name__}
