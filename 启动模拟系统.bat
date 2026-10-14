@echo off
title Drone Sim Launcher
rem ============================================================
rem   Double-click this .bat to open the GUI launcher.
rem   The GUI menu (in Chinese) lets you quickly open:
rem     Flight Sim / AI Self-test / 3D Demo / Project Log
rem ============================================================
cd /d "%~dp0"

rem Find python (PATH first)
where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] python not found in PATH.
  echo         Install Python 3.9+ and add to PATH, then retry.
  pause
  exit /b 1
)

rem Launch GUI with pythonw (no console window)
start "" pythonw drone_sim_launcher.pyw
