@echo off
setlocal
cd /d "%~dp0\.."
where python >nul 2>nul
if not errorlevel 1 (
  python scripts\build_v10_1_manifest.py
  exit /b %errorlevel%
)
where py >nul 2>nul
if errorlevel 1 (
  echo [FAIL] Python 3 is required to build BUILD_MANIFEST.json.
  exit /b 1
)
py -3 scripts\build_v10_1_manifest.py
exit /b %errorlevel%
