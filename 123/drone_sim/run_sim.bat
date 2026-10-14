@echo off
title Drone Flight Simulation
cd /d "%~dp0"

echo ============================================
echo   Drone Flight Simulation
echo   Results shown directly in this window
echo ============================================
echo.
set /p MIN="Sim minutes (default 8): "
set /p SEED="Seed (blank=random): "
if "%MIN%"=="" set MIN=8

echo.
echo   [Running] Simulating %MIN% minutes...
if defined SEED (
  python run_sim.py %MIN% %SEED%
) else (
  python run_sim.py %MIN%
)

if errorlevel 1 (
  echo.
  echo   [ERROR] Simulation failed. See messages above.
) else (
  echo.
  echo   [OK] Full report shown above. No result file written.
)
echo.
pause
