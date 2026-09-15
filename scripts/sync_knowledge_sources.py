from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def dotenv_value(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    path = ROOT / ".env"
    if not path.exists():
        return None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith(f"{name}="):
            return raw.split("=", 1)[1].strip()
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Đồng bộ nguồn web vào kho tri thức dưới dạng draft bằng phiên kỹ thuật viên.")
    parser.add_argument("--base-url", default="http://localhost:18200")
    parser.add_argument("--identity-url", default="http://localhost:18100")
    parser.add_argument("--username", default=os.getenv("NEXTFARM_TECH_USERNAME", "kythuat.01"))
    parser.add_argument("--password", default=dotenv_value("NEXTFARM_TECH_PASSWORD"))
    parser.add_argument("--manifest", default=str(ROOT / "config" / "knowledge_sources.json"))
    args = parser.parse_args()
    password = args.password or getpass.getpass(f"Mật khẩu cho {args.username}: ")

    sources = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    results = []
    with httpx.Client(timeout=45) as client:
        login = client.post(f"{args.identity_url.rstrip('/')}/auth/login", json={"username": args.username, "password": password})
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        for item in sources:
            try:
                response = client.post(f"{args.base_url.rstrip('/')}/admin/ingest-url", headers=headers, json=item)
                body = response.json()
                results.append({"url": item["url"], "status": response.status_code, "result": body})
                print(f"[{response.status_code}] {item['source_name']}")
            except Exception as exc:  # noqa: BLE001
                results.append({"url": item["url"], "status": 0, "error": str(exc)})
                print(f"[ERROR] {item['source_name']}: {exc}")

    output = ROOT / "docs" / "evidence" / "knowledge-sync-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Đã lưu báo cáo: {output}")


if __name__ == "__main__":
    main()
