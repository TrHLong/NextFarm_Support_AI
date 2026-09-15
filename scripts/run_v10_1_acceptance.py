from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import joblib
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
RESULTS: list[dict[str, Any]] = []
EXPECTED_CATEGORIES = {
    "latest_sensor": 30,
    "device_state": 20,
    "irrigation_history": 20,
    "irrigation_schedule": 20,
    "missing_stale_data": 20,
    "unauthorized_cross_farm": 20,
    "agricultural_factual_qa": 50,
    "no_answer_hallucination": 30,
    "vietnamese_robustness": 30,
    "multi_turn_context": 20,
}


def report_path(value: str) -> Path:
    normalized = str(value).replace("\\", "/")
    if normalized.startswith("/models/"):
        return ROOT / "model-artifacts" / normalized[len("/models/"):]
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def record(name: str, passed: bool, detail: Any) -> None:
    RESULTS.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_benchmark() -> list[dict[str, Any]]:
    path = ROOT / "benchmarks/v10.1/acceptance_260.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_rows(name: str) -> list[dict[str, Any]]:
    return pq.read_table(ROOT / f"data/operational/{name}.parquet").to_pylist()


def latest_sensor_rows() -> dict[tuple[str, str, str], dict[str, Any]]:
    folder = ROOT / "data/operational"
    zones = {row["zone_id"]: row["zone_code"] for row in read_rows("zones")}
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    columns = ["sensor_id", "farm_id", "zone_id", "metric_type", "value", "unit", "quality", "measured_at", "received_at", "scenario_id"]
    for batch in pq.ParquetFile(folder / "sensor_readings.parquet").iter_batches(columns=columns, batch_size=32768):
        for row in batch.to_pylist():
            key = (row["farm_id"], zones[row["zone_id"]], row["metric_type"])
            if key not in latest or row["measured_at"] > latest[key]["measured_at"]:
                latest[key] = row
    return latest


def parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def check_syntax_and_assets() -> None:
    errors = []
    python_files = list((ROOT / "services").rglob("*.py")) + list((ROOT / "scripts").glob("*.py"))
    for path in python_files:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")
    record("python_syntax", not errors, {"files": len(python_files), "errors": errors[:5]})

    js_errors = []
    js_files = list(ROOT.rglob("*.js"))
    for path in js_files:
        result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
        if result.returncode:
            js_errors.append(f"{path.relative_to(ROOT)}: {result.stderr.strip()}")
    record("javascript_syntax", not js_errors, {"files": len(js_files), "errors": js_errors[:5]})
    required = [
        "apps/web/app.js",
        "infra/database/06_v10_1_acceptance.sql",
        "benchmarks/v10.1/acceptance_260.jsonl",
        "data/operational/sensor_readings.parquet",
        "docs/V10.1-FEEDBACK-AUDIT.md",
    ]
    missing = [item for item in required if not (ROOT / item).exists()]
    record("package_completeness", not missing, {"missing": missing})


def check_benchmark_plan_and_context(rows: list[dict[str, Any]]) -> None:
    router = load_module("v101_router", ROOT / "services/llm-gateway-service/app/logic.py")
    context = load_module("v101_context", ROOT / "services/chatbot-service/app/context_policy.py")
    counts = Counter(row["category"] for row in rows)
    taxonomy_ok = len(rows) == 260 and counts == Counter(EXPECTED_CATEGORIES) and len({row["case_id"] for row in rows}) == 260
    record("benchmark_feedback_taxonomy", taxonomy_ok, {"cases": len(rows), "categories": dict(sorted(counts.items()))})

    evaluated = 0
    correct_tools = 0
    correct_arguments = 0
    failures = []
    multi_source = 0
    for row in rows:
        if row["category"] == "unauthorized_cross_farm":
            continue
        plan = router.deterministic_plan(row["message"])
        actual_tools = [step["tool_name"] for step in plan["steps"]]
        expected_tools = row["expected_tools"]
        evaluated += 1
        tools_ok = actual_tools == expected_tools
        correct_tools += int(tools_ok)
        multi_source += int(len(actual_tools) > 1)

        actual_arguments = dict(plan["steps"][0].get("arguments") or {}) if plan.get("steps") else {}
        expected_arguments = dict(row.get("expected_arguments") or {})
        if row["category"] == "multi_turn_context":
            recent = [turn["tool_payload"] for turn in reversed(row["conversation"]) if turn.get("tool_payload")]
            resolved_zone, source = context.resolve_zone_context(None, recent)
            actual_arguments["zone"] = resolved_zone
            arguments_ok = source == "recent_confirmed_tool_result"
        else:
            arguments_ok = True
        arguments_ok = arguments_ok and all(actual_arguments.get(key) == value for key, value in expected_arguments.items())
        correct_arguments += int(arguments_ok)
        if not tools_ok or not arguments_ok:
            failures.append({
                "case_id": row["case_id"], "actual_tools": actual_tools, "expected_tools": expected_tools,
                "actual_arguments": actual_arguments, "expected_arguments": expected_arguments,
            })

    tool_accuracy = correct_tools / max(1, evaluated)
    argument_accuracy = correct_arguments / max(1, evaluated)
    record("planner_tool_selection", tool_accuracy >= 0.95, {"evaluated": evaluated, "accuracy": round(tool_accuracy, 4), "failures": failures[:8]})
    record("planner_argument_resolution", argument_accuracy >= 0.95, {"evaluated": evaluated, "accuracy": round(argument_accuracy, 4), "failures": failures[:8]})
    record("multi_source_planning", multi_source >= 20, {"multi_source_cases": multi_source, "minimum": 20})


