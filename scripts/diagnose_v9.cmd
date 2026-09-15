@echo off
setlocal
cd /d "%~dp0\.."
echo ==== DOCKER COMPOSE PS ====
docker compose ps -a
echo.

echo ==== HEALTH JSON ====
for %%U in (8100 8600 8800 8400) do (
  echo -- localhost:%%U/health --
  curl -s http://localhost:%%U/health 2>nul
  echo.
)
echo.
for %%S in (postgres mosquitto identity-service telemetry-ingestion-service data-simulator-service ai-analytics-service farm-data-service frontend data-studio knowledge-studio) do (
  echo ==== %%S ====
  docker compose logs --no-color --tail=120 %%S
  echo.
)
endlocal
