@echo off
setlocal
if "%~1"=="" (
  echo Usage: scripts\setup_v10_production.cmd https://your-domain.example
  exit /b 2
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_v10_production.ps1" -CorsAllowOrigins "%~1"
exit /b %errorlevel%
