@echo off
title Drone Sim Frontend
echo ========================================
echo   Drone Sim 3D Frontend - Flask Server
echo ========================================
echo.
cd /d "%~dp0"
echo Starting on http://localhost:5000 ...
python server.py 5000
pause
