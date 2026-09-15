@echo off
setlocal
cd /d "%~dp0\.."
echo [1/5] Kiem tra Docker...
docker info >nul 2>&1 || (echo [LOI] Docker Desktop chua san sang. & exit /b 1)

echo [2/5] Khoi dong lai MQTT + ingestion + simulator...
docker compose up -d --force-recreate mosquitto telemetry-ingestion-service data-simulator-service
if errorlevel 1 exit /b 1

echo [3/5] Cho luong realtime tu phuc hoi...
timeout /t 20 /nobreak >nul

echo [4/5] Trang thai service...
curl -s http://localhost:18800/health
echo.
curl -s http://localhost:18400/health
echo.

echo [5/5] Kiem tra du lieu moi trong PostgreSQL...
docker compose exec -T postgres psql -U nextfarm -d nextfarm_support -c "SELECT farm_id,count(*) FILTER (WHERE observed_at >= now()-interval '10 minutes') AS recent_10m,max(observed_at) AS newest FROM farm_db.sensor_readings GROUP BY farm_id ORDER BY farm_id;"
echo.
echo Neu recent_10m van bang 0, chay:
echo   docker compose logs --no-color --tail=200 telemetry-ingestion-service data-simulator-service mosquitto
endlocal
