from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import threading
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
TOKEN_SECRET = os.getenv("TOKEN_SECRET", "")
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", "28800"))
EXPOSE_DEMO_ACCOUNTS = os.getenv("EXPOSE_DEMO_ACCOUNTS", "false").lower() in {"1", "true", "yes"}
INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")
TECHNICIAN_BOOTSTRAP_PASSWORD = os.getenv("TECHNICIAN_BOOTSTRAP_PASSWORD", "")
FARMER_BOOTSTRAP_PASSWORD = os.getenv("FARMER_BOOTSTRAP_PASSWORD", "")
DB_STARTUP_RETRIES = max(1, int(os.getenv("DB_STARTUP_RETRIES", "30")))
DB_STARTUP_RETRY_SECONDS = max(1.0, float(os.getenv("DB_STARTUP_RETRY_SECONDS", "2")))
LOGGER = logging.getLogger("nextfarm.identity")
IDENTITY_READY = threading.Event()
IDENTITY_STOP = threading.Event()
identity_state: dict[str, Any] = {
    "ready": False,
    "last_error": None,
    "last_attempt_at": None,
}


def _require_bootstrap_passwords() -> None:
    if len(TECHNICIAN_BOOTSTRAP_PASSWORD) < 12 or len(FARMER_BOOTSTRAP_PASSWORD) < 12:
        raise RuntimeError("Thiếu mật khẩu bootstrap ngẫu nhiên; chạy scripts/setup_v9_env.cmd trước.")


def bootstrap_seed_passwords() -> None:
    """Replace unusable seed hashes after PostgreSQL has finished init/seed.

    Docker's pg_isready can become true while the official image is still
    executing init scripts. Retrying here prevents a transient startup race
    from terminating Uvicorn's lifespan with exit code 3.
    """
    _require_bootstrap_passwords()
    last_error: Exception | None = None
    for attempt in range(1, DB_STARTUP_RETRIES + 1):
        try:
            with conn() as db, db.cursor() as cur:
                # UPDATE itself is also the readiness probe: undefined table or
                # transient connection failures are caught and retried below.
                cur.execute(
                    """UPDATE user_db.users SET password_hash=%s,updated_at=now()
                       WHERE user_id='tech_01' AND password_hash='bootstrap_required'""",
                    (hash_password(TECHNICIAN_BOOTSTRAP_PASSWORD),),
                )
                cur.execute(
                    """UPDATE user_db.users SET password_hash=%s,updated_at=now()
                       WHERE user_id IN ('farmer_long','farmer_lan','farmer_minh')
                         AND password_hash='bootstrap_required'""",
                    (hash_password(FARMER_BOOTSTRAP_PASSWORD),),
                )
                db.commit()
                return
        except (psycopg.Error, OSError, RuntimeError) as exc:
            last_error = exc
            if attempt < DB_STARTUP_RETRIES:
                LOGGER.warning(
                    "PostgreSQL/schema chưa sẵn sàng (%s/%s): %s",
                    attempt, DB_STARTUP_RETRIES, exc,
                )
                time.sleep(DB_STARTUP_RETRY_SECONDS)
    raise RuntimeError(f"Không bootstrap được Identity sau {DB_STARTUP_RETRIES} lần: {last_error}")


def _bootstrap_worker() -> None:
    """Keep Uvicorn alive while the fresh V9 PostgreSQL schema finishes initialization."""
    while not IDENTITY_STOP.is_set():
        identity_state["last_attempt_at"] = time.time()
        try:
            bootstrap_seed_passwords()
            IDENTITY_READY.set()
            identity_state.update({"ready": True, "last_error": None})
            return
        except Exception as exc:  # noqa: BLE001
            identity_state.update({"ready": False, "last_error": str(exc)})
            LOGGER.exception("Identity bootstrap chưa sẵn sàng: %s", exc)
            IDENTITY_STOP.wait(10)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    worker = threading.Thread(target=_bootstrap_worker, daemon=True, name="nextfarm-identity-bootstrap")
    worker.start()
    try:
        yield
    finally:
        IDENTITY_STOP.set()


app = FastAPI(title="NextFarm User DB / Identity Service", version="10.1.0", lifespan=lifespan)
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


def _require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("Thiếu DATABASE_URL; hãy chạy dịch vụ qua Docker Compose sau scripts/setup_v9_env.cmd.")
    return DATABASE_URL


