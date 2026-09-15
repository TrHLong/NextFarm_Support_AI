from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
import psycopg
from bs4 import BeautifulSoup
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
ENABLE_WEB_INGEST = os.getenv("ENABLE_WEB_INGEST", "false").lower() == "true"
IDENTITY_URL = os.getenv("IDENTITY_URL", "http://localhost:8100")
INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")
RAG_SIMILARITY_THRESHOLD = float(os.getenv("RAG_SIMILARITY_THRESHOLD", "0.18"))
RAG_THRESHOLD_VERSION = os.getenv("RAG_THRESHOLD_VERSION", "v10.1-validation-set")
ALLOWED_DOMAINS = {
    "nextfarm.vn",
    "www.nextfarm.vn",
    "fao.org",
    "www.fao.org",
    "ecocrop.apps.fao.org",
    "khuyennongvn.gov.vn",
    "www.khuyennongvn.gov.vn",
    "ppd.gov.vn",
    "www.ppd.gov.vn",
    "sansangxuatkhau.ppd.gov.vn",
    "open-meteo.com",
    "www.open-meteo.com",
    "seasonal-api.open-meteo.com",
    "docs.oasis-open.org",
    "oasis-open.org",
    "www.oasis-open.org",
    "postgresql.org",
    "www.postgresql.org",
    "docs.timescale.com",
}

app = FastAPI(title="NextFarm Knowledge RAG Service", version="10.1.0")
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


def require_technician(authorization: str | None = None, x_internal_service_key: str | None = None) -> dict[str, Any] | None:
    if INTERNAL_SERVICE_KEY and x_internal_service_key and hmac.compare_digest(x_internal_service_key, INTERNAL_SERVICE_KEY):
        return None
    if not authorization:
        raise HTTPException(status_code=401, detail="Knowledge Studio yêu cầu đăng nhập kỹ thuật viên.")
    try:
        with httpx.Client(timeout=8) as client:
            response = client.post(f"{IDENTITY_URL}/auth/verify", headers={"Authorization": authorization})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Không kết nối được dịch vụ xác thực.") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập không hợp lệ.")
    user = response.json()["user"]
    if user.get("role") != "technician":
        raise HTTPException(status_code=403, detail="Chỉ kỹ thuật viên được quản trị kho tri thức.")
    return user


def require_reader(authorization: str | None = None, x_internal_service_key: str | None = None) -> dict[str, Any] | None:
    if INTERNAL_SERVICE_KEY and x_internal_service_key and hmac.compare_digest(x_internal_service_key, INTERNAL_SERVICE_KEY):
        return None
    if not authorization:
        raise HTTPException(status_code=401, detail="Kho tri thức yêu cầu phiên đăng nhập hoặc service key nội bộ.")
    try:
        with httpx.Client(timeout=8) as client:
            response = client.post(f"{IDENTITY_URL}/auth/verify", headers={"Authorization": authorization})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Không kết nối được dịch vụ xác thực.") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập không hợp lệ.")
    return response.json()["user"]


def _validate_allowed_https(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in ALLOWED_DOMAINS:
        raise HTTPException(status_code=400, detail="Tên miền chưa nằm trong allowlist HTTPS.")
    return host


def _fetch_allowed(url: str, *, timeout: int = 25, user_agent: str = "NextFarm-KnowledgeStudio/2.0") -> httpx.Response:
    _validate_allowed_https(url)
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"User-Agent": user_agent})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Không tải được nguồn: {exc}") from exc
    final_host = (urlparse(str(response.url)).hostname or "").lower()
    if final_host not in ALLOWED_DOMAINS:
        raise HTTPException(status_code=400, detail="Redirect dẫn ra ngoài allowlist; yêu cầu đã bị chặn.")
    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type and "text/plain" not in content_type:
        raise HTTPException(status_code=415, detail="Chỉ chấp nhận nguồn văn bản HTML/plain text.")
    return response


def _require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("Thiếu DATABASE_URL; hãy chạy dịch vụ qua Docker Compose sau scripts/setup_v9_env.cmd.")
    return DATABASE_URL


def conn():
    return psycopg.connect(_require_database_url(), row_factory=dict_row)


def norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower().replace("đ", "d")
    return re.sub(r"[^a-z0-9\s]", " ", text).strip()


def tokens(text: str) -> set[str]:
    stop = {
        "la", "va", "cua", "co", "khong", "toi", "em", "anh", "chi", "gi", "the", "nao", "mot",
        "nhung", "cho", "hay", "nen", "duoc", "voi", "ve", "trong", "vuon", "minh", "toi",
    }
    return {x for x in norm(text).split() if len(x) > 1 and x not in stop}


def lexical_score(query: str, text: str) -> float:
    q = tokens(query)
    t = tokens(text)
    if not q or not t:
        return 0.0
    overlap = len(q & t) / max(1, len(q))
    phrase_bonus = 0.2 if norm(query) in norm(text) else 0.0
    return min(1.0, overlap + phrase_bonus)


def build_source(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": row["source_id"],
        "source_name": row["source_name"],
        "source_url": row["source_url"],
        "domain": row["domain"],
        "source_type": row["source_type"],
        "trust_tier": row["trust_tier"],
    }