def check_benchmark_oracles(rows: list[dict[str, Any]]) -> None:
    latest = latest_sensor_rows()
    devices = {row["device_id"]: row for row in read_rows("devices")}
    schedules = {row["schedule_id"]: row for row in read_rows("irrigation_schedules")}
    permissions = {(row["user_id"], row["farm_id"]): row for row in read_rows("user_farm_permissions")}
    zones = {row["zone_id"]: row for row in read_rows("zones")}
    events_by_farm_zone: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in read_rows("irrigation_events"):
        events_by_farm_zone[(event["farm_id"], zones[event["zone_id"]]["zone_code"])].append(event)
    snapshot = datetime(2026, 9, 4, tzinfo=timezone.utc)
    errors = []
    checked = 0

    for row in rows:
        category = row["category"]
        oracle = row.get("oracle") or {}
        expected = row.get("expected_arguments") or {}
        try:
            if category == "latest_sensor":
                source = latest[(row["farm_id"], expected["zone"], expected["metric"])]
                if abs(float(source["value"]) - float(oracle["value"])) > 1e-9 or source["unit"] != oracle["unit"]:
                    raise AssertionError("sensor value/unit mismatch")
                if parse_datetime(oracle["measured_at"]) != source["measured_at"]:
                    raise AssertionError("sensor timestamp mismatch")
                checked += 1
            elif category == "device_state":
                source = devices[oracle["device_id"]]
                if source["farm_id"] != row["farm_id"] or bool(source["online"]) != bool(oracle["online"]):
                    raise AssertionError("device state mismatch")
                checked += 1
            elif category == "irrigation_schedule":
                source = schedules[oracle["schedule_id"]]
                if source["farm_id"] != row["farm_id"] or source["start_time"] != oracle["start_time"]:
                    raise AssertionError("schedule mismatch")
                checked += 1
            elif category == "irrigation_history":
                source = [
                    item for item in events_by_farm_zone[(row["farm_id"], expected["zone"])]
                    if snapshot - timedelta(hours=expected["hours"]) <= item["started_at"] <= snapshot
                ]
                if len(source) != oracle["event_count"]:
                    raise AssertionError("history count mismatch")
                if abs(sum(float(item["duration_minutes"]) for item in source) - float(oracle["total_minutes"])) > 1e-9:
                    raise AssertionError("history duration mismatch")
                checked += 1
            elif category == "missing_stale_data" and oracle.get("source_table") == "sensor_readings" and "value" in oracle:
                source = latest[(row["farm_id"], expected["zone"], expected["metric"])]
                if parse_datetime(oracle["measured_at"]) != source["measured_at"]:
                    raise AssertionError("stale/quality source mismatch")
                if oracle.get("fresh") is False and (snapshot - source["measured_at"]).total_seconds() <= 1800:
                    raise AssertionError("stale oracle is fresh")
                checked += 1
            elif category == "missing_stale_data" and oracle.get("available") is False:
                if (row["farm_id"], expected["zone"], expected["metric"]) in latest:
                    raise AssertionError("no-data oracle has a reading")
                checked += 1
            elif category == "unauthorized_cross_farm":
                if (row["user_id"], row["farm_id"]) in permissions:
                    raise AssertionError("ACL oracle grants requested farm")
                if not any(key[0] == row["user_id"] for key in permissions):
                    raise AssertionError("ACL oracle user has no baseline permission")
                checked += 1
        except Exception as exc:
            errors.append(f"{row['case_id']}: {exc}")

    record("benchmark_oracle_integrity", not errors and checked >= 120, {"checked": checked, "errors": errors[:10]})
    agronomy = [row for row in rows if row["category"] == "agricultural_factual_qa"]
    tracked = len(agronomy) == 50 and all(row.get("expert_review_status") == "pending_nextfarm_agronomist" for row in agronomy)
    record("agronomy_expert_review_tracking", tracked, {"cases": len(agronomy), "pending_expert_review": sum(row.get("expert_review_status") == "pending_nextfarm_agronomist" for row in agronomy)})


