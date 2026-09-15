from __future__ import annotations

import argparse
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
FIXED = {
    "COMPOSE_PROJECT_NAME": "nextfarm_v10_crop_ai",
    "NEXTFARM_PG_VOLUME_NAME": "nextfarm_v10_crop_ai_pg",
}
SECRETS = {
    "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(24),
    "TOKEN_SECRET": lambda: secrets.token_urlsafe(48),
    "INTERNAL_SERVICE_KEY": lambda: secrets.token_urlsafe(48),
    "NEXTFARM_TECH_PASSWORD": lambda: secrets.token_urlsafe(18),
    "NEXTFARM_FARMER_PASSWORD": lambda: secrets.token_urlsafe(18),
    "MQTT_INGEST_PASSWORD": lambda: secrets.token_urlsafe(24),
    "MQTT_SIMULATOR_PASSWORD": lambda: secrets.token_urlsafe(24),
    "NEXTFARM_INGEST_KEY": lambda: secrets.token_urlsafe(48),
}
DEFAULTS = {
    "LLM_PROVIDER": "deterministic",
    "OPENAI_API_KEY": "",
    "OPENAI_MODEL": "gpt-5.6-luna",
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "LLM_TIMEOUT_SECONDS": "20",
    "LLM_ENABLE_VERBALIZER": "true",
    "CORS_ALLOW_ORIGINS": "http://localhost:18080,http://localhost:18081,http://localhost:18082,http://localhost:18084",
    "NEXTFARM_POSTGRES_BIND": "127.0.0.1:15432",
    "NEXTFARM_MQTT_BIND": "127.0.0.1:11883",
    "NEXTFARM_IDENTITY_BIND": "127.0.0.1:18100",
    "NEXTFARM_KNOWLEDGE_BIND": "127.0.0.1:18200",
    "NEXTFARM_FARM_DATA_BIND": "127.0.0.1:18300",
    "NEXTFARM_SIMULATOR_BIND": "127.0.0.1:18400",
    "NEXTFARM_TICKET_BIND": "127.0.0.1:18500",
    "NEXTFARM_ANALYTICS_BIND": "127.0.0.1:18600",
    "NEXTFARM_TRUTH_GUARD_BIND": "127.0.0.1:18700",
    "NEXTFARM_TELEMETRY_BIND": "127.0.0.1:18800",
    "NEXTFARM_CROP_ROUTER_BIND": "127.0.0.1:18900",
    "NEXTFARM_LLM_GATEWAY_BIND": "127.0.0.1:18950",
    "NEXTFARM_CHATBOT_BIND": "127.0.0.1:18000",
    "NEXTFARM_HTTP_BIND": "127.0.0.1:18080",
    "NEXTFARM_DATA_STUDIO_BIND": "127.0.0.1:18081",
    "NEXTFARM_KNOWLEDGE_STUDIO_BIND": "127.0.0.1:18082",
    "NEXTFARM_AI_ENCYCLOPEDIA_BIND": "127.0.0.1:18084",
}
LEGACY_PORT_DEFAULTS = {
    "CORS_ALLOW_ORIGINS": (
        "http://localhost:8080,http://localhost:8081,http://localhost:8082,http://localhost:8084",
        "http://localhost:18080,http://localhost:18081,http://localhost:18082,http://localhost:18084",
    ),
    "NEXTFARM_HTTP_BIND": ("127.0.0.1:8080", "127.0.0.1:18080"),
    "NEXTFARM_DATA_STUDIO_BIND": ("127.0.0.1:8081", "127.0.0.1:18081"),
    "NEXTFARM_KNOWLEDGE_STUDIO_BIND": ("127.0.0.1:8082", "127.0.0.1:18082"),
    "NEXTFARM_AI_ENCYCLOPEDIA_BIND": ("127.0.0.1:8084", "127.0.0.1:18084"),
}


def read_existing() -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    comments: list[str] = []
    if not ENV_PATH.exists():
        return values, comments
    known = set(FIXED) | set(SECRETS) | set(DEFAULTS)
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            if raw.strip():
                comments.append(raw)
            continue
        key, value = line.split("=", 1)
        if key in known:
            values[key] = value.strip()
        else:
            comments.append(raw)
    return values, comments


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or upgrade the local NextFarm V10 environment file.")
    parser.add_argument("--show-demo-passwords", action="store_true", help="Print local demo passwords to this terminal.")
    args = parser.parse_args()
    current, preserved = read_existing()
    added: list[str] = []
    migrated_binds: list[str] = []
    for key, factory in SECRETS.items():
        if not current.get(key):
            current[key] = factory()
            added.append(key)
    for key, value in FIXED.items():
        current[key] = value
    for key, (legacy, replacement) in LEGACY_PORT_DEFAULTS.items():
        if current.get(key) == legacy:
            current[key] = replacement
            migrated_binds.append(key)
    for key, value in DEFAULTS.items():
        current.setdefault(key, value)

    lines = ["# NextFarm V10 local config - DO NOT COMMIT OR SHARE"]
    lines += [f"{k}={current[k]}" for k in FIXED]
    lines += [f"{k}={current[k]}" for k in SECRETS]
    lines += ["", "# LLM configuration"]
    lines += [f"{k}={current[k]}" for k in DEFAULTS]
    if preserved:
        lines += ["", "# Preserved custom values", *preserved]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("[OK] NextFarm V10 .env ready.")
    if added:
        print("[OK] Generated secrets: " + ", ".join(added))
    if migrated_binds:
        print("[OK] Migrated V10 defaults away from legacy V9 ports: " + ", ".join(migrated_binds))
    print("[TAI KHOAN DEMO]")
    print("  Farmer usernames: nongdan.long / nongdan.lan / nongdan.minh")
    print("  Technician      : kythuat.01")
    if args.show_demo_passwords:
        print("  Farmer password : " + current["NEXTFARM_FARMER_PASSWORD"])
        print("  Technician pass : " + current["NEXTFARM_TECH_PASSWORD"])
    else:
        print("  Passwords are stored in .env; use --show-demo-passwords only on a private terminal.")
    print("[LLM] provider=" + current["LLM_PROVIDER"] + ", model=" + current["OPENAI_MODEL"])
    print("[LUU Y] .env contains credentials. Do not send or commit it.")


if __name__ == "__main__":
    main()
