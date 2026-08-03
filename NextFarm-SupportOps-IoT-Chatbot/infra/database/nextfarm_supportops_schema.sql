-- NextFarm SupportOps - initial database design
-- PostgreSQL oriented schema for chatbot PoC and future company API mapping.

CREATE SCHEMA IF NOT EXISTS identity;
CREATE SCHEMA IF NOT EXISTS farm;
CREATE SCHEMA IF NOT EXISTS iot;
CREATE SCHEMA IF NOT EXISTS knowledge;
CREATE SCHEMA IF NOT EXISTS chat;
CREATE SCHEMA IF NOT EXISTS support;
CREATE SCHEMA IF NOT EXISTS sales;
CREATE SCHEMA IF NOT EXISTS ai;
CREATE SCHEMA IF NOT EXISTS audit;

-- 1. Identity and access control
CREATE TABLE IF NOT EXISTS identity.user_accounts (
  user_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  phone TEXT UNIQUE,
  email TEXT,
  user_type TEXT NOT NULL CHECK (user_type IN ('customer','technician','manager','admin')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive','pending')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS identity.user_external_identities (
  external_identity_id TEXT PRIMARY KEY,
  user_id TEXT REFERENCES identity.user_accounts(user_id),
  provider TEXT NOT NULL CHECK (provider IN ('zalo_oa','nextfarm_app','phone','web_demo')),
  provider_user_id TEXT NOT NULL,
  verified BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(provider, provider_user_id)
);

CREATE TABLE IF NOT EXISTS identity.roles (
  role_id TEXT PRIMARY KEY,
  role_name TEXT NOT NULL UNIQUE,
  description TEXT
);

CREATE TABLE IF NOT EXISTS identity.permissions (
  permission_id TEXT PRIMARY KEY,
  permission_code TEXT NOT NULL UNIQUE,
  description TEXT
);

CREATE TABLE IF NOT EXISTS identity.user_roles (
  user_id TEXT REFERENCES identity.user_accounts(user_id),
  role_id TEXT REFERENCES identity.roles(role_id),
  PRIMARY KEY(user_id, role_id)
);

CREATE TABLE IF NOT EXISTS identity.customer_leads (
  lead_id TEXT PRIMARY KEY,
  full_name TEXT NOT NULL,
  phone TEXT NOT NULL,
  region TEXT,
  note TEXT,
  status TEXT NOT NULL DEFAULT 'temp' CHECK (status IN ('temp','qualified','converted','rejected')),
  matched_user_id TEXT REFERENCES identity.user_accounts(user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Farm/GIS/crop profile
CREATE TABLE IF NOT EXISTS farm.crops (
  crop_id TEXT PRIMARY KEY,
  crop_name TEXT NOT NULL,
  crop_group TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS farm.farms (
  farm_id TEXT PRIMARY KEY,
  farm_name TEXT NOT NULL,
  owner_user_id TEXT REFERENCES identity.user_accounts(user_id),
  region TEXT NOT NULL,
  address TEXT,
  area_ha NUMERIC(10,2),
  farm_type TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS identity.farm_memberships (
  farm_id TEXT REFERENCES farm.farms(farm_id),
  user_id TEXT REFERENCES identity.user_accounts(user_id),
  farm_role TEXT NOT NULL CHECK (farm_role IN ('owner','operator','viewer','technician')),
  can_read_data BOOLEAN NOT NULL DEFAULT true,
  can_request_control BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(farm_id, user_id)
);

CREATE TABLE IF NOT EXISTS farm.plot_zones (
  zone_id TEXT PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm.farms(farm_id),
  zone_code TEXT NOT NULL,
  zone_name TEXT,
  crop_id TEXT REFERENCES farm.crops(crop_id),
  area_ha NUMERIC(10,2),
  geometry_json JSONB,
  target_moisture_min NUMERIC(6,2),
  target_moisture_max NUMERIC(6,2),
  UNIQUE(farm_id, zone_code)
);

CREATE TABLE IF NOT EXISTS farm.crop_cycles (
  cycle_id TEXT PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm.farms(farm_id),
  crop_id TEXT REFERENCES farm.crops(crop_id),
  start_date DATE,
  expected_harvest_date DATE,
  growth_stage TEXT,
  status TEXT NOT NULL DEFAULT 'active'
);

-- 3. IoT realtime data
CREATE TABLE IF NOT EXISTS iot.devices (
  device_id TEXT PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm.farms(farm_id),
  zone_id TEXT REFERENCES farm.plot_zones(zone_id),
  device_type TEXT NOT NULL CHECK (device_type IN ('esp32_controller','nmc','fertikit','gateway','weather_station')),
  model_name TEXT,
  firmware_version TEXT,
  connectivity TEXT CHECK (connectivity IN ('wifi','ethernet','cellular','unknown')),
  installed_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS iot.device_ports (
  port_id TEXT PRIMARY KEY,
  device_id TEXT NOT NULL REFERENCES iot.devices(device_id),
  zone_id TEXT REFERENCES farm.plot_zones(zone_id),
  port_number INTEGER NOT NULL,
  port_name TEXT NOT NULL,
  port_type TEXT NOT NULL CHECK (port_type IN ('valve','pump','fertilizer_valve','relay')),
  normally_open BOOLEAN NOT NULL DEFAULT false,
  UNIQUE(device_id, port_number)
);

CREATE TABLE IF NOT EXISTS iot.sensors (
  sensor_id TEXT PRIMARY KEY,
  device_id TEXT NOT NULL REFERENCES iot.devices(device_id),
  zone_id TEXT REFERENCES farm.plot_zones(zone_id),
  sensor_type TEXT NOT NULL CHECK (sensor_type IN ('soil_moisture','temperature','humidity','ec','ph','flow','light','co2','rain','wind')),
  unit TEXT NOT NULL,
  modbus_address TEXT,
  status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS iot.sensor_readings (
  reading_id TEXT PRIMARY KEY,
  timestamp_utc TIMESTAMPTZ NOT NULL,
  farm_id TEXT NOT NULL REFERENCES farm.farms(farm_id),
  zone_id TEXT REFERENCES farm.plot_zones(zone_id),
  device_id TEXT REFERENCES iot.devices(device_id),
  sensor_id TEXT REFERENCES iot.sensors(sensor_id),
  metric_type TEXT NOT NULL,
  value NUMERIC(14,4) NOT NULL,
  unit TEXT NOT NULL,
  quality TEXT NOT NULL DEFAULT 'ok' CHECK (quality IN ('ok','late','missing','suspect','manual')),
  source TEXT NOT NULL DEFAULT 'mqtt'
);

CREATE INDEX IF NOT EXISTS idx_sensor_readings_farm_zone_time ON iot.sensor_readings(farm_id, zone_id, timestamp_utc DESC);

CREATE TABLE IF NOT EXISTS iot.device_status_events (
  status_event_id TEXT PRIMARY KEY,
  timestamp_utc TIMESTAMPTZ NOT NULL,
  farm_id TEXT NOT NULL REFERENCES farm.farms(farm_id),
  device_id TEXT NOT NULL REFERENCES iot.devices(device_id),
  port_id TEXT REFERENCES iot.device_ports(port_id),
  online BOOLEAN,
  running BOOLEAN,
  last_seen_utc TIMESTAMPTZ,
  raw_status JSONB,
  source TEXT NOT NULL DEFAULT 'mqtt'
);

CREATE INDEX IF NOT EXISTS idx_device_status_farm_time ON iot.device_status_events(farm_id, timestamp_utc DESC);

CREATE TABLE IF NOT EXISTS iot.irrigation_schedules (
  schedule_id TEXT PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm.farms(farm_id),
  zone_id TEXT REFERENCES farm.plot_zones(zone_id),
  port_id TEXT REFERENCES iot.device_ports(port_id),
  schedule_name TEXT NOT NULL,
  start_time_local TIME,
  duration_minutes INTEGER,
  days_of_week TEXT,
  mode TEXT NOT NULL CHECK (mode IN ('fixed_time','sensor_threshold','manual')),
  enabled BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS iot.irrigation_runs (
  run_id TEXT PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm.farms(farm_id),
  zone_id TEXT REFERENCES farm.plot_zones(zone_id),
  schedule_id TEXT REFERENCES iot.irrigation_schedules(schedule_id),
  port_id TEXT REFERENCES iot.device_ports(port_id),
  started_at TIMESTAMPTZ NOT NULL,
  ended_at TIMESTAMPTZ,
  duration_minutes INTEGER,
  water_liters NUMERIC(14,3),
  status TEXT NOT NULL CHECK (status IN ('running','completed','failed','cancelled')),
  source TEXT NOT NULL CHECK (source IN ('schedule','manual','chatbot','sensor_rule'))
);

CREATE TABLE IF NOT EXISTS iot.device_commands (
  command_id TEXT PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm.farms(farm_id),
  device_id TEXT REFERENCES iot.devices(device_id),
  port_id TEXT REFERENCES iot.device_ports(port_id),
  requested_by TEXT REFERENCES identity.user_accounts(user_id),
  command_type TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','confirmed','sent','accepted','rejected','failed','cancelled')),
  permission_checked BOOLEAN NOT NULL DEFAULT false,
  firmware_rule_checked BOOLEAN NOT NULL DEFAULT false,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  confirmed_at TIMESTAMPTZ,
  result_json JSONB
);

CREATE TABLE IF NOT EXISTS iot.alerts (
  alert_id TEXT PRIMARY KEY,
  farm_id TEXT NOT NULL REFERENCES farm.farms(farm_id),
  zone_id TEXT REFERENCES farm.plot_zones(zone_id),
  device_id TEXT REFERENCES iot.devices(device_id),
  alert_type TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('low','medium','high','critical')),
  message_vi TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved','ignored')),
  suggested_checklist_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ,
  source TEXT NOT NULL DEFAULT 'rule_engine'
);

-- 4. Knowledge and RAG
CREATE TABLE IF NOT EXISTS knowledge.product_modules (
  module_id TEXT PRIMARY KEY,
  module_name TEXT NOT NULL,
  module_slug TEXT NOT NULL UNIQUE,
  purpose_vi TEXT NOT NULL,
  public_url TEXT
);

CREATE TABLE IF NOT EXISTS knowledge.knowledge_sources (
  source_id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL CHECK (source_type IN ('website','manual','faq','runbook','ticket_resolution','expert_note','company_pdf')),
  title TEXT NOT NULL,
  url TEXT,
  owner TEXT,
  trust_level TEXT NOT NULL DEFAULT 'reviewed',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge.knowledge_articles (
  article_id TEXT PRIMARY KEY,
  source_id TEXT REFERENCES knowledge.knowledge_sources(source_id),
  module_id TEXT REFERENCES knowledge.product_modules(module_id),
  title TEXT NOT NULL,
  topic TEXT NOT NULL,
  body_vi TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','deprecated')),
  reviewer TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge.knowledge_chunks (
  chunk_id TEXT PRIMARY KEY,
  article_id TEXT NOT NULL REFERENCES knowledge.knowledge_articles(article_id),
  chunk_index INTEGER NOT NULL,
  chunk_text_vi TEXT NOT NULL,
  token_count INTEGER,
  status TEXT NOT NULL DEFAULT 'approved',
  UNIQUE(article_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS knowledge.glossary_terms (
  term_id TEXT PRIMARY KEY,
  term TEXT NOT NULL UNIQUE,
  explanation_vi TEXT NOT NULL,
  module_id TEXT REFERENCES knowledge.product_modules(module_id)
);

CREATE TABLE IF NOT EXISTS knowledge.local_language_aliases (
  alias_id TEXT PRIMARY KEY,
  alias_text TEXT NOT NULL,
  normalized_text TEXT NOT NULL,
  meaning TEXT NOT NULL,
  region TEXT,
  confidence NUMERIC(5,4) DEFAULT 1.0
);

-- 5. Chat, tool calling, and grounding
CREATE TABLE IF NOT EXISTS chat.conversations (
  conversation_id TEXT PRIMARY KEY,
  user_id TEXT REFERENCES identity.user_accounts(user_id),
  lead_id TEXT REFERENCES identity.customer_leads(lead_id),
  farm_id TEXT REFERENCES farm.farms(farm_id),
  channel TEXT NOT NULL CHECK (channel IN ('web','mobile_app','zalo_oa','demo')),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS chat.chat_messages (
  message_id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES chat.conversations(conversation_id),
  role TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool')),
  content_vi TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  latency_ms INTEGER
);

CREATE TABLE IF NOT EXISTS chat.intent_events (
  intent_event_id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL REFERENCES chat.chat_messages(message_id),
  intent TEXT NOT NULL,
  slots_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  confidence NUMERIC(5,4),
  model_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat.tool_call_logs (
  tool_call_id TEXT PRIMARY KEY,
  message_id TEXT REFERENCES chat.chat_messages(message_id),
  tool_name TEXT NOT NULL,
  request_json JSONB NOT NULL,
  response_json JSONB,
  status TEXT NOT NULL CHECK (status IN ('success','error','blocked')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat.answer_citations (
  citation_id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL REFERENCES chat.chat_messages(message_id),
  source_type TEXT NOT NULL CHECK (source_type IN ('knowledge_chunk','sensor_reading','alert','device_status','irrigation_run','ticket','model_prediction')),
  source_id TEXT NOT NULL,
  confidence NUMERIC(5,4)
);

-- 6. SupportOps
CREATE TABLE IF NOT EXISTS support.support_tickets (
  ticket_id TEXT PRIMARY KEY,
  conversation_id TEXT REFERENCES chat.conversations(conversation_id),
  user_id TEXT REFERENCES identity.user_accounts(user_id),
  lead_id TEXT REFERENCES identity.customer_leads(lead_id),
  farm_id TEXT REFERENCES farm.farms(farm_id),
  zone_id TEXT REFERENCES farm.plot_zones(zone_id),
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  product_module_id TEXT REFERENCES knowledge.product_modules(module_id),
  category TEXT NOT NULL,
  priority TEXT NOT NULL CHECK (priority IN ('low','normal','high','urgent')),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','assigned','in_progress','resolved','closed')),
  assigned_to TEXT REFERENCES identity.user_accounts(user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  first_response_at TIMESTAMPTZ,
  resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS support.ticket_events (
  ticket_event_id TEXT PRIMARY KEY,
  ticket_id TEXT NOT NULL REFERENCES support.support_tickets(ticket_id),
  actor_user_id TEXT REFERENCES identity.user_accounts(user_id),
  event_type TEXT NOT NULL,
  note_vi TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS support.ticket_checklists (
  checklist_id TEXT PRIMARY KEY,
  category TEXT NOT NULL,
  title_vi TEXT NOT NULL,
  module_id TEXT REFERENCES knowledge.product_modules(module_id),
  active BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS support.ticket_checklist_items (
  item_id TEXT PRIMARY KEY,
  checklist_id TEXT NOT NULL REFERENCES support.ticket_checklists(checklist_id),
  item_order INTEGER NOT NULL,
  instruction_vi TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS support.resolution_notes (
  resolution_id TEXT PRIMARY KEY,
  ticket_id TEXT NOT NULL REFERENCES support.support_tickets(ticket_id),
  root_cause TEXT,
  resolution_vi TEXT NOT NULL,
  reusable_for_knowledge BOOLEAN NOT NULL DEFAULT false,
  reviewed_by TEXT REFERENCES identity.user_accounts(user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS support.sla_policies (
  sla_policy_id TEXT PRIMARY KEY,
  priority TEXT NOT NULL,
  first_response_minutes INTEGER NOT NULL,
  resolution_minutes INTEGER NOT NULL
);

-- 7. AI/model lifecycle
CREATE TABLE IF NOT EXISTS ai.model_registry (
  model_id TEXT PRIMARY KEY,
  model_name TEXT NOT NULL,
  model_type TEXT NOT NULL CHECK (model_type IN ('intent','retrieval','rerank','forecast','alert_root_cause','recommendation','llm_adapter')),
  version TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','staging','production','retired')),
  artifact_uri TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai.dataset_versions (
  dataset_id TEXT PRIMARY KEY,
  dataset_name TEXT NOT NULL,
  source_tables TEXT[] NOT NULL,
  version TEXT NOT NULL,
  row_count INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai.feature_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  model_id TEXT REFERENCES ai.model_registry(model_id),
  farm_id TEXT REFERENCES farm.farms(farm_id),
  zone_id TEXT REFERENCES farm.plot_zones(zone_id),
  window_start_utc TIMESTAMPTZ,
  window_end_utc TIMESTAMPTZ,
  features_json JSONB NOT NULL,
  label_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai.training_runs (
  run_id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL REFERENCES ai.model_registry(model_id),
  dataset_id TEXT REFERENCES ai.dataset_versions(dataset_id),
  status TEXT NOT NULL CHECK (status IN ('queued','running','completed','failed')),
  metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ai.evaluation_sets (
  eval_set_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  purpose TEXT NOT NULL,
  expected_metric TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai.evaluation_results (
  eval_result_id TEXT PRIMARY KEY,
  run_id TEXT REFERENCES ai.training_runs(run_id),
  eval_set_id TEXT REFERENCES ai.evaluation_sets(eval_set_id),
  metric_name TEXT NOT NULL,
  metric_value NUMERIC(10,4) NOT NULL,
  passed BOOLEAN NOT NULL,
  details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai.prediction_logs (
  prediction_id TEXT PRIMARY KEY,
  model_id TEXT REFERENCES ai.model_registry(model_id),
  conversation_id TEXT REFERENCES chat.conversations(conversation_id),
  input_json JSONB NOT NULL,
  output_json JSONB NOT NULL,
  confidence NUMERIC(5,4),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 8. Audit
CREATE TABLE IF NOT EXISTS audit.access_audit_logs (
  audit_id TEXT PRIMARY KEY,
  actor_user_id TEXT REFERENCES identity.user_accounts(user_id),
  farm_id TEXT REFERENCES farm.farms(farm_id),
  action TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('allow','deny')),
  reason TEXT,
  request_context JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 9. Sales/pre-sales for visitors and leads
CREATE TABLE IF NOT EXISTS sales.lead_profiles (
  lead_profile_id TEXT PRIMARY KEY,
  lead_id TEXT REFERENCES identity.customer_leads(lead_id),
  full_name TEXT,
  phone TEXT,
  region TEXT,
  channel TEXT NOT NULL DEFAULT 'web_chat',
  lead_status TEXT NOT NULL DEFAULT 'new' CHECK (lead_status IN ('new','qualifying','qualified','converted','lost')),
  interest_level TEXT NOT NULL DEFAULT 'unknown' CHECK (interest_level IN ('unknown','learning','considering','wants_demo','wants_quote','ready_to_buy')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sales.lead_requirements (
  requirement_id TEXT PRIMARY KEY,
  lead_profile_id TEXT NOT NULL REFERENCES sales.lead_profiles(lead_profile_id),
  crop_text TEXT,
  area_value NUMERIC(12,2),
  area_unit TEXT,
  cultivation_type TEXT CHECK (cultivation_type IN ('open_field','greenhouse','net_house','home_garden','unknown')),
  province_or_region TEXT,
  water_source TEXT,
  has_pump BOOLEAN,
  business_goal TEXT CHECK (business_goal IN ('home_use','trial','commercial','cooperative','unknown')),
  raw_message TEXT NOT NULL,
  extracted_confidence NUMERIC(5,4),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sales.lead_pain_points (
  pain_point_id TEXT PRIMARY KEY,
  lead_profile_id TEXT NOT NULL REFERENCES sales.lead_profiles(lead_profile_id),
  pain_point_code TEXT NOT NULL,
  description_vi TEXT NOT NULL,
  severity TEXT DEFAULT 'normal' CHECK (severity IN ('low','normal','high')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sales.module_recommendations (
  recommendation_id TEXT PRIMARY KEY,
  lead_profile_id TEXT NOT NULL REFERENCES sales.lead_profiles(lead_profile_id),
  module_id TEXT REFERENCES knowledge.product_modules(module_id),
  fit_level TEXT NOT NULL CHECK (fit_level IN ('must_have','recommended','later','not_needed_now')),
  reason_vi TEXT NOT NULL,
  created_by TEXT NOT NULL DEFAULT 'chatbot',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sales.consultation_notes (
  consultation_note_id TEXT PRIMARY KEY,
  lead_profile_id TEXT REFERENCES sales.lead_profiles(lead_profile_id),
  conversation_id TEXT REFERENCES chat.conversations(conversation_id),
  note_type TEXT NOT NULL CHECK (note_type IN ('bot_advice','clarifying_question','user_answer','handoff_summary')),
  content_vi TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sales.opportunities (
  opportunity_id TEXT PRIMARY KEY,
  lead_profile_id TEXT NOT NULL REFERENCES sales.lead_profiles(lead_profile_id),
  title TEXT NOT NULL,
  stage TEXT NOT NULL DEFAULT 'new' CHECK (stage IN ('new','contacted','demo_scheduled','proposal_sent','won','lost')),
  estimated_value_vnd NUMERIC(16,2),
  assigned_to TEXT REFERENCES identity.user_accounts(user_id),
  next_action_vi TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sales.proposal_drafts (
  proposal_id TEXT PRIMARY KEY,
  opportunity_id TEXT REFERENCES sales.opportunities(opportunity_id),
  lead_profile_id TEXT NOT NULL REFERENCES sales.lead_profiles(lead_profile_id),
  proposal_summary_vi TEXT NOT NULL,
  module_plan_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  assumptions_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','reviewed','sent','archived')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

