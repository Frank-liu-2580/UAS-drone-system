@echo off
title Drone Sim Offline Demo Launcher
rem ==========================================
rem   Drone Sim 3D - Offline Demo (small window)
rem   No backend. No localhost:5000. No internet.
rem ==========================================
echo.
echo   Drone Sim Offline Demo Launcher
echo   -------------------------------
cd /d "%~dp0"

rem Ensure pywebview is installed (one-time)
python -c "import webview" >nul 2>&1
if errorlevel 1 (
  echo   First run: installing pywebview ...
  python -m pip install pywebview
)

rem Launch the small-window app (.pyw = no console flash)
start "" pythonw launch_app.pyw

echo.
echo   A small demo window should open.
echo   Press any key to close this console...
pause >nul