def check_context_and_truth_policies() -> None:
    context = load_module("v101_context_policy", ROOT / "services/chatbot-service/app/context_policy.py")
    authorized = {"farms": [{"farm_id": "farm_a", "can_read": True}]}
    blocked = 0
    for index in range(50):
        try:
            context.resolve_farm_context(authorized, f"farm_forbidden_{index}")
        except context.ContextPolicyError as exc:
            blocked += int(exc.code == "FORBIDDEN")
    record("acl_cross_farm_denial", blocked == 50, {"attempts": 50, "blocked": blocked, "leaks": 50 - blocked})
    zone, source = context.resolve_zone_context(None, [{"items": [{"zone_code": "A"}, {"zone_code": "B"}]}])
    record("ambiguous_zone_fail_closed", zone is None and source == "missing", {"zone": zone, "source": source})

    guard = load_module("v101_guard", ROOT / "services/truth-guard-service/app/guard_logic.py")
    rejected = [
        guard.evaluate_answer(answer="Độ ẩm hiện là 62%.", evidence=[{"farm_id": "farm_a", "value": 62, "fresh": False}], confidence=.8, min_confidence=.55, requires_human=False, knowledge_mode=False, expected_farm_id="farm_a"),
        guard.evaluate_answer(answer="Độ ẩm hiện là 62%.", evidence=[{"farm_id": "farm_a", "value": 62, "quality": "suspect"}], confidence=.8, min_confidence=.55, requires_human=False, knowledge_mode=False, expected_farm_id="farm_a"),
        guard.evaluate_answer(answer="Độ ẩm hiện là 62%.", evidence=[{"farm_id": "farm_a", "available": False, "error_code": "NO_DATA"}], confidence=.8, min_confidence=.55, requires_human=False, knowledge_mode=False, expected_farm_id="farm_a"),
        guard.evaluate_answer(answer="Độ ẩm hiện là 62%.", evidence=[{"farm_id": "farm_b", "value": 62}], confidence=.8, min_confidence=.55, requires_human=False, knowledge_mode=False, expected_farm_id="farm_a"),
        guard.evaluate_answer(answer="Độ ẩm hiện là 75%.", evidence=[{"farm_id": "farm_a", "value": 62}], confidence=.8, min_confidence=.55, requires_human=False, knowledge_mode=False, expected_farm_id="farm_a"),
    ]
    valid = guard.evaluate_answer(answer="Độ ẩm hiện là 62%.", evidence=[{"farm_id": "farm_a", "value": 62, "fresh": True, "quality": "good"}], confidence=.8, min_confidence=.55, requires_human=False, knowledge_mode=False, expected_farm_id="farm_a")
    record("truth_guard_fail_closed", all(not item["allowed"] for item in rejected) and valid["allowed"], {"blocked": sum(not item["allowed"] for item in rejected), "negative_cases": len(rejected), "valid_allowed": valid["allowed"]})