def conn():
    return psycopg.connect(_require_database_url(), row_factory=dict_row)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _require_token_secret() -> None:
    if len(TOKEN_SECRET) < 32:
        raise HTTPException(status_code=503, detail="Identity Service chưa được cấu hình TOKEN_SECRET an toàn.")


def create_token(user_id: str) -> str:
    _require_token_secret()
    payload = {"sub": user_id, "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    encoded = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = _b64(hmac.new(TOKEN_SECRET.encode(), encoded.encode(), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def verify_token(token: str) -> dict[str, Any]:
    _require_token_secret()
    try:
        encoded, signature = token.split(".", 1)
        expected = _b64(hmac.new(TOKEN_SECRET.encode(), encoded.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad signature")
        payload = json.loads(_unb64(encoded))
        if int(payload["exp"]) < int(time.time()):
            raise ValueError("expired")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập không hợp lệ hoặc đã hết hạn.") from exc


def bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Thiếu thông tin đăng nhập.")
    return authorization.split(" ", 1)[1].strip()




def require_internal_key(x_internal_service_key: str | None) -> None:
    if not INTERNAL_SERVICE_KEY or not x_internal_service_key or not hmac.compare_digest(x_internal_service_key, INTERNAL_SERVICE_KEY):
        raise HTTPException(status_code=403, detail="Endpoint nội bộ yêu cầu service key hợp lệ.")


def user_context(user_id: str) -> dict[str, Any]:
    require_identity_ready()
    with conn() as db, db.cursor() as cur:
        cur.execute(
            "SELECT user_id,username,display_name,phone,email,role,status FROM user_db.users WHERE user_id=%s",
            (user_id,),
        )
        user = cur.fetchone()
        if not user or user["status"] != "active":
            raise HTTPException(status_code=404, detail="Không tìm thấy người dùng đang hoạt động.")
        cur.execute(
            """
            SELECT fa.farm_id,fa.access_role,fa.can_read,fa.can_support,
                   f.farm_name,f.crop_name,f.region
            FROM user_db.farm_access fa
            JOIN farm_db.farms f ON f.farm_id=fa.farm_id
            WHERE fa.user_id=%s
            ORDER BY f.farm_name
            """,
            (user_id,),
        )
        farms = cur.fetchall()
    readable_farms = [farm for farm in farms if farm.get("can_read")]
    # Chỉ tự chọn khi tài khoản thực sự có đúng một vườn. Với nhiều vườn,
    # client phải gửi farm_id đã được người dùng chọn; không dùng thứ tự DB.
    default_farm_id = readable_farms[0]["farm_id"] if len(readable_farms) == 1 else None
    return {
        **user,
        "farms": farms,
        "default_farm_id": default_farm_id,
        "requires_farm_selection": len(readable_farms) > 1,
    }


def hash_password(password: str, *, iterations: int = 310_000) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> tuple[bool, bool]:
    """Return (valid, needs_upgrade). Fresh V9 accepts PBKDF2 hashes only."""
    if not stored.startswith("pbkdf2_sha256$"):
        return False, False
    try:
        _, iterations_text, salt_hex, digest_hex = stored.split("$", 3)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations_text)).hex()
        return hmac.compare_digest(actual, digest_hex), False
    except (ValueError, TypeError):
        return False, False


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthorizeRequest(BaseModel):
    user_id: str
    farm_id: str
    action: str = "read"


class ExternalIdentityRequest(BaseModel):
    provider: str
    external_subject: str
    user_id: str
    tenant_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExternalIdentityResolveRequest(BaseModel):
    provider: str
    external_subject: str


def require_identity_ready() -> None:
    if not IDENTITY_READY.is_set():
        raise HTTPException(status_code=503, detail="Identity Service đang chờ PostgreSQL và bootstrap tài khoản.")


@app.get("/health")
def health():
    configured = len(TOKEN_SECRET) >= 32 and len(TECHNICIAN_BOOTSTRAP_PASSWORD) >= 12 and len(FARMER_BOOTSTRAP_PASSWORD) >= 12
    payload = {
        "service": "identity-service",
        "status": "ok" if configured and IDENTITY_READY.is_set() else "starting",
        "database": "user_db",
        "token_secret_configured": len(TOKEN_SECRET) >= 32,
        "bootstrap_passwords_configured": len(TECHNICIAN_BOOTSTRAP_PASSWORD) >= 12 and len(FARMER_BOOTSTRAP_PASSWORD) >= 12,
        "bootstrap_ready": IDENTITY_READY.is_set(),
        "last_error": identity_state.get("last_error"),
    }
    if not configured or not IDENTITY_READY.is_set():
        return JSONResponse(status_code=503, content=payload)
    try:
        with conn() as db, db.cursor() as cur:
            cur.execute("SELECT count(*) AS total FROM user_db.users WHERE status='active'")
            payload["active_users"] = int(cur.fetchone()["total"])
    except Exception as exc:  # noqa: BLE001
        payload.update({"status": "starting", "last_error": str(exc)})
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.post("/auth/login")
def login(payload: LoginRequest):
    require_identity_ready()
    with conn() as db, db.cursor() as cur:
        cur.execute(
            "SELECT user_id,password_hash,status FROM user_db.users WHERE username=%s",
            (payload.username.strip(),),
        )
        row = cur.fetchone()
        valid, needs_upgrade = verify_password(payload.password, row["password_hash"]) if row else (False, False)
        if not row or not valid or row["status"] != "active":
            raise HTTPException(status_code=401, detail="Sai tài khoản hoặc mật khẩu.")
    context = user_context(row["user_id"])
    return {"access_token": create_token(row["user_id"]), "token_type": "bearer", "user": context}


@app.get("/auth/me")
def me(authorization: str | None = Header(default=None)):
    payload = verify_token(bearer(authorization))
    return user_context(payload["sub"])


@app.post("/auth/verify")
def verify(authorization: str | None = Header(default=None)):
    payload = verify_token(bearer(authorization))
    return {"valid": True, "user": user_context(payload["sub"])}


@app.get("/context/{user_id}")
def context(user_id: str, x_internal_service_key: str | None = Header(default=None)):
    require_internal_key(x_internal_service_key)
    return user_context(user_id)


@app.post("/authorize")
def authorize(payload: AuthorizeRequest, x_internal_service_key: str | None = Header(default=None)):
    require_internal_key(x_internal_service_key)
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT u.role,fa.can_read,fa.can_support
            FROM user_db.users u
            LEFT JOIN user_db.farm_access fa ON fa.user_id=u.user_id AND fa.farm_id=%s
            WHERE u.user_id=%s AND u.status='active'
            """,
            (payload.farm_id, payload.user_id),
        )
        row = cur.fetchone()
    if not row:
        return {"allowed": False, "reason": "Không tìm thấy người dùng."}
    if payload.action == "support":
        allowed = row["role"] == "technician" and bool(row["can_support"])
    else:
        allowed = bool(row["can_read"])
    return {
        "allowed": allowed,
        "reason": "Được phép truy cập." if allowed else "Tài khoản không có quyền truy cập vườn này.",
    }


def _technician_context(authorization: str | None) -> dict[str, Any]:
    payload = verify_token(bearer(authorization))
    current = user_context(payload["sub"])
    if current["role"] != "technician":
        raise HTTPException(status_code=403, detail="Chỉ kỹ thuật viên được quản lý ánh xạ danh tính ngoài.")
    return current


@app.get("/external-identities")
def list_external_identities(authorization: str | None = Header(default=None)):
    current = _technician_context(authorization)
    farm_ids = [x["farm_id"] for x in current.get("farms", []) if x.get("can_support")]
    if not farm_ids:
        return {"items": []}
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ei.external_identity_id,ei.provider,ei.external_subject,ei.user_id,
                   u.display_name,ei.tenant_ref,ei.verified_at,ei.revoked_at,ei.metadata
            FROM user_db.external_identities ei
            JOIN user_db.users u ON u.user_id=ei.user_id
            JOIN user_db.farm_access fa ON fa.user_id=ei.user_id
            WHERE fa.farm_id=ANY(%s)
            ORDER BY ei.verified_at DESC
            """,
            (farm_ids,),
        )
        rows = cur.fetchall()
    return {"items": rows}


