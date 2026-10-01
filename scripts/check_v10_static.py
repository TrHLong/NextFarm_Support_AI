from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
FAIL: list[str] = []
PASS: list[str] = []
SKIP: list[str] = []


def report_path(value: str) -> Path:
    normalized = str(value).replace("\\", "/")
    if normalized.startswith("/models/"):
        return ROOT / "model-artifacts" / normalized[len("/models/"):]
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name + (f": {detail}" if detail else ""))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def skip(name: str, detail: str) -> None:
    SKIP.append(name + f": {detail}")
    print(f"[SKIP] {name} - {detail}")


# Required V10 components
required = [
    "infra/database/04_v10_ai_encyclopedia.sql",
    "services/crop-router-service/app/main.py",
    "services/llm-gateway-service/app/main.py",
    "apps/ai-encyclopedia/index.html",
    "apps/ai-encyclopedia/app.js",
    "infra/ai-encyclopedia-nginx.conf",
    "docs/14-v10-crop-aware-ai-encyclopedia.md",
    "docs/15-v10-install-run.md",
    "docs/16-v10-research-model-catalog.md",
]
for rel in required:
    check(f"exists {rel}", (ROOT / rel).exists())

# Runtime setup is allowed to create secrets locally; the repository must exclude them.
gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
check("root .env is ignored", any(line.strip() == ".env" for line in gitignore.splitlines()))
check("runtime secret directory is ignored", any(line.strip() == ".secrets/*" for line in gitignore.splitlines()))

# No large raw reference download is bundled.
raw_files = [p for p in (ROOT / "research-data/reference/raw").rglob("*") if p.is_file()] if (ROOT / "research-data/reference/raw").exists() else []
check("raw external reference payload omitted", not raw_files, f"files={len(raw_files)}")

# Catalog counts from migration.
sql = (ROOT / "infra/database/04_v10_ai_encyclopedia.sql").read_text(encoding="utf-8")
def count_seed(start_marker: str, end_marker: str) -> int:
    a = sql.index(start_marker); b = sql.index(end_marker, a)
    return len(re.findall(r"^\('[a-z0-9_]+',", sql[a:b], re.M))
try:
    crop_count = count_seed("INSERT INTO ai_db.crop_catalog", "ON CONFLICT (crop_key)")
    cap_count = count_seed("INSERT INTO ai_db.model_capabilities", "ON CONFLICT (capability_key)")
except Exception:
    crop_count = cap_count = -1
check("crop catalog has 34 keys", crop_count == 34, f"count={crop_count}")
check("AI encyclopedia has 32 capabilities", cap_count == 32, f"count={cap_count}")
check("farm crop inventory uses non-null zone key", "zone_id TEXT NOT NULL REFERENCES farm_db.zones" in sql)
check("capability implementation is explicitly gated", "implementation_state" in sql and "catalog_only" in sql)

# Python syntax without creating __pycache__ in the source package.
python_files = sorted((ROOT / "services").rglob("*.py")) + sorted((ROOT / "scripts").glob("*.py"))
syntax_errors: list[str] = []
for path in python_files:
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeError) as exc:
        syntax_errors.append(f"{path.relative_to(ROOT)}: {exc}")
check("Python syntax", not syntax_errors, "; ".join(syntax_errors[:5]))

# Catch route-level regressions that syntax-only checks miss. The v10.4
# crop-router is a thin service adapter around nextfarm_device.api.
crop_router = (ROOT / "services/crop-router-service/app/main.py").read_text(encoding="utf-8")
current_crop_router = "from nextfarm_device.api import catalog_app" in crop_router and "app = catalog_app()" in crop_router
legacy_helpers = all(f"def {helper}(" in crop_router for helper in ["_catalog", "_auth_user", "_internal_ok", "_ensure_farm", "_readiness_snapshot"])
check("crop router exposes current catalog adapter", current_crop_router or legacy_helpers)
crop_tests = (ROOT / "services/crop-router-service/tests/test_crop_router.py").read_text(encoding="utf-8")
check("crop router has endpoint contract tests", "TestClient" in crop_tests or "catalog_app" in crop_tests)

