from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


FILES = {
    Path("model-artifacts/shared/training_dataset.parquet"): "nextfarm-v10.1-training",
    Path("research-data/reference/reference_bootstrap_training.parquet"): "nextfarm-v10.1-reference-bootstrap",
    Path("research-data/reference/normalized_reference.parquet"): "nextfarm-v10.1-normalized-reference",
}


def normalize(path: Path, dataset_id: str) -> None:
    source_checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    frame = pd.read_parquet(path, engine="pyarrow")
    for column in [name for name in frame.columns if name in {"observed_at", "timestamp", "measured_at", "received_at"}]:
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="raise")
    if "synthetic" not in frame.columns:
        frame["synthetic"] = "bootstrap" in dataset_id or "training" in dataset_id
    if "generator_version" not in frame.columns:
        frame["generator_version"] = "v10.1-normalizer"
    if "scenario_id" not in frame.columns and "training" in dataset_id:
        frame["scenario_id"] = "packaged_training"
    if "scenario_tag" not in frame.columns and "training" in dataset_id:
        frame["scenario_tag"] = "reference_blend"
    table = pa.Table.from_pandas(frame, preserve_index=False)
    meta = dict(table.schema.metadata or {})
    meta.update({
        b"dataset_id": dataset_id.encode(), b"schema_version": b"10.1.0",
        b"source_checksum_sha256": source_checksum.encode(), b"normalized_at": b"2026-09-04T00:00:00Z",
        b"provenance_policy": b"row_fields_plus_parquet_metadata",
    })
    pq.write_table(table.replace_schema_metadata(meta), path, compression="zstd", use_dictionary=True)


if __name__ == "__main__":
    for parquet_path, identifier in FILES.items():
        normalize(parquet_path, identifier)
        print(f"normalized {parquet_path}")
