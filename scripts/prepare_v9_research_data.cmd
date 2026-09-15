@echo off
setlocal
cd /d "%~dp0\.."
echo [V9] Dang tai va khoa bo du lieu tham chieu cong khai...
python scripts\prepare_v9_reference_data.py %*
if errorlevel 1 (
  echo [LOI] Khong tao duoc static reference pack. V9 se KHONG tu sinh du lieu tham chieu gia.
  exit /b 1
)
echo [OK] Static reference + calibration + bootstrap training da san sang.
endlocal
