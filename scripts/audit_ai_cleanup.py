from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ARTIFACT_ROOTS = ("model-artifacts", "backup", "data", "research-data")
MODEL_EXTENSIONS = {
    ".joblib",
    ".pkl",
    ".pickle",
    ".onnx",
    ".pt",
    ".pth",
    ".h5",
    ".bin",
    ".model",
}
DATA_EXTENSIONS = {".csv", ".parquet", ".jsonl", ".json"}
IGNORED_DIRS = {".git", ".pytest_cache", "__pycache__", ".venv", "node_modules"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def walk_files(root: Path):
    for path in root.rglob("*"):
        if path.is_file() and not any(part in IGNORED_DIRS for part in path.parts):
            yield path


def classify(relative: str, path: Path) -> tuple[str, str]:
    normalized = relative.replace("\\", "/")
    if normalized.startswith("backup/"):
        return "ARCHIVE", "rollback snapshot; not loaded by runtime"
    if normalized.startswith("model-artifacts/data/customers/"):
        return "ARCHIVE", "large historical runtime snapshots; current API reads Postgres"
    if normalized.startswith("model-artifacts/shared/"):
        return "ARCHIVE", "legacy 10-model shared benchmark; current analytics endpoint serves no ML"
    if normalized.startswith("model-artifacts/benchmark-retrain/"):
        return "ARCHIVE", "synthetic benchmark outputs; no production promotion"
    if normalized.startswith("model-artifacts/historical-customer/"):
        return "ARCHIVE", "historical experiment outputs; no production promotion"
    if normalized.startswith("model-artifacts/device-v11"):
        return "ARCHIVE", "legacy device model runs; auto-training is disabled by default"
    if normalized.startswith("model-artifacts/reports/"):
        return "ARCHIVE", "generated reports derived from legacy artifacts"
    if path.suffix.lower() in MODEL_EXTENSIONS:
        return "REVIEW", "model artifact requires explicit registry reference"
    if normalized.startswith("data/canonical_reset/"):
        return "KEEP", "canonical reproducible query fixture"
    if normalized.startswith("data/operational/"):
        return "KEEP", "operational query data"
    if normalized.startswith("nextfarm_device/") or normalized.startswith("services/"):
        return "KEEP", "runtime source code"
    if normalized.startswith("scripts/") or normalized.startswith("docs/"):
        return "KEEP", "reproducibility and documentation"
    if path.suffix.lower() in DATA_EXTENSIONS:
        return "REVIEW", "data file outside canonical/operational roots"
    return "KEEP", "source/configuration or small project metadata"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve()
    records = []
    summary = {}
    for base in ARTIFACT_ROOTS:
        path = root / base
        if not path.exists():
            continue
        for item in walk_files(path):
            relative = item.relative_to(root).as_posix()
            action, reason = classify(relative, item)
            record = {
                "path": relative,
                "bytes": item.stat().st_size,
                "sha256": sha256(item),
                "action": action,
                "reason": reason,
            }
            records.append(record)
            summary.setdefault(action, {"files": 0, "bytes": 0})
            summary[action]["files"] += 1
            summary[action]["bytes"] += record["bytes"]

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "scope": "AI cleanup audit; no files deleted by this command",
        "summary": summary,
        "files": records,
    }
    (root / "docs" / "evidence").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "evidence" / "PROJECT_AUDIT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Project Audit — AI Cleanup",
        "",
        f"- Created: `{report['created_at']}`",
        "- Scope: data/artifact inventory only; no deletion performed by the audit.",
        "",
        "## Summary",
        "",
        "| Classification | Files | Size (GB) | Meaning |",
        "|---|---:|---:|---|",
    ]
    meanings = {
        "KEEP": "source, canonical data, operational fixtures",
        "ARCHIVE": "large generated data/model history moved outside active project",
        "REVIEW": "requires an explicit dependency before removal",
    }
    for action in ("KEEP", "REVIEW", "ARCHIVE"):
        value = summary.get(action, {"files": 0, "bytes": 0})
        lines.append(
            f"| `{action}` | {value['files']} | {value['bytes'] / 1024**3:.3f} | {meanings[action]} |"
        )
    lines.extend(
        [
            "",
            "## Active-runtime conclusion",
            "",
            "The current `nextfarm_device.api.analytics_app` returns `NOT_VALIDATED` and an empty prediction list. "
            "It does not load the legacy shared/device joblib registries for farmer answers.",
            "",
            "The legacy ten-model artifacts are therefore archival evidence, not production capabilities. "
            "The active product surface is deterministic data retrieval, temporal parsing, rule checks and authorization.",
            "",
            "The complete machine-readable inventory is `docs/evidence/PROJECT_AUDIT.json`.",
        ]
    )
    (root / "PROJECT_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "manifest": "docs/evidence/PROJECT_AUDIT.json"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
