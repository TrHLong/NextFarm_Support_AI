@echo off
setlocal
cd /d "%~dp0\.."
where python >nul 2>nul
if errorlevel 1 (
  echo [LOI] Can Python de tao secret va mat khau bootstrap ngau nhien.
  exit /b 1
)
python scripts\setup_v9_env.py
if errorlevel 1 exit /b 1
endlocal
