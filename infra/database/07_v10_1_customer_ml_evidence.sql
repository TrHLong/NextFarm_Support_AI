-- NextFarm V10.1 customer identity and governed chat feedback migration.
-- Idempotent for fresh databases and existing V10.1 volumes.

BEGIN;

CREATE TABLE IF NOT EXISTS user_db.customers (
  customer_id TEXT PRIMARY KEY,
  customer_name TEXT NOT NULL,
  customer_type TEXT NOT NULL DEFAULT 'farm_owner'
    CHECK (customer_type IN ('farm_owner','support_team','organization')),
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active','inactive')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE user_db.users ADD COLUMN IF NOT EXISTS customer_id TEXT;
ALTER TABLE farm_db.farms ADD COLUMN IF NOT EXISTS customer_id TEXT;

INSERT INTO user_db.customers(customer_id,customer_name,customer_type) VALUES
  ('customer_long','Khách hàng Anh Long','farm_owner'),
  ('customer_lan','Khách hàng Chị Lan','farm_owner'),
  ('customer_minh','Khách hàng Anh Minh','farm_owner'),
  ('customer_nextfarm_support','Đội hỗ trợ NextFarm','support_team')
ON CONFLICT (customer_id) DO UPDATE SET
  customer_name=EXCLUDED.customer_name,
  customer_type=EXCLUDED.customer_type,
  status='active',
  updated_at=now();

UPDATE user_db.users SET customer_id='customer_long' WHERE user_id='farmer_long';
UPDATE user_db.users SET customer_id='customer_lan' WHERE user_id='farmer_lan';
UPDATE user_db.users SET customer_id='customer_minh' WHERE user_id='farmer_minh';
UPDATE user_db.users SET customer_id='customer_nextfarm_support' WHERE role='technician' AND customer_id IS NULL;

INSERT INTO user_db.customers(customer_id,customer_name,customer_type)
SELECT
  'customer_user_' || regexp_replace(lower(u.user_id), '[^a-z0-9]+', '_', 'g'),
  'Khách hàng ' || u.display_name,
  CASE WHEN u.role='technician' THEN 'support_team' ELSE 'farm_owner' END
FROM user_db.users u
WHERE u.customer_id IS NULL
ON CONFLICT (customer_id) DO NOTHING;

UPDATE user_db.users u
SET customer_id='customer_user_' || regexp_replace(lower(u.user_id), '[^a-z0-9]+', '_', 'g')
WHERE u.customer_id IS NULL;

UPDATE farm_db.farms f
SET customer_id=u.customer_id
FROM user_db.users u
WHERE u.user_id=f.owner_user_id AND f.customer_id IS NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname='fk_users_customer'
  ) THEN
    ALTER TABLE user_db.users
      ADD CONSTRAINT fk_users_customer
      FOREIGN KEY (customer_id) REFERENCES user_db.customers(customer_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname='fk_farms_customer'
  ) THEN
    ALTER TABLE farm_db.farms
      ADD CONSTRAINT fk_farms_customer
      FOREIGN KEY (customer_id) REFERENCES user_db.customers(customer_id);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_users_customer ON user_db.users(customer_id);
CREATE INDEX IF NOT EXISTS idx_farms_customer ON farm_db.farms(customer_id);

ALTER TABLE knowledge_db.ml_datasets DROP CONSTRAINT IF EXISTS ml_datasets_source_type_check;
ALTER TABLE knowledge_db.ml_datasets
  ADD CONSTRAINT ml_datasets_source_type_check
  CHECK (source_type IN ('reference_bootstrap','v9_runtime','v9_runtime_blend','v10_runtime_database','v10_runtime_csv_snapshot'));

ALTER TABLE knowledge_db.ml_datasets
  ADD COLUMN IF NOT EXISTS customer_id TEXT REFERENCES user_db.customers(customer_id);

ALTER TABLE knowledge_db.model_registry DROP CONSTRAINT IF EXISTS model_registry_scope_type_check;
ALTER TABLE knowledge_db.model_registry
  ADD CONSTRAINT model_registry_scope_type_check
  CHECK (scope_type IN ('global','customer','crop_group','region_group','enterprise_override'));

ALTER TABLE farm_db.ai_training_runs
  ADD COLUMN IF NOT EXISTS customer_id TEXT REFERENCES user_db.customers(customer_id);

CREATE TABLE IF NOT EXISTS knowledge_db.customer_ml_watermarks (
  customer_id TEXT PRIMARY KEY REFERENCES user_db.customers(customer_id) ON DELETE CASCADE,
  last_snapshot_id TEXT,
  last_dataset_version TEXT,
  last_group_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
  last_training_status TEXT NOT NULL DEFAULT 'never'
    CHECK (last_training_status IN ('never','running','success','failed','insufficient_data')),
  last_started_at TIMESTAMPTZ,
  last_finished_at TIMESTAMPTZ,
  last_error TEXT,
  active_model_count INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Chat messages are audit data and never become training data automatically.
-- A human reviewer must explicitly approve a feedback record before a later,
-- separate curation pipeline may use it.
CREATE TABLE IF NOT EXISTS support_db.chat_feedback (
  feedback_id BIGSERIAL PRIMARY KEY,
  message_id BIGINT NOT NULL REFERENCES support_db.chat_messages(message_id) ON DELETE CASCADE,
  submitted_by TEXT REFERENCES user_db.users(user_id),
  rating SMALLINT CHECK (rating BETWEEN 1 AND 5),
  correction TEXT,
  review_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (review_status IN ('pending','approved','rejected')),
  training_use_allowed BOOLEAN NOT NULL DEFAULT false,
  reviewed_by TEXT REFERENCES user_db.users(user_id),
  reviewed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (message_id, submitted_by)
);

CREATE INDEX IF NOT EXISTS idx_chat_feedback_review
  ON support_db.chat_feedback(review_status,training_use_allowed,created_at);

COMMENT ON TABLE support_db.chat_feedback IS
  'Governed feedback queue. support_db.chat_messages are not automatic ML/RAG training input.';
COMMENT ON COLUMN support_db.chat_feedback.training_use_allowed IS
  'Must remain false until a reviewer approves provenance, privacy, tenant scope and answer correctness.';

COMMIT;
