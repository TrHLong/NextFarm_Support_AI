-- NextFarm V10 demo runtime seed.
-- Idempotent: refreshes a compact seven-day irrigation history on every start.
-- This gives the assistant meaningful data for today/week irrigation questions
-- without pretending that the records came from production hardware.

WITH demo_runs AS (
  SELECT
    'v10_demo_' || s.schedule_id || '_' || g.day_offset::text AS run_id,
    s.farm_id,
    s.zone_id,
    s.port_id,
    CASE
      WHEN g.day_offset = 0 THEN now() - interval '45 minutes'
      ELSE date_trunc('day', now()) - (g.day_offset * interval '1 day') + s.start_time
    END AS started_at,
    s.duration_minutes::numeric AS duration_minutes,
    CASE
      WHEN (s.schedule_id = 'sch_long_b' AND g.day_offset = 2)
        OR (s.schedule_id = 'sch_minh_a' AND g.day_offset = 5)
      THEN 'failed'
      ELSE 'success'
    END AS result
  FROM farm_db.irrigation_schedules s
  CROSS JOIN generate_series(0, 6) AS g(day_offset)
  WHERE s.enabled
)
INSERT INTO farm_db.irrigation_runs(
  run_id, farm_id, zone_id, port_id, started_at, ended_at,
  duration_minutes, water_liters, result, source
)
SELECT
  run_id,
  farm_id,
  zone_id,
  port_id,
  started_at,
  started_at + (duration_minutes * interval '1 minute'),
  duration_minutes,
  CASE WHEN result = 'success' THEN duration_minutes * 11.5 ELSE duration_minutes * 1.5 END,
  result,
  'demo_seed_v10'
FROM demo_runs
ON CONFLICT (run_id) DO UPDATE SET
  farm_id = EXCLUDED.farm_id,
  zone_id = EXCLUDED.zone_id,
  port_id = EXCLUDED.port_id,
  started_at = EXCLUDED.started_at,
  ended_at = EXCLUDED.ended_at,
  duration_minutes = EXCLUDED.duration_minutes,
  water_liters = EXCLUDED.water_liters,
  result = EXCLUDED.result,
  source = EXCLUDED.source;
