from __future__ import annotations

import http.client
import json
import sys
import time
import urllib.error
import urllib.request

URL = "http://localhost:8600/health"
TIMEOUT_SECONDS = 1200


def fetch() -> dict:
    with urllib.request.urlopen(URL, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    deadline = time.time() + TIMEOUT_SECONDS
    last = None
    while time.time() < deadline:
        try:
            last = fetch()
            phase = last.get("training_phase")
            ready = bool(last.get("reference_bootstrap_ready"))
            err = last.get("last_error")
            print(f"[AI] phase={phase} reference_bootstrap_ready={ready} error={err or '-'}")
            if ready:
                return 0
            if err:
                print("[WAIT] AI đang retry; nếu lỗi lặp lại hãy chạy scripts\\diagnose_v9.cmd")
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            http.client.RemoteDisconnected,
            ConnectionError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            # Docker may publish port 8600 a moment before Uvicorn is fully ready.
            # RemoteDisconnected/ConnectionReset during this window is transient and
            # must not abort the whole V9 bootstrap pipeline.
            print(f"[WAIT] AI API đang khởi động/chưa sẵn sàng: {type(exc).__name__}: {exc}")
        time.sleep(5)
    print(f"[LOI] Hết {TIMEOUT_SECONDS}s nhưng AI bootstrap chưa hoàn tất. Last={last}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