def check_operational_parquet() -> None:
    folder = ROOT / "data/operational"
    required_columns = {
        "users": {"user_id", "customer_id", "role", "status"},
        "user_farm_permissions": {"user_id", "farm_id", "can_read", "can_control"},
        "farms": {"farm_id", "customer_id", "province", "crop_profile"},
        "zones": {"zone_id", "farm_id", "crop_name", "variety", "growth_stage", "soil_type"},
        "devices": {"device_id", "farm_id", "controller_type", "online", "updated_at"},
        "sensors": {"sensor_id", "device_id", "zone_id", "metric_type", "unit"},
        "sensor_readings": {"sensor_id", "measured_at", "received_at", "quality", "value", "unit"},
        "irrigation_schedules": {"schedule_id", "zone_id", "start_time", "duration_minutes", "enabled"},
        "irrigation_events": {"run_id", "zone_id", "started_at", "ended_at", "duration_minutes", "water_liters", "result"},
        "command_logs": {"command_id", "actor", "device_id", "command", "requested_at", "result"},
        "alerts": {"alert_id", "farm_id", "zone_id", "alert_type", "severity", "status"},
    }
    trace_columns = {"synthetic", "scenario_id", "generator_version"}
    counts = {}
    errors = []
    hashes: dict[str, list[str]] = defaultdict(list)
    tables: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(folder.glob("*.parquet")):
        name = path.stem
        try:
            table = pq.read_table(path)
            tables[name] = table.to_pylist() if name != "sensor_readings" else []
            counts[name] = table.num_rows
            metadata = table.schema.metadata or {}
            if metadata.get(b"dataset_id") != b"nextfarm-v10.1-operational-acceptance" or metadata.get(b"synthetic") != b"true":
                errors.append(f"{path.name}: missing provenance metadata")
            missing = (required_columns.get(name, set()) | trace_columns) - set(table.schema.names)
            if missing:
                errors.append(f"{path.name}: missing columns {sorted(missing)}")
            for column in trace_columns & set(table.schema.names):
                if table[column].null_count:
                    errors.append(f"{path.name}: {column} contains null")
            if "synthetic" in table.schema.names and table["synthetic"].to_pylist().count(False):
                errors.append(f"{path.name}: contains non-synthetic row")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            hashes[digest].append(path.name)
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")

    duplicates = [names for names in hashes.values() if len(names) > 1]
    if duplicates:
        errors.append(f"duplicate files: {duplicates}")
    if set(counts) != set(required_columns):
        errors.append(f"table set mismatch: {sorted(counts)}")

    farms = {row["farm_id"] for row in tables.get("farms", [])}
    zones = {row["zone_id"]: row for row in tables.get("zones", [])}
    devices = {row["device_id"]: row for row in tables.get("devices", [])}
    users = {row["user_id"] for row in tables.get("users", [])}
    for row in tables.get("zones", []):
        if row["farm_id"] not in farms:
            errors.append(f"zone {row['zone_id']} has unknown farm")
    for row in tables.get("sensors", []):
        if row["zone_id"] not in zones or row["device_id"] not in devices or zones[row["zone_id"]]["farm_id"] != row["farm_id"]:
            errors.append(f"sensor {row['sensor_id']} has invalid relationship")
    for row in tables.get("user_farm_permissions", []):
        if row["user_id"] not in users or row["farm_id"] not in farms:
            errors.append(f"permission {row['user_id']}/{row['farm_id']} has invalid relationship")
    for row in tables.get("irrigation_events", []):
        actual = (row["ended_at"] - row["started_at"]).total_seconds() / 60
        if row["ended_at"] < row["started_at"] or abs(actual - float(row["duration_minutes"])) > 0.01:
            errors.append(f"event {row['run_id']} duration mismatch")
    for row in tables.get("command_logs", []):
        if row["status"] in {"rejected", "pending_confirmation"} and row["result"] != "not_executed":
            errors.append(f"command {row['command_id']} changed state without success")

    latest = latest_sensor_rows()
    unit_map = {"soil_moisture": "%", "temperature": "°C", "ph": "pH"}
    for row in latest.values():
        if row["unit"] != unit_map.get(row["metric_type"]):
            errors.append(f"sensor unit mismatch {row['sensor_id']}")
    offline_farms = {row["farm_id"] for row in tables.get("devices", []) if row["device_type"] == "sensor_gateway" and not row["online"]}
    snapshot = datetime(2026, 9, 4, tzinfo=timezone.utc)
    for farm_id in offline_farms:
        if any((snapshot - row["measured_at"]).total_seconds() <= 1800 for key, row in latest.items() if key[0] == farm_id):
            errors.append(f"offline farm {farm_id} still has fresh readings")
    alert_types = {row["alert_type"] for row in tables.get("alerts", [])}
    if len(alert_types) < 8:
        errors.append(f"alert scenario coverage too small: {len(alert_types)}")

    counts_ok = counts.get("farms") == 40 and counts.get("zones") == 120 and counts.get("users") == 80 and counts.get("sensor_readings", 0) >= 700_000
    record("operational_parquet_contract", counts_ok and not errors, {"counts": counts, "alert_types": len(alert_types), "offline_farms": len(offline_farms), "errors": errors[:12]})