def retrieve(query_text: str, limit: int = 5, category: str | None = None) -> list[dict[str, Any]]:
    with conn() as db, db.cursor() as cur:
        params: list[Any] = []
        category_sql = ""
        if category:
            category_sql = " AND d.category=%s"
            params.append(category)
        cur.execute(
            f"""
            SELECT c.chunk_id,c.content_vi,c.chunk_order,c.metadata,c.heading,c.section_path,c.source_locator,
                   d.document_id,d.title,d.category,d.summary_vi,d.crop_tags,d.product_tags,d.region_tags,
                   s.source_id,s.source_name,s.source_url,s.domain,s.source_type,s.trust_tier
            FROM knowledge_db.document_chunks c
            JOIN knowledge_db.documents d ON d.document_id=c.document_id
            JOIN knowledge_db.sources s ON s.source_id=d.source_id
            WHERE d.active=true AND d.approved=true AND s.active=true {category_sql}
            ORDER BY s.trust_tier,d.title,c.chunk_order
            """,
            params,
        )
        rows = cur.fetchall()

    if not rows:
        return []

    corpus = [f"{r['title']} {r['summary_vi']} {r['content_vi']}" for r in rows]
    tfidf_scores = [0.0] * len(rows)
    try:
        vectorizer = TfidfVectorizer(preprocessor=norm, ngram_range=(1, 2), min_df=1)
        matrix = vectorizer.fit_transform(corpus + [query_text])
        tfidf_scores = cosine_similarity(matrix[-1], matrix[:-1]).flatten().tolist()
    except ValueError:
        pass

    ranked: list[tuple[float, dict[str, Any]]] = []
    for idx, row in enumerate(rows):
        lex = lexical_score(query_text, corpus[idx])
        trust_bonus = max(0.0, (5 - int(row["trust_tier"])) * 0.025)
        final = min(1.0, 0.62 * float(tfidf_scores[idx]) + 0.33 * lex + trust_bonus)
        if final > 0.02:
            ranked.append((final, row))
    ranked.sort(key=lambda x: x[0], reverse=True)

    items: list[dict[str, Any]] = []
    seen_docs: set[str] = set()
    for score_value, row in ranked:
        if row["document_id"] in seen_docs:
            continue
        seen_docs.add(row["document_id"])
        items.append(
            {
                "chunk_id": row["chunk_id"],
                "document_id": row["document_id"],
                "title": row["title"],
                "category": row["category"],
                "summary": row["summary_vi"],
                "content": row["content_vi"],
                "heading": row.get("heading"),
                "section_path": row.get("section_path"),
                "source_locator": row.get("source_locator"),
                "score": round(score_value, 4),
                "source": build_source(row),
                "citation": {
                    "title": row["title"],
                    "section": row.get("section_path") or row.get("heading") or "Mục nội dung",
                    "source_url": row.get("source_locator") or row["source_url"],
                },
            }
        )
        if len(items) >= limit:
            break
    return items


def range_fit(value: float | None, low: float | None, high: float | None, tolerance: float) -> tuple[float, str]:
    if value is None or low is None or high is None:
        return 0.5, "thiếu dữ liệu"
    if low <= value <= high:
        center = (low + high) / 2
        half = max((high - low) / 2, 0.1)
        score_value = 1.0 - 0.15 * abs(value - center) / half
        return max(0.85, score_value), "nằm trong khoảng tối ưu tham khảo"
    distance = low - value if value < low else value - high
    return max(0.0, 1.0 - distance / tolerance), "nằm ngoài khoảng tối ưu tham khảo"


class CropRecommendationRequest(BaseModel):
    farm_id: str | None = None
    region: str | None = None
    previous_crop: str | None = None
    cultivation_type: str | None = None
    temperature_mean: float | None = None
    temperature_min: float | None = None
    temperature_max: float | None = None
    air_humidity_mean: float | None = None
    soil_moisture_mean: float | None = None
    soil_ph: float | None = None
    soil_ec: float | None = None
    annual_rainfall_mm: float | None = None
    seasonal_forecast_available: bool = False
    seasonal_forecast_days: int | None = None
    seasonal_precipitation_mm: float | None = None
    seasonal_source_url: str | None = None
    drainage: str | None = None
    market_data_available: bool = False
    desired_cycle_days_max: int | None = Field(default=None, ge=30, le=1000)
    limit: int = Field(default=5, ge=1, le=10)


class WebIngestRequest(BaseModel):
    url: str
    source_name: str
    category: str = "WEB_RESEARCH"
    approved: bool = False
    crop_tags: list[str] = Field(default_factory=list)
    product_tags: list[str] = Field(default_factory=list)


class CrawlRequest(BaseModel):
    start_url: str
    category: str = "WEB_RESEARCH"
    path_prefix: str | None = None
    max_pages: int = Field(default=20, ge=1, le=50)
    crop_tags: list[str] = Field(default_factory=list)
    product_tags: list[str] = Field(default_factory=list)


@app.get("/health")
def health():
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM knowledge_db.documents WHERE active=true AND approved=true")
        docs = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM knowledge_db.crop_profiles WHERE reviewed=true")
        crops = cur.fetchone()["n"]
    return {
        "service": "knowledge-service",
        "status": "ok",
        "database": "knowledge_db",
        "rag": "tfidf+lexical+trust-tier",
        "similarity_threshold": RAG_SIMILARITY_THRESHOLD,
        "threshold_version": RAG_THRESHOLD_VERSION,
        "approved_documents": docs,
        "reviewed_crop_profiles": crops,
        "web_ingest_enabled": ENABLE_WEB_INGEST,
    }


@app.get("/sources")
def sources(authorization: str | None = Header(default=None), x_internal_service_key: str | None = Header(default=None)):
    require_reader(authorization, x_internal_service_key)
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT * FROM knowledge_db.sources WHERE active=true ORDER BY trust_tier,source_name")
        rows = cur.fetchall()
    return {"items": rows, "total": len(rows)}


