-- NextFarm V10.1 acceptance hardening.
-- Idempotent for both new installations and existing V10 volumes.
\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE farm_db.sensor_readings
  ADD COLUMN IF NOT EXISTS received_at TIMESTAMPTZ NOT NULL DEFAULT now();

UPDATE farm_db.sensor_readings
SET received_at = created_at
WHERE received_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_reading_received
  ON farm_db.sensor_readings(farm_id, received_at DESC);

ALTER TABLE farm_db.sensors DROP CONSTRAINT IF EXISTS sensors_metric_type_check;
ALTER TABLE farm_db.sensors
  ADD CONSTRAINT sensors_metric_type_check
  CHECK (metric_type IN ('soil_moisture','air_humidity','temperature','ec','ph','flow_rate'));

ALTER TABLE knowledge_db.retrieval_audits
  ADD COLUMN IF NOT EXISTS threshold_version TEXT NOT NULL DEFAULT 'v10.1-calibrated';

CREATE TABLE IF NOT EXISTS ops_db.acceptance_runs (
  run_id TEXT PRIMARY KEY,
  build_version TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  benchmark_version TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  passed BOOLEAN,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  artifact_path TEXT,
  checksum_sha256 TEXT
);

COMMIT;