# v10.4 uses five simulation-only models and a single end-to-end report.
simulation_report_path = ROOT / "model-artifacts/simulation-v104/latest/TRAINING_END_TO_END_REPORT.json"
simulation_model_dir = ROOT / "model-artifacts/simulation-v104/latest/models"
try:
    simulation = json.loads(simulation_report_path.read_text(encoding="utf-8"))
    model_names = [item["model"] for item in simulation.get("models", [])]
    models = [simulation_model_dir / f"{name}.joblib" for name in model_names]
    check(
        "five v10.4 simulation model candidates",
        len(models) == 5 and all(path.exists() for path in models),
        f"count={len(models)}",
    )
    check("v10.4 training report has five evaluations", len(model_names) == 5, f"count={len(model_names)}")
    check(
        "simulation artifacts remain fail-closed",
        simulation.get("scope") == "SYNTHETIC_SIMULATION_ONLY" and simulation.get("production_ready") is False,
        f"scope={simulation.get('scope')}, production_ready={simulation.get('production_ready')}",
    )
    check(
        "simulation deployment smoke passed",
        simulation.get("deployment_smoke", {}).get("status") == "PASS"
        and simulation.get("deployment_smoke", {}).get("models_loaded") == 5,
        f"status={simulation.get('deployment_smoke', {}).get('status')}",
    )
except Exception as exc:
    check("v10.4 simulation training summary readable", False, str(exc))

# Load/inference smoke test. This only proves artifact serialization/predict API, not field accuracy.
try:
    import joblib
    import numpy as np
    loaded = 0
    for path in models:
        bundle = joblib.load(path)
        n = len(bundle.get("features") or [])
        if n <= 0:
            raise RuntimeError(f"{path}: no features")
        _ = bundle["model"].predict(np.zeros((1, n), dtype=float))
        loaded += 1
    check("all packaged models load and predict", loaded == 10, f"count={loaded}")
except Exception as exc:
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        skip("all packaged models load and predict", "cài requirements của ai-analytics-service hoặc chạy Docker runtime check")
    else:
        check("all packaged models load and predict", False, str(exc))

# Compose static references
compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
for service in ["crop-router-service:", "llm-gateway-service:", "ai-encyclopedia:"]:
    check(f"compose contains {service[:-1]}", service in compose)
check("compose mounts V10 migration", "04_v10_ai_encyclopedia.sql" in compose)
check("LLM default is current configurable model", "OPENAI_MODEL: ${OPENAI_MODEL:-gpt-5.6-luna}" in compose)
check("local service ports use configurable loopback binds", "NEXTFARM_LLM_GATEWAY_BIND" in compose and "NEXTFARM_POSTGRES_BIND" in compose and "127.0.0.1" in compose)
check("ingest uses dedicated key", "INGEST_API_KEY: ${NEXTFARM_INGEST_KEY" in compose)
check("LLM and Truth Guard receive internal key", compose.count("INTERNAL_SERVICE_KEY: ${INTERNAL_SERVICE_KEY") >= 5)

setup = (ROOT / "scripts/setup_v10_env.py").read_text(encoding="utf-8")
for secret in ["MQTT_INGEST_PASSWORD", "MQTT_SIMULATOR_PASSWORD", "NEXTFARM_INGEST_KEY"]:
    check(f"setup generates {secret}", f'"{secret}"' in setup)
production_setup = ROOT / "scripts/setup_v10_production.ps1"
check("production setup creates Mosquitto password file", production_setup.exists() and "mosquitto_passwd" in production_setup.read_text(encoding="utf-8"))
restore = (ROOT / "scripts/restore_v10.ps1").read_text(encoding="utf-8")
check("restore includes V10 services", all(name in restore for name in ["crop-router-service", "llm-gateway-service", "ai-encyclopedia"]))
check("restore reapplies AI Encyclopedia migration", "04_v10_ai_encyclopedia.sql" in restore)
runtime_check = ROOT / "scripts/check_v10_runtime.ps1"
check("runtime smoke test covers V10 core flow", runtime_check.exists() and all(marker in runtime_check.read_text(encoding="utf-8") for marker in ["/me/crops", "/capabilities", "/plan", "/verify"]))
unit_check = ROOT / "scripts/check_v10_unit_tests.ps1"
check(
    "container unit-test runner covers V10 AI services and artifacts",
    unit_check.exists()
    and all(
        marker in unit_check.read_text(encoding="utf-8")
        for marker in [
            "crop-router-service",
            "llm-gateway-service",
            "truth-guard-service",
            "ai-analytics-service",
            "artifact_smoke_test.py",
        ]
    ),
)

result = {
    "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
    "passed": not FAIL,
    "pass_count": len(PASS),
    "fail_count": len(FAIL),
    "skip_count": len(SKIP),
    "passes": PASS,
    "failures": FAIL,
    "skips": SKIP,
    "note": "Static/artifact validation only; Docker end-to-end must be run on a host with Docker Engine.",
}
out = ROOT / "docs/evidence/v10.4-static-validation.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nSummary: {len(PASS)} PASS / {len(FAIL)} FAIL / {len(SKIP)} SKIP")
sys.exit(1 if FAIL else 0)