@app.post("/external-identities")
def upsert_external_identity(payload: ExternalIdentityRequest, authorization: str | None = Header(default=None)):
    current = _technician_context(authorization)
    farm_ids = [x["farm_id"] for x in current.get("farms", []) if x.get("can_support")]
    provider = payload.provider.strip().lower()
    subject = payload.external_subject.strip()
    if provider not in {"zalo_oa", "nextfarm", "web", "mobile", "partner_api"} or not subject:
        raise HTTPException(status_code=422, detail="Provider hoặc external_subject không hợp lệ.")
    with conn() as db, db.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM user_db.farm_access WHERE user_id=%s AND farm_id=ANY(%s)",
            (payload.user_id, farm_ids),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=403, detail="Kỹ thuật viên không được quản lý người dùng này.")
        cur.execute(
            "SELECT external_identity_id,user_id FROM user_db.external_identities WHERE provider=%s AND external_subject=%s",
            (provider, subject),
        )
        existing = cur.fetchone()
        if existing and existing["user_id"] != payload.user_id:
            raise HTTPException(status_code=409, detail="Danh tính ngoài đã được ánh xạ tới tài khoản khác; phải thu hồi trước khi gán lại.")
        identity_id = existing["external_identity_id"] if existing else f"ext_{hashlib.sha256(f'{provider}:{subject}'.encode()).hexdigest()[:24]}"
        cur.execute(
            """
            INSERT INTO user_db.external_identities(
              external_identity_id,provider,external_subject,user_id,tenant_ref,metadata,verified_at,revoked_at
            ) VALUES (%s,%s,%s,%s,%s,%s,now(),NULL)
            ON CONFLICT (external_identity_id) DO UPDATE SET
              tenant_ref=excluded.tenant_ref,metadata=excluded.metadata,verified_at=now(),revoked_at=NULL
            RETURNING external_identity_id,provider,external_subject,user_id,tenant_ref,verified_at,revoked_at,metadata
            """,
            (identity_id, provider, subject, payload.user_id, payload.tenant_ref, Jsonb(payload.metadata)),
        )
        row = cur.fetchone()
        db.commit()
    return row


