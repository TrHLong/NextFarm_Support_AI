-- NextFarm AI Support - Bài toán B
-- Các cơ sở dữ liệu logic được triển khai dưới dạng schema PostgreSQL
-- để PoC dễ chạy bằng một container nhưng vẫn tách biệt trách nhiệm.

CREATE SCHEMA IF NOT EXISTS user_db;
CREATE SCHEMA IF NOT EXISTS farm_db;
CREATE SCHEMA IF NOT EXISTS knowledge_db;
CREATE SCHEMA IF NOT EXISTS support_db;
CREATE SCHEMA IF NOT EXISTS ops_db;

-- ============================================================
-- 1) USER DB: tài khoản, vai trò, phân quyền vườn
-- ============================================================
CREATE TABLE IF NOT EXISTS user_db.users (
  user_id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name TEXT NOT NULL,
  phone TEXT UNIQUE,
  email TEXT,
  role TEXT NOT NULL CHECK (role IN ('farmer','technician')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_db.farm_access (
  user_id TEXT NOT NULL REFERENCES user_db.users(user_id) ON DELETE CASCADE,
  farm_id TEXT NOT NULL,
  access_role TEXT NOT NULL CHECK (access_role IN ('owner','technician')),
  can_read BOOLEAN NOT NULL DEFAULT true,
  can_support BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, farm_id)
);

-- Ánh xạ danh tính từ kênh ngoài (Zalo OA, ứng dụng NextFarm, API đối tác)
-- vào tài khoản nội bộ. Chatbot chỉ được phép dùng farm_access sau khi ánh xạ
-- đã được xác minh; không suy đoán "vườn của tôi" từ tên hiển thị.
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

-- ============================================================
-- 2) FARM DB: hồ sơ vườn và dữ liệu IoT
-- ============================================================
CREATE TABLE IF NOT EXISTS farm_db.farms (
  farm_id TEXT PRIMARY KEY,
  owner_user_id TEXT NOT NULL REFERENCES user_db.users(user_id),
  farm_name TEXT NOT NULL,
  crop_name TEXT NOT NULL,
  region TEXT NOT NULL,
  address TEXT,
  area_ha NUMERIC(10,2),
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS farm_db.zones (
  zone_id TEXT PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  zone_code TEXT NOT NULL,
  zone_name TEXT NOT NULL,
  crop_name TEXT,
  area_ha NUMERIC(10,2),
  moisture_min NUMERIC(6,2),
  moisture_max NUMERIC(6,2),
  ec_min NUMERIC(8,2),
  ec_max NUMERIC(8,2),
  ph_min NUMERIC(6,2),
  ph_max NUMERIC(6,2),
  UNIQUE (farm_id, zone_code)
);

CREATE TABLE IF NOT EXISTS farm_db.devices (
  device_id TEXT PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  zone_id TEXT REFERENCES farm_db.zones(zone_id),
  device_name TEXT NOT NULL,
  device_type TEXT NOT NULL CHECK (device_type IN ('controller','sensor_gateway','weather_station')),
  model_name TEXT,
  firmware_version TEXT,
  connectivity TEXT CHECK (connectivity IN ('wifi','ethernet','cellular','unknown')),
  installed_at TIMESTAMPTZ,
  active BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS farm_db.device_ports (
  port_id TEXT PRIMARY KEY,
  device_id TEXT NOT NULL REFERENCES farm_db.devices(device_id) ON DELETE CASCADE,
  zone_id TEXT REFERENCES farm_db.zones(zone_id),
  port_number INTEGER NOT NULL,
  port_name TEXT NOT NULL,
  port_type TEXT NOT NULL CHECK (port_type IN ('valve','pump','fertilizer_valve','relay')),
  UNIQUE (device_id, port_number)
);

CREATE TABLE IF NOT EXISTS farm_db.sensors (
  sensor_id TEXT PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  zone_id TEXT REFERENCES farm_db.zones(zone_id),
  device_id TEXT REFERENCES farm_db.devices(device_id),
  sensor_name TEXT NOT NULL,
  metric_type TEXT NOT NULL CHECK (metric_type IN ('soil_moisture','air_humidity','temperature','ec','ph','flow_rate')),
  unit TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS farm_db.sensor_readings (
  reading_id BIGSERIAL PRIMARY KEY,
  sensor_id TEXT NOT NULL REFERENCES farm_db.sensors(sensor_id) ON DELETE CASCADE,
  farm_id TEXT NOT NULL REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  zone_id TEXT REFERENCES farm_db.zones(zone_id),
  metric_type TEXT NOT NULL,
  value NUMERIC(14,3) NOT NULL,
  unit TEXT NOT NULL,
  quality TEXT NOT NULL DEFAULT 'good' CHECK (quality IN ('good','suspect','bad')),
  observed_at TIMESTAMPTZ NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_reading_lookup
  ON farm_db.sensor_readings(farm_id, zone_id, metric_type, observed_at DESC);

CREATE TABLE IF NOT EXISTS farm_db.device_status (
  status_id BIGSERIAL PRIMARY KEY,
  device_id TEXT NOT NULL REFERENCES farm_db.devices(device_id) ON DELETE CASCADE,
  port_id TEXT REFERENCES farm_db.device_ports(port_id) ON DELETE CASCADE,
  online BOOLEAN NOT NULL,
  running BOOLEAN,
  last_seen_at TIMESTAMPTZ NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_device_status_lookup
  ON farm_db.device_status(device_id, port_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS farm_db.irrigation_schedules (
  schedule_id TEXT PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  zone_id TEXT REFERENCES farm_db.zones(zone_id),
  port_id TEXT REFERENCES farm_db.device_ports(port_id),
  schedule_name TEXT NOT NULL,
  start_time TIME NOT NULL,
  duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
  days_of_week TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS farm_db.irrigation_runs (
  run_id TEXT PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  zone_id TEXT REFERENCES farm_db.zones(zone_id),
  port_id TEXT REFERENCES farm_db.device_ports(port_id),
  started_at TIMESTAMPTZ NOT NULL,
  ended_at TIMESTAMPTZ,
  duration_minutes NUMERIC(10,2),
  water_liters NUMERIC(12,2),
  result TEXT NOT NULL CHECK (result IN ('success','failed','running','cancelled')),
  source TEXT NOT NULL DEFAULT 'schedule'
);

CREATE TABLE IF NOT EXISTS farm_db.alerts (
  alert_id TEXT PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  zone_id TEXT REFERENCES farm_db.zones(zone_id),
  device_id TEXT REFERENCES farm_db.devices(device_id),
  alert_type TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('low','medium','high','urgent')),
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved')),
  suggested_checklist_code TEXT,
  detected_at TIMESTAMPTZ NOT NULL,
  resolved_at TIMESTAMPTZ
);

-- Nhật ký lệnh là phần bắt buộc trước khi bật điều khiển thật. PoC hiện chỉ
-- tạo/audit yêu cầu; firmware vẫn là lớp quyết định an toàn cuối cùng.
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

-- ============================================================
-- 3) KNOWLEDGE DB: tài liệu, checklist, ca đã giải quyết
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge_db.articles (
  article_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  body_vi TEXT NOT NULL,
  keywords TEXT NOT NULL DEFAULT '',
  source_name TEXT NOT NULL DEFAULT 'NextFarm nội bộ',
  version TEXT NOT NULL DEFAULT '1.0',
  approved_by TEXT,
  active BOOLEAN NOT NULL DEFAULT true,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_db.checklists (
  checklist_code TEXT PRIMARY KEY,
  category TEXT NOT NULL,
  title TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS knowledge_db.checklist_items (
  item_id TEXT PRIMARY KEY,
  checklist_code TEXT NOT NULL REFERENCES knowledge_db.checklists(checklist_code) ON DELETE CASCADE,
  item_order INTEGER NOT NULL,
  instruction TEXT NOT NULL,
  UNIQUE (checklist_code, item_order)
);

CREATE TABLE IF NOT EXISTS knowledge_db.resolved_cases (
  case_id TEXT PRIMARY KEY,
  source_ticket_id TEXT,
  category TEXT NOT NULL,
  title TEXT NOT NULL,
  symptoms TEXT NOT NULL,
  root_cause TEXT NOT NULL,
  resolution TEXT NOT NULL,
  keywords TEXT NOT NULL DEFAULT '',
  reusable BOOLEAN NOT NULL DEFAULT true,
  reviewed_by TEXT REFERENCES user_db.users(user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 4) SUPPORT DB: hội thoại, ticket, phản hồi, cảnh báo cho khách
-- ============================================================
CREATE TABLE IF NOT EXISTS support_db.conversations (
  conversation_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES user_db.users(user_id),
  farm_id TEXT REFERENCES farm_db.farms(farm_id),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_message_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS support_db.chat_messages (
  message_id BIGSERIAL PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES support_db.conversations(conversation_id) ON DELETE CASCADE,
  sender_type TEXT NOT NULL CHECK (sender_type IN ('farmer','bot','technician','system')),
  sender_id TEXT REFERENCES user_db.users(user_id),
  content TEXT NOT NULL,
  intent TEXT,
  grounded BOOLEAN,
  tool_name TEXT,
  tool_payload JSONB,
  client_message_id TEXT,
  delivery_status TEXT NOT NULL DEFAULT 'saved'
    CHECK (delivery_status IN ('saved','delivered','failed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_client_message
  ON support_db.chat_messages(conversation_id,client_message_id) WHERE client_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation_time
  ON support_db.chat_messages(conversation_id, created_at, message_id);

CREATE TABLE IF NOT EXISTS support_db.tickets (
  ticket_id TEXT PRIMARY KEY,
  requester_id TEXT NOT NULL REFERENCES user_db.users(user_id),
  farm_id TEXT NOT NULL REFERENCES farm_db.farms(farm_id),
  zone_id TEXT REFERENCES farm_db.zones(zone_id),
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  category TEXT NOT NULL,
  priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','urgent')),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','waiting_customer','resolved','closed','reopened')),
  assigned_to TEXT REFERENCES user_db.users(user_id),
  source TEXT NOT NULL DEFAULT 'chatbot' CHECK (source IN ('chatbot','farmer_web','technician')),
  first_response_at TIMESTAMPTZ,
  resolved_at TIMESTAMPTZ,
  closed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ticket_queue
  ON support_db.tickets(status, priority, created_at);

CREATE TABLE IF NOT EXISTS support_db.ticket_messages (
  ticket_message_id BIGSERIAL PRIMARY KEY,
  ticket_id TEXT NOT NULL REFERENCES support_db.tickets(ticket_id) ON DELETE CASCADE,
  sender_id TEXT NOT NULL REFERENCES user_db.users(user_id),
  message_type TEXT NOT NULL DEFAULT 'message' CHECK (message_type IN ('message','warning','system')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS support_db.ticket_events (
  event_id BIGSERIAL PRIMARY KEY,
  ticket_id TEXT NOT NULL REFERENCES support_db.tickets(ticket_id) ON DELETE CASCADE,
  actor_id TEXT REFERENCES user_db.users(user_id),
  event_type TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT,
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS support_db.ticket_checklist_results (
  result_id BIGSERIAL PRIMARY KEY,
  ticket_id TEXT NOT NULL REFERENCES support_db.tickets(ticket_id) ON DELETE CASCADE,
  checklist_item_id TEXT NOT NULL REFERENCES knowledge_db.checklist_items(item_id),
  completed BOOLEAN NOT NULL DEFAULT false,
  completed_by TEXT REFERENCES user_db.users(user_id),
  completed_at TIMESTAMPTZ,
  note TEXT,
  UNIQUE(ticket_id, checklist_item_id)
);

CREATE TABLE IF NOT EXISTS support_db.ticket_resolutions (
  resolution_id TEXT PRIMARY KEY,
  ticket_id TEXT NOT NULL UNIQUE REFERENCES support_db.tickets(ticket_id) ON DELETE CASCADE,
  root_cause TEXT NOT NULL,
  resolution TEXT NOT NULL,
  reusable_for_knowledge BOOLEAN NOT NULL DEFAULT false,
  resolved_by TEXT NOT NULL REFERENCES user_db.users(user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS support_db.notifications (
  notification_id TEXT PRIMARY KEY,
  recipient_id TEXT NOT NULL REFERENCES user_db.users(user_id),
  farm_id TEXT REFERENCES farm_db.farms(farm_id),
  created_by TEXT REFERENCES user_db.users(user_id),
  severity TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  read_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 5) AI / SIMULATION: dữ liệu sinh tự động, mô hình và kết quả phân tích
-- ============================================================
CREATE TABLE IF NOT EXISTS farm_db.simulation_runs (
  simulation_run_id BIGSERIAL PRIMARY KEY,
  run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  generated_readings INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'success',
  detail TEXT
);

CREATE TABLE IF NOT EXISTS knowledge_db.model_registry (
  model_id TEXT PRIMARY KEY,
  farm_id TEXT NOT NULL,
  zone_id TEXT,
  metric_type TEXT NOT NULL,
  model_type TEXT NOT NULL,
  trained_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  sample_count INTEGER NOT NULL,
  training_window_hours INTEGER NOT NULL,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'ready'
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_model_registry_scope
  ON knowledge_db.model_registry(farm_id,coalesce(zone_id,''),metric_type,model_type);

CREATE TABLE IF NOT EXISTS support_db.ai_insight_logs (
  insight_id BIGSERIAL PRIMARY KEY,
  user_id TEXT,
  farm_id TEXT NOT NULL,
  zone_id TEXT,
  metric_type TEXT,
  insight_type TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'info',
  summary TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  decision TEXT NOT NULL CHECK (decision IN ('ai_can_handle','observe','human_required')),
  confidence NUMERIC(5,4),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ai_insight_logs_farm_time
  ON support_db.ai_insight_logs(farm_id,created_at DESC);

-- ============================================================
-- 6) AI TRAIN/TEST V4: lưu dataset, artifact và kết quả đánh giá thực
-- ============================================================
ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS artifact_path TEXT;
ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS dataset_version TEXT;
ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS train_count INTEGER;
ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS test_count INTEGER;
ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS split_strategy TEXT;
ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS feature_names JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS knowledge_db.model_evaluations (
  model_id TEXT PRIMARY KEY,
  farm_id TEXT NOT NULL,
  model_name TEXT NOT NULL,
  task TEXT NOT NULL CHECK (task IN ('regression','classification')),
  dataset_version TEXT NOT NULL,
  train_count INTEGER NOT NULL,
  test_count INTEGER NOT NULL,
  split_time TIMESTAMPTZ NOT NULL,
  metrics JSONB NOT NULL,
  evaluation_chart TEXT NOT NULL,
  importance_chart TEXT NOT NULL,
  evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_model_evaluations_farm
  ON knowledge_db.model_evaluations(farm_id,evaluated_at DESC);

CREATE TABLE IF NOT EXISTS farm_db.ai_training_runs (
  training_run_id BIGSERIAL PRIMARY KEY,
  farm_id TEXT,
  dataset_version TEXT NOT NULL,
  model_count INTEGER NOT NULL,
  train_count INTEGER NOT NULL,
  test_count INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('running','success','failed')),
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

-- ============================================================
-- 7) KNOWLEDGE RAG + TRUTH GUARD V5
-- ============================================================
ALTER TABLE farm_db.sensors DROP CONSTRAINT IF EXISTS sensors_metric_type_check;
ALTER TABLE farm_db.sensors
  ADD CONSTRAINT sensors_metric_type_check
  CHECK (metric_type IN ('soil_moisture','air_humidity','temperature','ec','ph','flow_rate'));

ALTER TABLE farm_db.farms ADD COLUMN IF NOT EXISTS latitude NUMERIC(10,7);
ALTER TABLE farm_db.farms ADD COLUMN IF NOT EXISTS longitude NUMERIC(10,7);
ALTER TABLE farm_db.farms ADD COLUMN IF NOT EXISTS cultivation_type TEXT DEFAULT 'open_field';
ALTER TABLE farm_db.farms ADD COLUMN IF NOT EXISTS soil_texture TEXT;
ALTER TABLE farm_db.farms ADD COLUMN IF NOT EXISTS drainage TEXT;

CREATE TABLE IF NOT EXISTS knowledge_db.sources (
  source_id TEXT PRIMARY KEY,
  source_name TEXT NOT NULL,
  source_url TEXT NOT NULL UNIQUE,
  domain TEXT NOT NULL,
  source_type TEXT NOT NULL CHECK (source_type IN ('nextfarm','government','international','university','internal','support_case')),
  trust_tier INTEGER NOT NULL CHECK (trust_tier BETWEEN 1 AND 4),
  language TEXT NOT NULL DEFAULT 'vi',
  usage_note TEXT,
  active BOOLEAN NOT NULL DEFAULT true,
  last_checked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_db.documents (
  document_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES knowledge_db.sources(source_id),
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  summary_vi TEXT NOT NULL,
  content_vi TEXT NOT NULL,
  crop_tags TEXT[] NOT NULL DEFAULT '{}',
  product_tags TEXT[] NOT NULL DEFAULT '{}',
  region_tags TEXT[] NOT NULL DEFAULT '{}',
  published_at TIMESTAMPTZ,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  approved BOOLEAN NOT NULL DEFAULT false,
  approved_by TEXT REFERENCES user_db.users(user_id),
  checksum TEXT,
  active BOOLEAN NOT NULL DEFAULT true,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_documents_category ON knowledge_db.documents(category, approved, active);
CREATE INDEX IF NOT EXISTS idx_documents_search
  ON knowledge_db.documents USING GIN (to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(summary_vi,'') || ' ' || coalesce(content_vi,'')));

CREATE TABLE IF NOT EXISTS knowledge_db.document_chunks (
  chunk_id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES knowledge_db.documents(document_id) ON DELETE CASCADE,
  chunk_order INTEGER NOT NULL,
  content_vi TEXT NOT NULL,
  token_estimate INTEGER NOT NULL DEFAULT 0,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(document_id, chunk_order)
);
CREATE INDEX IF NOT EXISTS idx_chunks_search
  ON knowledge_db.document_chunks USING GIN (to_tsvector('simple', content_vi));

CREATE TABLE IF NOT EXISTS knowledge_db.crop_profiles (
  crop_id TEXT PRIMARY KEY,
  common_name_vi TEXT NOT NULL,
  scientific_name TEXT,
  family_name TEXT,
  crop_group TEXT NOT NULL,
  temp_opt_min NUMERIC(8,2),
  temp_opt_max NUMERIC(8,2),
  temp_abs_min NUMERIC(8,2),
  temp_abs_max NUMERIC(8,2),
  ph_opt_min NUMERIC(8,2),
  ph_opt_max NUMERIC(8,2),
  rainfall_opt_min NUMERIC(10,2),
  rainfall_opt_max NUMERIC(10,2),
  cycle_days_min INTEGER,
  cycle_days_max INTEGER,
  drainage_requirement TEXT,
  protected_cultivation BOOLEAN NOT NULL DEFAULT false,
  notes_vi TEXT NOT NULL DEFAULT '',
  source_ids TEXT[] NOT NULL DEFAULT '{}',
  reviewed BOOLEAN NOT NULL DEFAULT false,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_db.retrieval_audits (
  retrieval_id BIGSERIAL PRIMARY KEY,
  query_text TEXT NOT NULL,
  farm_id TEXT,
  intent TEXT,
  returned_chunk_ids TEXT[] NOT NULL DEFAULT '{}',
  top_score NUMERIC(8,5),
  answerable BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS support_db.answer_verifications (
  verification_id BIGSERIAL PRIMARY KEY,
  user_id TEXT,
  farm_id TEXT,
  intent TEXT,
  original_answer TEXT NOT NULL,
  final_answer TEXT NOT NULL,
  evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
  confidence NUMERIC(6,5),
  allowed BOOLEAN NOT NULL,
  reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_answer_verifications_farm_time
  ON support_db.answer_verifications(farm_id, created_at DESC);

CREATE TABLE IF NOT EXISTS farm_db.external_climate_snapshots (
  snapshot_id BIGSERIAL PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  horizon_days INTEGER NOT NULL,
  source_url TEXT NOT NULL,
  payload JSONB NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_external_climate_farm_time
  ON farm_db.external_climate_snapshots(farm_id,fetched_at DESC);

-- ============================================================
-- 8) MULTI-TENANT SHARED MODELS V6
-- 10.000 farm dùng chung model family; chỉ lưu profile/calibration/prediction theo farm.
-- ============================================================
ALTER TABLE knowledge_db.model_registry ALTER COLUMN farm_id DROP NOT NULL;
ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS model_family TEXT;
ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS model_version TEXT;
ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS scope_type TEXT NOT NULL DEFAULT 'global';
ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS scope_key TEXT NOT NULL DEFAULT 'all_farms';
ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS task TEXT;
ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS artifact_uri TEXT;
ALTER TABLE knowledge_db.model_registry DROP CONSTRAINT IF EXISTS model_registry_scope_type_check;
ALTER TABLE knowledge_db.model_registry
  ADD CONSTRAINT model_registry_scope_type_check
  CHECK (scope_type IN ('global','crop_group','region_group','enterprise_override'));
DROP INDEX IF EXISTS knowledge_db.ux_model_registry_scope;
CREATE UNIQUE INDEX IF NOT EXISTS ux_model_registry_shared_scope
  ON knowledge_db.model_registry(model_family,model_version,scope_type,scope_key);

ALTER TABLE knowledge_db.model_evaluations ALTER COLUMN farm_id DROP NOT NULL;
ALTER TABLE knowledge_db.model_evaluations ADD COLUMN IF NOT EXISTS evaluation_scope TEXT NOT NULL DEFAULT 'global';
ALTER TABLE knowledge_db.model_evaluations ADD COLUMN IF NOT EXISTS evaluation_key TEXT NOT NULL DEFAULT 'all_farms';
ALTER TABLE knowledge_db.model_evaluations ADD COLUMN IF NOT EXISTS validation_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE knowledge_db.model_evaluations ADD COLUMN IF NOT EXISTS lofo_metrics JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS farm_db.farm_ai_profiles (
  farm_id TEXT PRIMARY KEY REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  crop_code TEXT NOT NULL DEFAULT 'other',
  crop_variety TEXT,
  growth_stage TEXT,
  cultivation_type TEXT NOT NULL DEFAULT 'other',
  climate_region TEXT NOT NULL DEFAULT 'other',
  soil_type TEXT NOT NULL DEFAULT 'other',
  target_moisture_min NUMERIC(8,3),
  target_moisture_max NUMERIC(8,3),
  target_ec_min NUMERIC(8,3),
  target_ec_max NUMERIC(8,3),
  target_ph_min NUMERIC(8,3),
  target_ph_max NUMERIC(8,3),
  active_model_scope TEXT NOT NULL DEFAULT 'global',
  active_model_version TEXT NOT NULL DEFAULT '2.0.0',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS farm_db.farm_model_calibrations (
  farm_id TEXT NOT NULL REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  model_family TEXT NOT NULL,
  model_version TEXT NOT NULL,
  bias NUMERIC(14,6) NOT NULL DEFAULT 0,
  scale NUMERIC(14,6) NOT NULL DEFAULT 1,
  sample_count INTEGER NOT NULL DEFAULT 0,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (farm_id,model_family,model_version)
);

CREATE TABLE IF NOT EXISTS farm_db.farm_feature_snapshots (
  snapshot_id BIGSERIAL PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  zone_id TEXT REFERENCES farm_db.zones(zone_id) ON DELETE CASCADE,
  features JSONB NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_feature_snapshots_farm_time
  ON farm_db.farm_feature_snapshots(farm_id,zone_id,observed_at DESC);

CREATE TABLE IF NOT EXISTS farm_db.farm_predictions (
  prediction_id BIGSERIAL PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  zone_id TEXT REFERENCES farm_db.zones(zone_id) ON DELETE CASCADE,
  model_family TEXT NOT NULL,
  model_version TEXT NOT NULL,
  prediction JSONB NOT NULL,
  confidence NUMERIC(8,6),
  decision TEXT NOT NULL CHECK (decision IN ('ai_can_handle','observe','human_required')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_farm_predictions_lookup
  ON farm_db.farm_predictions(farm_id,zone_id,model_family,created_at DESC);

-- ============================================================
-- 9) V9 REALTIME DATA STUDIO + KNOWLEDGE STUDIO
-- ============================================================
CREATE TABLE IF NOT EXISTS farm_db.telemetry_ingest_events (
  event_id BIGSERIAL PRIMARY KEY,
  packet_id TEXT NOT NULL UNIQUE,
  mqtt_topic TEXT NOT NULL,
  farm_id TEXT,
  zone_id TEXT,
  message_type TEXT NOT NULL DEFAULT 'telemetry',
  payload JSONB NOT NULL,
  sent_at TIMESTAMPTZ,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  inserted_readings INTEGER NOT NULL DEFAULT 0,
  insert_latency_ms NUMERIC(12,3),
  status TEXT NOT NULL DEFAULT 'stored' CHECK (status IN ('stored','duplicate','rejected','error')),
  error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_telemetry_events_time ON farm_db.telemetry_ingest_events(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_events_farm ON farm_db.telemetry_ingest_events(farm_id,received_at DESC);

CREATE TABLE IF NOT EXISTS farm_db.metric_rules (
  rule_id TEXT PRIMARY KEY,
  metric_type TEXT NOT NULL,
  rule_name TEXT NOT NULL,
  function_code TEXT NOT NULL,
  description_vi TEXT NOT NULL,
  required_metrics TEXT[] NOT NULL DEFAULT '{}',
  reference_name TEXT,
  reference_url TEXT,
  enabled BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS farm_db.data_evaluation_snapshots (
  evaluation_id BIGSERIAL PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  zone_id TEXT REFERENCES farm_db.zones(zone_id) ON DELETE CASCADE,
  metric_type TEXT NOT NULL,
  window_minutes INTEGER NOT NULL,
  evaluation JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_evaluation_snapshots_lookup
  ON farm_db.data_evaluation_snapshots(farm_id,zone_id,metric_type,created_at DESC);

ALTER TABLE knowledge_db.document_chunks ADD COLUMN IF NOT EXISTS heading TEXT;
ALTER TABLE knowledge_db.document_chunks ADD COLUMN IF NOT EXISTS section_path TEXT;
ALTER TABLE knowledge_db.document_chunks ADD COLUMN IF NOT EXISTS source_locator TEXT;
ALTER TABLE knowledge_db.document_chunks ADD COLUMN IF NOT EXISTS approved_snapshot BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS knowledge_db.answer_audits (
  answer_id BIGSERIAL PRIMARY KEY,
  query_text TEXT NOT NULL,
  answer_text TEXT NOT NULL,
  citation_chunk_ids TEXT[] NOT NULL DEFAULT '{}',
  source_urls TEXT[] NOT NULL DEFAULT '{}',
  answerable BOOLEAN NOT NULL,
  confidence NUMERIC(8,6),
  guard_status TEXT NOT NULL DEFAULT 'evidence_only',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO farm_db.metric_rules(rule_id,metric_type,rule_name,function_code,description_vi,required_metrics,reference_name,reference_url) VALUES
 ('rule_avg','all','Trung bình cửa sổ','avg','Giá trị trung bình trong khoảng thời gian được chọn.','{}','PostgreSQL aggregate functions','https://www.postgresql.org/docs/current/functions-aggregate.html'),
 ('rule_stddev','all','Độ biến động','stddev_pop','Độ lệch chuẩn quần thể, dùng để nhận biết dữ liệu dao động mạnh.','{}','PostgreSQL aggregate functions','https://www.postgresql.org/docs/current/functions-aggregate.html'),
 ('rule_slope','all','Xu hướng theo giờ','regr_slope','Độ dốc hồi quy tuyến tính của chỉ số theo thời gian.','{}','PostgreSQL aggregate functions','https://www.postgresql.org/docs/current/functions-aggregate.html'),
 ('rule_completeness','all','Độ đầy đủ dữ liệu','completeness','Tỷ lệ số mẫu thực nhận so với số mẫu dự kiến theo chu kỳ gửi.','{}','NextFarm PoC','https://nextfarm.vn/en/help-center/iot/bieu-do-canh-bao-iot'),
 ('rule_threshold','all','Tuân thủ ngưỡng','threshold_compliance','Tỷ lệ mẫu nằm trong ngưỡng mục tiêu của từng khu và thời gian vượt ngưỡng.','{}','NextFarm IoT alerts','https://nextfarm.vn/en/help-center/iot/bieu-do-canh-bao-iot'),
 ('rule_irrigation_response','soil_moisture','Đáp ứng sau tưới','irrigation_response','So sánh độ ẩm trung bình trước và sau ca tưới gần nhất.','{soil_moisture}','FAO CROPWAT / soil-water balance','https://www.fao.org/land-water/resources/tools/software/cropwat/en'),
 ('rule_device_uptime','device','Tỷ lệ thiết bị online','device_uptime','Tỷ lệ bản ghi trạng thái online trong cửa sổ được chọn.','{}','NextFarm IoT','https://nextfarm.vn/en/help-center/iot/dang-ky-quan-ly-thiet-bi-iot'),
 ('rule_irrigation_success','irrigation','Tỷ lệ ca tưới thành công','irrigation_success','Tỷ lệ ca tưới có kết quả success trong cửa sổ thời gian.','{}','NextFarm Irrigation','https://nextfarm.vn/he-thong-tuoi-tu-dong'),
 ('rule_eto_readiness','weather','Mức sẵn sàng tính ETo','eto_readiness','Kiểm tra đủ nhiệt độ, ẩm không khí, bức xạ và gió trước khi áp dụng FAO-56; không đủ thì không tính giả.','{temperature,air_humidity,solar_radiation,wind_speed}','FAO-56','https://www.fao.org/4/X0490E/X0490E00.htm')
ON CONFLICT (rule_id) DO UPDATE SET description_vi=EXCLUDED.description_vi, reference_url=EXCLUDED.reference_url;


-- ============================================================
-- 10) V9 DATASET REGISTRY + SCHEDULED INFERENCE AUDIT
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge_db.ml_datasets (
  dataset_version TEXT PRIMARY KEY,
  source_type TEXT NOT NULL CHECK (source_type IN ('reference_bootstrap','v9_runtime','v9_runtime_blend')),
  source_tables TEXT[] NOT NULL DEFAULT '{}',
  row_count INTEGER NOT NULL,
  farm_count INTEGER NOT NULL,
  zone_count INTEGER NOT NULL,
  checksum_sha256 TEXT NOT NULL,
  artifact_path TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  locked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ml_datasets_locked_at ON knowledge_db.ml_datasets(locked_at DESC);

ALTER TABLE farm_db.farm_predictions ADD COLUMN IF NOT EXISTS trigger_source TEXT NOT NULL DEFAULT 'api';
ALTER TABLE farm_db.farm_predictions ADD COLUMN IF NOT EXISTS deployment_status TEXT NOT NULL DEFAULT 'experimental';
CREATE INDEX IF NOT EXISTS idx_farm_predictions_farm_time ON farm_db.farm_predictions(farm_id,created_at DESC);

ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS deployment_status TEXT NOT NULL DEFAULT 'experimental';
ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS quality_gate JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS dataset_source TEXT NOT NULL DEFAULT 'unknown';

-- ============================================================
-- 11) V9 RESEARCH-CALIBRATED DATA LINEAGE
-- ============================================================
CREATE SCHEMA IF NOT EXISTS research_db;

ALTER TABLE farm_db.sensors DROP CONSTRAINT IF EXISTS sensors_metric_type_check;
ALTER TABLE farm_db.sensors
  ADD CONSTRAINT sensors_metric_type_check
  CHECK (metric_type IN ('soil_moisture','air_humidity','temperature','ec','ph','flow_rate'));

ALTER TABLE farm_db.sensor_readings ADD COLUMN IF NOT EXISTS data_origin TEXT NOT NULL DEFAULT 'simulated_device_calibrated_v9';
ALTER TABLE farm_db.sensor_readings ADD COLUMN IF NOT EXISTS source_dataset TEXT;
ALTER TABLE farm_db.sensor_readings ADD COLUMN IF NOT EXISTS simulation_profile_version TEXT;
ALTER TABLE farm_db.sensor_readings ADD COLUMN IF NOT EXISTS ingest_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE farm_db.sensor_readings DROP CONSTRAINT IF EXISTS sensor_readings_data_origin_check;
ALTER TABLE farm_db.sensor_readings
  ADD CONSTRAINT sensor_readings_data_origin_check
  CHECK (data_origin IN (
    'simulated_device_calibrated_v9',
    'nextfarm_api',
    'nextfarm_mqtt',
    'manual_import',
    'partner_api'
  ));
CREATE INDEX IF NOT EXISTS idx_sensor_readings_origin_time
  ON farm_db.sensor_readings(data_origin,observed_at DESC);

CREATE TABLE IF NOT EXISTS research_db.sources (
  source_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  doi TEXT,
  repository TEXT NOT NULL,
  license TEXT,
  cadence TEXT,
  variables JSONB NOT NULL DEFAULT '[]'::jsonb,
  intended_use JSONB NOT NULL DEFAULT '[]'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  registered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS research_db.calibration_profiles (
  profile_version TEXT PRIMARY KEY,
  checksum_sha256 TEXT NOT NULL,
  source_ids TEXT[] NOT NULL DEFAULT '{}',
  parameters JSONB NOT NULL,
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE knowledge_db.ml_datasets ADD COLUMN IF NOT EXISTS origin_mix JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE knowledge_db.ml_datasets ADD COLUMN IF NOT EXISTS latest_observed_at TIMESTAMPTZ;
ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS training_origin_mix JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE knowledge_db.model_registry ADD COLUMN IF NOT EXISTS training_phase TEXT NOT NULL DEFAULT 'unknown';

CREATE TABLE IF NOT EXISTS research_db.reference_datasets (
  reference_id TEXT PRIMARY KEY,
  lock_sha256 TEXT NOT NULL,
  normalized_rows INTEGER NOT NULL,
  bootstrap_rows INTEGER NOT NULL,
  source_manifest JSONB NOT NULL DEFAULT '[]'::jsonb,
  metric_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 12) DATA OPERATIONS: báo cáo ngày, cảnh báo pipeline, backup
-- ============================================================
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