def check_models_and_evidence() -> None:
    suite = json.loads((ROOT / "model-artifacts/shared/latest_training_report.json").read_text(encoding="utf-8"))
    summary = json.loads((ROOT / "docs/evidence/shared-ml-latest.json").read_text(encoding="utf-8"))
    models = [report_path(item["artifact_path"]) for item in suite.get("models", [])]
    load_errors = []
    for path in models:
        try:
            bundle = joblib.load(path)
            if not bundle.get("features") or "model" not in bundle:
                load_errors.append(f"{path}: incomplete bundle")
        except Exception as exc:
            load_errors.append(f"{path}: {exc}")
    synchronized = (
        suite.get("dataset_version") == summary.get("dataset_version")
        and suite.get("approved_model_count") == summary.get("approved_candidate_count")
        and suite.get("total_active_model_count") == summary.get("active_model_count")
    )
    record("model_artifacts", len(models) == 10 and not load_errors, {"count": len(models), "load_errors": load_errors})
    record("single_model_evidence", synchronized, {"dataset_version": suite.get("dataset_version"), "approved": suite.get("approved_model_count"), "experimental": suite.get("experimental_model_count")})


def check_static_security_contract() -> None:
    chatbot = (ROOT / "services/chatbot-service/app/main.py").read_text(encoding="utf-8")
    farm_data = (ROOT / "services/farm-data-service/app/main.py").read_text(encoding="utf-8")
    gateway = (ROOT / "services/llm-gateway-service/app/main.py").read_text(encoding="utf-8")
    knowledge = (ROOT / "services/knowledge-service/app/main.py").read_text(encoding="utf-8")
    checks = {
        "parallel_tools_enabled": '"parallel_tool_calls": True' in gateway,
        "no_zone_first_fallback": "ORDER BY zone_code LIMIT 1" not in farm_data,
        "planner_zone_not_trusted": "zone = zone or planned_args.get(\"zone\")" not in chatbot,
        "planner_metric_not_trusted": "metric, metric_label = detect_metric(message)" in chatbot,
        "truth_guard_outage_fails_closed": "Truth Guard là safety gate" in chatbot and "grounded = False" in chatbot,
        "quality_rejected_before_claim": "metric_quality_rejected" in chatbot,
        "knowledge_reader_auth": all(marker in knowledge for marker in ["def require_reader", "require_reader(authorization, x_internal_service_key)"]),
        "structured_table_chunks": '"content_type":content_type' in knowledge and '"table_context"' in knowledge,
        "received_at_contract": all(marker in farm_data for marker in ['"measured_at"', '"received_at"']),
    }
    record("static_security_contract", all(checks.values()), checks)


def docker_status() -> dict[str, Any]:
    executable = shutil.which("docker")
    if not executable:
        return {"status": "cli_unavailable", "docker_cli_available": False, "daemon_available": False, "certified": False}
    try:
        probe = subprocess.run([executable, "info", "--format", "{{json .ServerVersion}}"], capture_output=True, text=True, timeout=8)
        daemon = probe.returncode == 0
        return {
            "status": "available_not_run" if daemon else "daemon_unavailable",
            "docker_cli_available": True,
            "daemon_available": daemon,
            "certified": False,
            "detail": (probe.stdout or probe.stderr).strip()[:500],
        }
    except Exception as exc:
        return {"status": "probe_failed", "docker_cli_available": True, "daemon_available": False, "certified": False, "detail": str(exc)}


def main() -> None:
    rows = load_benchmark()
    check_syntax_and_assets()
    check_benchmark_plan_and_context(rows)
    check_benchmark_oracles(rows)
    check_context_and_truth_policies()
    check_operational_parquet()
    check_models_and_evidence()
    check_static_security_contract()
    passed = all(item["passed"] for item in RESULTS)
    runtime = docker_status()
    pending_expert = sum(row.get("expert_review_status") == "pending_nextfarm_agronomist" for row in rows)
    report = {
        "build_version": "10.1.1",
        "benchmark_version": rows[0].get("benchmark_version") if rows else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "offline_passed": passed,
        "pass_count": sum(item["passed"] for item in RESULTS),
        "fail_count": sum(not item["passed"] for item in RESULTS),
        "feedback_acceptance_ready": passed and runtime.get("certified", False) and pending_expert == 0,
        "external_gates": {
            "runtime_end_to_end": "pending" if not runtime.get("certified") else "passed",
            "nextfarm_agronomist_review": "pending" if pending_expert else "passed",
            "agronomy_cases_pending": pending_expert,
        },
        "runtime": {
            **runtime,
            "required_command": "powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\check_v10_completion.ps1 -Runtime",
        },
        "results": RESULTS,
    }
    output = ROOT / "docs/evidence/v10.1-acceptance-offline.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Summary: {report['pass_count']} PASS / {report['fail_count']} FAIL; runtime={report['runtime']['status']}; feedback_ready={report['feedback_acceptance_ready']}")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
