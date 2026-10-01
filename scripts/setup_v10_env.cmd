@echo off
setlocal
cd /d "%~dp0\.."

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_v10_env.ps1" %*
exit /b %errorlevel%
