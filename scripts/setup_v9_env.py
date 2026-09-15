from __future__ import annotations

import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
FIXED = {"COMPOSE_PROJECT_NAME": "nextfarm_v9_fresh", "NEXTFARM_PG_VOLUME_NAME": "nextfarm_v9_fresh_pg"}
KEYS = {
    "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(24),
    "TOKEN_SECRET": lambda: secrets.token_urlsafe(48),
    "INTERNAL_SERVICE_KEY": lambda: secrets.token_urlsafe(48),
    "NEXTFARM_TECH_PASSWORD": lambda: secrets.token_urlsafe(18),
    "NEXTFARM_FARMER_PASSWORD": lambda: secrets.token_urlsafe(18),
}


def main() -> None:
    current: dict[str, str] = {}
    unknown: list[str] = []
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                if raw.strip():
                    unknown.append(raw)
                continue
            key, value = line.split("=", 1)
            if key in KEYS or key in FIXED:
                current[key] = value.strip()
            else:
                unknown.append(raw)

    added: list[str] = []
    for key, factory in KEYS.items():
        if not current.get(key):
            current[key] = factory()
            added.append(key)

    for key, value in FIXED.items():
        current[key] = value
    lines = ["# NextFarm V9 standalone local config - DO NOT COMMIT OR SHARE"]
    lines.extend(f"{key}={current[key]}" for key in FIXED)
    lines.extend(f"{key}={current[key]}" for key in KEYS)
    if unknown:
        lines.extend(["", "# Preserved custom values", *unknown])
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if added:
        print("[OK] Da tao/bo sung: " + ", ".join(added))
    else:
        print("[OK] .env da co day du cac bien v9; khong doi gia tri hien tai.")
    print("[LUU Y] Khong commit/chia se .env. Mat khau bootstrap ban dau nam trong file nay.")


if __name__ == "__main__":
    main()
