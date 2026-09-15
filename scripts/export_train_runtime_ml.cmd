@echo off
setlocal
cd /d "%~dp0\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0export_train_runtime_ml.ps1"
if errorlevel 1 exit /b 1
endlocal