@app.get("/articles")
def articles(authorization: str | None = Header(default=None), x_internal_service_key: str | None = Header(default=None)):
    require_reader(authorization, x_internal_service_key)
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT d.document_id AS article_id,d.title,d.category,s.source_name,s.source_url,d.updated_at
            FROM knowledge_db.documents d JOIN knowledge_db.sources s ON s.source_id=d.source_id
            WHERE d.active=true AND d.approved=true ORDER BY d.title
            """
        )
        rows = cur.fetchall()
    return {"items": rows, "total": len(rows)}


@app.get("/query")
def query(q: str = Query(..., min_length=2), farm_id: str | None = None, limit: int = Query(5, ge=1, le=10), authorization: str | None = Header(default=None), x_internal_service_key: str | None = Header(default=None)):
    require_reader(authorization, x_internal_service_key)
    items = retrieve(q, limit=limit)
    top_score = items[0]["score"] if items else 0.0
    answerable = bool(items and top_score >= RAG_SIMILARITY_THRESHOLD)
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO knowledge_db.retrieval_audits(query_text,farm_id,intent,returned_chunk_ids,top_score,answerable)
            VALUES (%s,%s,'knowledge_query',%s,%s,%s)
            """,
            (q, farm_id, [x["chunk_id"] for x in items], top_score, answerable),
        )
        db.commit()
    if not answerable:
        return {
            "answerable": False,
            "answer": "Kho tri thức chưa có đủ nguồn đã kiểm duyệt để trả lời chắc chắn câu hỏi này.",
            "confidence": round(top_score, 3),
            "items": items,
        }
    best = items[0]
    return {
        "answerable": True,
        "answer": best["content"],
        "confidence": round(min(0.95, 0.45 + top_score * 0.55), 3),
        "source": best["source"],
        "citation": best.get("citation"),
        "sources": [x["source"] for x in items],
        "items": items,
    }


@app.post("/recommend/crops")
def recommend_crops(payload: CropRecommendationRequest, authorization: str | None = Header(default=None), x_internal_service_key: str | None = Header(default=None)):
    require_reader(authorization, x_internal_service_key)
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT * FROM knowledge_db.crop_profiles WHERE reviewed=true ORDER BY common_name_vi")
        crops = cur.fetchall()
        cur.execute("SELECT source_id,source_name,source_url,domain,source_type,trust_tier FROM knowledge_db.sources WHERE active=true")
        source_map = {row["source_id"]: row for row in cur.fetchall()}

    provided = {
        "temperature_mean": payload.temperature_mean,
        "soil_ph": payload.soil_ph,
        "annual_rainfall_mm": payload.annual_rainfall_mm,
        "seasonal_forecast": True if payload.seasonal_forecast_available else None,
        "drainage": payload.drainage,
        "cultivation_type": payload.cultivation_type,
        "desired_cycle_days_max": payload.desired_cycle_days_max,
        "market_data": True if payload.market_data_available else None,
    }
    completeness = sum(v is not None for v in provided.values()) / len(provided)
    ranked: list[dict[str, Any]] = []

    previous_norm = norm(payload.previous_crop or "")
    for crop in crops:
        temp_score, temp_reason = range_fit(
            payload.temperature_mean,
            float(crop["temp_opt_min"]) if crop["temp_opt_min"] is not None else None,
            float(crop["temp_opt_max"]) if crop["temp_opt_max"] is not None else None,
            tolerance=10.0,
        )
        ph_score, ph_reason = range_fit(
            payload.soil_ph,
            float(crop["ph_opt_min"]) if crop["ph_opt_min"] is not None else None,
            float(crop["ph_opt_max"]) if crop["ph_opt_max"] is not None else None,
            tolerance=2.0,
        )
        rain_score, rain_reason = range_fit(
            payload.annual_rainfall_mm,
            float(crop["rainfall_opt_min"]) if crop["rainfall_opt_min"] is not None else None,
            float(crop["rainfall_opt_max"]) if crop["rainfall_opt_max"] is not None else None,
            tolerance=1200.0,
        )
        drainage_score = 0.5
        drainage_reason = "chưa có dữ liệu thoát nước"
        if payload.drainage:
            drainage_score = 1.0 if norm(payload.drainage) == norm(crop["drainage_requirement"] or "") else 0.65
            drainage_reason = "phù hợp yêu cầu thoát nước" if drainage_score == 1.0 else "cần kiểm tra khả năng thoát nước"
        protected_score = 0.8
        if payload.cultivation_type:
            is_protected = payload.cultivation_type in {"greenhouse", "net_house", "protected"}
            if crop["protected_cultivation"] and is_protected:
                protected_score = 1.0
            elif crop["protected_cultivation"] and not is_protected:
                protected_score = 0.55
        cycle_score = 0.8
        if payload.desired_cycle_days_max and crop["cycle_days_min"]:
            cycle_score = 1.0 if crop["cycle_days_min"] <= payload.desired_cycle_days_max else max(
                0.2, payload.desired_cycle_days_max / float(crop["cycle_days_min"])
            )
        rotation_score = 1.0
        rotation_reason = "không phát hiện trùng cây vụ trước"
        if previous_norm and previous_norm in norm(crop["common_name_vi"]):
            rotation_score = 0.55
            rotation_reason = "trùng cây vụ trước; cần đánh giá luân canh và sâu bệnh tồn lưu"
        elif previous_norm == "ca chua" and crop["family_name"] == "Solanaceae":
            rotation_score = 0.7
            rotation_reason = "cùng họ với cà chua; cần thận trọng về luân canh"

        suitability = (
            temp_score * 0.31
            + ph_score * 0.24
            + rain_score * 0.11
            + drainage_score * 0.10
            + protected_score * 0.08
            + cycle_score * 0.07
            + rotation_score * 0.09
        )
        suitability *= 0.72 + 0.28 * completeness
        sources_for_crop = [build_source(source_map[sid]) for sid in crop["source_ids"] if sid in source_map]
        ranked.append(
            {
                "crop_id": crop["crop_id"],
                "crop_name": crop["common_name_vi"],
                "scientific_name": crop["scientific_name"],
                "family_name": crop["family_name"],
                "suitability_score": round(suitability * 100, 1),
                "confidence": round((0.42 + 0.48 * completeness) * min(1.0, len(sources_for_crop) / 2 + 0.5), 3),
                "reasons": [
                    f"Nhiệt độ: {temp_reason}",
                    f"pH: {ph_reason}",
                    f"Lượng mưa: {rain_reason}",
                    f"Thoát nước: {drainage_reason}",
                    f"Luân canh: {rotation_reason}",
                ],
                "cycle_days": [crop["cycle_days_min"], crop["cycle_days_max"]],
                "notes": crop["notes_vi"],
                "sources": sources_for_crop,
            }
        )

    ranked.sort(key=lambda x: x["suitability_score"], reverse=True)
    missing = [k for k, v in provided.items() if v is None]
    enough_for_screening = (
        completeness >= 0.42
        and payload.temperature_mean is not None
        and payload.seasonal_forecast_available
    )
    conclusion = (
        "Đây là xếp hạng mức phù hợp sinh thái sơ bộ, không phải cam kết năng suất hay lợi nhuận."
        if enough_for_screening
        else "Chưa đủ dữ liệu để khuyến nghị mùa vụ đáng tin cậy; kết quả chỉ là gợi ý sàng lọc ban đầu."
    )
    if not payload.market_data_available:
        conclusion += " Chưa có dữ liệu giá, đầu ra và chi phí nên không thể kết luận cây nào hiệu quả kinh tế cao nhất."

    return {
        "answerable": enough_for_screening,
        "farm_id": payload.farm_id,
        "data_completeness": round(completeness, 3),
        "missing_fields": missing,
        "conclusion": conclusion,
        "items": ranked[: payload.limit],
        "forecast_context": {
            "available": payload.seasonal_forecast_available,
            "forecast_days": payload.seasonal_forecast_days,
            "precipitation_total_mm": payload.seasonal_precipitation_mm,
            "source_url": payload.seasonal_source_url,
        },
        "method": "structured crop profile matching with trust-tier sources and seasonal climate context",
    }


