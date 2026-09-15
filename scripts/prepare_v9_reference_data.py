from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import random
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from parquet_writer import write_records

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research-data"
REFERENCE = RESEARCH / "reference"
RAW = REFERENCE / "raw"
NORMALIZED = REFERENCE / "normalized_reference.parquet"
CALIBRATION = REFERENCE / "reference_calibration.json"
BOOTSTRAP = REFERENCE / "reference_bootstrap_training.parquet"
LOCK = REFERENCE / "reference_lock.json"
PROFILE_PATH = RESEARCH / "calibration" / "v9_profiles.json"
USER_AGENT = "NextFarm-V9-Standalone/9.0 (+public research reference bootstrap)"

FIGSHARE_ARTICLE_ID = 28667981
MANDATORY_ZENODO_RECORD_IDS: list[int] = []
OPTIONAL_LARGE_ZENODO_RECORD_IDS = [18954708]
KARLY_RAW_URL = "https://raw.githubusercontent.com/felixriese/hyperspectral-soilmoisture-dataset/refs/heads/master/soilmoisture_dataset.csv"
MENDELEY_DATASETS = [("35wh56287y", 2), ("h8sfcf9487", 1)]

METRICS = ["temperature", "air_humidity", "soil_moisture", "ec", "ph", "flow_rate", "rainfall", "light"]
ALIASES = {
    "timestamp": ["timestamp", "datetime", "date_time", "created_at", "measured_at", "observed_at", "time", "date"],
    "temperature": ["temperature", "temp", "air_temperature", "air_temp", "t2m", "ambient_temperature", "greenhouse_temperature"],
    "air_humidity": ["humidity", "relative_humidity", "air_humidity", "rh", "rh2m", "ambient_humidity", "air_moisture"],
    "soil_moisture": ["soil_moisture", "substrate_moisture", "water_content", "volumetric_water_content", "vwc", "moisture_soil", "soil_water"],
    "ec": ["ec", "electrical_conductivity", "conductivity", "soil_ec", "substrate_ec"],
    "ph": ["ph", "p_h", "water_ph", "solution_ph"],
    "flow_rate": ["flow_rate", "flow", "water_flow", "irrigation_flow", "flow_lpm"],
    "rainfall": ["rain", "rainfall", "precipitation", "prectotcorr"],
    "light": ["light", "illuminance", "radiation", "solar", "par", "allsky_sfc_sw_dwn"],
}

PROFILE_INDEX = {
    "crop": {"tomato": 0, "durian": 1, "leafy_vegetable": 2, "other": 3},
    "cultivation": {"greenhouse": 0, "open_field": 1, "net_house": 2, "other": 3},
    "climate": {"highland": 0, "central_highlands": 1, "mekong_delta": 2, "other": 3},
    "soil": {"loam": 0, "basalt": 1, "alluvial": 2, "other": 3},
}

FEATURES = [
    "crop_index", "cultivation_index", "climate_index", "soil_index", "area_ha",
    "moisture_target_mid", "moisture_target_width", "ec_target_mid", "ph_target_mid",
    "zone_index", "minute_sin", "minute_cos", "day_sin", "day_cos",
    "soil_moisture", "temperature", "air_humidity", "ec", "ph", "flow_rate",
    "soil_moisture_missing", "temperature_missing", "air_humidity_missing", "ec_missing", "ph_missing", "flow_rate_missing",
    "valve_running", "pump_running", "device_online", "scheduled_irrigation",
    "minutes_since_irrigation", "sensor_age_seconds", "packet_loss_rate", "command_failure_rate",
    "moisture_delta", "temperature_delta", "humidity_delta", "ec_delta", "ph_delta", "flow_delta",
    "moisture_roll_mean", "moisture_roll_std", "flow_roll_mean", "flow_roll_std",
]
TARGETS = [
    "target_moisture_30m", "target_temperature_30m", "target_ec_30m", "target_ph_30m",
    "anomaly_label", "flow_fault_label", "irrigation_failure_label", "irrigation_need_label",
    "device_health_label", "farm_health_label",
]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")


def _match(header: str, kind: str) -> bool:
    h = _norm(header)
    for alias in ALIASES[kind]:
        a = _norm(alias)
        if h == a or (len(a) >= 4 and a in h):
            return True
    return False


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _urlopen(req: urllib.request.Request, timeout: int, attempts: int = 5):
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in {408, 425, 429, 500, 502, 503, 504} or attempt >= attempts:
                raise
            retry_after = exc.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else min(20.0, 1.5 * 2 ** (attempt - 1))
            print(f"[WAIT] HTTP {exc.code}; thử lại sau {delay:.1f}s")
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt >= attempts:
                raise
            delay = min(20.0, 1.5 * 2 ** (attempt - 1))
            print(f"[WAIT] Lỗi mạng; thử lại sau {delay:.1f}s")
            time.sleep(delay)
    assert last is not None
    raise last


