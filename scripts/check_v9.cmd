@echo off
setlocal
cd /d "%~dp0\.."
if not exist .env (echo [LOI] Thieu .env. Chay scripts\setup_v9_env.cmd & exit /b 1)
if not exist research-data\reference\reference_lock.json (echo [LOI] Thieu static reference lock. Chay scripts\prepare_v9_research_data.cmd & exit /b 1)

echo ==== V9 OFFLINE CONTRACT ====
python scripts\offline_v9_research_check.py
if errorlevel 1 exit /b 1

echo ==== DOCKER STATUS ====
docker compose ps -a
if errorlevel 1 exit /b 1

echo ==== V9 RUNTIME CONTRACT ====
python scripts\check_v9_runtime.py
if errorlevel 1 (
  call scripts\diagnose_v9.cmd
  exit /b 1
)

echo ==== V9 RUNTIME DATA ORIGIN ====
docker compose exec -T postgres psql -U nextfarm -d nextfarm_support -c "SELECT farm_id,data_origin,count(*) AS readings,max(observed_at) AS newest FROM farm_db.sensor_readings GROUP BY farm_id,data_origin ORDER BY farm_id,data_origin;"
if errorlevel 1 exit /b 1

echo ==== STATIC REFERENCE + MODEL PHASE ====
docker compose exec -T postgres psql -U nextfarm -d nextfarm_support -c "SELECT reference_id,normalized_rows,bootstrap_rows,loaded_at FROM research_db.reference_datasets ORDER BY loaded_at DESC LIMIT 3;"
docker compose exec -T postgres psql -U nextfarm -d nextfarm_support -c "SELECT dataset_version,source_type,row_count,origin_mix,locked_at FROM knowledge_db.ml_datasets ORDER BY locked_at DESC LIMIT 5;"
docker compose exec -T postgres psql -U nextfarm -d nextfarm_support -c "SELECT model_family,training_phase,deployment_status,dataset_source,training_origin_mix FROM knowledge_db.model_registry WHERE scope_type='global' ORDER BY model_family;"

echo [OK] V9 standalone runtime check hoan tat.
endlocal