@app.get("/checklists/{checklist_code}")
def checklist(checklist_code: str, authorization: str | None = Header(default=None), x_internal_service_key: str | None = Header(default=None)):
    require_reader(authorization, x_internal_service_key)
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT * FROM knowledge_db.checklists WHERE checklist_code=%s AND active=true", (checklist_code,))
        head = cur.fetchone()
        if not head:
            raise HTTPException(status_code=404, detail="Không tìm thấy checklist.")
        cur.execute(
            "SELECT item_id,item_order,instruction FROM knowledge_db.checklist_items WHERE checklist_code=%s ORDER BY item_order",
            (checklist_code,),
        )
        items = cur.fetchall()
    return {**head, "items": items}


@app.get("/similar-cases")
def similar_cases(q: str = "", category: str | None = None, limit: int = 5, authorization: str | None = Header(default=None), x_internal_service_key: str | None = Header(default=None)):
    require_reader(authorization, x_internal_service_key)
    with conn() as db, db.cursor() as cur:
        if category:
            cur.execute("SELECT * FROM knowledge_db.resolved_cases WHERE reusable=true AND category=%s", (category,))
        else:
            cur.execute("SELECT * FROM knowledge_db.resolved_cases WHERE reusable=true")
        rows = cur.fetchall()
    ranked = []
    for row in rows:
        s = 0.5 if category and row["category"] == category else 0.0
        if q:
            s += lexical_score(q, f"{row['title']} {row['symptoms']} {row['root_cause']} {row['resolution']} {row['keywords']}")
        if s > 0:
            ranked.append((s, row))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return {
        "items": [{**row, "similarity_score": round(s, 3)} for s, row in ranked[:limit]],
        "total": min(len(ranked), limit),
    }