def _get_json(url: str, timeout: int = 60, headers: dict[str, str] | None = None) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
    with _urlopen(req, timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download(url: str, dest: Path, timeout: int = 240, headers: dict[str, str] | None = None) -> Path:
    """Download with visible progress. Existing non-empty files are reused."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[CACHE] {dest.name} ({dest.stat().st_size / 1024 / 1024:.1f} MB)")
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    partial = dest.with_suffix(dest.suffix + ".part")
    try:
        with _urlopen(req, timeout) as resp, partial.open("wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            last_report = -1
            print(f"[GET] {dest.name}" + (f" ({total/1024/1024:.1f} MB)" if total else ""))
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                mb = int(done / (5 * 1024 * 1024))
                if mb != last_report or (total and done >= total):
                    last_report = mb
                    if total:
                        pct = min(100.0, done * 100.0 / total)
                        print(f"      {done/1024/1024:8.1f} / {total/1024/1024:.1f} MB  ({pct:5.1f}%)")
                    else:
                        print(f"      {done/1024/1024:8.1f} MB")
        if not partial.exists() or partial.stat().st_size <= 0:
            raise RuntimeError(f"File tải về rỗng: {url}")
        partial.replace(dest)
        print(f"[OK] {dest.name} sha256={_sha256(dest)[:12]}... bytes={dest.stat().st_size}")
    finally:
        partial.unlink(missing_ok=True)
    return dest


def download_karly_soil_moisture() -> dict[str, Any]:
    """Small, explicit CC-BY-4.0 soil-moisture anchor (680 CSV lines)."""
    out = RAW / "karly_soil_moisture_1227837"
    out.mkdir(parents=True, exist_ok=True)
    path = _download(KARLY_RAW_URL, out / "soilmoisture_dataset.csv", timeout=120)
    return {
        "id": "karly_soil_moisture_1227837",
        "repository": "GitHub/Zenodo",
        "record": "10.5281/zenodo.1227837",
        "license": "CC BY 4.0",
        "files": [{
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }],
    }


def download_figshare() -> dict[str, Any]:
    meta = _get_json(f"https://api.figshare.com/v2/articles/{FIGSHARE_ARTICLE_ID}")
    out = RAW / "figshare_iot_28667981"
    out.mkdir(parents=True, exist_ok=True)
    (out / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    files = []
    for item in meta.get("files", []):
        name = Path(str(item.get("name") or item.get("id") or "file.bin")).name
        url = item.get("download_url")
        if not url or Path(name).suffix.lower() != ".csv":
            continue
        path = _download(str(url), out / name)
        files.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": _sha256(path), "bytes": path.stat().st_size})
    if not files:
        raise RuntimeError("Figshare không trả CSV có thể tải.")
    return {"id": "figshare_iot_28667981", "repository": "Figshare", "record": str(FIGSHARE_ARTICLE_ID), "license": "CC0", "files": files}


def _safe_extract_reference_zip(path: Path, out: Path) -> list[Path]:
    extracted: list[Path] = []
    target_root = (out / (path.stem + "_extracted")).resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            suffix = Path(info.filename).suffix.lower()
            if suffix not in {".csv", ".txt"} or info.file_size > 100 * 1024 * 1024:
                continue
            name = Path(info.filename).name
            if not name:
                continue
            target = (target_root / name).resolve()
            if target.parent != target_root:
                continue
            with zf.open(info) as src, target.open("wb") as dst:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    dst.write(chunk)
            extracted.append(target)
    return extracted


def download_zenodo(record_id: int, *, mandatory: bool = False) -> dict[str, Any] | None:
    try:
        meta = _get_json(f"https://zenodo.org/api/records/{record_id}")
    except Exception as exc:
        if mandatory:
            raise RuntimeError(f"Zenodo {record_id} không tải được: {exc}") from exc
        print(f"[WARN] Zenodo {record_id}: {exc}")
        return None
    out = RAW / f"zenodo_{record_id}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    files: list[dict[str, Any]] = []
    for item in meta.get("files", []):
        name = Path(str(item.get("key") or "file.bin")).name
        suffix = Path(name).suffix.lower()
        size = int(item.get("size") or 0)
        if suffix not in {".csv", ".txt", ".zip"} or size > 300 * 1024 * 1024:
            continue
        url = (item.get("links") or {}).get("content") or (item.get("links") or {}).get("self")
        if not url:
            continue
        try:
            path = _download(str(url), out / name)
            files.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": _sha256(path), "bytes": path.stat().st_size, "kind": "archive" if suffix == ".zip" else "data"})
            if suffix == ".zip":
                for extracted in _safe_extract_reference_zip(path, out):
                    files.append({"path": str(extracted.relative_to(ROOT)).replace("\\", "/"), "sha256": _sha256(extracted), "bytes": extracted.stat().st_size, "kind": "extracted_data"})
        except Exception as exc:
            if mandatory:
                print(f"[WARN] Zenodo mandatory file {name}: {exc}")
            else:
                print(f"[WARN] Zenodo file {name}: {exc}")
    usable = [f for f in files if Path(str(f["path"])).suffix.lower() in {".csv", ".txt"}]
    if not usable:
        if mandatory:
            raise RuntimeError(f"Zenodo {record_id} không có CSV/TXT sử dụng được sau khi tải/giải nén.")
        return None
    return {"id": f"zenodo_{record_id}", "repository": "Zenodo", "record": str(record_id), "files": files}


def download_optional_large_zenodo() -> list[dict[str, Any]]:
    """AgriDataValue is valuable but ~1.2 GB. Opt-in so first run is deterministic and fast."""
    if os.getenv("NEXTFARM_DOWNLOAD_LARGE_REFERENCE", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        print("[INFO] Bỏ qua AgriDataValue ~1.2 GB ở first-run. Đặt NEXTFARM_DOWNLOAD_LARGE_REFERENCE=1 nếu muốn tải thêm.")
        return []
    results: list[dict[str, Any]] = []
    for rid in OPTIONAL_LARGE_ZENODO_RECORD_IDS:
        item = download_zenodo(rid, mandatory=False)
        if item:
            results.append(item)
    return results


def download_mendeley_if_token() -> list[dict[str, Any]]:
    token = os.getenv("MENDELEY_ACCESS_TOKEN", "").strip()
    if not token:
        print("[INFO] MENDELEY_ACCESS_TOKEN chưa đặt; raw Mendeley là nguồn bổ sung, bỏ qua.")
        return []
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.mendeley-public-dataset.1+json"}
    results = []
    for dataset_id, version in MENDELEY_DATASETS:
        try:
            # New Mendeley Data endpoint is preferred; legacy endpoint is retained as fallback.
            try:
                meta = _get_json(f"https://api.data.mendeley.com/datasets/{dataset_id}?version={version}", headers=headers)
            except Exception:
                meta = _get_json(f"https://api.mendeley.com/datasets/{dataset_id}?version={version}", headers=headers)
            out = RAW / "mendeley" / f"{dataset_id}_v{version}"
            out.mkdir(parents=True, exist_ok=True)
            (out / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            files = []
            for item in meta.get("files", []):
                name = Path(str(item.get("filename") or item.get("name") or "file.bin")).name
                if Path(name).suffix.lower() != ".csv":
                    continue
                details = item.get("content_details") if isinstance(item.get("content_details"), dict) else {}
                url = item.get("download_url") or details.get("download_url") or details.get("link")
                if url:
                    path = _download(str(url), out / name, headers=headers)
                    files.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": _sha256(path), "bytes": path.stat().st_size})
            if files:
                results.append({"id": f"mendeley_{dataset_id}_v{version}", "repository": "Mendeley Data", "record": dataset_id, "files": files})
        except Exception as exc:
            print(f"[WARN] Mendeley {dataset_id}: {exc}")
    return results


def download_nasa_power(year: int, profiles: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for farm_id, farm in profiles["farms"].items():
        params = {
            "parameters": "T2M,RH2M,PRECTOTCORR,ALLSKY_SFC_SW_DWN,WS2M",
            "community": "AG", "longitude": str(farm["longitude"]), "latitude": str(farm["latitude"]),
            "start": f"{year}0101", "end": f"{year}1231", "format": "CSV", "time-standard": "LST",
        }
        url = "https://power.larc.nasa.gov/api/temporal/hourly/point?" + urllib.parse.urlencode(params)
        path = _download(url, RAW / "nasa_power" / f"{farm_id}_{year}.csv")
        results.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": _sha256(path), "bytes": path.stat().st_size, "farm_id": farm_id})
    return results


def _header_index(lines: list[str]) -> int:
    for i, line in enumerate(lines[:160]):
        cells = [_norm(x) for x in re.split(r"[,;\t]", line)]
        if any(x in {"timestamp", "datetime", "date", "time", "year"} for x in cells):
            return i
    return 0


def _parse_dt(row: dict[str, str]) -> datetime | None:
    by_norm = {_norm(k): v for k, v in row.items() if k is not None}
    if {"year", "mo", "dy", "hr"}.issubset(by_norm):
        try:
            return datetime(int(float(by_norm["year"])), int(float(by_norm["mo"])), int(float(by_norm["dy"])), int(float(by_norm["hr"])), tzinfo=timezone.utc)
        except Exception:
            pass
    for key, value in row.items():
        if not key or not _match(key, "timestamp") or not str(value or "").strip():
            continue
        raw = str(value).strip()
        if raw.isdigit() and len(raw) >= 10:
            try:
                n = int(raw)
                if n > 10**12:
                    n /= 1000
                return datetime.fromtimestamp(n, tz=timezone.utc)
            except Exception:
                pass
        text = raw.replace("Z", "+00:00")
        for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
            try:
                dt = datetime.fromisoformat(text) if fmt is None else datetime.strptime(text, fmt)
                return dt.replace(tzinfo=dt.tzinfo or timezone.utc).astimezone(timezone.utc)
            except Exception:
                continue
    return None


def _metric_columns(headers: Iterable[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for header in headers:
        for metric in METRICS:
            if metric not in mapping and _match(header, metric):
                mapping[metric] = header
    return mapping


def normalize_csvs() -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    source_counts: dict[str, int] = defaultdict(int)
    use_large_zenodo = os.getenv("NEXTFARM_USE_LARGE_ZENODO_REFERENCE", "0").strip().lower() in {"1", "true", "yes", "on"}
    for path in sorted(RAW.rglob("*.csv")):
        try:
            rel_probe = path.relative_to(RAW).as_posix()
            if rel_probe.startswith("zenodo_18954708/") and not use_large_zenodo:
                continue
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            lines = text.splitlines()
            body = "\n".join(lines[_header_index(lines):])
            try:
                dialect = csv.Sniffer().sniff(body[:8192], delimiters=",;\t")
                reader = csv.DictReader(body.splitlines(), dialect=dialect)
            except csv.Error:
                reader = csv.DictReader(body.splitlines())
            headers = reader.fieldnames or []
            mapping = _metric_columns(headers)
            if not mapping:
                continue
            rel = path.relative_to(RAW)
            source_id = rel.parts[0] if rel.parts else path.parent.name
            if source_id == "mendeley" and len(rel.parts) > 1:
                source_id = f"mendeley_{rel.parts[1]}"
            for raw in reader:
                ts = _parse_dt(raw)
                if ts is None:
                    continue
                item: dict[str, Any] = {"timestamp": ts.isoformat(), "source_id": source_id, "source_file": path.name}
                valid = 0
                for metric, col in mapping.items():
                    try:
                        value = float(str(raw.get(col, "")).strip())
                    except (ValueError, TypeError):
                        continue
                    if not math.isfinite(value) or value <= -900:
                        continue
                    # Normalize only when the unit conversion is strongly inferable.
                    # Ambiguous/out-of-range values are dropped instead of forcing them
                    # into the calibration and making the simulator look artificially noisy.
                    if metric == "temperature" and 60.0 <= value <= 140.0:
                        value = (value - 32.0) * 5.0 / 9.0  # likely Fahrenheit -> Celsius
                    if metric in {"air_humidity", "soil_moisture"} and 0 <= value <= 1.2:
                        value *= 100.0
                    if metric == "ec" and value > 100:
                        value /= 1000.0  # common µS/cm -> mS/cm representation
                    bounds = {
                        "temperature": (-20.0, 65.0),
                        "air_humidity": (0.0, 100.0),
                        "soil_moisture": (0.0, 100.0),
                        "ec": (0.0, 20.0),
                        "ph": (0.0, 14.0),
                        "flow_rate": (0.0, 500.0),
                        "rainfall": (0.0, 500.0),
                        "light": (0.0, 200000.0),
                    }
                    lo, hi = bounds.get(metric, (-math.inf, math.inf))
                    if value < lo or value > hi:
                        continue
                    item[metric] = value
                    valid += 1
                if valid:
                    rows.append(item)
                    source_counts[source_id] += 1
        except Exception as exc:
            print(f"[WARN] Không đọc được {path.name}: {exc}")
    rows.sort(key=lambda x: (x["source_id"], x["timestamp"]))
    NORMALIZED.parent.mkdir(parents=True, exist_ok=True)
    normalized_fields = ["timestamp", "source_id", "source_file", *METRICS]
    normalized_schema = {"timestamp": "string", "source_id": "string", "source_file": "string", **{m: "double" for m in METRICS}}
    write_records(NORMALIZED, rows, normalized_fields, normalized_schema)
    return rows, dict(source_counts)


def _quantile(values: list[float], q: float) -> float:
    vals = sorted(values)
    if not vals:
        return 0.0
    pos = (len(vals) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    return vals[lo] if lo == hi else vals[lo] * (hi - pos) + vals[hi] * (pos - lo)


def _metric_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for metric in METRICS:
        # Keep source boundaries when calculating steps so unrelated files do not create fake jumps.
        by_source: dict[tuple[str, str], list[float]] = defaultdict(list)
        vals = []
        for r in rows:
            if metric in r:
                v = float(r[metric]); vals.append(v); by_source[(r["source_id"], r["source_file"])].append(v)
        if len(vals) < 20:
            continue
        diffs = [b-a for seq in by_source.values() for a,b in zip(seq, seq[1:])]
        mean = statistics.fmean(vals)
        var = statistics.fmean([(x-mean)**2 for x in vals]) if len(vals) > 1 else 0.0
        lag_pairs = [(a,b) for seq in by_source.values() for a,b in zip(seq,seq[1:])]
        if var > 0 and lag_pairs:
            cov = statistics.fmean([(b-mean)*(a-mean) for a,b in lag_pairs])
            ar1 = max(-0.995, min(0.995, cov/var))
        else:
            ar1 = 0.9
        abs_diffs = [abs(x) for x in diffs]
        stats[metric] = {
            "n": len(vals), "p01": _quantile(vals,.01), "p05": _quantile(vals,.05), "p25": _quantile(vals,.25),
            "median": _quantile(vals,.50), "p75": _quantile(vals,.75), "p95": _quantile(vals,.95), "p99": _quantile(vals,.99),
            "std": math.sqrt(max(var,0.0)),
            "median_abs_step": statistics.median(abs_diffs) if abs_diffs else 0.0,
            "step_p90": _quantile(abs_diffs, .90) if abs_diffs else 0.0,
            "step_p99": _quantile(abs_diffs, .99) if abs_diffs else 0.0,
            "ar1": ar1,
        }
    return stats


def build_calibration(rows: list[dict[str, Any]], source_manifest: list[dict[str, Any]]) -> dict[str, Any]:
    stats = _metric_stats(rows)
    corr: dict[str, float] = {}
    for a,b in [("temperature","air_humidity"),("ec","ph"),("soil_moisture","ec"),("rainfall","soil_moisture")]:
        xy=[(float(r[a]),float(r[b])) for r in rows if a in r and b in r]
        if len(xy)<30:
            continue
        xs,ys=[x for x,_ in xy],[y for _,y in xy]; mx,my=statistics.fmean(xs),statistics.fmean(ys)
        sx=math.sqrt(statistics.fmean([(x-mx)**2 for x in xs])); sy=math.sqrt(statistics.fmean([(y-my)**2 for y in ys]))
        if sx>0 and sy>0:
            corr[f"{a}__{b}"]=statistics.fmean([(x-mx)*(y-my) for x,y in xy])/(sx*sy)
    calibration={
        "version":"v9-reference-calibration-1", "created_at":datetime.now(timezone.utc).isoformat(),
        "normalized_rows":len(rows), "metrics":stats, "correlations":corr, "sources":source_manifest,
        "policy":{"raw_reference_is_not_nextfarm_telemetry":True,"simulation_must_be_anchored_to_reference_quantiles":True,"no_silent_synthetic_fallback":True},
    }
    CALIBRATION.write_text(json.dumps(calibration,ensure_ascii=False,indent=2),encoding="utf-8")
    return calibration


def _clip(x: float, lo: float, hi: float) -> float:
    return min(hi,max(lo,x))


def _median(cal: dict[str,Any], metric: str, fallback: float) -> float:
    return float(cal.get("metrics",{}).get(metric,{}).get("median",fallback))


def _spread(cal: dict[str,Any], metric: str, fallback: float) -> float:
    s=cal.get("metrics",{}).get(metric,{})
    return max(float(s.get("p95",fallback))-float(s.get("p05",fallback)), fallback*.1 if fallback else .1)


def _empirical_step(cal: dict[str, Any], metric: str, fallback: float) -> float:
    s = cal.get("metrics", {}).get(metric, {})
    return max(0.0, float(s.get("median_abs_step", fallback)))


def _empirical_ar1(cal: dict[str, Any], metric: str, fallback: float = 0.9) -> float:
    s = cal.get("metrics", {}).get(metric, {})
    return _clip(float(s.get("ar1", fallback)), -0.995, 0.995)


def _profile_features(farm: dict[str,Any]) -> dict[str,float]:
    moist_min,moist_max=float(farm["soil"]["dry_floor"]),float(farm["soil"]["field_capacity"])
    ec_min,ec_max=float(farm["nutrition"]["ec_min"]),float(farm["nutrition"]["ec_max"])
    return {
        "crop_index":float(PROFILE_INDEX["crop"].get(farm["crop"],3)),
        "cultivation_index":float(PROFILE_INDEX["cultivation"].get(farm["cultivation"],3)),
        "climate_index":float(PROFILE_INDEX["climate"].get(farm.get("climate_region","other"),3)),
        "soil_index":float(PROFILE_INDEX["soil"].get(farm.get("soil_type","other"),3)),
        "area_ha":float(farm.get("area_ha",1.0)),
        "moisture_target_mid":float(farm["soil"]["moisture_target"]),
        "moisture_target_width":max(5.0,moist_max-moist_min),
        "ec_target_mid":(ec_min+ec_max)/2,
        "ph_target_mid":float(farm["nutrition"]["ph_target"]),
    }


def build_reference_bootstrap(cal: dict[str,Any], profiles: dict[str,Any], days: int=14, step_minutes: int=15) -> int:
    """Build model-ready sequences derived from the downloaded static reference calibration.

    These rows are never inserted into sensor_readings and never represented as real device data.
    """
    rng=random.Random(20260811); start=datetime(2026,1,1,tzinfo=timezone.utc); steps=int(days*24*60/step_minutes)
    temp_ref=_median(cal,"temperature",26); rh_ref=_median(cal,"air_humidity",72); soil_ref=_median(cal,"soil_moisture",58)
    ec_ref=_median(cal,"ec",1.7); ph_ref=_median(cal,"ph",6.2)
    temp_spread=min(15,max(3,_spread(cal,"temperature",8))); rh_spread=min(45,max(8,_spread(cal,"air_humidity",25)))
    soil_spread=min(55,max(8,_spread(cal,"soil_moisture",25))); ec_spread=min(5,max(.25,_spread(cal,"ec",1.5))); ph_spread=min(5,max(.2,_spread(cal,"ph",1)))
    temp_step=max(.004,min(.20,_empirical_step(cal,"temperature",.02))); rh_step=max(.01,min(.8,_empirical_step(cal,"air_humidity",.10)))
    soil_step=max(.005,min(.5,_empirical_step(cal,"soil_moisture",.03))); ec_step=max(.0003,min(.04,_empirical_step(cal,"ec",.002))); ph_step=max(.0003,min(.03,_empirical_step(cal,"ph",.002)))
    temp_alpha=_clip(1.0-_empirical_ar1(cal,"temperature",.90),.025,.22); rh_alpha=_clip(1.0-_empirical_ar1(cal,"air_humidity",.90),.025,.22)
    ec_alpha=_clip(1.0-_empirical_ar1(cal,"ec",.97),.008,.08); ph_alpha=_clip(1.0-_empirical_ar1(cal,"ph",.985),.004,.05)
    corr=float(cal.get("correlations",{}).get("temperature__air_humidity",-.55)); corr=_clip(corr,-.95,.95)
    raw_rows=[]
    for farm_i,(farm_id,farm) in enumerate(profiles["farms"].items()):
        pf=_profile_features(farm)
        for zone_i,zone in enumerate(("A","B","C")):
            temp=.45*temp_ref+.55*float(farm["climate"]["temp_mean"])+zone_i*.15
            rh=.45*rh_ref+.55*float(farm["climate"]["rh_mean"])-zone_i*.4
            soil=.35*soil_ref+.65*float(farm["soil"]["moisture_target"])+(zone_i-1)*.8
            ec=.35*ec_ref+.65*float(farm["nutrition"]["ec_target"]); ph=.35*ph_ref+.65*float(farm["nutrition"]["ph_target"])
            last_irrigation=start-timedelta(hours=8)
            for i in range(steps):
                ts=start+timedelta(minutes=i*step_minutes); local_hour=(ts.hour+7)%24+ts.minute/60
                solar=0.0 if local_hour<5.5 or local_hour>18.5 else max(0.0,math.sin(math.pi*(local_hour-5.5)/13))
                scheduled=int(any(int(h)==int(local_hour) for h in farm["irrigation"]["hours"]) and ts.minute<int(farm["irrigation"]["duration_minutes"]))
                if soil<float(farm["irrigation"]["threshold_trigger"]) and ts.minute<10: scheduled=1
                cycle=(i+farm_i*37+zone_i*19)%960; fault=None
                if 180<=cycle<186: fault="no_flow"; scheduled=1
                elif 420<=cycle<427: fault="leak"; scheduled=0
                elif 660<=cycle<665: fault="offline"
                elif 810<=cycle<820: fault="drift"
                if 90<=cycle<98 and not scheduled:
                    soil=min(soil,float(farm["soil"]["dry_floor"])+.2*(float(farm["soil"]["moisture_target"])-float(farm["soil"]["dry_floor"])))
                e1,e2=rng.gauss(0,1),rng.gauss(0,1)
                temp_target=float(farm["climate"]["temp_mean"])+float(farm["climate"]["temp_amp"])*(solar-.32)
                temp+=temp_alpha*(temp_target-temp)+temp_step*.55*e1
                rh_target=float(farm["climate"]["rh_mean"])-float(farm["climate"]["rh_amp"])*solar
                rh+=rh_alpha*(rh_target-rh)+rh_step*.55*(corr*e1+math.sqrt(max(0,1-corr*corr))*e2); rh=_clip(rh,30,99)
                nominal=float(farm["irrigation"]["flow_lpm"])*(1+.025*(zone_i-1))
                online=0 if fault=="offline" else 1
                if not online: flow=0.0
                elif scheduled and fault=="no_flow": flow=max(0,rng.gauss(.2,.08))
                elif not scheduled and fault=="leak": flow=max(1,rng.gauss(nominal*.2,.25))
                elif scheduled: flow=max(0,rng.gauss(nominal,nominal*.02))
                else: flow=max(0,rng.gauss(.03,.02))
                if scheduled and flow>1:
                    last_irrigation=ts; soil+=float(farm["soil"]["irrigation_gain_per_min"])*step_minutes*min(1.2,flow/max(nominal,.1))
                evap=float(farm["soil"]["evap_per_hour"])*(.35+.95*solar)*(1.15-rh/130)*(step_minutes/60)
                soil-=evap
                if soil>float(farm["soil"]["moisture_target"]):
                    soil-=float(farm["soil"]["drain_per_hour"])*(step_minutes/60)*(soil-float(farm["soil"]["moisture_target"]))/10
                soil+=rng.gauss(0,min(.08,soil_step*.35)); soil=_clip(soil,float(farm["soil"]["dry_floor"]),float(farm["soil"]["field_capacity"]))
                ec_target=float(farm["nutrition"]["ec_target"])+float(farm["nutrition"]["ec_moisture_coupling"])*(soil-float(farm["soil"]["moisture_target"]))/18
                ec+=ec_alpha*(ec_target-ec)+rng.gauss(0,min(.006,ec_step*.45)); ph+=ph_alpha*(float(farm["nutrition"]["ph_target"])-ph)+rng.gauss(0,min(.008,ph_step*.35))
                if fault=="drift": ph+=.015
                ec=_clip(ec,max(.15,float(farm["nutrition"]["ec_min"])*.65),float(farm["nutrition"]["ec_max"])*1.35); ph=_clip(ph,4.2,8.2)
                minute=ts.hour*60+ts.minute
                raw_rows.append({
                    "farm_id":farm_id,"farm_name":farm["name"],"zone_code":zone,"observed_at":ts.isoformat(),**pf,
                    "zone_index":float(zone_i),"minute_sin":math.sin(2*math.pi*minute/1440),"minute_cos":math.cos(2*math.pi*minute/1440),"day_sin":math.sin(2*math.pi*ts.weekday()/7),"day_cos":math.cos(2*math.pi*ts.weekday()/7),
                    "soil_moisture":soil,"temperature":temp,"air_humidity":rh,"ec":ec,"ph":ph,"flow_rate":flow,
                    "soil_moisture_missing":0,"temperature_missing":0,"air_humidity_missing":0,"ec_missing":0,"ph_missing":0,"flow_rate_missing":0,
                    "valve_running":scheduled,"pump_running":scheduled,"device_online":online,"scheduled_irrigation":scheduled,
                    "minutes_since_irrigation":max(0,(ts-last_irrigation).total_seconds()/60),"sensor_age_seconds":0.0,
                    "packet_loss_rate":.65 if fault=="offline" else (.08 if fault else .01),"command_failure_rate":1.0 if scheduled and fault in {"offline","no_flow"} else 0.0,"_fault":fault,
                })
    grouped=defaultdict(list)
    for r in raw_rows: grouped[(r["farm_id"],r["zone_code"])].append(r)
    output=[]; horizon=max(1,round(30/step_minutes))
    for group in grouped.values():
        mwin=deque(maxlen=8); fwin=deque(maxlen=8); prev=None
        for idx,r in enumerate(group):
            mwin.append(float(r["soil_moisture"])); fwin.append(float(r["flow_rate"]))
            vals=[0]*6 if prev is None else [r[m]-prev[m] for m in ("soil_moisture","temperature","air_humidity","ec","ph","flow_rate")]
            for name,val in zip(("moisture_delta","temperature_delta","humidity_delta","ec_delta","ph_delta","flow_delta"),vals): r[name]=val
            r["moisture_roll_mean"]=statistics.fmean(mwin); r["moisture_roll_std"]=statistics.pstdev(mwin) if len(mwin)>1 else 0
            r["flow_roll_mean"]=statistics.fmean(fwin); r["flow_roll_std"]=statistics.pstdev(fwin) if len(fwin)>1 else 0
            if idx+horizon>=len(group): continue
            future=group[idx+horizon]
            r["target_moisture_30m"]=future["soil_moisture"]; r["target_temperature_30m"]=future["temperature"]; r["target_ec_30m"]=future["ec"]; r["target_ph_30m"]=future["ph"]
            flow=float(r["flow_rate"]); scheduled=bool(r["scheduled_irrigation"]); offline=int(r["device_online"])==0
            r["flow_fault_label"]=1 if scheduled and flow<1 else (2 if not scheduled and flow>1.5 else 0)
            r["irrigation_failure_label"]=int(scheduled and (flow<1 or offline or r["command_failure_rate"]>.3))
            moisture_min=float(r["moisture_target_mid"]-r["moisture_target_width"]/2); r["irrigation_need_label"]=int(r["soil_moisture"]<moisture_min and not scheduled)
            r["anomaly_label"]=int(r["moisture_roll_std"]>6 or r["flow_roll_std"]>3 or offline or r["_fault"] in {"drift","leak","no_flow"})
            r["device_health_label"]=2 if offline or r["packet_loss_rate"]>.5 else (1 if r["packet_loss_rate"]>.15 else 0)
            r["farm_health_label"]=2 if (r["irrigation_failure_label"] or r["flow_fault_label"] or r["device_health_label"]==2) else (1 if (r["anomaly_label"] or r["irrigation_need_label"] or r["device_health_label"]==1) else 0)
            r.pop("_fault",None); output.append(r.copy()); prev=r
    BOOTSTRAP.parent.mkdir(parents=True,exist_ok=True)
    fields=["farm_id","farm_name","zone_code","observed_at",*FEATURES,*TARGETS]
    bootstrap_schema = {k: ("string" if k in {"farm_id","farm_name","zone_code","observed_at"} else "double") for k in fields}
    for k in TARGETS:
        if k.endswith("_label"):
            bootstrap_schema[k] = "int64"
    write_records(BOOTSTRAP, output, fields, bootstrap_schema)
    return len(output)


def main() -> int:
    print("NextFarm V9 - tạo static reference pack mới; không đọc database/version dự án nào khác.")
    profiles=json.loads(PROFILE_PATH.read_text(encoding="utf-8")); REFERENCE.mkdir(parents=True,exist_ok=True)
    sources=[]
    try:
        sources.append(download_figshare())
    except Exception as exc:
        print(f"[ERROR] Không tải được nguồn bắt buộc Figshare: {exc}")
        print("V9 dừng thay vì tự bịa static reference."); return 2
    try:
        sources.append(download_karly_soil_moisture())
    except Exception as exc:
        print(f"[ERROR] Không tải được soil-moisture anchor KarLy bắt buộc: {exc}")
        print("V9 dừng thay vì tự bịa soil-moisture reference.")
        return 2
    sources.extend(download_optional_large_zenodo())
    sources.extend(download_mendeley_if_token())
    try:
        nasa=download_nasa_power(2025,profiles); sources.append({"id":"nasa_power_2025","repository":"NASA POWER","record":"hourly point API","files":nasa})
    except Exception as exc:
        print(f"[ERROR] Không tải được NASA POWER bắt buộc cho baseline khí hậu từng vườn: {exc}")
        print("V9 dừng thay vì dùng profile khí hậu không có reference theo vị trí.")
        return 2
    rows,source_counts=normalize_csvs(); metric_counts={m:sum(1 for r in rows if m in r) for m in METRICS}
    required={"temperature":5000,"air_humidity":5000,"soil_moisture":500,"ec":5000,"ph":5000}
    insufficient={m:{"got":metric_counts.get(m,0),"need":n} for m,n in required.items() if metric_counts.get(m,0)<n}
    if len(rows)<10000 or insufficient:
        print(f"[ERROR] Static reference chưa đủ: rows={len(rows)}, metrics={metric_counts}, insufficient={insufficient}")
        print("V9 dừng; không có random fallback."); return 3
    calibration=build_calibration(rows,sources); bootstrap_rows=build_reference_bootstrap(calibration,profiles)
    lock={
        "version":"9.0.1","created_at":datetime.now(timezone.utc).isoformat(),"normalized_reference_rows":len(rows),"reference_source_counts":source_counts,"metric_counts":metric_counts,"bootstrap_training_rows":bootstrap_rows,
        "normalized_sha256":_sha256(NORMALIZED),"calibration_sha256":_sha256(CALIBRATION),"bootstrap_sha256":_sha256(BOOTSTRAP),
        "policy":{"uses_prior_project_data":False,"uses_external_project_database":False,"reference_role":"downloaded_static_reference","bootstrap_role":"derived_reference_training_not_device_telemetry","runtime_role":"simulated_device_calibrated_v9_after_bootstrap"},"sources":sources,
    }
    LOCK.write_text(json.dumps(lock,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"[OK] normalized_reference_rows={len(rows):,}"); print(f"[OK] reference_bootstrap_training_rows={bootstrap_rows:,}"); print(f"[OK] {LOCK.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
