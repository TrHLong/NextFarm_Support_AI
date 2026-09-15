@echo off
setlocal
cd /d "%~dp0\.."
where python >nul 2>nul
if not errorlevel 1 (
  python scripts\sync_v10_model_summary.py
  exit /b %errorlevel%
)
where py >nul 2>nul
if errorlevel 1 (
  echo [FAIL] Python 3 is required to synchronize the V10 model report.
  exit /b 1
)
py -3 scripts\sync_v10_model_summary.py
exit /b %errorlevel%