@app.get("/admin/drafts")
def draft_documents(authorization: str | None = Header(default=None), x_internal_service_key: str | None = Header(default=None)):
    require_technician(authorization, x_internal_service_key)
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT d.document_id,d.title,d.category,d.fetched_at,d.approved,s.source_name,s.source_url
            FROM knowledge_db.documents d JOIN knowledge_db.sources s ON s.source_id=d.source_id
            WHERE d.active=true AND d.approved=false ORDER BY d.fetched_at DESC
            """
        )
        rows = cur.fetchall()
    return {"items": rows, "total": len(rows)}


@app.post("/admin/documents/{document_id}/approve")
def approve_document(document_id: str, authorization: str | None = Header(default=None), x_internal_service_key: str | None = Header(default=None)):
    user = require_technician(authorization, x_internal_service_key)
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            UPDATE knowledge_db.documents
            SET approved=true,approved_by=%s,updated_at=now()
            WHERE document_id=%s AND active=true
            RETURNING document_id,title,approved
            """,
            ((user or {}).get("user_id", "system_service"), document_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu.")
        cur.execute(
            "UPDATE knowledge_db.document_chunks SET approved_snapshot=true WHERE document_id=%s",
            (document_id,),
        )
        db.commit()
    return row


@app.post("/admin/crawl-site")
def crawl_site(payload: CrawlRequest, authorization: str | None = Header(default=None), x_internal_service_key: str | None = Header(default=None)):
    require_technician(authorization, x_internal_service_key)
    if not ENABLE_WEB_INGEST:
        raise HTTPException(status_code=403, detail="Web ingestion đang tắt.")
    parsed_start = urlparse(payload.start_url)
    if parsed_start.scheme != "https" or parsed_start.netloc.lower() not in ALLOWED_DOMAINS:
        raise HTTPException(status_code=400, detail="Tên miền chưa nằm trong allowlist.")
    prefix = payload.path_prefix or parsed_start.path or "/"
    queue = [payload.start_url]
    visited: set[str] = set()
    ingested: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    while queue and len(visited) < payload.max_pages:
        current = queue.pop(0)
        current_parsed = urlparse(current)
        normalized_url = urlunparse((current_parsed.scheme, current_parsed.netloc, current_parsed.path, "", "", ""))
        if normalized_url in visited:
            continue
        if current_parsed.netloc.lower() != parsed_start.netloc.lower() or not current_parsed.path.startswith(prefix):
            continue
        visited.add(normalized_url)
        try:
            page = _fetch_allowed(normalized_url, timeout=20, user_agent="NextFarm-KnowledgeCrawler/2.0")
            soup = BeautifulSoup(page.text, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else normalized_url
            result = ingest_url(
                WebIngestRequest(
                    url=normalized_url,
                    source_name=title[:200],
                    category=payload.category,
                    approved=False,
                    crop_tags=payload.crop_tags,
                    product_tags=payload.product_tags,
                ),
                x_internal_service_key=INTERNAL_SERVICE_KEY,
            )
            ingested.append(result)
            for link in soup.select("a[href]"):
                candidate = urljoin(normalized_url, link.get("href", ""))
                candidate_parsed = urlparse(candidate)
                candidate_normalized = urlunparse((candidate_parsed.scheme, candidate_parsed.netloc, candidate_parsed.path, "", "", ""))
                if (
                    candidate_parsed.scheme == "https"
                    and candidate_parsed.netloc.lower() == parsed_start.netloc.lower()
                    and candidate_parsed.path.startswith(prefix)
                    and not re.search(r"\.(pdf|jpg|jpeg|png|gif|svg|webp|zip)$", candidate_parsed.path, re.I)
                    and candidate_normalized not in visited
                    and candidate_normalized not in queue
                ):
                    queue.append(candidate_normalized)
        except Exception as exc:  # noqa: BLE001
            errors.append({"url": normalized_url, "error": str(exc)})

    return {
        "ok": True,
        "start_url": payload.start_url,
        "path_prefix": prefix,
        "visited": len(visited),
        "ingested": len(ingested),
        "draft_documents": ingested,
        "errors": errors,
        "note": "Tất cả trang crawl được lưu dạng draft, chưa được RAG sử dụng cho đến khi duyệt.",
    }


@app.post("/admin/ingest-url")
def ingest_url(payload: WebIngestRequest, authorization: str | None = Header(default=None), x_internal_service_key: str | None = Header(default=None)):
    require_technician(authorization, x_internal_service_key)
    if not ENABLE_WEB_INGEST:
        raise HTTPException(status_code=403, detail="Web ingestion đang tắt. Bật ENABLE_WEB_INGEST=true để sử dụng.")
    parsed = urlparse(payload.url)
    if parsed.scheme != "https" or parsed.netloc.lower() not in ALLOWED_DOMAINS:
        raise HTTPException(status_code=400, detail="Tên miền chưa nằm trong danh sách nguồn được phép.")
    response = _fetch_allowed(payload.url, timeout=20, user_agent="NextFarm-KnowledgeBot/2.0")
    soup = BeautifulSoup(response.text, "html.parser")
    title, sections = _extract_structured_sections(soup, payload.url)
    text = "\n".join(section["content"] for section in sections)[:60000]
    if len(text) < 200:
        raise HTTPException(status_code=422, detail="Trang không có đủ nội dung văn bản để nhập.")
    checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
    source_id = "web_" + hashlib.sha1(payload.url.encode("utf-8")).hexdigest()[:14]
    document_id = "doc_" + hashlib.sha1((payload.url + checksum).encode("utf-8")).hexdigest()[:16]
    chunks = sections[:200]
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO knowledge_db.sources(source_id,source_name,source_url,domain,source_type,trust_tier,usage_note,last_checked_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,now())
            ON CONFLICT (source_url) DO UPDATE SET source_name=EXCLUDED.source_name,last_checked_at=now()
            RETURNING source_id
            """,
            (
                source_id,
                payload.source_name,
                payload.url,
                parsed.netloc.lower(),
                "nextfarm" if "nextfarm.vn" in parsed.netloc.lower() else "international" if "fao.org" in parsed.netloc.lower() else "government",
                1 if any(x in parsed.netloc.lower() for x in ["fao.org", "khuyennongvn.gov.vn", "ppd.gov.vn", "nextfarm.vn"]) else 3,
                "Nội dung web được nhập tự động; phải kiểm duyệt trước khi dùng trả lời.",
            ),
        )
        actual_source_id = cur.fetchone()["source_id"]
        cur.execute(
            """
            INSERT INTO knowledge_db.documents(document_id,source_id,title,category,summary_vi,content_vi,crop_tags,product_tags,approved,checksum)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (document_id) DO UPDATE SET content_vi=EXCLUDED.content_vi,checksum=EXCLUDED.checksum,updated_at=now()
            """,
            (
                document_id,
                actual_source_id,
                title,
                payload.category,
                text[:600],
                text,
                payload.crop_tags,
                payload.product_tags,
                payload.approved,
                checksum,
            ),
        )
        for idx, chunk in enumerate(chunks):
            cur.execute(
                """
                INSERT INTO knowledge_db.document_chunks(
                  chunk_id,document_id,chunk_order,content_vi,token_estimate,metadata,
                  heading,section_path,source_locator,approved_snapshot
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (chunk_id) DO UPDATE SET
                  content_vi=EXCLUDED.content_vi,token_estimate=EXCLUDED.token_estimate,
                  heading=EXCLUDED.heading,section_path=EXCLUDED.section_path,
                  source_locator=EXCLUDED.source_locator,approved_snapshot=EXCLUDED.approved_snapshot
                """,
                (
                    f"{document_id}_{idx}", document_id, idx, chunk["content"], max(1, len(chunk["content"]) // 4),
                    Jsonb({"url": payload.url, "extraction": "html_structure_v10.1"}), chunk["heading"],
                    chunk["section_path"], chunk["source_locator"], payload.approved,
                ),
            )
        db.commit()
    return {
        "ok": True,
        "document_id": document_id,
        "source_id": actual_source_id,
        "title": title,
        "chunks": len(chunks),
        "approved": payload.approved,
        "note": "Nguồn chưa được dùng để trả lời nếu approved=false.",
    }

# ============================================================
# V9 - Knowledge Studio: quản trị nguồn, mục trích dẫn và trả lời evidence-first
# ============================================================
class StudioAnswerRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    farm_id: str | None = None
    limit: int = Field(default=4, ge=1, le=8)


class StructuredIngestRequest(BaseModel):
    url: str
    source_name: str | None = None
    category: str = "WEB_RESEARCH"
    crop_tags: list[str] = Field(default_factory=list)
    product_tags: list[str] = Field(default_factory=list)


def _chunk_citation(row: dict[str, Any], rank: int) -> dict[str, Any]:
    metadata = row.get("metadata") or {}
    section = row.get("section_path") or row.get("heading") or metadata.get("section") or "Mục nội dung"
    locator = row.get("source_locator") or metadata.get("url") or row.get("source_url")
    return {
        "citation_id": f"S{rank}",
        "chunk_id": row["chunk_id"],
        "document_id": row["document_id"],
        "title": row["title"],
        "section": section,
        "source_name": row["source_name"],
        "source_url": row["source_url"],
        "source_locator": locator,
        "trust_tier": row["trust_tier"],
        "score": round(float(row.get("score") or 0), 4),
    }


def studio_retrieve(query_text: str, limit: int = 5) -> list[dict[str, Any]]:
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT c.chunk_id,c.content_vi,c.chunk_order,c.metadata,c.heading,c.section_path,c.source_locator,
                   d.document_id,d.title,d.category,d.summary_vi,
                   s.source_id,s.source_name,s.source_url,s.domain,s.source_type,s.trust_tier
            FROM knowledge_db.document_chunks c
            JOIN knowledge_db.documents d ON d.document_id=c.document_id
            JOIN knowledge_db.sources s ON s.source_id=d.source_id
            WHERE d.active=true AND d.approved=true AND s.active=true
            ORDER BY s.trust_tier,d.title,c.chunk_order
            """
        )
        rows = cur.fetchall()
    if not rows:
        return []
    corpus = [f"{r['title']} {r.get('heading') or ''} {r.get('section_path') or ''} {r['content_vi']}" for r in rows]
    tfidf_scores = [0.0] * len(rows)
    try:
        vectorizer = TfidfVectorizer(preprocessor=norm, ngram_range=(1, 2), min_df=1)
        matrix = vectorizer.fit_transform(corpus + [query_text])
        tfidf_scores = cosine_similarity(matrix[-1], matrix[:-1]).flatten().tolist()
    except ValueError:
        pass
    ranked = []
    for idx,row in enumerate(rows):
        lex = lexical_score(query_text, corpus[idx])
        trust_bonus = max(0.0,(5-int(row["trust_tier"]))*0.025)
        score_value=min(1.0,0.65*float(tfidf_scores[idx])+0.30*lex+trust_bonus)
        if score_value>0.02:
            ranked.append((score_value,row))
    ranked.sort(key=lambda x:x[0], reverse=True)
    output=[]
    for score_value,row in ranked[:limit]:
        item=dict(row); item["score"]=score_value; output.append(item)
    return output


@app.get("/studio/stats")
def knowledge_studio_stats(authorization: str | None = Header(default=None), x_internal_service_key: str | None = Header(default=None)):
    require_technician(authorization, x_internal_service_key)
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT count(*) AS total,count(*) FILTER (WHERE approved=true) AS approved,count(*) FILTER (WHERE approved=false) AS drafts FROM knowledge_db.documents WHERE active=true")
        documents=cur.fetchone()
        cur.execute("SELECT count(*) AS chunks FROM knowledge_db.document_chunks")
        chunks=cur.fetchone()
        cur.execute("SELECT count(*) AS sources FROM knowledge_db.sources WHERE active=true")
        sources_count=cur.fetchone()
        cur.execute("SELECT count(*) AS queries,count(*) FILTER (WHERE answerable=true) AS answered FROM knowledge_db.retrieval_audits")
        retrieval=cur.fetchone()
    thresholds = {"sources": 30, "approved_documents": 100, "chunks": 500, "reviewed_crop_profiles": 30}
    with conn() as db, db.cursor() as cur:
        cur.execute("SELECT count(*) AS reviewed_crop_profiles FROM knowledge_db.crop_profiles WHERE reviewed=true")
        crop_coverage = cur.fetchone()
        cur.execute("SELECT count(DISTINCT category) AS covered_categories FROM knowledge_db.documents WHERE active=true AND approved=true")
        categories = cur.fetchone()
    current = {
        "sources": int(sources_count["sources"]),
        "approved_documents": int(documents["approved"]),
        "chunks": int(chunks["chunks"]),
        "reviewed_crop_profiles": int(crop_coverage["reviewed_crop_profiles"]),
    }
    gaps = [f"{name}: {current[name]}/{minimum}" for name, minimum in thresholds.items() if current[name] < minimum]
    return {
        **documents, **chunks, **sources_count, **retrieval, **crop_coverage, **categories,
        "retrieval_mode": "TF-IDF + lexical + trust tier + evidence-only answer",
        "production_gate": {"ready": not gaps, "thresholds": thresholds, "current": current, "gaps": gaps},
        "note": "Kho V9 không tự nhận là sâu/production nếu chưa đạt ngưỡng và chưa được kỹ thuật viên duyệt.",
    }


@app.get("/studio/documents")
def knowledge_studio_documents(approved: str = "all", limit: int = Query(default=200,ge=1,le=1000), authorization: str | None = Header(default=None), x_internal_service_key: str | None = Header(default=None)):
    require_technician(authorization, x_internal_service_key)
    where="d.active=true"; params=[]
    if approved in {"true","false"}:
        where += " AND d.approved=%s"; params.append(approved=="true")
    params.append(limit)
    with conn() as db, db.cursor() as cur:
        cur.execute(
            f"""SELECT d.document_id,d.title,d.category,d.summary_vi,d.approved,d.approved_by,d.fetched_at,d.updated_at,
                       s.source_id,s.source_name,s.source_url,s.domain,s.trust_tier,
                       (SELECT count(*) FROM knowledge_db.document_chunks c WHERE c.document_id=d.document_id) AS chunk_count
                FROM knowledge_db.documents d JOIN knowledge_db.sources s ON s.source_id=d.source_id
                WHERE {where} ORDER BY d.approved DESC,s.trust_tier,d.updated_at DESC LIMIT %s""",
            params,
        )
        rows=cur.fetchall()
    return {"items":rows,"total":len(rows)}


@app.get("/studio/documents/{document_id}")
def knowledge_studio_document(document_id: str, authorization: str | None = Header(default=None), x_internal_service_key: str | None = Header(default=None)):
    require_technician(authorization, x_internal_service_key)
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """SELECT d.*,s.source_name,s.source_url,s.domain,s.trust_tier FROM knowledge_db.documents d
               JOIN knowledge_db.sources s ON s.source_id=d.source_id WHERE d.document_id=%s""",
            (document_id,),
        )
        document=cur.fetchone()
        if not document: raise HTTPException(status_code=404,detail="Không tìm thấy tài liệu")
        cur.execute("SELECT chunk_id,chunk_order,heading,section_path,source_locator,content_vi,metadata FROM knowledge_db.document_chunks WHERE document_id=%s ORDER BY chunk_order",(document_id,))
        chunks=cur.fetchall()
    return {**document,"chunks":chunks}


@app.get("/studio/search")
def knowledge_studio_search(q: str = Query(...,min_length=2),limit: int = Query(default=5,ge=1,le=10), authorization: str | None = Header(default=None), x_internal_service_key: str | None = Header(default=None)):
    require_technician(authorization, x_internal_service_key)
    rows=studio_retrieve(q,limit)
    items=[]
    for index,row in enumerate(rows,1):
        citation=_chunk_citation(row,index)
        items.append({"content":row["content_vi"],"citation":citation})
    return {"query":q,"answerable":bool(items and items[0]["citation"]["score"]>=RAG_SIMILARITY_THRESHOLD),"items":items,"threshold":RAG_SIMILARITY_THRESHOLD,"threshold_version":RAG_THRESHOLD_VERSION}


@app.post("/studio/answer")
def knowledge_studio_answer(payload: StudioAnswerRequest, authorization: str | None = Header(default=None), x_internal_service_key: str | None = Header(default=None)):
    require_technician(authorization, x_internal_service_key)
    rows=studio_retrieve(payload.query,payload.limit)
    top_score=float(rows[0]["score"]) if rows else 0.0
    answerable=bool(rows and top_score>=RAG_SIMILARITY_THRESHOLD)
    citations=[]
    if answerable:
        selected=rows[:min(3,len(rows))]
        parts=[]
        for index,row in enumerate(selected,1):
            citation=_chunk_citation(row,index); citations.append(citation)
            content=re.sub(r"\s+"," ",row["content_vi"]).strip()
            if len(content)>550: content=content[:547].rsplit(" ",1)[0]+"…"
            parts.append(f"Theo [{citation['citation_id']}] {citation['title']} — {citation['section']}: {content}")
        answer="\n\n".join(parts)
        confidence=min(0.97,0.45+top_score*0.52)
    else:
        answer="Kho tri thức chưa có mục đã kiểm duyệt đủ gần với câu hỏi này. Hệ thống từ chối suy đoán và đề nghị bổ sung hoặc duyệt nguồn phù hợp."
        confidence=top_score
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """INSERT INTO knowledge_db.answer_audits(query_text,answer_text,citation_chunk_ids,source_urls,answerable,confidence,guard_status)
               VALUES (%s,%s,%s,%s,%s,%s,'evidence_only')""",
            (payload.query,answer,[c["chunk_id"] for c in citations],[c["source_url"] for c in citations],answerable,confidence),
        )
        cur.execute(
            """INSERT INTO knowledge_db.retrieval_audits(query_text,farm_id,intent,returned_chunk_ids,top_score,answerable)
               VALUES (%s,%s,'knowledge_studio_answer',%s,%s,%s)""",
            (payload.query,payload.farm_id,[c["chunk_id"] for c in citations],top_score,answerable),
        )
        db.commit()
    return {"answerable":answerable,"answer":answer,"confidence":round(confidence,3),"citations":citations,"guard":{"mode":"evidence_only","numeric_generation":False,"uncited_claims_allowed":False}}