@app.post("/external-identities/{external_identity_id}/revoke")
def revoke_external_identity(external_identity_id: str, authorization: str | None = Header(default=None)):
    current = _technician_context(authorization)
    farm_ids = [x["farm_id"] for x in current.get("farms", []) if x.get("can_support")]
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            UPDATE user_db.external_identities ei SET revoked_at=now()
            WHERE ei.external_identity_id=%s AND EXISTS (
              SELECT 1 FROM user_db.farm_access fa WHERE fa.user_id=ei.user_id AND fa.farm_id=ANY(%s)
            ) RETURNING external_identity_id,revoked_at
            """,
            (external_identity_id, farm_ids),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Không tìm thấy ánh xạ trong phạm vi hỗ trợ.")
        db.commit()
    return row


@app.post("/external-identities/resolve")
def resolve_external_identity(
    payload: ExternalIdentityResolveRequest,
    x_internal_service_key: str | None = Header(default=None),
):
    require_internal_key(x_internal_service_key)
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT user_id,external_identity_id,tenant_ref,verified_at
            FROM user_db.external_identities
            WHERE provider=%s AND external_subject=%s AND revoked_at IS NULL
            """,
            (payload.provider.strip().lower(), payload.external_subject.strip()),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Danh tính ngoài chưa được xác minh hoặc đã bị thu hồi.")
    return {**row, "user": user_context(row["user_id"])}


@app.get("/demo-accounts")
def demo_accounts():
    if not EXPOSE_DEMO_ACCOUNTS:
        raise HTTPException(status_code=404, detail="Danh sách tài khoản demo đã tắt.")
    return {
        "items": [
            {"label": "Anh Long – cà chua", "username": "nongdan.long", "role": "farmer"},
            {"label": "Chị Lan – sầu riêng", "username": "nongdan.lan", "role": "farmer"},
            {"label": "Anh Minh – rau ăn lá", "username": "nongdan.minh", "role": "farmer"},
            {"label": "Kỹ thuật viên 01", "username": "kythuat.01", "role": "technician"},
        ],
        "passwords_exposed": False,
    }

@app.get("/support/farmers")
def support_farmers(authorization: str | None = Header(default=None)):
    payload = verify_token(bearer(authorization))
    current = user_context(payload["sub"])
    if current["role"] != "technician":
        raise HTTPException(status_code=403, detail="Chỉ kỹ thuật viên được xem danh sách khách hàng hỗ trợ.")
    farm_ids = [x["farm_id"] for x in current.get("farms", []) if x.get("can_support")]
    if not farm_ids:
        return {"items": []}
    with conn() as db, db.cursor() as cur:
        cur.execute(
            """
            SELECT u.user_id,u.display_name,u.phone,f.farm_id,f.farm_name,f.crop_name,f.region
            FROM farm_db.farms f
            JOIN user_db.users u ON u.user_id=f.owner_user_id
            WHERE f.farm_id=ANY(%s)
            ORDER BY u.display_name
            """,
            (farm_ids,),
        )
        rows = cur.fetchall()
    return {"items": rows}
