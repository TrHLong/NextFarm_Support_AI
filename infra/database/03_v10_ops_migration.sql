-- NextFarm V10 foundation migration.
-- Idempotent: safe for a fresh database and an existing V9 volume.
\set ON_ERROR_STOP on

BEGIN;

CREATE SCHEMA IF NOT EXISTS ops_db;

CREATE TABLE IF NOT EXISTS user_db.external_identities (
  external_identity_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL CHECK (provider IN ('zalo_oa','nextfarm','web','mobile','partner_api')),
  external_subject TEXT NOT NULL,
  user_id TEXT NOT NULL REFERENCES user_db.users(user_id) ON DELETE CASCADE,
  tenant_ref TEXT,
  verified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_at TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (provider, external_subject)
);
CREATE INDEX IF NOT EXISTS idx_external_identities_user
  ON user_db.external_identities(user_id) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS farm_db.control_commands (
  command_id TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  requested_by TEXT NOT NULL REFERENCES user_db.users(user_id),
  farm_id TEXT NOT NULL REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  zone_id TEXT REFERENCES farm_db.zones(zone_id),
  device_id TEXT REFERENCES farm_db.devices(device_id),
  port_id TEXT REFERENCES farm_db.device_ports(port_id),
  command_type TEXT NOT NULL,
  parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_channel TEXT NOT NULL DEFAULT 'chatbot',
  status TEXT NOT NULL DEFAULT 'pending_confirmation'
    CHECK (status IN ('pending_confirmation','confirmed','rejected','sent','executed','failed','expired')),
  confirmation_required BOOLEAN NOT NULL DEFAULT true,
  confirmed_by TEXT REFERENCES user_db.users(user_id),
  requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  confirmed_at TIMESTAMPTZ,
  executed_at TIMESTAMPTZ,
  result JSONB,
  error_message TEXT,
  correlation_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_control_commands_farm_time
  ON farm_db.control_commands(farm_id, requested_at DESC);

ALTER TABLE support_db.chat_messages ADD COLUMN IF NOT EXISTS client_message_id TEXT;
ALTER TABLE support_db.chat_messages ADD COLUMN IF NOT EXISTS delivery_status TEXT NOT NULL DEFAULT 'saved';
ALTER TABLE support_db.chat_messages DROP CONSTRAINT IF EXISTS chat_messages_delivery_status_check;
ALTER TABLE support_db.chat_messages
  ADD CONSTRAINT chat_messages_delivery_status_check CHECK (delivery_status IN ('saved','delivered','failed'));
DROP INDEX IF EXISTS support_db.uq_chat_messages_client_message;
CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_client_message
  ON support_db.chat_messages(conversation_id,client_message_id) WHERE client_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation_time
  ON support_db.chat_messages(conversation_id, created_at, message_id);

ALTER TABLE farm_db.sensor_readings DROP CONSTRAINT IF EXISTS sensor_readings_data_origin_check;
ALTER TABLE farm_db.sensor_readings
  ADD CONSTRAINT sensor_readings_data_origin_check
  CHECK (data_origin IN (
    'simulated_device_calibrated_v9','nextfarm_api','nextfarm_mqtt','manual_import','partner_api'
  ));

CREATE TABLE IF NOT EXISTS ops_db.daily_data_reports (
  report_date DATE NOT NULL,
  farm_id TEXT NOT NULL REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  data_group TEXT NOT NULL,
  row_count BIGINT NOT NULL DEFAULT 0 CHECK (row_count >= 0),
  accepted_count BIGINT NOT NULL DEFAULT 0 CHECK (accepted_count >= 0),
  duplicate_count BIGINT NOT NULL DEFAULT 0 CHECK (duplicate_count >= 0),
  rejected_count BIGINT NOT NULL DEFAULT 0 CHECK (rejected_count >= 0),
  oldest_observed_at TIMESTAMPTZ,
  newest_observed_at TIMESTAMPTZ,
  freshness_seconds NUMERIC(14,2),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (report_date, farm_id, data_group)
);
CREATE INDEX IF NOT EXISTS idx_daily_data_reports_farm_date
  ON ops_db.daily_data_reports(farm_id, report_date DESC);

CREATE TABLE IF NOT EXISTS ops_db.ingest_attempts (
  attempt_id BIGSERIAL PRIMARY KEY,
  packet_id TEXT,
  farm_id TEXT,
  data_origin TEXT,
  transport TEXT NOT NULL DEFAULT 'mqtt',
  status TEXT NOT NULL CHECK (status IN ('accepted','duplicate','rejected','error')),
  row_count INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0),
  latency_ms NUMERIC(14,3),
  error_message TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ingest_attempts_farm_time
  ON ops_db.ingest_attempts(farm_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingest_attempts_status_time
  ON ops_db.ingest_attempts(status, received_at DESC);

CREATE TABLE IF NOT EXISTS ops_db.pipeline_alerts (
  alert_id BIGSERIAL PRIMARY KEY,
  farm_id TEXT REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  data_group TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
  alert_code TEXT NOT NULL,
  message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved')),
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_pipeline_alerts_open
  ON ops_db.pipeline_alerts(status, severity, detected_at DESC);

CREATE TABLE IF NOT EXISTS ops_db.backup_runs (
  backup_id TEXT PRIMARY KEY,
  backup_type TEXT NOT NULL CHECK (backup_type IN ('manual','scheduled')),
  status TEXT NOT NULL CHECK (status IN ('started','completed','failed','verified')),
  artifact_path TEXT NOT NULL,
  size_bytes BIGINT,
  checksum_sha256 TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  verified_at TIMESTAMPTZ,
  error_message TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

COMMIT;
