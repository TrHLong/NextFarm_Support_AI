@echo off
setlocal
cd /d "%~dp0\.."

echo ================================================
echo NextFarm V9 STANDALONE - FRESH DATA PIPELINE
echo ================================================

echo [1/8] Kiem tra Docker va Python...
docker info >nul 2>&1 || (echo [LOI] Docker Desktop chua san sang. & exit /b 1)
where python >nul 2>nul || (echo [LOI] Can Python 3 de tai/khoa static reference. & exit /b 1)

if not exist .env (
  echo [2/8] Tao .env V9 standalone...
  call scripts\setup_v9_env.cmd
  if errorlevel 1 exit /b 1
) else (
  echo [2/8] Da co .env V9 standalone.
)

echo [3/8] Tai + khoa static public reference truoc khi build...
call scripts\prepare_v9_research_data.cmd
if errorlevel 1 (
  echo [LOI] Khong co reference pack hop le nen V9 dung lai. Khong co fake fallback.
  exit /b 1
)

echo [4/8] Dung stack V9 hien tai neu co, KHONG xoa volume...
docker compose down --remove-orphans
if errorlevel 1 exit /b 1

echo [5/8] Build/start PostgreSQL V9 + MQTT + Identity + AI bootstrap...
docker compose up -d --build postgres mosquitto identity-service ai-analytics-service
if errorlevel 1 (
  call scripts\diagnose_v9.cmd
  exit /b 1
)

echo [6/8] Cho AI API khoi dong va hoc bo static reference da khoa...
python scripts\wait_v9_bootstrap.py
if errorlevel 1 (
  call scripts\diagnose_v9.cmd
  exit /b 1
)

echo [7/8] Bat dau luong gia lap thiet bi -> MQTT -> PostgreSQL va cac service con lai...
docker compose up -d --build
if errorlevel 1 (
  call scripts\diagnose_v9.cmd
  exit /b 1
)

echo [8/8] Cho telemetry moi va kiem tra runtime...
timeout /t 20 /nobreak >nul
call scripts\check_v9.cmd
if errorlevel 1 exit /b 1

echo.
echo [OK] NextFarm V9 standalone da san sang.
echo Web:       http://localhost:8080
echo Data:      http://localhost:8081
echo Knowledge: http://localhost:8082
endlocal
