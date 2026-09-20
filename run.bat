@echo off
rem Voyager 1 - Research Assistant launcher
rem Uses .venv in this folder when present, otherwise falls back to python on PATH.
title Voyager 1 - Research Assistant
cd /d "%~dp0"

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

if not exist "config.json" (
    echo [!] config.json not found. Copying config.example.json ...
    copy /y "config.example.json" "config.json" >nul
    echo [!] Please open config.json and fill in your DeepSeek API key.
    pause
)

echo Starting Voyager 1 ...
"%PY%" main.py
pause
