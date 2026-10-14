@echo off
chcp 65001 >nul
title Drone Video Crawler (Pure Crawler + Data Only)
echo ============================================
echo   Drone Video Crawler - Multi-Site + xlsx
echo   本目录只保留：爬虫脚本 + 爬取数据(data\)
echo   AI/分析 相关已全部移至 项目根\123\drone_ai（相对路径，不再硬编码盘符）
echo ============================================
echo.
echo [0/2] Check Python + install deps ...
python --version || (echo Python not found. & pause & exit /b 1)
python -m pip install -q -r requirements.txt
echo.
echo [1/2] Run multi-site crawler ...
python multi_site_crawler.py
if %errorlevel% neq 0 (
    echo [ERROR] 爬虫脚本失败：缺少依赖或网络不通，请检查 requirements.txt 是否已安装
    pause
    exit /b 1
)
echo.
echo [2/2] Generate xlsx (one sheet per site) ...
python xlsx_generator.py
echo.
echo ============================================
echo   Done!
echo   - Raw JSONL : data\raw\multi_raw.jsonl
echo   - Excel     : data\raw\drone_videos.xlsx
echo   AI 分析请运行:  在 123\drone_ai 目录执行 python -m analyzer.run_all
echo ============================================
pause