def _extract_structured_sections(soup: BeautifulSoup,url: str) -> tuple[str,list[dict[str,Any]]]:
    for node in soup(["script","style","nav","footer","form","noscript"]): node.decompose()
    title=soup.title.get_text(" ",strip=True) if soup.title else url
    current=[]; sections=[]; order=0
    for node in soup.find_all(["h1","h2","h3","h4","p","li","table"]):
        if node.name == "table":
            table_rows=[]
            for row in node.find_all("tr"):
                cells=[re.sub(r"\s+"," ",cell.get_text(" ",strip=True)).strip() for cell in row.find_all(["th","td"])]
                if any(cells): table_rows.append(" | ".join(cells))
            text="\n".join(table_rows).strip()
            content_type="table"
        else:
            text=re.sub(r"\s+"," ",node.get_text(" ",strip=True)).strip()
            content_type="list_item" if node.name == "li" else "paragraph"
        if len(text)<2: continue
        if node.name in {"h1","h2","h3","h4"}:
            level=int(node.name[1]); current=current[:level-1]; current.append(text[:220]); continue
        heading=" > ".join(current) if current else "Nội dung chính"
        if content_type != "table" and len(text)<40: continue
        order+=1
        sections.append({
            "heading":current[-1] if current else "Nội dung chính",
            "section_path":heading,
            "content":text,
            "content_type":content_type,
            "table_context":heading if content_type == "table" else None,
            "source_locator":f"{url}#section-{order}",
        })
    return title[:300],sections[:200]


