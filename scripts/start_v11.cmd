@echo off
setlocal
cd /d "%~dp0\.."

call scripts\setup_v10_env.cmd
if errorlevel 1 exit /b 1
if not exist .env (
  echo [ERROR] Missing .env after setup. Run scripts\setup_v10_env.cmd and retry.
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker Engine is not ready. Open Docker Desktop, wait for Engine running, then retry.
  exit /b 1
)
docker compose --env-file .env stop ticket-service
docker compose --env-file .env up -d --build
if errorlevel 1 exit /b 1
docker compose --env-file .env exec -T farm-data-service python import_device_reference.py
if errorlevel 1 exit /b 1
docker compose --env-file .env exec -T ai-analytics-service python -m pytest tests_device -q
if errorlevel 1 exit /b 1
echo [OK] Device services built. Open http://127.0.0.1:18080
echo [INFO] Problem B: collect 72 real hours before CSV training. Old synthetic READY is not served.
echo [INFO] Read docs/problem-b/BAO-CAO-BAI-TOAN-B.html.
endlocal
