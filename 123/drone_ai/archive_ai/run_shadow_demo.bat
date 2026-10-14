@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Shadow AI Decision Engine Demo
echo   (reads Anomaly_Events + Decision_Strategies)
echo ============================================
echo.
python shadow_ai\decision_engine.py
echo.
pause