@app.post("/studio/ingest-url")
def knowledge_studio_ingest(payload: StructuredIngestRequest, authorization: str | None=Header(default=None), x_internal_service_key: str | None=Header(default=None)):
    require_technician(authorization, x_internal_service_key)
    if not ENABLE_WEB_INGEST: raise HTTPException(status_code=403,detail="Web ingestion đang tắt")
    parsed=urlparse(payload.url)
    _validate_allowed_https(payload.url)
    response=_fetch_allowed(payload.url,timeout=25,user_agent="NextFarm-KnowledgeStudio/2.0")
    parsed=urlparse(str(response.url))
    soup=BeautifulSoup(response.text,"html.parser")
    title,sections=_extract_structured_sections(soup,payload.url)
    if not sections: raise HTTPException(status_code=422,detail="Không tách được nội dung theo mục")
    combined="\n".join(x["content"] for x in sections)[:60000]
    checksum=hashlib.sha256(combined.encode("utf-8")).hexdigest()
    source_id="web_"+hashlib.sha1(payload.url.encode("utf-8")).hexdigest()[:14]
    document_id="doc_"+hashlib.sha1((payload.url+checksum).encode("utf-8")).hexdigest()[:16]
    with conn() as db,db.cursor() as cur:
        cur.execute(
            """INSERT INTO knowledge_db.sources(source_id,source_name,source_url,domain,source_type,trust_tier,usage_note,last_checked_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT (source_url) DO UPDATE SET source_name=EXCLUDED.source_name,last_checked_at=now() RETURNING source_id""",
            (source_id,payload.source_name or title,payload.url,parsed.netloc.lower(),"nextfarm" if "nextfarm.vn" in parsed.netloc.lower() else "international" if "fao.org" in parsed.netloc.lower() else "government",1 if any(x in parsed.netloc.lower() for x in ["nextfarm.vn","fao.org","khuyennongvn.gov.vn","ppd.gov.vn"]) else 3,"Tự động tách theo heading; bắt buộc duyệt trước khi RAG sử dụng."),
        )
        actual_source_id=cur.fetchone()["source_id"]
        cur.execute(
            """INSERT INTO knowledge_db.documents(document_id,source_id,title,category,summary_vi,content_vi,crop_tags,product_tags,approved,checksum)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,false,%s)
               ON CONFLICT (document_id) DO UPDATE SET content_vi=EXCLUDED.content_vi,checksum=EXCLUDED.checksum,updated_at=now(),approved=false""",
            (document_id,actual_source_id,title,payload.category,sections[0]["content"][:600],combined,payload.crop_tags,payload.product_tags,checksum),
        )
        cur.execute("DELETE FROM knowledge_db.document_chunks WHERE document_id=%s",(document_id,))
        for idx,section in enumerate(sections):
            content=section["content"]
            cur.execute(
                """INSERT INTO knowledge_db.document_chunks(chunk_id,document_id,chunk_order,content_vi,token_estimate,metadata,heading,section_path,source_locator,approved_snapshot)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,false)""",
                (
                    f"{document_id}_{idx}",document_id,idx,content,max(1,len(content)//4),
                    Jsonb({
                        "url":payload.url,
                        "source_version":checksum,
                        "content_type":section["content_type"],
                        "table_context":section["table_context"],
                        "extraction_status":"complete",
                        "extraction_coverage":1.0,
                        "ocr_required":False,
                    }),
                    section["heading"],section["section_path"],section["source_locator"],
                ),
            )
        db.commit()
    return {"ok":True,"document_id":document_id,"title":title,"sections":len(sections),"approved":False,"note":"Tài liệu ở trạng thái draft. Duyệt rồi mới được trả lời."}
