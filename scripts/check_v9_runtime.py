from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def env() -> dict[str, str]:
    values = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


def req(url: str, *, method: str = "GET", body: dict | None = None, token: str | None = None, expected=(200,)) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=10) as res:
            status = res.status
            payload = json.loads(res.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            payload = {}
    if status not in expected:
        raise RuntimeError(f"{method} {url}: HTTP {status}, expected {expected}, body={payload}")
    return payload


def wait_health(url: str, seconds: int = 120) -> dict:
    end = time.time() + seconds
    last = None
    while time.time() < end:
        try:
            last = req(url)
            if last.get("status") == "ok":
                return last
        except Exception as exc:
            last = {"error": str(exc)}
        time.sleep(3)
    raise RuntimeError(f"Health timeout {url}: {last}")


def main() -> int:
    cfg = env()
    for port in (8100, 8400, 8600, 8800):
        h = wait_health(f"http://localhost:{port}/health", 180)
        print(f"[PASS] health {port}: {h.get('status')}")

    farmer = req("http://localhost:8100/auth/login", method="POST", body={"username": "nongdan.long", "password": cfg["NEXTFARM_FARMER_PASSWORD"]})
    tech = req("http://localhost:8100/auth/login", method="POST", body={"username": "kythuat.01", "password": cfg["NEXTFARM_TECH_PASSWORD"]})
    ft = farmer["access_token"]
    tt = tech["access_token"]
    print("[PASS] login farmer + technician")

    req("http://localhost:8300/farms/farm_long/overview", token=ft)
    req("http://localhost:8300/farms/farm_lan/overview", token=ft, expected=(403,))
    print("[PASS] tenant isolation")

    grid = req("http://localhost:8300/studio/grid?farm_id=farm_long", token=ft)
    if not grid.get("items"):
        raise RuntimeError("farm_long grid chưa có telemetry V9.")
    origins = {str(x.get("data_origin") or "") for x in grid.get("items", []) if x.get("data_origin")}
    if origins != {"simulated_device_calibrated_v9"}:
        raise RuntimeError(f"Runtime origin không đúng V9 standalone: {origins}")
    print(f"[PASS] runtime grid rows={len(grid['items'])}, origin={origins}")

    status = req("http://localhost:8600/ml/status", token=tt)
    if not status.get("reference_bootstrap_ready"):
        raise RuntimeError(f"AI reference bootstrap chưa sẵn sàng: {status}")
    if status.get("production_ready"):
        raise RuntimeError("V9 simulator/reference-only không được tự báo production_ready.")
    print(f"[PASS] AI phase={status.get('training_phase')}, runtime={status.get('runtime_reading_count')}/{status.get('runtime_retrain_threshold')}")
    print("[PASS] production_ready=false cho tới khi có validation thiết bị thật ngoài V9")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1)
