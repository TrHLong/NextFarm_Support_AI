@echo off
setlocal
cd /d "%~dp0\.."
where python >nul 2>nul
if not errorlevel 1 (
  python scripts\setup_v10_env.py %*
  if errorlevel 1 exit /b 1
  goto :done
)
where py >nul 2>nul
if errorlevel 1 (
  echo [LOI] Can Python 3 de tao secret/password cho V10.
  exit /b 1
)
py -3 scripts\setup_v10_env.py %*
if errorlevel 1 exit /b 1
:done
endlocal
