from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_NAMES = {"BUILD_MANIFEST.json"}


def report_path(value: str) -> Path:
    normalized = str(value).replace("\\", "/")
    if normalized.startswith("/models/"):
        return ROOT / "model-artifacts" / normalized[len("/models/"):]
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


files = []
tree_digest = hashlib.sha256()
for path in sorted(item for item in ROOT.rglob("*") if item.is_file()):
    relative = path.relative_to(ROOT).as_posix()
    if path.name in EXCLUDED_NAMES or "__pycache__" in path.parts or path.suffix == ".pyc" or ".git" in path.parts:
        continue
    digest = sha256(path)
    size = path.stat().st_size
    files.append({"path": relative, "bytes": size, "sha256": digest})
    tree_digest.update(relative.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n")

suite = json.loads((ROOT / "model-artifacts/shared/latest_training_report.json").read_text(encoding="utf-8"))
model_artifacts = [report_path(item["artifact_path"]) for item in suite.get("models", [])]
acceptance = json.loads((ROOT / "docs/evidence/v10.1-acceptance-offline.json").read_text(encoding="utf-8"))
manifest = {
    "package": "NextFarm-AI-Support-v10.1.1-COMPLETE",
    "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "source_tree_sha256": tree_digest.hexdigest(),
    "file_count": len(files),
    "total_bytes": sum(item["bytes"] for item in files),
    "canonical_dataset_version": suite["dataset_version"],
    "model_artifact_count": len(model_artifacts),
    "model_approved_count": suite["approved_model_count"],
    "model_experimental_count": suite["experimental_model_count"],
    "model_active_count": suite.get("total_active_model_count", 0),
    "model_artifacts_exist": all(path.exists() for path in model_artifacts),
    "offline_acceptance_passed": acceptance["offline_passed"],
    "runtime_certified": bool((acceptance.get("runtime") or {}).get("certified")),
    "runtime_note": "Must be generated on the target Docker host; no runtime claim is bundled.",
    "files": files,
}
(ROOT / "BUILD_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: manifest[key] for key in ["version", "source_tree_sha256", "file_count", "total_bytes", "offline_acceptance_passed"]}, ensure_ascii=False))
